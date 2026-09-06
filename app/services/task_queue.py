# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Awaitable, Callable

from sqlalchemy import Float, Index, Integer, String, Text, and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.domain.contracts import QueueJob
from app.services.database import create_engine, create_session_factory, sqlite_url
from app.services.timing import timed_stage
from config.settings import settings

logger = logging.getLogger(__name__)
JobHandler = Callable[[QueueJob], Awaitable[dict[str, object]]]
DeadLetterHandler = Callable[[QueueJob, Exception], Awaitable[None]]

_NON_RETRYABLE_ERROR_MARKERS = (
    "does not support .csv file format",
    "requires a .csv or .tsv input file",
    "currently supports .xlsx files only",
    "unsupported excel operation",
    "workflow selected unknown skills",
)


def is_non_retryable_error(error: Exception) -> bool:
    """Return True for failures that cannot succeed without changing the input or plan."""
    if isinstance(error, (ValueError, TypeError, KeyError)):
        return True
    message = str(error).lower()
    return any(marker in message for marker in _NON_RETRYABLE_ERROR_MARKERS)


class Base(DeclarativeBase):
    pass


class TaskJobRecord(Base):
    __tablename__ = "task_jobs"
    __table_args__ = (
        Index("idx_task_jobs_claim", "status", "available_at", "created_at"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_unicode_ci",
        },
    )

    job_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)


class PersistentTaskQueue:
    """MySQL-backed asynchronous, idempotent queue shared by API and Bot."""

    def __init__(
        self,
        database_url: str | Path | None = None,
        max_attempts: int = 3,
        lease_seconds: int = 300,
        max_wait_seconds: int | None = None,
    ) -> None:
        if isinstance(database_url, Path):
            database_url = sqlite_url(database_url)
        self.database_url = database_url or settings.database_url
        self.max_attempts = max_attempts
        self.lease_seconds = lease_seconds
        self.max_wait_seconds = max_wait_seconds or settings.task_queue_max_wait_seconds
        self.engine = create_engine(self.database_url)
        self.session_factory = create_session_factory(self.engine)

    async def initialize(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        await self.engine.dispose()

    async def enqueue(self, job_id: str, kind: str, payload: dict[str, object]) -> bool:
        now = time.time()
        async with self.session_factory() as session:
            session.add(
                TaskJobRecord(
                    job_id=job_id,
                    kind=kind,
                    payload=json.dumps(payload, ensure_ascii=False),
                    status="pending",
                    attempts=0,
                    available_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return False
        return True

    async def claim(self) -> QueueJob | None:
        now = time.time()
        stale_before = now - self.lease_seconds
        expire_before = now - self.max_wait_seconds
        async with self.session_factory() as session:
            async with session.begin():
                expired = await session.execute(
                    update(TaskJobRecord)
                    .where(
                        TaskJobRecord.status.in_(["pending", "retry"]),
                        TaskJobRecord.created_at < expire_before,
                    )
                    .values(
                        status="dead",
                        last_error=(
                            f"Queue wait exceeded {self.max_wait_seconds} seconds."
                        ),
                        updated_at=now,
                    )
                )
                expired_count = int(expired.rowcount or 0)
                if expired_count:
                    logger.warning(
                        "Expired %s queued task(s) after waiting more than %s seconds.",
                        expired_count,
                        self.max_wait_seconds,
                    )
                statement = (
                    select(TaskJobRecord)
                    .where(
                        TaskJobRecord.attempts < self.max_attempts,
                        or_(
                            and_(
                                TaskJobRecord.status.in_(["pending", "retry"]),
                                TaskJobRecord.available_at <= now,
                            ),
                            and_(
                                TaskJobRecord.status == "running",
                                TaskJobRecord.updated_at <= stale_before,
                            ),
                        ),
                    )
                    .order_by(TaskJobRecord.created_at)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
                record = (await session.execute(statement)).scalar_one_or_none()
                if record is None:
                    return None
                record.status = "running"
                record.attempts += 1
                record.updated_at = now
                await session.flush()
                return self._to_domain(record)

    async def complete(self, job_id: str, result: dict[str, object]) -> None:
        now = time.time()
        async with self.session_factory() as session:
            await session.execute(
                update(TaskJobRecord)
                .where(TaskJobRecord.job_id == job_id)
                .values(
                    status="completed",
                    result=json.dumps(result, ensure_ascii=False),
                    last_error=None,
                    updated_at=now,
                )
            )
            await session.commit()

    async def fail(self, job: QueueJob, error: Exception) -> str:
        status = (
            "dead"
            if job.attempts >= self.max_attempts or is_non_retryable_error(error)
            else "retry"
        )
        now = time.time()
        delay = min(2 ** max(job.attempts - 1, 0), 30)
        async with self.session_factory() as session:
            await session.execute(
                update(TaskJobRecord)
                .where(TaskJobRecord.job_id == job.job_id)
                .values(
                    status=status,
                    available_at=now + delay,
                    last_error=str(error)[:2000],
                    updated_at=now,
                )
            )
            await session.commit()
        return status

    async def get(self, job_id: str) -> QueueJob | None:
        async with self.session_factory() as session:
            record = (
                await session.execute(
                    select(TaskJobRecord).where(TaskJobRecord.job_id == job_id)
                )
            ).scalar_one_or_none()
            return self._to_domain(record) if record else None

    async def release(self, job: QueueJob) -> None:
        now = time.time()
        async with self.session_factory() as session:
            await session.execute(
                update(TaskJobRecord)
                .where(
                    TaskJobRecord.job_id == job.job_id,
                    TaskJobRecord.status == "running",
                )
                .values(
                    status="retry",
                    attempts=max(job.attempts - 1, 0),
                    available_at=now,
                    updated_at=now,
                )
            )
            await session.commit()

    @staticmethod
    def _to_domain(record: TaskJobRecord) -> QueueJob:
        return QueueJob(
            job_id=record.job_id,
            kind=record.kind,
            payload=json.loads(record.payload),
            status=record.status,
            attempts=record.attempts,
            result=json.loads(record.result) if record.result else None,
            last_error=record.last_error,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


class TaskWorker:
    def __init__(
        self,
        queue: PersistentTaskQueue,
        handlers: dict[str, JobHandler],
        concurrency: int = 4,
        poll_seconds: float = 0.25,
        dead_letter_handler: DeadLetterHandler | None = None,
    ) -> None:
        self.queue = queue
        self.handlers = handlers
        self.concurrency = concurrency
        self.poll_seconds = poll_seconds
        self.dead_letter_handler = dead_letter_handler
        self._tasks: list[asyncio.Task[None]] = []
        self._start_lock = asyncio.Lock()

    async def start(self) -> None:
        async with self._start_lock:
            if self._tasks:
                return
            await self.queue.initialize()
            self._tasks = [
                asyncio.create_task(self._run_loop(index), name=f"task-worker-{index}")
                for index in range(self.concurrency)
            ]

    async def stop(self) -> None:
        tasks, self._tasks = self._tasks, []
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_loop(self, index: int) -> None:
        while True:
            job = await self.queue.claim()
            if job is None:
                await asyncio.sleep(self.poll_seconds)
                continue
            handler = self.handlers.get(job.kind)
            if handler is None:
                await self.queue.fail(job, ValueError(f"Unknown job kind: {job.kind}"))
                continue
            try:
                queue_wait_ms = max(0.0, (time.time() - job.created_at) * 1000)
                async with timed_stage(
                    logger,
                    "queue.execute",
                    job_id=job.job_id,
                    fields={
                        "kind": job.kind,
                        "attempt": job.attempts,
                        "queue_wait_ms": round(queue_wait_ms, 3),
                        "task_id": job.payload.get("task_id"),
                    },
                ):
                    result = await handler(job)
                await self.queue.complete(job.job_id, result)
            except asyncio.CancelledError:
                await self.queue.release(job)
                raise
            except Exception as exc:
                logger.exception("Task worker %s failed job %s", index, job.job_id)
                status = await self.queue.fail(job, exc)
                if status == "dead" and self.dead_letter_handler:
                    await self.dead_letter_handler(job, exc)

# -*- coding: utf-8 -*-
import asyncio
import time

from sqlalchemy import update

from app.services.task_queue import PersistentTaskQueue
from app.services.task_queue import TaskJobRecord


def test_persistent_queue_is_idempotent_and_completes(tmp_path) -> None:
    async def scenario() -> None:
        queue = PersistentTaskQueue(tmp_path / "queue.sqlite3", max_attempts=2)
        await queue.initialize()

        assert await queue.enqueue("message:1", "message", {"text": "你好"}) is True
        assert await queue.enqueue("message:1", "message", {"text": "重复"}) is False

        job = await queue.claim()
        assert job is not None
        assert job.attempts == 1
        assert job.payload == {"text": "你好"}

        await queue.complete(job.job_id, {"ok": True})
        completed = await queue.get(job.job_id)
        assert completed is not None
        assert completed.status == "completed"
        assert completed.result == {"ok": True}

    asyncio.run(scenario())


def test_persistent_queue_retries_then_dead_letters(tmp_path) -> None:
    async def scenario() -> None:
        queue = PersistentTaskQueue(tmp_path / "queue.sqlite3", max_attempts=2)
        await queue.initialize()
        await queue.enqueue("message:2", "message", {})

        first = await queue.claim()
        assert first is not None
        assert await queue.fail(first, RuntimeError("first")) == "retry"
        await asyncio.sleep(1.05)

        second = await queue.claim()
        assert second is not None
        assert second.attempts == 2
        assert await queue.fail(second, RuntimeError("second")) == "dead"
        failed = await queue.get(second.job_id)
        assert failed is not None
        assert failed.status == "dead"

    asyncio.run(scenario())


def test_persistent_queue_dead_letters_deterministic_input_error_immediately(tmp_path) -> None:
    async def scenario() -> None:
        queue = PersistentTaskQueue(tmp_path / "queue.sqlite3", max_attempts=3)
        await queue.initialize()
        await queue.enqueue("message:invalid-input", "message", {})

        job = await queue.claim()
        assert job is not None
        assert await queue.fail(job, ValueError("CSV input is not readable")) == "dead"

        failed = await queue.get(job.job_id)
        assert failed is not None
        assert failed.status == "dead"
        assert failed.attempts == 1
        assert failed.last_error == "CSV input is not readable"

    asyncio.run(scenario())


def test_persistent_queue_expires_old_pending_jobs(tmp_path) -> None:
    async def scenario() -> None:
        queue = PersistentTaskQueue(tmp_path / "queue.sqlite3", max_wait_seconds=30)
        await queue.initialize()
        await queue.enqueue("message:old", "message", {})
        async with queue.session_factory() as session:
            await session.execute(
                update(TaskJobRecord)
                .where(TaskJobRecord.job_id == "message:old")
                .values(created_at=time.time() - 60)
            )
            await session.commit()

        assert await queue.claim() is None
        expired = await queue.get("message:old")
        assert expired is not None
        assert expired.status == "dead"
        assert "Queue wait exceeded" in (expired.last_error or "")

    asyncio.run(scenario())

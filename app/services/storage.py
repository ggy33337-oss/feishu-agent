# -*- coding: utf-8 -*-
from pathlib import Path

from config.settings import settings


class LocalArtifactStore:
    """Default artifact adapter; replaceable with shared or object storage."""

    def __init__(self, root: Path | None = None) -> None:
        configured = Path(settings.artifact_root) if settings.artifact_root else None
        self.root = root or configured or Path(__file__).resolve().parents[2] / "outputs"

    def input_dir(self, task_id: str) -> Path:
        path = self.root / task_id / "input"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def output_dir(self, task_id: str) -> Path:
        path = self.root / task_id
        path.mkdir(parents=True, exist_ok=True)
        return path

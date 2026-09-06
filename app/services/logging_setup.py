# -*- coding: utf-8 -*-
"""Process logging setup with explicit UTF-8 file output."""

from __future__ import annotations

import logging
from pathlib import Path


def configure_process_logging(process_name: str) -> Path:
    project_root = Path(__file__).resolve().parents[2]
    log_dir = project_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{process_name}.log"

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    has_stream = any(not isinstance(handler, logging.FileHandler) for handler in root.handlers)
    if not any(
        isinstance(handler, logging.FileHandler)
        and Path(handler.baseFilename).resolve() == log_path.resolve()
        for handler in root.handlers
    ):
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    if not has_stream:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)
    return log_path

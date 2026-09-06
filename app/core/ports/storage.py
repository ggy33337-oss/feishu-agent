# -*- coding: utf-8 -*-
from pathlib import Path
from typing import Protocol


class ArtifactStore(Protocol):
    def input_dir(self, task_id: str) -> Path: ...

    def output_dir(self, task_id: str) -> Path: ...


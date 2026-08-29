from pathlib import Path


class FileService:
    def __init__(self, storage_dir: str = "storage") -> None:
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def resolve(self, filename: str) -> Path:
        return self.storage_dir / filename


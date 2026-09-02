import asyncio
from pathlib import Path

from .base import StorageBackend


class LocalFileStorage(StorageBackend):

    def __init__(self, root: str = "./data/snapshots") -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = self._root / key
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def _write(self, key: str, data: bytes) -> None:
        self._path(key).write_bytes(data)

    def _read(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def _delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    async def save(self, key: str, data: bytes) -> None:
        await asyncio.to_thread(self._write, key, data)

    async def load(self, key: str) -> bytes:
        return await asyncio.to_thread(self._read, key)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._delete, key)

from abc import ABC, abstractmethod


class StorageBackend(ABC):
    """
    Save/load raw snapshot bytes by key. Two implementations exist
    AzureBlobStorage and S3Storage selected by STORAGE_PROVIDER in .env.
    Nothing outside app/storage/ should import a provider SDK directly.
    """

    @abstractmethod
    async def save(self, key: str, data: bytes) -> None: ...

    @abstractmethod
    async def load(self, key: str) -> bytes: ...

    @abstractmethod
    async def delete(self, key: str) -> None:
        """
        Remove a stored blob. Used by snapshot retention. Deleting a key
        that isn't there must succeed quietly -- callers prune best-effort and
        shouldn't have to care whether a previous prune already got there.
        """
        ...

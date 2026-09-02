from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob.aio import BlobServiceClient

from ..config import settings
from .base import StorageBackend


class AzureBlobStorage(StorageBackend):
    def __init__(self) -> None:
        if not settings.AZURE_STORAGE_CONNECTION_STRING:
            raise RuntimeError(
                "STORAGE_PROVIDER=azure but AZURE_STORAGE_CONNECTION_STRING is not set. "
                "Get it from Azure Portal -> Storage account -> Access keys."
            )
        self._client = BlobServiceClient.from_connection_string(
            settings.AZURE_STORAGE_CONNECTION_STRING
        )
        self._container = settings.AZURE_STORAGE_CONTAINER
        self._ensured = False

    async def _ensure_container(self) -> None:
        if self._ensured:
            return
        container = self._client.get_container_client(self._container)
        try:
            await container.create_container()
        except Exception:
            pass  # already exists
        self._ensured = True

    async def save(self, key: str, data: bytes) -> None:
        await self._ensure_container()
        blob = self._client.get_blob_client(container=self._container, blob=key)
        await blob.upload_blob(data, overwrite=True)

    async def load(self, key: str) -> bytes:
        blob = self._client.get_blob_client(container=self._container, blob=key)
        stream = await blob.download_blob()
        return await stream.readall()

    async def delete(self, key: str) -> None:
        blob = self._client.get_blob_client(container=self._container, blob=key)
        try:
            await blob.delete_blob()
        except ResourceNotFoundError:
            pass  # already gone

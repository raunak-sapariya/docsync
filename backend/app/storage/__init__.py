from ..config import settings
from .base import StorageBackend

_backend: StorageBackend | None = None


def get_storage() -> StorageBackend:
    global _backend
    if _backend is None:
        if settings.STORAGE_PROVIDER == "local":
            from .local import LocalFileStorage

            _backend = LocalFileStorage()
        elif settings.STORAGE_PROVIDER == "azure":
            from .azure_blob import AzureBlobStorage

            _backend = AzureBlobStorage()
        elif settings.STORAGE_PROVIDER == "aws":
            from .s3 import S3Storage

            _backend = S3Storage()
        else:
            raise ValueError(
                f"Unknown STORAGE_PROVIDER '{settings.STORAGE_PROVIDER}' -- use 'local', 'azure', or 'aws'"
            )
    return _backend

import asyncio

import boto3

from ..config import settings
from .base import StorageBackend


class S3Storage(StorageBackend):

    def __init__(self) -> None:
        self._client = boto3.client(
            "s3",
            region_name=settings.AWS_REGION,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID or None,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY or None,
        )
        self._bucket = settings.S3_BUCKET

    def _put(self, key: str, data: bytes) -> None:
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data)

    def _get(self, key: str) -> bytes:
        obj = self._client.get_object(Bucket=self._bucket, Key=key)
        return obj["Body"].read()

    def _delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)

    async def save(self, key: str, data: bytes) -> None:
        await asyncio.to_thread(self._put, key, data)

    async def load(self, key: str) -> bytes:
        return await asyncio.to_thread(self._get, key)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._delete, key)

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "Docsync"
    ENVIRONMENT: str = "development"  # development | production

    JWT_SECRET: str = "91875b688d09cd5e90145c50a7fa05fb7f107308ffa39df46ae6dbf21eb4b6df"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 12  # 12h token life

    # Postgres in production
    DATABASE_URL: str = "sqlite+aiosqlite:///./docsync.db"

    REDIS_URL: str = "redis://localhost:6379/0"

    STORAGE_PROVIDER: str = "local"

    AZURE_STORAGE_CONNECTION_STRING: str = ""
    AZURE_STORAGE_CONTAINER: str = "docsync-snapshots"

    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "ap-south-1"
    S3_BUCKET: str = "docsync-snapshots"

    SENTRY_DSN: str = "" 
    LOG_LEVEL: str = "INFO"

    SNAPSHOT_INTERVAL_SECONDS: int = 180  # periodic durable save while a doc has active clients

    # How long an empty room is kept alive before it's snapshotted and torn
    # down. A page refresh drops the socket and reopens it a moment later; the
    # grace period lets that reconnect land in the SAME room instead of racing
    # the teardown. Must comfortably exceed a reload round-trip.
    ROOM_GRACE_PERIOD_SECONDS: int = 15

    # How many snapshot versions to keep per document. Older ones are deleted
    # (blob + row) after each new save. The version referenced by
    # documents.latest_snapshot_id is never pruned. Set to 0 to keep every
    # version forever.
    SNAPSHOT_RETENTION_COUNT: int = 10

    CORS_ORIGINS: str = "http://localhost:5500,http://127.0.0.1:5500"
    # CORS_ORIGINS: str = "*"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

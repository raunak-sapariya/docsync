import asyncio
import os
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_tmp_db.name}"
os.environ["REDIS_URL"] = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
os.environ["STORAGE_PROVIDER"] = "local"
os.environ["JWT_SECRET"] = "test-secret-at-least-32-bytes-long-for-hs256"

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.database import Base
from app.main import app


@pytest.fixture(scope="session", autouse=True)
def schema():
    """
    Alembic owns the schema everywhere else, so the app no longer creates
    tables at startup. Tests run against a throwaway SQLite file, so build it
    straight from the models here.

    This uses its own engine and disposes it rather than app.database.engine:
    that engine's pooled connections belong to the TestClient's event loop, and
    seeding it from this one would leave connections bound to a closed loop.
    """

    # Base.metadata is populated transitively by `from app.main import app` --
    # its routers import every model. Fail loudly if that ever stops being true.
    assert Base.metadata.tables, "no models registered on Base.metadata"

    async def create() -> None:
        engine = create_async_engine(settings.DATABASE_URL)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()

    asyncio.run(create())


@pytest.fixture(scope="session")
def client(schema):
    with TestClient(app) as c:
        yield c

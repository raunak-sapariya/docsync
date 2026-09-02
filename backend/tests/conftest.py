import os
import tempfile

import pytest

# Must be set BEFORE importing the app, since app.config reads env at import time.
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_tmp_db.name}"
os.environ["REDIS_URL"] = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
os.environ["STORAGE_PROVIDER"] = "local"
os.environ["JWT_SECRET"] = "test-secret-at-least-32-bytes-long-for-hs256"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c

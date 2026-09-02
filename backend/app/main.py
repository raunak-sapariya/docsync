import asyncio
from contextlib import asynccontextmanager

import sentry_sdk
from sentry_sdk import metrics
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.logging import LoggingIntegration

from .config import settings
from .database import init_models
from .logging_config import configure_logging, get_logger
from .routers import auth as auth_router
from .routers import documents as documents_router
from .routers import permissions as permissions_router
from .websocket.editor import (
    docsync_ws_app,
    flush_pending_room_cleanups,
    periodic_snapshot_task,
    websocket_server,
)

configure_logging()
logger = get_logger("docsync.main")

if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENVIRONMENT,
        integrations=[
            FastApiIntegration(),
            AsyncioIntegration(),
            LoggingIntegration(level=None, event_level="ERROR"),
        ],
        traces_sample_rate=0.2,
        send_default_pii=False,
        enable_logs=True,
        profile_lifecycle="trace",
    )

    metrics.count("checkout.failed", 1)
    metrics.gauge("queue.depth", 42)
    metrics.distribution("cart.amount_usd", 187.5)
    logger.info("sentry_initialized")
else:
    logger.info("sentry_disabled_set_SENTRY_DSN_to_enable")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_models()
    async with websocket_server:
        snapshot_task = asyncio.create_task(periodic_snapshot_task())
        logger.info("docsync_started", extra={"event": settings.ENVIRONMENT})
        yield
        snapshot_task.cancel()

        try:
            await snapshot_task
        except asyncio.CancelledError:
            pass

        """
        Rooms still inside their post-disconnect grace period haven't been
        snapshotted yet -- save them before the server stops them.
        """
        await flush_pending_room_cleanups()
    logger.info("docsync_stopped")


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(documents_router.router)
app.include_router(permissions_router.router)

# Real-time collaborative editing: wss://host/ws/{doc_id}?token=...
app.mount("/ws", docsync_ws_app)


@app.get("/health")
async def health():
    return {"status": "ok", "app": settings.APP_NAME, "environment": settings.ENVIRONMENT}

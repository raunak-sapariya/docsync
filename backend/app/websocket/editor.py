"""
How a document's room works:
  - A client connects to  wss://host/ws/{doc_id}?token=...
  - We verify the JWT and look up the user's role for that document BEFORE
    accepting the connection. No permission row (and not the owner) -> the
    socket is closed immediately, the document is never touched.
  - Once accepted, pycrdt-websocket's YRoom takes over: it holds the shared
    Doc in memory, applies incoming CRDT updates, and broadcasts them to
    every other client in the same room. It also synchronizes "awareness"
    (cursor position, selection, presence) the same way entirely
    in-memory, no Redis round-trip needed.
  - We persist two ways: periodically (every SNAPSHOT_INTERVAL_SECONDS)
    while a room has active clients, and immediately when the last client
    leaves a room. Both call save_room_snapshot(), which encodes the room's
    entire current state as one update (room.ydoc.get_update()) and writes
    it through the storage backend (Azure Blob / S3) plus a Snapshots row.
    This is why there's no per-keystroke Operations table: Yjs's own binary
    update format already is that log, we just don't need to keep every
    individual delta once it's merged into the doc.
"""
import asyncio
from hashlib import sha256
from urllib.parse import parse_qs

from pycrdt.websocket import WebsocketServer, YRoom, exception_logger
from pycrdt.websocket.asgi_server import ASGIWebsocket
from sqlalchemy import delete as sql_delete
from sqlalchemy import select

from ..access import get_effective_role
from ..auth import get_user_from_raw_token
from ..config import settings
from ..database import SessionLocal
from ..logging_config import get_logger
from ..models import ActivityEvent, Document, EditActivity, Snapshot
from ..storage import get_storage

logger = get_logger("docsync.websocket")


async def load_latest_snapshot_bytes(doc_id: str) -> bytes | None:
    async with SessionLocal() as db:
        doc = (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one_or_none()
        if doc is None or doc.latest_snapshot_id is None:
            return None
        snap = (
            await db.execute(select(Snapshot).where(Snapshot.id == doc.latest_snapshot_id))
        ).scalar_one_or_none()
        if snap is None:
            return None
        blob_path = snap.blob_path
    try:
        return await get_storage().load(blob_path)
    except Exception:
        logger.exception("snapshot_load_failed", extra={"doc_id": doc_id})
        return None

"""
doc_id -> sha256 of the last state we wrote to storage. Lets us tell "the
document changed" from "the timer fired again", which is the difference
between a useful snapshot and a byte-identical duplicate. Hashing the encoded
update rather than comparing state vectors is deliberate: a pure deletion in
Yjs marks items as deleted without advancing any client's clock, so the state
vector can stay put across a real edit. The bytes can't.
"""
_last_saved_digest: dict[str, bytes] = {}


async def _prune_old_snapshots(doc_id: str, keep_snapshot_id: str) -> None:
    """Delete all but the newest SNAPSHOT_RETENTION_COUNT versions of a doc.

    Rows go first, then blobs: an orphaned blob is dead weight, but a row
    pointing at a blob that no longer exists is a broken document.
    """
    keep = settings.SNAPSHOT_RETENTION_COUNT
    if keep <= 0:
        return

    async with SessionLocal() as db:
        """
        Excluding the live snapshot: it's normally the newest version anyway,
        so it'd survive the offset. This makes it impossible to delete the row
        documents.latest_snapshot_id points at even if it isn't.
        """
        stale = (
            await db.execute(
                select(Snapshot)
                .where(Snapshot.document_id == doc_id, Snapshot.id != keep_snapshot_id)
                .order_by(Snapshot.version.desc())
                .offset(max(keep - 1, 0))
            )
        ).scalars().all()
        if not stale:
            return

        blob_paths = [snap.blob_path for snap in stale]
        await db.execute(sql_delete(Snapshot).where(Snapshot.id.in_([s.id for s in stale])))
        await db.commit()

    for blob_path in blob_paths:
        try:
            await get_storage().delete(blob_path)
        except Exception:
            # Because the row is already gone, so nothing reads this blob.
            logger.exception("snapshot_blob_delete_failed", extra={"doc_id": doc_id})

    logger.info("snapshots_pruned", extra={"doc_id": doc_id, "event": f"{len(blob_paths)} removed"})


async def save_room_snapshot(doc_id: str, room: YRoom) -> None:
    data = room.ydoc.get_update()
    if not data:
        return

    """
    Skip writes that would produce a duplicate of what's already stored. The
    periodic task fires on a timer regardless of activity, and the final save
    fires whenever a room empties without this, an untouched document
    collects a new version every few minutes just for being open.
    """
    digest = sha256(data).digest()
    if _last_saved_digest.get(doc_id) == digest:
        logger.debug("snapshot_skipped_unchanged", extra={"doc_id": doc_id})
        return

    async with SessionLocal() as db:
        doc = (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one_or_none()
        if doc is None:
            return
        last = (
            await db.execute(
                select(Snapshot)
                .where(Snapshot.document_id == doc_id)
                .order_by(Snapshot.version.desc())
            )
        ).scalars().first()
        version = (last.version + 1) if last else 1
        blob_path = f"{doc_id}/v{version}.bin"

        await get_storage().save(blob_path, data)

        snap = Snapshot(document_id=doc_id, version=version, blob_path=blob_path, size_bytes=len(data))
        db.add(snap)
        await db.flush()
        snap_id = snap.id
        doc.latest_snapshot_id = snap_id
        await db.commit()

    """
    Only record the digest once the write has actually committed, so a failed
    save is retried on the next tick instead of being skipped as "unchanged".
    """
    _last_saved_digest[doc_id] = digest
    logger.info("snapshot_saved", extra={"doc_id": doc_id, "event": f"v{version}"})

    await _prune_old_snapshots(doc_id, keep_snapshot_id=snap_id)


class PersistentWebsocketServer(WebsocketServer):
    """
    Same as WebsocketServer, except a freshly-created room is pre-loaded
    with the last saved snapshot instead of starting blank.
    """

    async def get_room(self, name: str) -> YRoom:
        is_new = name not in self.rooms
        room = await super().get_room(name)
        if is_new:
            snapshot_bytes = await load_latest_snapshot_bytes(name)
            if snapshot_bytes:
                """
                Seed the change detector from the doc we just restored, not
                from the snapshot bytes re-encoding can differ from what
                was stored, and it's the re-encoded form that future saves
                will be compared against. Without this, reopening a document
                and closing it again writes a duplicate of what's on disk.
                """
                room.ydoc.apply_update(snapshot_bytes)
                _last_saved_digest[name] = sha256(room.ydoc.get_update()).digest()
                logger.info("room_restored_from_snapshot", extra={"doc_id": name})
        return room


websocket_server = PersistentWebsocketServer(
    rooms_ready=True,
    auto_clean_rooms=False,  # we clean up manually, after saving
    exception_handler=exception_logger,
    log=logger,
)

"""
doc_id -> the deferred "last client left" cleanup task for that room.
See _schedule_room_cleanup below for why the teardown is deferred at all.
"""
_pending_cleanups: dict[str, asyncio.Task] = {}


async def _cleanup_room_if_still_empty(doc_id: str, room: YRoom) -> None:
    """
    Snapshot and tear down a room, but only if it's still the same room and
    still has no clients both before and after the (slow, I/O-bound) save.
    """
    try:
        await asyncio.sleep(settings.ROOM_GRACE_PERIOD_SECONDS)

        """
        Somebody reconnected during the grace period (a page refresh).
        The room is live again leave it completely alone.
        """
        if websocket_server.rooms.get(doc_id) is not room or room.clients:
            return

        try:
            await save_room_snapshot(doc_id, room)
        except Exception:
            logger.exception("final_snapshot_failed", extra={"doc_id": doc_id})

        """
        Re-check AFTER the save: save_room_snapshot awaits blob storage and
        the database, which is plenty of time for a client to join. Deleting
        the room here would cancel the room's task group and kill that
        freshly-connected client mid-session which is exactly what made
        refreshes reconnect in a loop.
        """
        if websocket_server.rooms.get(doc_id) is not room or room.clients:
            return

        await websocket_server.delete_room(name=doc_id)
        # Safe to drop: get_room() re-seeds this from the snapshot it restores when the document is next opened.
        _last_saved_digest.pop(doc_id, None)
        logger.info("room_closed", extra={"doc_id": doc_id})
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("room_cleanup_failed", extra={"doc_id": doc_id})
    finally:
        if _pending_cleanups.get(doc_id) is asyncio.current_task():
            del _pending_cleanups[doc_id]


def _cancel_pending_cleanup(doc_id: str) -> None:
    """
    Cancel any pending cleanup task for the given room.
    A client joined call off any teardown queued for this room.
    """
    task = _pending_cleanups.pop(doc_id, None)
    if task is not None and not task.done():
        task.cancel()


def _schedule_room_cleanup(doc_id: str, room: YRoom) -> None:
    _cancel_pending_cleanup(doc_id)
    _pending_cleanups[doc_id] = asyncio.create_task(_cleanup_room_if_still_empty(doc_id, room))


async def flush_pending_room_cleanups() -> None:
    """
    Called at shutdown: rooms sitting in their grace period haven't been
    snapshotted yet, and the server is about to stop them without saving.
    """
    for doc_id, task in list(_pending_cleanups.items()):
        task.cancel()
        room = websocket_server.rooms.get(doc_id)
        if room is not None and not room.clients:
            try:
                await save_room_snapshot(doc_id, room)
            except Exception:
                logger.exception("shutdown_snapshot_failed", extra={"doc_id": doc_id})
    _pending_cleanups.clear()


async def periodic_snapshot_task() -> None:
    """
    Runs for the lifetime of the app (main.py's lifespan).
    Durable save every SNAPSHOT_INTERVAL_SECONDS for any room currently
    being edited the same cadence you sketched in the original design.
    """
    while True:
        await asyncio.sleep(settings.SNAPSHOT_INTERVAL_SECONDS)
        for doc_id, room in list(websocket_server.rooms.items()):
            if room.clients:
                try:
                    await save_room_snapshot(doc_id, room)
                except Exception:
                    logger.exception("periodic_snapshot_failed", extra={"doc_id": doc_id})


async def docsync_ws_app(scope: dict, receive, send) -> None:
    """
    ASGI app rather than pycrdt-websocket's own ASGIServer wrapper,
    specifically so join/leave both run in one function
    with the doc_id and user_id in scope throughout ASGIServer's
    on_connect/on_disconnect callbacks don't share state with each other,
    which makes 'save when the last client leaves' awkward to express
    through that API. This wraps the same underlying primitives.
    """
    if scope["type"] != "websocket":
        return

    """
    Take the last path segment as doc_id rather than assuming the /ws mount
    prefix has been stripped from scope["path"].
    """
    doc_id = scope["path"].rstrip("/").rsplit("/", 1)[-1]
    query = parse_qs(scope.get("query_string", b"").decode())
    token = (query.get("token") or [None])[0]

    connect_msg = await receive()
    if connect_msg["type"] != "websocket.connect":
        return

    user = None
    role = None
    if token:
        async with SessionLocal() as db:
            user = await get_user_from_raw_token(token, db)
            if user is not None:
                role = await get_effective_role(db, doc_id, user.id)

    if user is None or role is None:
        await send({"type": "websocket.close", "code": 4401})
        logger.info("ws_rejected", extra={"doc_id": doc_id})
        return

    await send({"type": "websocket.accept"})

    """
    Do this before serving: if this connection is a refresh landing inside
    the previous one's grace period, the room is queued for teardown and we
    must call that off before we join it.
    """
    _cancel_pending_cleanup(doc_id)

    async with SessionLocal() as db:
        db.add(EditActivity(document_id=doc_id, user_id=user.id, event=ActivityEvent.join))
        await db.commit()
    logger.info("ws_join", extra={"doc_id": doc_id, "user_id": user.id})

    """
    Pass the cleaned doc_id, not the raw scope path WebsocketServer uses
    this exact string as the room name (`room = await self.get_room(websocket.path)`),
    and everything else in this function (permission checks, EditActivity, snapshot keys, the
    websocket_server.rooms.get(doc_id) lookup below) keys off doc_id too.
    They must be the same string or room lookups silently miss.
    """
    websocket = ASGIWebsocket(receive, send, doc_id)
    try:
        await websocket_server.serve(websocket)
    finally:
        async with SessionLocal() as db:
            db.add(EditActivity(document_id=doc_id, user_id=user.id, event=ActivityEvent.leave))
            await db.commit()
        logger.info("ws_leave", extra={"doc_id": doc_id, "user_id": user.id})

        room = websocket_server.rooms.get(doc_id)
        if room is not None and not room.clients:
            """
            Don't snapshot-and-delete inline. A refresh closes this socket
            and opens a new one milliseconds later; tearing the room down
            now would race that reconnect. Defer it instead and if the
            client does come back, the cleanup is cancelled and no snapshot
            is written at all.
            """
            _schedule_room_cleanup(doc_id, room)

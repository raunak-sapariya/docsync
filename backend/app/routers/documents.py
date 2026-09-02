import base64

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..access import can_edit, get_effective_role
from ..auth import get_current_user
from ..database import get_db
from ..logging_config import get_logger
from ..models import Document, EditActivity, Permission, Snapshot, User
from ..schemas import ActivityOut, DocumentContentOut, DocumentCreate, DocumentOut
from ..websocket.editor import load_latest_snapshot_bytes

router = APIRouter(prefix="/documents", tags=["documents"])
logger = get_logger("docsync.documents")


async def _doc_or_404(db: AsyncSession, doc_id: str) -> Document:
    doc = (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one_or_none()
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return doc


async def _require_role(db: AsyncSession, doc_id: str, user_id: str) -> str:
    role = await get_effective_role(db, doc_id, user_id)
    if role is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You don't have access to this document")
    return role


@router.post("", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def create_document(
    payload: DocumentCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    doc = Document(owner_id=user.id, title=payload.title)
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    logger.info("document_created", extra={"doc_id": doc.id, "user_id": user.id})
    return DocumentOut(
        id=doc.id, title=doc.title, owner_id=doc.owner_id,
        created_at=doc.created_at, updated_at=doc.updated_at, my_role="owner",
    )


@router.get("", response_model=list[DocumentOut])
async def list_documents(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    owned = (await db.execute(select(Document).where(Document.owner_id == user.id))).scalars().all()
    shared_perms = (
        await db.execute(select(Permission).where(Permission.user_id == user.id))
    ).scalars().all()
    shared_docs = []
    for perm in shared_perms:
        doc = (
            await db.execute(select(Document).where(Document.id == perm.document_id))
        ).scalar_one_or_none()
        if doc:
            shared_docs.append((doc, perm.role.value))

    results = [
        DocumentOut(
            id=d.id, title=d.title, owner_id=d.owner_id,
            created_at=d.created_at, updated_at=d.updated_at, my_role="owner",
        )
        for d in owned
    ] + [
        DocumentOut(
            id=d.id, title=d.title, owner_id=d.owner_id,
            created_at=d.created_at, updated_at=d.updated_at, my_role=role,
        )
        for d, role in shared_docs
    ]
    results.sort(key=lambda d: d.updated_at, reverse=True)
    return results


@router.get("/{doc_id}", response_model=DocumentOut)
async def get_document(
    doc_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    doc = await _doc_or_404(db, doc_id)
    role = await _require_role(db, doc_id, user.id)
    return DocumentOut(
        id=doc.id, title=doc.title, owner_id=doc.owner_id,
        created_at=doc.created_at, updated_at=doc.updated_at, my_role=role,
    )


@router.get("/{doc_id}/content", response_model=DocumentContentOut)
async def get_document_content(
    doc_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """
    Latest durable snapshot. Used for the initial paint
    while the WebSocket connects and Yjs takes over
    """
    doc = await _doc_or_404(db, doc_id)
    await _require_role(db, doc_id, user.id)

    snapshot_bytes = await load_latest_snapshot_bytes(doc_id)
    version = 0
    if doc.latest_snapshot_id:
        snap = (
            await db.execute(select(Snapshot).where(Snapshot.id == doc.latest_snapshot_id))
        ).scalar_one_or_none()
        version = snap.version if snap else 0

    return DocumentContentOut(
        id=doc.id,
        title=doc.title,
        content_b64=base64.b64encode(snapshot_bytes).decode() if snapshot_bytes else None,
        version=version,
    )


@router.patch("/{doc_id}", response_model=DocumentOut)
async def rename_document(
    doc_id: str,
    payload: DocumentCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    doc = await _doc_or_404(db, doc_id)
    role = await _require_role(db, doc_id, user.id)
    if not can_edit(role):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Viewers can't rename this document")
    doc.title = payload.title
    await db.commit()
    await db.refresh(doc)
    return DocumentOut(
        id=doc.id, title=doc.title, owner_id=doc.owner_id,
        created_at=doc.created_at, updated_at=doc.updated_at, my_role=role,
    )


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    doc_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    doc = await _doc_or_404(db, doc_id)
    if doc.owner_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the owner can delete this document")
    await db.delete(doc)
    await db.commit()
    logger.info("document_deleted", extra={"doc_id": doc_id, "user_id": user.id})


@router.get("/{doc_id}/activity", response_model=list[ActivityOut])
async def get_activity(
    doc_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    await _doc_or_404(db, doc_id)
    await _require_role(db, doc_id, user.id)

    rows = (
        await db.execute(
            select(EditActivity, User.username)
            .join(User, User.id == EditActivity.user_id)
            .where(EditActivity.document_id == doc_id)
            .order_by(EditActivity.created_at.desc())
            .limit(50)
        )
    ).all()
    return [
        ActivityOut(user_id=a.user_id, username=username, event=a.event.value, created_at=a.created_at)
        for a, username in rows
    ]

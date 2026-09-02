from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..access import can_manage_permissions, get_effective_role
from ..auth import get_current_user
from ..database import get_db
from ..logging_config import get_logger
from ..models import Document, Permission, User
from ..schemas import PermissionGrant, PermissionOut

router = APIRouter(prefix="/documents/{doc_id}/permissions", tags=["permissions"])
logger = get_logger("docsync.permissions")


async def _require_owner(db: AsyncSession, doc_id: str, user_id: str) -> None:
    doc = (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one_or_none()
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    role = await get_effective_role(db, doc_id, user_id)
    if not can_manage_permissions(role):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the owner can manage sharing")


@router.get("", response_model=list[PermissionOut])
async def list_permissions(
    doc_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    await _require_owner(db, doc_id, user.id)
    rows = (
        await db.execute(
            select(Permission, User.email)
            .join(User, User.id == Permission.user_id)
            .where(Permission.document_id == doc_id)
        )
    ).all()
    return [PermissionOut(user_id=p.user_id, email=email, role=p.role) for p, email in rows]


@router.post("", response_model=PermissionOut, status_code=status.HTTP_201_CREATED)
async def grant_permission(
    doc_id: str,
    payload: PermissionGrant,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_owner(db, doc_id, user.id)

    target = (await db.execute(select(User).where(User.email == payload.email))).scalar_one_or_none()
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No user with that email has registered yet")
    if target.id == user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You already own this document")

    existing = (
        await db.execute(
            select(Permission).where(
                Permission.document_id == doc_id, Permission.user_id == target.id
            )
        )
    ).scalar_one_or_none()
    if existing:
        existing.role = payload.role
    else:
        existing = Permission(document_id=doc_id, user_id=target.id, role=payload.role)
        db.add(existing)
    await db.commit()

    logger.info("permission_granted", extra={"doc_id": doc_id, "user_id": target.id})
    return PermissionOut(user_id=target.id, email=target.email, role=payload.role)


@router.delete("/{target_user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_permission(
    doc_id: str,
    target_user_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_owner(db, doc_id, user.id)
    perm = (
        await db.execute(
            select(Permission).where(
                Permission.document_id == doc_id, Permission.user_id == target_user_id
            )
        )
    ).scalar_one_or_none()
    if perm is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That user doesn't have access")
    await db.delete(perm)
    await db.commit()
    logger.info("permission_revoked", extra={"doc_id": doc_id, "user_id": target_user_id})

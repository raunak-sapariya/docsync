from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Document, Permission, Role


async def get_effective_role(db: AsyncSession, document_id: str, user_id: str) -> str | None:
    """Returns 'owner', a Role value ('viewer' | 'commenter' | 'editor'), or
    None if this user has no access to the document at all."""
    doc = (await db.execute(select(Document).where(Document.id == document_id))).scalar_one_or_none()
    if doc is None:
        return None
    if doc.owner_id == user_id:
        return "owner"
    perm = (
        await db.execute(
            select(Permission).where(
                Permission.document_id == document_id, Permission.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    return perm.role.value if perm else None


def can_edit(role: str | None) -> bool:
    return role in ("owner", Role.editor.value)


def can_manage_permissions(role: str | None) -> bool:
    return role == "owner"

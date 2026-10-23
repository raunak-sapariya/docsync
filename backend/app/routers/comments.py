from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..access import can_comment, get_effective_role
from ..auth import get_current_user
from ..database import get_db
from ..logging_config import get_logger
from ..models import Comment, CommentThread, Document, User
from ..schemas import CommentCreate, CommentOut, CommentThreadOut, ReplyCreate, ThreadResolve

router = APIRouter(prefix="/documents/{doc_id}/comments", tags=["comments"])
logger = get_logger("docsync.comments")


async def _read_access(db: AsyncSession, doc_id: str, user_id: str) -> str:
    """
    Reading threads only needs access to the document ,viewers included.
    Hiding existing discussion from someone who can already read the text it's
    attached to would be odd.
    """
    doc = (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one_or_none()
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    role = await get_effective_role(db, doc_id, user_id)
    if role is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You don't have access to this document")
    return role


async def _require_comment_access(db: AsyncSession, doc_id: str, user_id: str) -> str:
    """
    Writing needs at least the commenter role.
    """
    role = await _read_access(db, doc_id, user_id)
    if not can_comment(role):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Viewers can't comment on this document")
    return role


async def _thread_or_404(db: AsyncSession, doc_id: str, thread_id: str) -> CommentThread:
    thread = (
        await db.execute(
            select(CommentThread)
            .where(CommentThread.id == thread_id, CommentThread.document_id == doc_id)
            .options(selectinload(CommentThread.comments))
            # populate_existing is load-bearing, not a precaution. SessionLocal
            # sets expire_on_commit=False, so after a commit the thread is
            # still in the identity map with its comments collection marked
            # loaded ,and a plain re-query hands that cached object back
            # untouched, missing the reply that was just inserted. This forces
            # the row and the collection to be re-read.
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if thread is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment thread not found")
    return thread


async def _usernames_for(db: AsyncSession, threads: list[CommentThread]) -> dict[str, str]:
    """
    One lookup covering every author across every thread, rather than
    walking the relationship per comment and paying a query each time.
    """
    user_ids = {c.user_id for t in threads for c in t.comments}
    if not user_ids:
        return {}
    rows = (await db.execute(select(User.id, User.username).where(User.id.in_(user_ids)))).all()
    return {uid: name for uid, name in rows}


def _serialize(thread: CommentThread, usernames: dict[str, str]) -> CommentThreadOut:
    return CommentThreadOut(
        id=thread.id,
        document_id=thread.document_id,
        anchor_start=thread.anchor_start,
        anchor_end=thread.anchor_end,
        quoted_text=thread.quoted_text,
        resolved=thread.resolved_at is not None,
        resolved_at=thread.resolved_at,
        resolved_by=thread.resolved_by,
        created_at=thread.created_at,
        comments=[
            CommentOut(
                id=c.id,
                user_id=c.user_id,
                username=usernames.get(c.user_id, "unknown"),
                body=c.body,
                created_at=c.created_at,
            )
            for c in thread.comments
        ],
    )


@router.get("", response_model=list[CommentThreadOut])
async def list_threads(
    doc_id: str,
    include_resolved: bool = True,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _read_access(db, doc_id, user.id)

    query = (
        select(CommentThread)
        .where(CommentThread.document_id == doc_id)
        .options(selectinload(CommentThread.comments))
        .order_by(CommentThread.created_at)
    )
    if not include_resolved:
        query = query.where(CommentThread.resolved_at.is_(None))

    threads = list((await db.execute(query)).scalars().all())
    usernames = await _usernames_for(db, threads)
    return [_serialize(t, usernames) for t in threads]


@router.post("", response_model=CommentThreadOut, status_code=status.HTTP_201_CREATED)
async def create_thread(
    doc_id: str,
    payload: CommentCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_comment_access(db, doc_id, user.id)

    thread = CommentThread(
        document_id=doc_id,
        anchor_start=payload.anchor_start,
        anchor_end=payload.anchor_end,
        quoted_text=payload.quoted_text,
    )
    db.add(thread)
    await db.flush()
    db.add(Comment(thread_id=thread.id, user_id=user.id, body=payload.body))
    await db.commit()

    created = await _thread_or_404(db, doc_id, thread.id)
    logger.info("comment_thread_created", extra={"doc_id": doc_id, "user_id": user.id})
    return _serialize(created, await _usernames_for(db, [created]))


@router.post(
    "/{thread_id}/replies", response_model=CommentThreadOut, status_code=status.HTTP_201_CREATED
)
async def reply_to_thread(
    doc_id: str,
    thread_id: str,
    payload: ReplyCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_comment_access(db, doc_id, user.id)
    thread = await _thread_or_404(db, doc_id, thread_id)

    db.add(Comment(thread_id=thread.id, user_id=user.id, body=payload.body))
    await db.commit()

    updated = await _thread_or_404(db, doc_id, thread_id)
    logger.info("comment_reply_added", extra={"doc_id": doc_id, "user_id": user.id})
    return _serialize(updated, await _usernames_for(db, [updated]))


@router.patch("/{thread_id}", response_model=CommentThreadOut)
async def set_thread_resolved(
    doc_id: str,
    thread_id: str,
    payload: ThreadResolve,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Resolve or reopen. Anyone who can comment can do this, not only the
    thread's author: resolving is how a conversation gets closed out, and
    requiring the original author to come back and agree would leave stale
    threads pinned to the document forever.
    """
    await _require_comment_access(db, doc_id, user.id)
    thread = await _thread_or_404(db, doc_id, thread_id)

    if payload.resolved:
        # Leave an already-resolved thread alone so a second call doesn't
        # reassign credit for having resolved it.
        if thread.resolved_at is None:
            thread.resolved_at = datetime.now(timezone.utc)
            thread.resolved_by = user.id
    else:
        thread.resolved_at = None
        thread.resolved_by = None
    await db.commit()

    updated = await _thread_or_404(db, doc_id, thread_id)
    logger.info(
        "comment_thread_resolved" if payload.resolved else "comment_thread_reopened",
        extra={"doc_id": doc_id, "user_id": user.id},
    )
    return _serialize(updated, await _usernames_for(db, [updated]))


@router.delete("/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_thread(
    doc_id: str,
    thread_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Deleting a thread takes its replies with it, so it's limited to the
    person who opened it and the document's owner ,one commenter shouldn't be
    able to erase another's discussion.
    """
    await _require_comment_access(db, doc_id, user.id)
    thread = await _thread_or_404(db, doc_id, thread_id)
    doc = (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one()

    opener = thread.comments[0].user_id if thread.comments else None
    if user.id != opener and user.id != doc.owner_id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the thread's author or the document owner can delete it",
        )

    await db.delete(thread)
    await db.commit()
    logger.info("comment_thread_deleted", extra={"doc_id": doc_id, "user_id": user.id})


@router.delete("/{thread_id}/replies/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(
    doc_id: str,
    thread_id: str,
    comment_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete a single message. Authors can remove their own, the document
    owner can remove anyone's. Removing the message that opened the thread
    would leave its replies anchored to nothing, so that one goes through
    delete_thread instead.
    """
    await _require_comment_access(db, doc_id, user.id)
    thread = await _thread_or_404(db, doc_id, thread_id)
    doc = (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one()

    comment = next((c for c in thread.comments if c.id == comment_id), None)
    if comment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found")
    if comment.id == thread.comments[0].id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "That comment opened the thread -- delete the thread instead",
        )
    if user.id != comment.user_id and user.id != doc.owner_id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the comment's author or the document owner can delete it",
        )

    await db.delete(comment)
    await db.commit()
    logger.info("comment_deleted", extra={"doc_id": doc_id, "user_id": user.id})

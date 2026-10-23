import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Role(str, enum.Enum):
    viewer = "viewer"
    commenter = "commenter"
    editor = "editor"


class ActivityEvent(str, enum.Enum):
    join = "join"
    leave = "leave"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    owned_documents: Mapped[list["Document"]] = relationship(back_populates="owner")
    permissions: Mapped[list["Permission"]] = relationship(back_populates="user")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(255), default="Untitled document")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    latest_snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("snapshots.id", use_alter=True, name="fk_latest_snapshot"), nullable=True
    )

    owner: Mapped["User"] = relationship(back_populates="owned_documents", foreign_keys=[owner_id])
    permissions: Mapped[list["Permission"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    snapshots: Mapped[list["Snapshot"]] = relationship(
        back_populates="document", foreign_keys="Snapshot.document_id", cascade="all, delete-orphan"
    )
    activity: Mapped[list["EditActivity"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    comment_threads: Mapped[list["CommentThread"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.viewer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped["Document"] = relationship(back_populates="permissions")
    user: Mapped["User"] = relationship(back_populates="permissions")


class Snapshot(Base):
    __tablename__ = "snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    blob_path: Mapped[str] = mapped_column(String(500))  # key inside Azure Blob / S3
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[str] = mapped_column(String(50), default="system")  # 'system' = autosave

    document: Mapped["Document"] = relationship(back_populates="snapshots", foreign_keys=[document_id])


class EditActivity(Base):
    __tablename__ = "edit_activity"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    event: Mapped[ActivityEvent] = mapped_column(Enum(ActivityEvent))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped["Document"] = relationship(back_populates="activity")
    user: Mapped["User"] = relationship()


class CommentThread(Base):
    """
    One conversation pinned to a range of a document.

    The anchor is a pair of Yjs *relative* positions (base64-encoded), not
    integer offsets. A relative position names a place in the CRDT's item
    graph rather than a character count, so it keeps pointing at the same
    words while other people insert and delete text above it. Plain offsets
    would silently drift the moment anyone edited earlier in the document
    the comment would still render, just attached to the wrong sentence.

    The anchor and the resolved state live here rather than on individual
    comments because they describe the conversation, not any one message in
    it. Replies are just Comment rows sharing a thread_id.
    """

    __tablename__ = "comment_threads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    anchor_start: Mapped[str] = mapped_column(String(512))
    anchor_end: Mapped[str] = mapped_column(String(512))
    # The text that was selected when the thread was opened. Kept so an
    # "orphaned" thread ,one whose anchor no longer resolves because the
    # text it referred to was deleted ,can still show what it was about.
    quoted_text: Mapped[str] = mapped_column(String(300), default="")
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped["Document"] = relationship(back_populates="comment_threads")
    comments: Mapped[list["Comment"]] = relationship(
        back_populates="thread",
        cascade="all, delete-orphan",
        order_by="Comment.created_at",
    )


class Comment(Base):
    """
    A single message in a CommentThread. The first one is the comment that
    opened the thread; the rest are replies. The WebSocket room can only
    enforce permissions at connection time, so anything written into the CRDT
    is editable by anyone allowed to join. Keeping comments out of it is what
    makes 'commenter' a role the server can actually enforce ,a commenter
    writes here and is refused by /documents, instead of being merely asked
    not to type by a read-only editor.
    """

    __tablename__ = "comments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    thread_id: Mapped[str] = mapped_column(ForeignKey("comment_threads.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    thread: Mapped["CommentThread"] = relationship(back_populates="comments")
    user: Mapped["User"] = relationship()

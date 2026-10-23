from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from .models import Role

# auth
class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    username: str
    email: EmailStr


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# documents
class DocumentCreate(BaseModel):
    title: str = "Untitled document"


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    owner_id: str
    created_at: datetime
    updated_at: datetime
    my_role: str  # owner | editor | commenter | viewer


class DocumentContentOut(BaseModel):
    """
    Latest saved snapshot, base64-encoded, for the read-only initial paint
    before the WebSocket takes over.
    """

    id: str
    title: str
    content_b64: str | None
    version: int


# permissions
class PermissionGrant(BaseModel):
    email: EmailStr
    role: Role


class PermissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: str
    email: str
    role: Role


# comments
class CommentCreate(BaseModel):
    """Opening a new thread: the body plus where in the document it points.
    The anchors are base64-encoded Yjs relative positions produced by the
    client -- the server stores them verbatim and never interprets them, since
    resolving one back to a character offset needs the live Y.Doc."""

    body: str = Field(min_length=1, max_length=5000)
    anchor_start: str = Field(min_length=1, max_length=512)
    anchor_end: str = Field(min_length=1, max_length=512)
    quoted_text: str = Field(default="", max_length=300)


class ReplyCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class ThreadResolve(BaseModel):
    resolved: bool


class CommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    user_id: str
    username: str
    body: str
    created_at: datetime


class CommentThreadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    document_id: str
    anchor_start: str
    anchor_end: str
    quoted_text: str
    resolved: bool
    resolved_at: datetime | None
    resolved_by: str | None
    created_at: datetime
    comments: list[CommentOut]


# activity
class ActivityOut(BaseModel):
    user_id: str
    username: str
    event: str
    created_at: datetime

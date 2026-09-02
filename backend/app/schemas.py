from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr

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


# activity
class ActivityOut(BaseModel):
    user_id: str
    username: str
    event: str
    created_at: datetime

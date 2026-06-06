from datetime import datetime
from pydantic import BaseModel, ConfigDict


class MediaBase(BaseModel):
    title: str
    description: str | None = None
    tags: str | None = None
    uploader: str | None = "Guest"
    sale_status: str = "showcase"
    fixed_price: int | None = None
    min_price: int | None = None
    max_price: int | None = None


class MediaCreate(MediaBase):
    media_type: str


class MediaRead(MediaBase):
    id: int
    filename: str
    media_type: str
    views: int
    created_at: datetime
    artwork_status: str = "available"

    model_config = ConfigDict(from_attributes=True)


class UserCreate(BaseModel):
    username: str
    email: str | None = None
    password: str


class UserRead(BaseModel):
    id: int
    username: str
    email: str | None = None
    avatar: str | None = None
    bio: str | None = None
    is_admin: bool = False

    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class CommentCreate(BaseModel):
    media_id: int
    text: str


class CommentRead(BaseModel):
    id: int
    media_id: int
    user_id: int | None
    name: str
    text: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)



class PostCreate(BaseModel):
    title: str
    content: str
    published: bool = True


class PostRead(BaseModel):
    id: int
    title: str
    slug: str
    content: str
    author: str
    author_id: int | None
    published: bool
    created_at: datetime
    updated_at: datetime | None

    model_config = ConfigDict(from_attributes=True)
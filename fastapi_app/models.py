from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean
from .database import Base


class MediaItem(Base):
    __tablename__ = "media_items"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(140), nullable=False, index=True)
    description = Column(Text, nullable=True)
    tags = Column(String(255), nullable=True, index=True)
    filename = Column(String(255), nullable=False, unique=True)
    media_type = Column(String(20), nullable=False)
    uploader = Column(String(80), nullable=False, default="Guest")
    uploader_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    views = Column(Integer, default=0)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(80), unique=True, nullable=False, index=True)
    email = Column(String(200), unique=True, nullable=True)
    hashed_password = Column(String(200), nullable=False)
    avatar = Column(String(255), nullable=True)
    bio = Column(Text, nullable=True)
    is_admin = Column(Boolean, default=False, nullable=False)
    is_banned = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Comment(Base):
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True, index=True)
    media_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, nullable=True)
    name = Column(String(120), nullable=False)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Like(Base):
    __tablename__ = "likes"

    id = Column(Integer, primary_key=True, index=True)
    media_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, nullable=False, index=True)


class Post(Base):
    __tablename__ = "posts"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False, index=True)
    slug = Column(String(220), nullable=False, unique=True, index=True)
    content = Column(Text, nullable=False)
    author = Column(String(80), nullable=False)
    author_id = Column(Integer, nullable=True)
    published = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Follow(Base):
    __tablename__ = "follows"

    id = Column(Integer, primary_key=True, index=True)
    follower_id = Column(Integer, nullable=False, index=True)
    followed_id = Column(Integer, nullable=False, index=True)


class Saved(Base):
    __tablename__ = "saved"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    media_id = Column(Integer, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)   # recipient
    actor_id = Column(Integer, nullable=False)               # who triggered it
    kind = Column(String(20), nullable=False)                # 'follow', 'like', 'comment'
    media_id = Column(Integer, nullable=True)                # for like/comment
    is_read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
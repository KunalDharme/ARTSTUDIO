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
    sale_status = Column(String(20), nullable=False, default="showcase")  # showcase | fixed | negotiable
    fixed_price = Column(Integer, nullable=True)       # in smallest currency unit (paise / cents)
    min_price = Column(Integer, nullable=True)
    max_price = Column(Integer, nullable=True)
    artwork_status = Column(String(20), nullable=False, default="available")  # available | reserved | sold


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
    whatsapp = Column(String(30), nullable=True)
    telegram = Column(String(60), nullable=True)
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


class BuyRequest(Base):
    __tablename__ = "buy_requests"

    id = Column(Integer, primary_key=True, index=True)
    media_id = Column(Integer, nullable=False, index=True)
    buyer_id = Column(Integer, nullable=False, index=True)
    offer_price = Column(Integer, nullable=True)
    message = Column(String(300), nullable=True)
    purchase_type = Column(String(30), default="original")  # original | print | commission
    status = Column(String(20), default="pending")          # pending | accepted | rejected | cancelled
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Deal(Base):
    __tablename__ = "deals"

    id = Column(Integer, primary_key=True, index=True)
    buy_request_id = Column(Integer, nullable=False, unique=True, index=True)
    media_id = Column(Integer, nullable=False, index=True)
    buyer_id = Column(Integer, nullable=False, index=True)
    artist_id = Column(Integer, nullable=False, index=True)
    current_price = Column(Integer, nullable=True)
    last_actor_id = Column(Integer, nullable=True)   # who made the last offer/counter
    status = Column(String(30), default="negotiating")   # negotiating | agreed | buyer_confirmed | artist_confirmed | completed | cancelled
    buyer_confirmed = Column(Boolean, default=False)
    artist_confirmed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DealEvent(Base):
    __tablename__ = "deal_events"

    id = Column(Integer, primary_key=True, index=True)
    deal_id = Column(Integer, nullable=False, index=True)
    actor_id = Column(Integer, nullable=False)
    kind = Column(String(30), nullable=False)
    # offer | counter | question | answer | accept_price | cancel | deal_created | buyer_confirmed | artist_confirmed | completed
    amount = Column(Integer, nullable=True)              # for offer/counter events
    message = Column(String(200), nullable=True)         # optional note
    created_at = Column(DateTime, default=datetime.utcnow)
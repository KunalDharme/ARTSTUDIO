from sqlalchemy import or_
from sqlalchemy.orm import Session
from datetime import datetime
from . import models, schemas
from passlib.context import CryptContext
from passlib.exc import UnknownHashError
from sqlalchemy import func, desc

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(plain, hashed)
    except UnknownHashError:
        return plain == hashed


def get_media_item(db: Session, media_id: int) -> models.MediaItem | None:
    return db.query(models.MediaItem).filter(models.MediaItem.id == media_id).first()


def _normalize_tags(tags: str | None) -> str | None:
    if not tags:
        return None
    cleaned = [tag.strip().lower() for tag in tags.split(",") if tag.strip()]
    normalized = ", ".join(dict.fromkeys(cleaned))
    return normalized if normalized else None


def get_media_list(db: Session, search: str | None = None, tag: str | None = None) -> list[models.MediaItem]:
    query = db.query(models.MediaItem).order_by(models.MediaItem.created_at.desc())
    if search:
        search_term = f"%{search.strip()}%"
        query = query.filter(
            models.MediaItem.title.ilike(search_term)
            | models.MediaItem.description.ilike(search_term)
            | models.MediaItem.uploader.ilike(search_term)
            | models.MediaItem.tags.ilike(search_term)
        )
    if tag:
        tag_term = f"%{tag.strip().lower()}%"
        query = query.filter(models.MediaItem.tags.ilike(tag_term))
    return query.all()


def _apply_sort(query, sort: str | None = None):
    if sort == "popular":
        return query.order_by(models.MediaItem.views.desc(), models.MediaItem.created_at.desc())
    if sort == "oldest":
        return query.order_by(models.MediaItem.created_at.asc())
    return query.order_by(models.MediaItem.created_at.desc())


def get_media_page(
    db: Session,
    search: str | None = None,
    tag: str | None = None,
    page: int = 1,
    page_size: int = 12,
    sort: str | None = None,
) -> tuple[list[models.MediaItem], int]:
    query = db.query(models.MediaItem)
    if search:
        search_term = f"%{search.strip()}%"
        query = query.filter(
            models.MediaItem.title.ilike(search_term)
            | models.MediaItem.description.ilike(search_term)
            | models.MediaItem.uploader.ilike(search_term)
            | models.MediaItem.tags.ilike(search_term)
        )
    if tag:
        tag_term = f"%{tag.strip().lower()}%"
        query = query.filter(models.MediaItem.tags.ilike(tag_term))
    total = query.count()
    query = _apply_sort(query, sort)
    if page < 1:
        page = 1
    if page_size:
        query = query.limit(page_size).offset((page - 1) * page_size)
    return query.all(), total


def get_trending_media(db: Session, limit: int = 6) -> list[models.MediaItem]:
    return (
        db.query(models.MediaItem)
        .order_by(models.MediaItem.views.desc(), models.MediaItem.created_at.desc())
        .limit(limit)
        .all()
    )


def get_related_media(db: Session, media_item: models.MediaItem, limit: int = 6) -> list[models.MediaItem]:
    query = db.query(models.MediaItem).filter(models.MediaItem.id != media_item.id)
    if media_item.tags:
        terms = [tag.strip() for tag in media_item.tags.split(",") if tag.strip()]
        filters = [models.MediaItem.tags.ilike(f"%{term.lower()}%") for term in terms]
        query = query.filter(or_(*filters))
    else:
        query = query.filter(models.MediaItem.uploader == media_item.uploader)
    return query.order_by(models.MediaItem.views.desc(), models.MediaItem.created_at.desc()).limit(limit).all()


def get_media_for_user(db: Session, user_id: int) -> list[models.MediaItem]:
    return (
        db.query(models.MediaItem)
        .filter(models.MediaItem.uploader_id == user_id)
        .order_by(models.MediaItem.created_at.desc())
        .all()
    )


def get_liked_media(db: Session, user_id: int) -> list[models.MediaItem]:
    return (
        db.query(models.MediaItem)
        .join(models.Like, models.Like.media_id == models.MediaItem.id)
        .filter(models.Like.user_id == user_id)
        .order_by(models.MediaItem.created_at.desc())
        .all()
    )


def create_media_item(db: Session, media: schemas.MediaCreate, filename: str, uploader_id: int | None = None) -> models.MediaItem:
    db_item = models.MediaItem(
        title=media.title,
        description=media.description,
        tags=_normalize_tags(media.tags),
        filename=filename,
        media_type=media.media_type,
        uploader=media.uploader or "Guest",
        uploader_id=uploader_id,
        sale_status=media.sale_status or "showcase",
        fixed_price=media.fixed_price,
        min_price=media.min_price,
        max_price=media.max_price,
        created_at=datetime.utcnow(),
    )
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item


def update_media_item(db: Session, media_item: models.MediaItem, title: str, description: str | None, tags: str | None) -> models.MediaItem:
    media_item.title = title
    media_item.description = description
    media_item.tags = _normalize_tags(tags)
    db.add(media_item)
    db.commit()
    db.refresh(media_item)
    return media_item


def delete_media_item(db: Session, media_item: models.MediaItem) -> None:
    db.query(models.Comment).filter(models.Comment.media_id == media_item.id).delete()
    db.query(models.Like).filter(models.Like.media_id == media_item.id).delete()
    db.delete(media_item)
    db.commit()


def increment_media_views(db: Session, media_item: models.MediaItem) -> models.MediaItem:
    media_item.views += 1
    db.add(media_item)
    db.commit()
    db.refresh(media_item)
    return media_item


# ----------------- Users -----------------
def create_user(db: Session, username: str, password: str, email: str | None = None, is_admin: bool = False) -> models.User:
    hashed = get_password_hash(password)
    user = models.User(username=username, email=email, hashed_password=hashed, is_admin=is_admin)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_user_by_username(db: Session, username: str) -> models.User | None:
    return db.query(models.User).filter(models.User.username == username).first()


def get_all_users(db: Session) -> list[models.User]:
    return db.query(models.User).order_by(models.User.created_at.desc()).all()


def set_user_admin(db: Session, username: str, is_admin: bool) -> models.User | None:
    user = get_user_by_username(db, username)
    if not user:
        return None
    user.is_admin = is_admin
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def set_user_banned(db: Session, username: str, is_banned: bool) -> models.User | None:
    user = get_user_by_username(db, username)
    if not user:
        return None
    user.is_banned = is_banned
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_site_stats(db: Session) -> dict:
    total_users = db.query(models.User).count()
    total_media = db.query(models.MediaItem).count()
    total_posts = db.query(models.Post).count()
    total_comments = db.query(models.Comment).count()
    total_likes = db.query(models.Like).count()
    banned_users = db.query(models.User).filter(models.User.is_banned == True).count()
    return {
        "total_users": total_users,
        "total_media": total_media,
        "total_posts": total_posts,
        "total_comments": total_comments,
        "total_likes": total_likes,
        "banned_users": banned_users,
    }


def get_all_media_admin(db: Session, page: int = 1, page_size: int = 20) -> tuple[list[models.MediaItem], int]:
    query = db.query(models.MediaItem).order_by(models.MediaItem.created_at.desc())
    total = query.count()
    items = query.limit(page_size).offset((page - 1) * page_size).all()
    return items, total


def get_all_posts_admin(db: Session, page: int = 1, page_size: int = 20) -> tuple[list[models.Post], int]:
    query = db.query(models.Post).order_by(models.Post.created_at.desc())
    total = query.count()
    items = query.limit(page_size).offset((page - 1) * page_size).all()
    return items, total


def get_all_comments_admin(db: Session, page: int = 1, page_size: int = 30) -> tuple[list[models.Comment], int]:
    query = db.query(models.Comment).order_by(models.Comment.created_at.desc())
    total = query.count()
    items = query.limit(page_size).offset((page - 1) * page_size).all()
    return items, total


def authenticate_user(db: Session, username: str, password: str) -> models.User | None:
    user = get_user_by_username(db, username)
    if not user:
        return None
    if getattr(user, "is_banned", False):
        return None
    if verify_password(password, user.hashed_password):
        try:
            # Upgrade legacy plain-text passwords to secure hashes automatically.
            if pwd_context.identify(user.hashed_password) is None:
                user.hashed_password = get_password_hash(password)
                db.add(user)
                db.commit()
                db.refresh(user)
        except Exception:
            pass
        return user
    return None


# ----------------- Comments & Likes -----------------
def create_comment(db: Session, media_id: int, name: str, text: str, user_id: int | None = None) -> models.Comment:
    c = models.Comment(media_id=media_id, user_id=user_id, name=name, text=text)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def get_comments_for_media(db: Session, media_id: int) -> list[models.Comment]:
    return db.query(models.Comment).filter(models.Comment.media_id == media_id).order_by(models.Comment.created_at.desc()).all()


def delete_comment(db: Session, comment_id: int) -> None:
    db.query(models.Comment).filter(models.Comment.id == comment_id).delete()
    db.commit()


def toggle_like(db: Session, media_id: int, user_id: int) -> bool:
    existing = db.query(models.Like).filter(models.Like.media_id == media_id, models.Like.user_id == user_id).first()
    if existing:
        db.delete(existing)
        db.commit()
        return False
    like = models.Like(media_id=media_id, user_id=user_id)
    db.add(like)
    db.commit()
    return True


def count_likes(db: Session, media_id: int) -> int:
    return db.query(models.Like).filter(models.Like.media_id == media_id).count()


def user_liked(db: Session, media_id: int, user_id: int) -> bool:
    return db.query(models.Like).filter(models.Like.media_id == media_id, models.Like.user_id == user_id).count() > 0


# ----------------- Posts -----------------
def _slugify(title: str) -> str:
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:200]


def create_post(db: Session, post: schemas.PostCreate, author: str, author_id: int | None = None) -> models.Post:
    slug_base = _slugify(post.title)
    slug = slug_base
    idx = 1
    while db.query(models.Post).filter(models.Post.slug == slug).first():
        idx += 1
        slug = f"{slug_base}-{idx}"

    p = models.Post(
        title=post.title,
        slug=slug,
        content=post.content,
        author=author,
        author_id=author_id,
        published=post.published,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def get_post(db: Session, post_id: int) -> models.Post | None:
    return db.query(models.Post).filter(models.Post.id == post_id).first()


def get_post_by_slug(db: Session, slug: str) -> models.Post | None:
    return db.query(models.Post).filter(models.Post.slug == slug).first()


def update_post(db: Session, post_item: models.Post, title: str, content: str, published: bool) -> models.Post:
    post_item.title = title
    post_item.content = content
    post_item.published = published
    db.add(post_item)
    db.commit()
    db.refresh(post_item)
    return post_item


def delete_post(db: Session, post_item: models.Post) -> None:
    db.delete(post_item)
    db.commit()


def list_posts(db: Session, limit: int = 20) -> list[models.Post]:
    return db.query(models.Post).order_by(models.Post.created_at.desc()).limit(limit).all()


# ----------------- Follows / Feed -----------------
def follow_user(db: Session, follower_id: int, followed_id: int) -> bool:
    if follower_id == followed_id:
        return False
    exists = db.query(models.Follow).filter(models.Follow.follower_id == follower_id, models.Follow.followed_id == followed_id).first()
    if exists:
        return False
    f = models.Follow(follower_id=follower_id, followed_id=followed_id)
    db.add(f)
    db.commit()
    return True


def unfollow_user(db: Session, follower_id: int, followed_id: int) -> bool:
    deleted = db.query(models.Follow).filter(models.Follow.follower_id == follower_id, models.Follow.followed_id == followed_id).delete()
    db.commit()
    return deleted > 0


def get_following_ids(db: Session, user_id: int) -> list[int]:
    rows = db.query(models.Follow).filter(models.Follow.follower_id == user_id).all()
    return [r.followed_id for r in rows]


def count_followers(db: Session, user_id: int) -> int:
    return db.query(models.Follow).filter(models.Follow.followed_id == user_id).count()


def count_following(db: Session, user_id: int) -> int:
    return db.query(models.Follow).filter(models.Follow.follower_id == user_id).count()


def is_following(db: Session, follower_id: int, followed_id: int) -> bool:
    return db.query(models.Follow).filter(models.Follow.follower_id == follower_id, models.Follow.followed_id == followed_id).count() > 0


def get_follow_suggestions(db: Session, user_id: int | None, limit: int = 5) -> list[dict]:
    """
    Suggest users to follow for `user_id`.
    Returns list of dicts: {user: models.User, followers: int}
    """
    # If no user (anonymous), suggest top users by followers
    query = db.query(models.User, func.count(models.Follow.id).label("followers_count")).outerjoin(
        models.Follow, models.Follow.followed_id == models.User.id
    )
    if user_id:
        # exclude self and already-followed
        followed_ids = get_following_ids(db, user_id)
        exclude_ids = followed_ids + [user_id]
        if exclude_ids:
            query = query.filter(~models.User.id.in_(exclude_ids))
    query = query.group_by(models.User.id).order_by(desc("followers_count"))
    rows = query.limit(limit).all()
    suggestions = []
    for user, followers_count in rows:
        suggestions.append({
            "id": user.id,
            "username": user.username,
            "bio": getattr(user, "bio", None),
            "avatar": getattr(user, "avatar", None),
            "followers": int(followers_count or 0),
        })
    return suggestions


def get_personal_feed(db: Session, user_id: int | None, limit: int = 20) -> list[models.Post]:
    # if no user, return latest public posts
    query = db.query(models.Post).filter(models.Post.published == True)
    if user_id:
        ids = get_following_ids(db, user_id)
        if ids:
            query = query.filter(models.Post.author_id.in_(ids))
        else:
            # no follows: return recent posts
            pass
    return query.order_by(models.Post.created_at.desc()).limit(limit).all()


# ----------------- Saved -----------------
def toggle_saved(db: Session, media_id: int, user_id: int) -> bool:
    """Returns True if now saved, False if unsaved."""
    existing = db.query(models.Saved).filter(
        models.Saved.media_id == media_id,
        models.Saved.user_id == user_id
    ).first()
    if existing:
        db.delete(existing)
        db.commit()
        return False
    saved = models.Saved(media_id=media_id, user_id=user_id)
    db.add(saved)
    db.commit()
    return True


def is_saved(db: Session, media_id: int, user_id: int) -> bool:
    return db.query(models.Saved).filter(
        models.Saved.media_id == media_id,
        models.Saved.user_id == user_id
    ).count() > 0


def get_saved_media(db: Session, user_id: int) -> list[models.MediaItem]:
    return (
        db.query(models.MediaItem)
        .join(models.Saved, models.Saved.media_id == models.MediaItem.id)
        .filter(models.Saved.user_id == user_id)
        .order_by(models.Saved.created_at.desc())
        .all()
    )


def get_saved_ids(db: Session, user_id: int) -> set[int]:
    rows = db.query(models.Saved.media_id).filter(models.Saved.user_id == user_id).all()
    return {r.media_id for r in rows}


def get_liked_ids(db: Session, user_id: int) -> set[int]:
    rows = db.query(models.Like.media_id).filter(models.Like.user_id == user_id).all()
    return {r.media_id for r in rows}


# ----------------- Notifications -----------------
def create_notification(db: Session, user_id: int, actor_id: int, kind: str, media_id: int | None = None) -> None:
    """Create a notification, skip if actor == recipient or duplicate within 60s."""
    if user_id == actor_id:
        return
    # Deduplicate: don't spam same action within 60 seconds
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(seconds=60)
    exists = db.query(models.Notification).filter(
        models.Notification.user_id == user_id,
        models.Notification.actor_id == actor_id,
        models.Notification.kind == kind,
        models.Notification.media_id == media_id,
        models.Notification.created_at >= cutoff,
    ).first()
    if exists:
        return
    n = models.Notification(user_id=user_id, actor_id=actor_id, kind=kind, media_id=media_id)
    db.add(n)
    db.commit()


def get_notifications(db: Session, user_id: int, limit: int = 30) -> list[models.Notification]:
    return (
        db.query(models.Notification)
        .filter(models.Notification.user_id == user_id)
        .order_by(models.Notification.created_at.desc())
        .limit(limit)
        .all()
    )


def count_unread_notifications(db: Session, user_id: int) -> int:
    return db.query(models.Notification).filter(
        models.Notification.user_id == user_id,
        models.Notification.is_read == False,
    ).count()


def mark_notifications_read(db: Session, user_id: int) -> None:
    db.query(models.Notification).filter(
        models.Notification.user_id == user_id,
        models.Notification.is_read == False,
    ).update({"is_read": True})
    db.commit()


def delete_read_notifications(db: Session, user_id: int) -> None:
    """Called on logout — clears already-read notifications."""
    db.query(models.Notification).filter(
        models.Notification.user_id == user_id,
        models.Notification.is_read == True,
    ).delete()
    db.commit()


# ----------------- Buy Requests -----------------
def create_buy_request(
    db: Session,
    media_id: int,
    buyer_id: int,
    offer_price: int | None,
    message: str | None,
    purchase_type: str = "original",
) -> models.BuyRequest:
    req = models.BuyRequest(
        media_id=media_id,
        buyer_id=buyer_id,
        offer_price=offer_price,
        message=message,
        purchase_type=purchase_type,
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    return req


def get_buy_request(db: Session, request_id: int) -> models.BuyRequest | None:
    return db.query(models.BuyRequest).filter(models.BuyRequest.id == request_id).first()


def get_requests_for_artist(db: Session, user_id: int) -> list[models.BuyRequest]:
    """All buy requests for media owned by this user."""
    media_ids = db.query(models.MediaItem.id).filter(models.MediaItem.uploader_id == user_id).subquery()
    return (
        db.query(models.BuyRequest)
        .filter(models.BuyRequest.media_id.in_(media_ids))
        .order_by(models.BuyRequest.created_at.desc())
        .all()
    )


def get_requests_by_buyer(db: Session, buyer_id: int) -> list[models.BuyRequest]:
    return (
        db.query(models.BuyRequest)
        .filter(models.BuyRequest.buyer_id == buyer_id)
        .order_by(models.BuyRequest.created_at.desc())
        .all()
    )


def has_pending_request(db: Session, media_id: int, buyer_id: int) -> bool:
    return db.query(models.BuyRequest).filter(
        models.BuyRequest.media_id == media_id,
        models.BuyRequest.buyer_id == buyer_id,
        models.BuyRequest.status.in_(["pending", "accepted"]),
    ).count() > 0


def update_request_status(db: Session, request_id: int, status: str) -> models.BuyRequest | None:
    req = get_buy_request(db, request_id)
    if not req:
        return None
    req.status = status
    db.add(req)
    db.commit()
    db.refresh(req)
    return req
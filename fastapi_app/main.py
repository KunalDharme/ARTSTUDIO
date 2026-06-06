import os
import shutil
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, Depends, Request, Form, UploadFile, File, HTTPException, Response
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.exception_handlers import http_exception_handler
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy.orm import Session
from starlette.status import HTTP_303_SEE_OTHER
from jose import JWTError, jwt
from markdown import markdown as md_to_html
import bleach
from jinja2 import Environment, FileSystemLoader

from . import crud, models, schemas
from .database import SessionLocal, engine, init_db
from werkzeug.utils import secure_filename

# Simple JWT settings (keep secret safe in env for production)
SECRET_KEY = os.environ.get("FASTAPI_SECRET_KEY", "change-me-please")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
ALLOWED_PHOTO_TYPES = {"image/png", "image/jpeg", "image/gif"}
ALLOWED_VIDEO_TYPES = {"video/mp4", "video/webm"}
PAGE_SIZE = 12

init_db()

app = FastAPI(title="FastAPI Media Portal")
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

template_dir = os.path.join(BASE_DIR, "templates")
templates = Jinja2Templates(
    env=Environment(loader=FileSystemLoader(template_dir), cache_size=0),
)


@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    db = SessionLocal()
    try:
        current_user = get_current_user(request, db)
        if exc.status_code == 404:
            tpl = templates.env.get_template("404.html")
            content = tpl.render({"request": request, "current_user": current_user, "flash": None})
            return Response(content, status_code=404, media_type="text/html")
        if exc.status_code == 403:
            tpl = templates.env.get_template("error.html")
            content = tpl.render({"request": request, "current_user": current_user, "flash": None,
                                  "status_code": 403, "detail": "You don't have permission to do that."})
            return Response(content, status_code=403, media_type="text/html")
        tpl = templates.env.get_template("error.html")
        content = tpl.render({"request": request, "current_user": current_user, "flash": None,
                              "status_code": exc.status_code, "detail": str(exc.detail)})
        return Response(content, status_code=exc.status_code, media_type="text/html")
    except Exception:
        return Response(f"<h1>{exc.status_code}</h1><p>{exc.detail}</p>", status_code=exc.status_code, media_type="text/html")
    finally:
        db.close()


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    import traceback
    tb = traceback.format_exc()
    try:
        with open(os.path.join(BASE_DIR, "last_error.log"), "a", encoding="utf-8") as f:
            f.write(f"--- Unhandled error ---\n{tb}\n")
    except Exception:
        pass
    db = SessionLocal()
    try:
        current_user = get_current_user(request, db)
        tpl = templates.env.get_template("error.html")
        content = tpl.render({"request": request, "current_user": current_user, "flash": None,
                              "status_code": 500, "detail": "Something went wrong on our end."})
        return Response(content, status_code=500, media_type="text/html")
    except Exception:
        return Response("<h1>500 Internal Server Error</h1>", status_code=500, media_type="text/html")
    finally:
        db.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def get_current_user(request: Request, db: Session = Depends(get_db)) -> Optional[models.User]:
    token = None
    # support cookie or Authorization header
    if "access_token" in request.cookies:
        token = request.cookies.get("access_token")
    else:
        auth = request.headers.get("Authorization")
        if auth and auth.startswith("Bearer "):
            token = auth.split(" ", 1)[1]

    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            return None
    except JWTError:
        return None
    user = crud.get_user_by_username(db, username)
    return user


import json as _json

FLASH_COOKIE = "_flash"

def set_flash(response: Response, message: str, category: str = "info") -> None:
    """Store a single flash message in a short-lived cookie."""
    payload = _json.dumps({"msg": message, "cat": category})
    response.set_cookie(FLASH_COOKIE, payload, max_age=10, httponly=True, samesite="lax")


def get_flash(request: Request) -> dict | None:
    """Read and return the flash cookie payload (consumed once by render_template)."""
    raw = request.cookies.get(FLASH_COOKIE)
    if not raw:
        return None
    try:
        return _json.loads(raw)
    except Exception:
        return None


def redirect_with_flash(url: str, message: str, category: str = "info") -> RedirectResponse:
    resp = RedirectResponse(url=url, status_code=HTTP_303_SEE_OTHER)
    set_flash(resp, message, category)
    return resp


def render_template(request: Request, template_name: str, db: Session, **context):
    current_user = get_current_user(request, db)
    flash = get_flash(request)
    unread_notifications = crud.count_unread_notifications(db, current_user.id) if current_user else 0
    try:
        tpl = templates.env.get_template(template_name)
        content = tpl.render({
            "request": request,
            "current_user": current_user,
            "flash": flash,
            "unread_notifications": unread_notifications,
            **context,
        })
        resp = Response(content, media_type="text/html")
        if flash:
            resp.delete_cookie(FLASH_COOKIE)
        return resp
    except Exception:
        import traceback
        tb = traceback.format_exc()
        try:
            with open(os.path.join(BASE_DIR, "last_error.log"), "a", encoding="utf-8") as f:
                f.write(f"--- Template error: {template_name} ---\n")
                f.write(tb)
                f.write("\n")
        except Exception:
            pass
        raise


@app.on_event("startup")
def startup_event():
    os.makedirs(UPLOAD_DIR, exist_ok=True)


@app.get("/")
def home(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    latest_media = crud.get_media_list(db)[:6]
    trending_media = crud.get_trending_media(db, limit=6)
    total_items = len(crud.get_media_list(db))
    suggestions = crud.get_follow_suggestions(db, current_user.id if current_user else None, limit=6)
    liked_ids = crud.get_liked_ids(db, current_user.id) if current_user else set()
    saved_ids = crud.get_saved_ids(db, current_user.id) if current_user else set()
    return render_template(
        request,
        "home.html",
        db,
        latest_media=latest_media,
        trending_media=trending_media,
        count=total_items,
        suggestions=suggestions,
        liked_ids=liked_ids,
        saved_ids=saved_ids,
    )


@app.get("/browse")
@app.get("/explore")
def browse(
    request: Request,
    q: str | None = None,
    tag: str | None = None,
    sort: str | None = "newest",
    page: int = 1,
    db: Session = Depends(get_db),
):
    media_items, total = crud.get_media_page(
        db,
        search=q,
        tag=tag,
        page=page,
        page_size=PAGE_SIZE,
        sort=sort,
    )
    page_count = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    current_user = get_current_user(request, db)
    saved_ids = crud.get_saved_ids(db, current_user.id) if current_user else set()
    liked_ids = crud.get_liked_ids(db, current_user.id) if current_user else set()
    return render_template(
        request,
        "browse.html",
        db,
        media_items=media_items,
        search=q or "",
        tag=tag or "",
        sort=sort or "newest",
        page=page,
        page_count=page_count,
        total_results=total,
        saved_ids=saved_ids,
        liked_ids=liked_ids,
    )


@app.get("/upload")
def upload_form(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return redirect_with_flash("/login", "Please sign in to upload media.", "info")
    return render_template(request, "upload.html", db)


@app.post("/upload")
async def upload_media(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    tags: str = Form(""),
    sale_status: str = Form("showcase"),
    fixed_price: str = Form(""),
    min_price: str = Form(""),
    max_price: str = Form(""),
    media_file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return redirect_with_flash("/login", "Please sign in to upload media.", "info")

    content_type = media_file.content_type
    if content_type not in ALLOWED_PHOTO_TYPES.union(ALLOWED_VIDEO_TYPES):
        raise HTTPException(status_code=400, detail="Upload must be an image or MP4/WebM video.")

    file_bytes = await media_file.read()
    max_bytes = 500 * 1024 * 1024 if content_type.startswith("video/") else 50 * 1024 * 1024
    if len(file_bytes) > max_bytes:
        limit_label = "500 MB" if content_type.startswith("video/") else "50 MB"
        raise HTTPException(status_code=413, detail=f"File too large. Maximum size is {limit_label}.")

    filename = secure_filename(media_file.filename)
    if not filename:
        raise HTTPException(status_code=400, detail="Invalid file name.")

    save_path = os.path.join(UPLOAD_DIR, filename)
    if os.path.exists(save_path):
        root, ext = os.path.splitext(filename)
        filename = f"{root}-{int(os.path.getmtime(save_path))}{ext}"
        save_path = os.path.join(UPLOAD_DIR, filename)

    with open(save_path, "wb") as buffer:
        buffer.write(file_bytes)

    # Parse prices — store as integer rupees
    def _parse_price(val: str) -> int | None:
        try:
            return max(0, int(val.strip())) if val.strip() else None
        except ValueError:
            return None

    sale_status = sale_status if sale_status in ("showcase", "fixed", "negotiable") else "showcase"
    media_type = "video" if content_type.startswith("video/") else "image"
    media = schemas.MediaCreate(
        title=title.strip() or "Untitled Upload",
        description=description.strip(),
        tags=tags.strip(),
        uploader=current_user.username,
        media_type=media_type,
        sale_status=sale_status,
        fixed_price=_parse_price(fixed_price) if sale_status == "fixed" else None,
        min_price=_parse_price(min_price) if sale_status == "negotiable" else None,
        max_price=_parse_price(max_price) if sale_status == "negotiable" else None,
    )
    crud.create_media_item(db, media, filename, uploader_id=current_user.id)
    return redirect_with_flash("/browse", "Your media was uploaded successfully!", "success")


def _media_owner_check(current_user: models.User | None, media_item: models.MediaItem) -> bool:
    return current_user is not None and current_user.id == media_item.uploader_id


@app.get("/watch/{media_id}")
def watch_media(request: Request, media_id: int, db: Session = Depends(get_db)):
    media_item = crud.get_media_item(db, media_id)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found.")
    crud.increment_media_views(db, media_item)
    comments = crud.get_comments_for_media(db, media_item.id)
    likes = crud.count_likes(db, media_item.id)
    current_user = get_current_user(request, db)
    user_liked = False
    user_saved = False
    if current_user:
        user_liked = crud.user_liked(db, media_item.id, current_user.id)
        user_saved = crud.is_saved(db, media_item.id, current_user.id)
    related = crud.get_related_media(db, media_item, limit=6)
    return render_template(
        request,
        "watch.html",
        db,
        media=media_item,
        comments=comments,
        likes=likes,
        user_liked=user_liked,
        user_saved=user_saved,
        related_media=related,
    )


@app.get("/media/{media_id}/edit")
def edit_media_form(request: Request, media_id: int, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/login", status_code=HTTP_303_SEE_OTHER)
    media_item = crud.get_media_item(db, media_id)
    if not media_item or not _media_owner_check(current_user, media_item):
        raise HTTPException(status_code=403, detail="Permission denied.")
    return render_template(
        request,
        "edit_media.html",
        db,
        media=media_item,
    )


@app.post("/media/{media_id}/edit")
def edit_media(
    request: Request,
    media_id: int,
    title: str = Form(...),
    description: str = Form(""),
    tags: str = Form(""),
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/login", status_code=HTTP_303_SEE_OTHER)
    media_item = crud.get_media_item(db, media_id)
    if not media_item or not _media_owner_check(current_user, media_item):
        raise HTTPException(status_code=403, detail="Permission denied.")
    crud.update_media_item(db, media_item, title.strip() or media_item.title, description.strip(), tags.strip())
    return redirect_with_flash(f"/watch/{media_id}", "Media updated successfully.", "success")


@app.post("/media/{media_id}/delete")
def delete_media(media_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/login", status_code=HTTP_303_SEE_OTHER)
    media_item = crud.get_media_item(db, media_id)
    if not media_item or not _media_owner_check(current_user, media_item):
        raise HTTPException(status_code=403, detail="Permission denied.")
    file_path = os.path.join(UPLOAD_DIR, media_item.filename)
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
        except OSError:
            pass
    crud.delete_media_item(db, media_item)
    return redirect_with_flash("/dashboard", "Media deleted.", "success")


@app.get("/posts/new")
def new_post_form(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/login", status_code=HTTP_303_SEE_OTHER)
    return render_template(request, "new_post.html", db)


@app.post("/posts/new")
def create_post_route(request: Request, title: str = Form(...), content: str = Form(""), published: str = Form("1"), db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/login", status_code=HTTP_303_SEE_OTHER)
    post = schemas.PostCreate(title=title.strip(), content=content.strip(), published=(published != "0"))
    p = crud.create_post(db, post, current_user.username, author_id=current_user.id)
    return redirect_with_flash(f"/post/{p.id}", "Post published!", "success")


@app.get("/post/{post_id}")
def view_post(request: Request, post_id: int, db: Session = Depends(get_db)):
    post = crud.get_post(db, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    # render markdown to safe HTML
    def _render_markdown(content: str) -> str:
        allowed_tags = list(bleach.sanitizer.ALLOWED_TAGS) + ["p", "pre", "span", "h1", "h2", "h3", "h4", "img", "table", "thead", "tbody", "tr", "th", "td"]
        allowed_attrs = {"img": ["src", "alt", "title"], "*": ["class"]}
        html = md_to_html(content or "", extensions=["fenced_code", "tables"]) if content else ""
        clean = bleach.clean(html, tags=allowed_tags, attributes=allowed_attrs, strip=True)
        return clean

    post_html = _render_markdown(post.content)
    return render_template(request, "post_view.html", db, post=post, post_html=post_html)


@app.get("/posts/{post_id}/edit")
def edit_post_form(request: Request, post_id: int, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/login", status_code=HTTP_303_SEE_OTHER)
    post_item = crud.get_post(db, post_id)
    if not post_item or post_item.author_id != current_user.id:
        raise HTTPException(status_code=403)
    return render_template(request, "edit_post.html", db, post=post_item)


@app.post("/posts/{post_id}/edit")
def edit_post_route(request: Request, post_id: int, title: str = Form(...), content: str = Form(""), published: str = Form("1"), db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/login", status_code=HTTP_303_SEE_OTHER)
    post_item = crud.get_post(db, post_id)
    if not post_item or post_item.author_id != current_user.id:
        raise HTTPException(status_code=403)
    crud.update_post(db, post_item, title.strip(), content.strip(), published != "0")
    return RedirectResponse(url=f"/post/{post_id}", status_code=HTTP_303_SEE_OTHER)


@app.post("/settings/email")
async def settings_change_email(request: Request, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return JSONResponse({"message": "Not authenticated"}, status_code=401)
    if not crud.verify_password(password, current_user.hashed_password):
        return JSONResponse({"message": "Incorrect password"}, status_code=400)
    existing = db.query(models.User).filter(models.User.email == email, models.User.id != current_user.id).first()
    if existing:
        return JSONResponse({"message": "Email already in use"}, status_code=400)
    current_user.email = email
    db.add(current_user)
    db.commit()
    return JSONResponse({"message": "Email updated successfully"})


@app.post("/settings/password")
async def settings_change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return JSONResponse({"message": "Not authenticated"}, status_code=401)
    if not crud.verify_password(current_password, current_user.hashed_password):
        return JSONResponse({"message": "Current password is incorrect"}, status_code=400)
    if new_password != confirm_password:
        return JSONResponse({"message": "New passwords do not match"}, status_code=400)
    if len(new_password) < 8:
        return JSONResponse({"message": "Password must be at least 8 characters"}, status_code=400)
    current_user.hashed_password = crud.get_password_hash(new_password)
    db.add(current_user)
    db.commit()
    return JSONResponse({"message": "Password updated successfully"})


@app.post("/settings/delete-account")
async def settings_delete_account(
    request: Request,
    confirm_text: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return redirect_with_flash("/login", "Please sign in to upload media.", "info")
    if confirm_text != "DELETE":
        raise HTTPException(status_code=400, detail="Type DELETE to confirm")
    if not crud.verify_password(password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect password")
    # Delete all user content
    user_media = crud.get_media_for_user(db, current_user.id)
    for item in user_media:
        file_path = os.path.join(UPLOAD_DIR, item.filename)
        if os.path.exists(file_path):
            try: os.remove(file_path)
            except OSError: pass
        crud.delete_media_item(db, item)
    db.query(models.Comment).filter(models.Comment.user_id == current_user.id).delete()
    db.query(models.Like).filter(models.Like.user_id == current_user.id).delete()
    db.query(models.Follow).filter(
        (models.Follow.follower_id == current_user.id) | (models.Follow.followed_id == current_user.id)
    ).delete()
    user_posts = db.query(models.Post).filter(models.Post.author_id == current_user.id).all()
    for p in user_posts:
        db.delete(p)
    db.delete(current_user)
    db.commit()
    response = RedirectResponse(url="/", status_code=HTTP_303_SEE_OTHER)
    response.delete_cookie("access_token")
    return response



async def upload_post_image(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    content_type = file.content_type
    if content_type not in ALLOWED_PHOTO_TYPES:
        raise HTTPException(status_code=400, detail="Only image uploads are allowed")
    filename = secure_filename(file.filename)
    if not filename:
        raise HTTPException(status_code=400, detail="Invalid file name")
    save_path = os.path.join(UPLOAD_DIR, filename)
    if os.path.exists(save_path):
        root, ext = os.path.splitext(filename)
        filename = f"{root}-{int(os.path.getmtime(save_path))}{ext}"
        save_path = os.path.join(UPLOAD_DIR, filename)
    with open(save_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    url = f"/uploads/{filename}"
    return {"url": url}


@app.get("/register")
def register_form(request: Request, db: Session = Depends(get_db)):
    return render_template(request, "register.html", db)


@app.post("/register")
def register(request: Request, username: str = Form(...), password: str = Form(...), email: str = Form(None), db: Session = Depends(get_db)):
    existing = crud.get_user_by_username(db, username)
    if existing:
        return render_template(request, "register.html", db, error="Username already exists")
    user = crud.create_user(db, username=username, password=password, email=email)
    token = create_access_token({"sub": user.username})
    response = RedirectResponse(url=f"/profile/{user.username}", status_code=HTTP_303_SEE_OTHER)
    response.set_cookie(key="access_token", value=token, httponly=True)
    return response


@app.get("/login")
def login_form(request: Request, db: Session = Depends(get_db)):
    return render_template(request, "login.html", db)


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = crud.authenticate_user(db, username, password)
    if not user:
        return render_template(request, "login.html", db, error="Invalid credentials")
    token = create_access_token({"sub": user.username})
    response = RedirectResponse(url=f"/profile/{user.username}", status_code=HTTP_303_SEE_OTHER)
    response.set_cookie(key="access_token", value=token, httponly=True)
    return response


@app.get("/profile/{username}")
def profile(request: Request, username: str, db: Session = Depends(get_db)):
    user = crud.get_user_by_username(db, username)
    if not user:
        raise HTTPException(status_code=404)
    media = db.query(models.MediaItem).filter(models.MediaItem.uploader == user.username).order_by(models.MediaItem.created_at.desc()).all()
    current_user = get_current_user(request, db)
    is_following = False
    if current_user:
        # check follow
        following_ids = crud.get_following_ids(db, current_user.id)
        is_following = user.id in following_ids
    followers = crud.count_followers(db, user.id)
    following = crud.count_following(db, user.id)
    suggestions = crud.get_follow_suggestions(db, current_user.id if current_user else None, limit=5)
    return render_template(
        request,
        "profile.html",
        db,
        user=user,
        media=media,
        is_following=is_following,
        followers=followers,
        following=following,
        suggestions=suggestions,
    )


@app.post("/follow/{username}")
def follow_user(username: str, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/login", status_code=HTTP_303_SEE_OTHER)
    target = crud.get_user_by_username(db, username)
    if not target:
        raise HTTPException(status_code=404)
    crud.follow_user(db, current_user.id, target.id)
    return RedirectResponse(url=f"/profile/{username}", status_code=HTTP_303_SEE_OTHER)


@app.post("/unfollow/{username}")
def unfollow_user(username: str, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/login", status_code=HTTP_303_SEE_OTHER)
    target = crud.get_user_by_username(db, username)
    if not target:
        raise HTTPException(status_code=404)
    crud.unfollow_user(db, current_user.id, target.id)
    return RedirectResponse(url=f"/profile/{username}", status_code=HTTP_303_SEE_OTHER)


@app.post("/api/follow/{username}/toggle")
def api_toggle_follow(username: str, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    target = crud.get_user_by_username(db, username)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if crud.is_following(db, current_user.id, target.id):
        crud.unfollow_user(db, current_user.id, target.id)
        is_following = False
    else:
        crud.follow_user(db, current_user.id, target.id)
        is_following = True
        crud.create_notification(db, user_id=target.id, actor_id=current_user.id, kind="follow")
    followers = crud.count_followers(db, target.id)
    following = crud.count_following(db, target.id)
    return {"is_following": is_following, "followers": followers, "following": following}


@app.get("/feed")
def feed(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    posts = crud.get_personal_feed(db, current_user.id if current_user else None, limit=30)
    suggestions = crud.get_follow_suggestions(db, current_user.id if current_user else None, limit=6)
    return render_template(request, "feed.html", db, posts=posts, suggestions=suggestions)


@app.get("/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/login", status_code=HTTP_303_SEE_OTHER)
    uploads = crud.get_media_for_user(db, current_user.id)
    liked_media = crud.get_liked_media(db, current_user.id)
    saved_media = crud.get_saved_media(db, current_user.id)
    return render_template(request, "dashboard.html", db, uploads=uploads, liked_media=liked_media, saved_media=saved_media)


@app.get("/profile/{username}/edit")
def profile_edit(request: Request, username: str, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user or current_user.username != username:
        raise HTTPException(status_code=403)
    return render_template(request, "profile_edit.html", db, user=current_user)


@app.post("/profile/{username}/edit")
def profile_update(
    request: Request,
    username: str,
    bio: str = Form(""),
    avatar: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    if not current_user or current_user.username != username:
        raise HTTPException(status_code=403)

    if avatar is not None and avatar.filename:
        avatar_name = secure_filename(avatar.filename)
        save_path = os.path.join(UPLOAD_DIR, avatar_name)
        if os.path.exists(save_path):
            root, ext = os.path.splitext(avatar_name)
            avatar_name = f"{root}-{int(os.path.getmtime(save_path))}{ext}"
            save_path = os.path.join(UPLOAD_DIR, avatar_name)
        with open(save_path, "wb") as buffer:
            shutil.copyfileobj(avatar.file, buffer)
        current_user.avatar = avatar_name

    current_user.bio = bio.strip()
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return RedirectResponse(url=f"/profile/{username}", status_code=HTTP_303_SEE_OTHER)


@app.get("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if current_user:
        crud.delete_read_notifications(db, current_user.id)
    response = RedirectResponse(url='/', status_code=HTTP_303_SEE_OTHER)
    response.delete_cookie('access_token')
    return response


@app.get("/api/notifications")
def api_get_notifications(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return JSONResponse({"notifications": [], "unread": 0})
    notifications = crud.get_notifications(db, current_user.id)
    # Enrich with actor usernames and media titles
    result = []
    for n in notifications:
        actor = db.query(models.User).filter(models.User.id == n.actor_id).first()
        media = crud.get_media_item(db, n.media_id) if n.media_id else None
        result.append({
            "id": n.id,
            "kind": n.kind,
            "actor": actor.username if actor else "Someone",
            "media_id": n.media_id,
            "media_title": media.title if media else None,
            "is_read": n.is_read,
            "created_at": n.created_at.strftime("%b %d, %H:%M"),
        })
    unread = crud.count_unread_notifications(db, current_user.id)
    return JSONResponse({"notifications": result, "unread": unread})


@app.post("/api/notifications/read")
def api_mark_notifications_read(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return JSONResponse({"ok": False})
    crud.mark_notifications_read(db, current_user.id)
    return JSONResponse({"ok": True})


def _require_admin(request: Request, db: Session) -> models.User:
    current_user = get_current_user(request, db)
    if not current_user or not getattr(current_user, "is_admin", False):
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


@app.get("/admin")
def admin_dashboard(
    request: Request,
    q: str | None = None,
    is_admin: str | None = None,
    tab: str | None = "users",
    page: int = 1,
    db: Session = Depends(get_db),
):
    _require_admin(request, db)
    users = crud.get_all_users(db)
    if q:
        users = [u for u in users if q.lower() in u.username.lower()]
    if is_admin is not None and is_admin != "":
        val = is_admin.lower()
        if val in ("1", "true", "yes"):
            users = [u for u in users if getattr(u, "is_admin", False)]
        elif val in ("0", "false", "no"):
            users = [u for u in users if not getattr(u, "is_admin", False)]

    stats = crud.get_site_stats(db)
    media_items, media_total = crud.get_all_media_admin(db, page=page)
    posts, posts_total = crud.get_all_posts_admin(db, page=page)
    comments, comments_total = crud.get_all_comments_admin(db, page=page)

    return render_template(
        request,
        "admin_dashboard.html",
        db,
        users=users,
        stats=stats,
        media_items=media_items,
        media_total=media_total,
        posts=posts,
        posts_total=posts_total,
        comments=comments,
        comments_total=comments_total,
        tab=tab,
        page=page,
        q=q or "",
        is_admin=is_admin or "",
    )


@app.post("/admin/user/{username}/promote")
def promote_user(username: str, make_admin: str = Form("0"), request: Request = None, db: Session = Depends(get_db)):
    _require_admin(request, db)
    is_admin = make_admin == "1" or make_admin == "true" or make_admin == "True"
    user = crud.set_user_admin(db, username, is_admin)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return RedirectResponse(url="/admin?tab=users", status_code=HTTP_303_SEE_OTHER)


@app.post("/admin/user/{username}/ban")
def ban_user(username: str, action: str = Form("ban"), request: Request = None, db: Session = Depends(get_db)):
    _require_admin(request, db)
    current_user = get_current_user(request, db)
    target = crud.get_user_by_username(db, username)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot ban yourself")
    crud.set_user_banned(db, username, action == "ban")
    return RedirectResponse(url="/admin?tab=users", status_code=HTTP_303_SEE_OTHER)


@app.post("/admin/media/{media_id}/delete")
def admin_delete_media(media_id: int, request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)
    media_item = crud.get_media_item(db, media_id)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media not found")
    file_path = os.path.join(UPLOAD_DIR, media_item.filename)
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
        except OSError:
            pass
    crud.delete_media_item(db, media_item)
    return RedirectResponse(url="/admin?tab=media", status_code=HTTP_303_SEE_OTHER)


@app.post("/admin/post/{post_id}/delete")
def admin_delete_post(post_id: int, request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)
    post_item = crud.get_post(db, post_id)
    if not post_item:
        raise HTTPException(status_code=404, detail="Post not found")
    crud.delete_post(db, post_item)
    return RedirectResponse(url="/admin?tab=posts", status_code=HTTP_303_SEE_OTHER)


@app.post("/admin/comment/{comment_id}/delete")
def admin_delete_comment(comment_id: int, request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)
    crud.delete_comment(db, comment_id)
    return RedirectResponse(url="/admin?tab=comments", status_code=HTTP_303_SEE_OTHER)




@app.post("/comment")
def post_comment(request: Request, media_id: int = Form(...), text: str = Form(...), db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return redirect_with_flash("/login", "Please sign in to post a comment.", "info")
    crud.create_comment(db, media_id=media_id, name=user.username, text=text, user_id=user.id)
    # Notify media owner
    media_item = crud.get_media_item(db, media_id)
    if media_item and media_item.uploader_id:
        crud.create_notification(db, user_id=media_item.uploader_id, actor_id=user.id, kind="comment", media_id=media_id)
    return RedirectResponse(url=f"/watch/{media_id}", status_code=HTTP_303_SEE_OTHER)


@app.post("/like/{media_id}")
def like_media(media_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required to like")
    liked = crud.toggle_like(db, media_id, user.id)
    if liked:
        media_item = crud.get_media_item(db, media_id)
        if media_item and media_item.uploader_id:
            crud.create_notification(db, user_id=media_item.uploader_id, actor_id=user.id, kind="like", media_id=media_id)
    return {"liked": liked, "likes": crud.count_likes(db, media_id)}


@app.post("/save/{media_id}")
def toggle_save(media_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return JSONResponse({"error": "Login required"}, status_code=401)
    saved = crud.toggle_saved(db, media_id, current_user.id)
    return JSONResponse({"saved": saved})


@app.get("/buy-request/{media_id}")
def buy_request_form(media_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return redirect_with_flash("/login", "Please sign in to raise a buy request.", "info")
    media_item = crud.get_media_item(db, media_id)
    if not media_item:
        raise HTTPException(status_code=404, detail="Artwork not found")
    if media_item.sale_status == "showcase":
        return redirect_with_flash(f"/watch/{media_id}", "This artwork is not available for purchase.", "info")
    if media_item.uploader_id == current_user.id:
        return redirect_with_flash(f"/watch/{media_id}", "You cannot buy your own artwork.", "info")
    if media_item.artwork_status != "available":
        return redirect_with_flash(f"/watch/{media_id}", f"This artwork is {media_item.artwork_status}.", "info")
    if crud.has_pending_request(db, media_id, current_user.id):
        return redirect_with_flash(f"/watch/{media_id}", "You already have an active request for this artwork.", "info")
    return render_template(request, "buy_request.html", db, media=media_item)


@app.post("/buy-request/{media_id}")
def submit_buy_request(
    media_id: int,
    request: Request,
    offer_price: str = Form(""),
    message: str = Form(""),
    purchase_type: str = Form("original"),
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return redirect_with_flash("/login", "Please sign in.", "info")
    media_item = crud.get_media_item(db, media_id)
    if not media_item or media_item.sale_status == "showcase":
        raise HTTPException(status_code=400, detail="Not available for purchase")
    if media_item.uploader_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot buy your own artwork")
    if crud.has_pending_request(db, media_id, current_user.id):
        return redirect_with_flash(f"/watch/{media_id}", "You already have an active request.", "info")

    # Parse and validate price
    try:
        price = int(offer_price.strip()) if offer_price.strip() else None
    except ValueError:
        price = None

    if media_item.sale_status == "fixed" and media_item.fixed_price:
        price = price or media_item.fixed_price
    elif media_item.sale_status == "negotiable":
        if price is None:
            return redirect_with_flash(f"/buy-request/{media_id}", "Please enter an offer price.", "error")
        if media_item.min_price and price < media_item.min_price:
            return redirect_with_flash(f"/buy-request/{media_id}", f"Offer must be at least ₹{media_item.min_price:,}.", "error")
        if media_item.max_price and price > media_item.max_price:
            return redirect_with_flash(f"/buy-request/{media_id}", f"Offer cannot exceed ₹{media_item.max_price:,}.", "error")

    req = crud.create_buy_request(
        db,
        media_id=media_id,
        buyer_id=current_user.id,
        offer_price=price,
        message=message.strip()[:300] if message.strip() else None,
        purchase_type=purchase_type,
    )
    # Notify the artist
    if media_item.uploader_id:
        crud.create_notification(
            db,
            user_id=media_item.uploader_id,
            actor_id=current_user.id,
            kind="buy_request",
            media_id=media_id,
        )
    return redirect_with_flash(f"/watch/{media_id}", "Your buy request has been sent! The artist will respond soon.", "success")


@app.get("/requests")
def my_requests(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return redirect_with_flash("/login", "Please sign in.", "info")
    # Requests buyer sent
    sent = crud.get_requests_by_buyer(db, current_user.id)
    # Requests artist received
    received = crud.get_requests_for_artist(db, current_user.id)
    # Enrich with media and user info
    def enrich(reqs):
        result = []
        for r in reqs:
            media = crud.get_media_item(db, r.media_id)
            buyer = db.query(models.User).filter(models.User.id == r.buyer_id).first()
            result.append({"req": r, "media": media, "buyer": buyer})
        return result
    return render_template(request, "requests.html", db,
                           sent=enrich(sent), received=enrich(received))


@app.post("/requests/{request_id}/accept")
def accept_buy_request(request_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return redirect_with_flash("/login", "Please sign in.", "info")
    req = crud.get_buy_request(db, request_id)
    if not req:
        raise HTTPException(status_code=404)
    media = crud.get_media_item(db, req.media_id)
    if not media or media.uploader_id != current_user.id:
        raise HTTPException(status_code=403)
    crud.update_request_status(db, request_id, "accepted")
    crud.create_notification(db, user_id=req.buyer_id, actor_id=current_user.id, kind="request_accepted", media_id=req.media_id)
    return redirect_with_flash("/requests", "Request accepted! The deal room will open in Stage 3.", "success")


@app.post("/requests/{request_id}/reject")
def reject_buy_request(request_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return redirect_with_flash("/login", "Please sign in.", "info")
    req = crud.get_buy_request(db, request_id)
    if not req:
        raise HTTPException(status_code=404)
    media = crud.get_media_item(db, req.media_id)
    if not media or media.uploader_id != current_user.id:
        raise HTTPException(status_code=403)
    crud.update_request_status(db, request_id, "rejected")
    crud.create_notification(db, user_id=req.buyer_id, actor_id=current_user.id, kind="request_rejected", media_id=req.media_id)
    return redirect_with_flash("/requests", "Request rejected.", "success")


@app.post("/requests/{request_id}/cancel")
def cancel_buy_request(request_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return redirect_with_flash("/login", "Please sign in.", "info")
    req = crud.get_buy_request(db, request_id)
    if not req or req.buyer_id != current_user.id:
        raise HTTPException(status_code=403)
    crud.update_request_status(db, request_id, "cancelled")
    return redirect_with_flash("/requests", "Request cancelled.", "success")


@app.get("/api/media", response_model=list[schemas.MediaRead])
def api_media_list(db: Session = Depends(get_db)):
    return crud.get_media_list(db)


@app.get("/api/media/{media_id}", response_model=schemas.MediaRead)
def api_media_item(media_id: int, db: Session = Depends(get_db)):
    media_item = crud.get_media_item(db, media_id)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found.")
    return media_item
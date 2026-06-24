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


@app.post("/media/{media_id}/mark-sold")
def mark_media_sold(media_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return redirect_with_flash("/login", "Please sign in.", "info")
    media_item = crud.get_media_item(db, media_id)
    if not media_item or media_item.uploader_id != current_user.id:
        raise HTTPException(status_code=403, detail="Permission denied.")
    media_item.artwork_status = "sold"
    db.add(media_item)
    db.commit()
    return redirect_with_flash(f"/watch/{media_id}", "Artwork marked as sold.", "success")


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


@app.post("/settings/contact")
async def settings_contact(
    request: Request,
    whatsapp: str = Form(""),
    telegram: str = Form(""),
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return JSONResponse({"message": "Not authenticated"}, status_code=401)
    current_user.whatsapp = whatsapp.strip()[:30] or None
    current_user.telegram = telegram.strip()[:60] or None
    db.add(current_user)
    db.commit()
    return JSONResponse({"message": "Contact info saved."})


# ═══════════════════════════════════════════
#  STAGE 4 — DEAL RECEIPT
# ═══════════════════════════════════════════

@app.get("/deal/{deal_id}/receipt/download")
def download_deal_receipt(deal_id: int, request: Request, db: Session = Depends(get_db)):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from io import BytesIO

    current_user = get_current_user(request, db)
    if not current_user:
        return redirect_with_flash("/login", "Please sign in.", "info")
    deal = crud.get_deal(db, deal_id)
    if not deal or not _deal_access(deal, current_user):
        raise HTTPException(status_code=403)
    if not (deal.buyer_confirmed and deal.artist_confirmed):
        return redirect_with_flash(f"/deal/{deal_id}/receipt", "Receipt only available after both parties confirm.", "info")

    media = crud.get_media_item(db, deal.media_id)
    buyer = db.query(models.User).filter(models.User.id == deal.buyer_id).first()
    artist = db.query(models.User).filter(models.User.id == deal.artist_id).first()
    events = crud.get_deal_events(db, deal_id)

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=20*mm, leftMargin=20*mm,
        topMargin=20*mm, bottomMargin=20*mm,
    )

    styles = getSampleStyleSheet()
    accent = colors.HexColor("#e60023")
    dark   = colors.HexColor("#1a1a2e")
    muted  = colors.HexColor("#718096")
    green  = colors.HexColor("#276749")

    h1  = ParagraphStyle("H1",  parent=styles["Normal"], fontSize=22, textColor=dark,  fontName="Helvetica-Bold", spaceAfter=2)
    h2  = ParagraphStyle("H2",  parent=styles["Normal"], fontSize=11, textColor=muted, fontName="Helvetica",      spaceAfter=6)
    h3  = ParagraphStyle("H3",  parent=styles["Normal"], fontSize=10, textColor=dark,  fontName="Helvetica-Bold", spaceBefore=10, spaceAfter=4)
    body= ParagraphStyle("Body",parent=styles["Normal"], fontSize=9,  textColor=dark,  fontName="Helvetica",      leading=14)
    sm  = ParagraphStyle("Sm",  parent=styles["Normal"], fontSize=8,  textColor=muted, fontName="Helvetica",      leading=12)
    ctr = ParagraphStyle("Ctr", parent=styles["Normal"], fontSize=9,  textColor=dark,  fontName="Helvetica",      alignment=TA_CENTER)
    price_style = ParagraphStyle("Price", parent=styles["Normal"], fontSize=18, textColor=accent, fontName="Helvetica-Bold", alignment=TA_CENTER)

    story = []

    # ── Header ──
    story.append(Paragraph("ArtStudio", ParagraphStyle("Brand", parent=h1, textColor=accent, fontSize=28)))
    story.append(Paragraph("Art Deal Receipt", h2))
    story.append(HRFlowable(width="100%", thickness=2, color=accent, spaceAfter=10))

    # ── Deal ID + Date row ──
    deal_id_str = f"ART-{deal.id:06d}"
    header_data = [
        [Paragraph(f"<b>Deal ID:</b> {deal_id_str}", body),
         Paragraph(f"<b>Date:</b> {deal.created_at.strftime('%d %B %Y')}", body)],
        [Paragraph(f"<b>Status:</b> {'Fully Confirmed ✓' if deal.status == 'completed' else deal.status.replace('_',' ').title()}", body),
         Paragraph(f"<b>Platform:</b> ArtStudio", body)],
    ]
    t = Table(header_data, colWidths=[85*mm, 85*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#f8f9fa")),
        ("BOX",        (0,0), (-1,-1), 0.5, colors.HexColor("#dee2e6")),
        ("INNERGRID",  (0,0), (-1,-1), 0.3, colors.HexColor("#dee2e6")),
        ("TOPPADDING", (0,0), (-1,-1), 6),
        ("BOTTOMPADDING",(0,0),(-1,-1), 6),
        ("LEFTPADDING", (0,0), (-1,-1), 8),
    ]))
    story.append(t)
    story.append(Spacer(1, 8*mm))

    # ── Artwork ──
    story.append(Paragraph("ARTWORK", ParagraphStyle("Label", parent=sm, textColor=muted, fontName="Helvetica-Bold", spaceBefore=0)))
    art_data = [
        ["Title",         media.title if media else "—"],
        ["Description",   (media.description or "No description")[:120] if media else "—"],
        ["Tags",          (media.tags or "None") if media else "—"],
        ["Type",          (media.media_type or "—").capitalize() if media else "—"],
        ["Sale Status",   (media.sale_status or "—").capitalize() if media else "—"],
    ]
    art_table = Table(
        [[Paragraph(f"<b>{r[0]}</b>", body), Paragraph(str(r[1]), body)] for r in art_data],
        colWidths=[40*mm, 130*mm]
    )
    art_table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), colors.white),
        ("BOX",        (0,0), (-1,-1), 0.5, colors.HexColor("#dee2e6")),
        ("INNERGRID",  (0,0), (-1,-1), 0.3, colors.HexColor("#f0f0f0")),
        ("TOPPADDING", (0,0), (-1,-1), 5),
        ("BOTTOMPADDING",(0,0),(-1,-1),5),
        ("LEFTPADDING", (0,0),(-1,-1), 8),
        ("BACKGROUND", (0,0),(0,-1), colors.HexColor("#f8f9fa")),
    ]))
    story.append(art_table)
    story.append(Spacer(1, 6*mm))

    # ── Parties ──
    story.append(Paragraph("PARTIES", ParagraphStyle("Label", parent=sm, textColor=muted, fontName="Helvetica-Bold")))
    parties_data = [
        [Paragraph("<b>Artist</b>", body), Paragraph("<b>Buyer</b>", body)],
        [Paragraph(artist.username if artist else "—", body), Paragraph(buyer.username if buyer else "—", body)],
        [Paragraph(artist.email or "Not provided", sm), Paragraph(buyer.email or "Not provided", sm)],
        [Paragraph(f"WhatsApp: {artist.whatsapp or 'Not provided'}", sm), Paragraph(f"WhatsApp: {buyer.whatsapp or 'Not provided'}", sm)],
        [Paragraph(f"Telegram: {artist.telegram or 'Not provided'}", sm), Paragraph(f"Telegram: {buyer.telegram or 'Not provided'}", sm)],
        [Paragraph(f"Confirmed: {'Yes ✓' if deal.artist_confirmed else 'No'}", sm), Paragraph(f"Confirmed: {'Yes ✓' if deal.buyer_confirmed else 'No'}", sm)],
    ]
    pt = Table(parties_data, colWidths=[85*mm, 85*mm])
    pt.setStyle(TableStyle([
        ("BOX",         (0,0),(-1,-1), 0.5, colors.HexColor("#dee2e6")),
        ("INNERGRID",   (0,0),(-1,-1), 0.3, colors.HexColor("#f0f0f0")),
        ("TOPPADDING",  (0,0),(-1,-1), 5),
        ("BOTTOMPADDING",(0,0),(-1,-1),5),
        ("LEFTPADDING", (0,0),(-1,-1), 8),
        ("BACKGROUND",  (0,0),(-1,0), colors.HexColor("#f8f9fa")),
        ("FONTNAME",    (0,0),(-1,0), "Helvetica-Bold"),
    ]))
    story.append(pt)
    story.append(Spacer(1, 6*mm))

    # ── Final Price ──
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#dee2e6"), spaceAfter=6))
    story.append(Paragraph("FINAL AGREED PRICE", ParagraphStyle("Label", parent=sm, textColor=muted, fontName="Helvetica-Bold", alignment=TA_CENTER)))
    price_str = f"Rs. {deal.current_price:,}" if deal.current_price else "—"
    story.append(Paragraph(price_str, price_style))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#dee2e6"), spaceBefore=6, spaceAfter=8))

    # ── Deal Timeline ──
    story.append(Paragraph("DEAL TIMELINE", ParagraphStyle("Label", parent=sm, textColor=muted, fontName="Helvetica-Bold")))
    for ev in events:
        actor = db.query(models.User).filter(models.User.id == ev.actor_id).first()
        actor_name = actor.username if actor else "System"
        time_str = ev.created_at.strftime("%d %b %Y, %H:%M")
        label = ev.kind.replace("_", " ").title()
        amt = f" · Rs. {ev.amount:,}" if ev.amount else ""
        msg = f" — {ev.message}" if ev.message else ""
        story.append(Paragraph(f"<b>{time_str}</b>  [{label}]  {actor_name}{amt}{msg}", sm))
    story.append(Spacer(1, 6*mm))

    # ── Platform Notice ──
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#dee2e6"), spaceAfter=6))
    story.append(Paragraph("PLATFORM NOTICE", ParagraphStyle("Label", parent=sm, textColor=muted, fontName="Helvetica-Bold")))
    notice_text = (
        "This Deal Receipt records the agreement details shared between the buyer and artist through the ArtStudio platform. "
        "The platform does not process payments, hold funds, arrange shipping, verify artwork authenticity, or guarantee delivery. "
        "All payment, shipping, delivery, and communication arrangements after contact exchange are the sole responsibility of the buyer and artist. "
        "By confirming this deal, both parties acknowledge that ArtStudio serves only as a communication and agreement-recording service. "
        "This document is not a legal contract and carries no legal liability for ArtStudio or its operators."
    )
    story.append(Paragraph(notice_text, sm))
    story.append(Spacer(1, 6*mm))

    # ── Digital Acknowledgement ──
    story.append(Paragraph("DIGITAL ACKNOWLEDGEMENT", ParagraphStyle("Label", parent=sm, textColor=muted, fontName="Helvetica-Bold")))
    ack_data = [
        [Paragraph("<b>Artist signature</b>", sm), Paragraph("<b>Buyer signature</b>", sm)],
        [Paragraph(f"{artist.username if artist else '—'}\nConfirmed digitally on ArtStudio\n{deal.updated_at.strftime('%d %B %Y') if deal.updated_at else '—'}", sm),
         Paragraph(f"{buyer.username if buyer else '—'}\nConfirmed digitally on ArtStudio\n{deal.updated_at.strftime('%d %B %Y') if deal.updated_at else '—'}", sm)],
    ]
    at = Table(ack_data, colWidths=[85*mm, 85*mm])
    at.setStyle(TableStyle([
        ("BOX",         (0,0),(-1,-1), 0.5, colors.HexColor("#dee2e6")),
        ("INNERGRID",   (0,0),(-1,-1), 0.3, colors.HexColor("#f0f0f0")),
        ("TOPPADDING",  (0,0),(-1,-1), 8),
        ("BOTTOMPADDING",(0,0),(-1,-1),8),
        ("LEFTPADDING", (0,0),(-1,-1), 8),
        ("BACKGROUND",  (0,0),(-1,0), colors.HexColor("#f8f9fa")),
    ]))
    story.append(at)
    story.append(Spacer(1, 4*mm))

    # ── Footer ──
    story.append(HRFlowable(width="100%", thickness=1, color=accent, spaceAfter=4))
    story.append(Paragraph(
        f"Generated by ArtStudio · {deal_id_str} · {deal.created_at.strftime('%d %B %Y')} · This is a platform record only.",
        ParagraphStyle("Footer", parent=sm, alignment=TA_CENTER, textColor=muted)
    ))

    doc.build(story)
    buffer.seek(0)

    from fastapi.responses import StreamingResponse
    filename = f"ArtStudio-Deal-{deal_id_str}.pdf"
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@app.get("/deal/{deal_id}/receipt")
def deal_receipt(deal_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return redirect_with_flash("/login", "Please sign in.", "info")
    deal = crud.get_deal(db, deal_id)
    if not deal:
        raise HTTPException(status_code=404)
    if not _deal_access(deal, current_user):
        raise HTTPException(status_code=403)
    if deal.status not in ("agreed", "buyer_confirmed", "artist_confirmed", "completed"):
        return redirect_with_flash(f"/deal/{deal_id}", "Both parties must agree on a price before creating the receipt.", "info")
    media = crud.get_media_item(db, deal.media_id)
    buyer = db.query(models.User).filter(models.User.id == deal.buyer_id).first()
    artist = db.query(models.User).filter(models.User.id == deal.artist_id).first()
    is_buyer = current_user.id == deal.buyer_id
    # Contact only visible after both confirmed
    show_contact = deal.status == "completed" or (deal.buyer_confirmed and deal.artist_confirmed)
    return render_template(
        request, "deal_receipt.html", db,
        deal=deal,
        media=media,
        buyer=buyer,
        artist=artist,
        is_buyer=is_buyer,
        show_contact=show_contact,
        current_user=current_user,
    )


@app.post("/deal/{deal_id}/confirm")
def deal_confirm(deal_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return redirect_with_flash("/login", "Please sign in.", "info")
    deal = crud.get_deal(db, deal_id)
    if not deal or not _deal_access(deal, current_user):
        raise HTTPException(status_code=403)
    if deal.status == "completed":
        return redirect_with_flash(f"/deal/{deal_id}/receipt", "Deal already completed.", "info")

    is_buyer = current_user.id == deal.buyer_id
    if is_buyer and not deal.buyer_confirmed:
        crud.update_deal(db, deal, buyer_confirmed=True, status="buyer_confirmed")
        crud.add_deal_event(db, deal_id, current_user.id, "buyer_confirmed", message="Buyer confirmed the deal receipt.")
        crud.create_notification(db, user_id=deal.artist_id, actor_id=current_user.id, kind="deal_confirmed", media_id=deal.media_id)
    elif not is_buyer and not deal.artist_confirmed:
        crud.update_deal(db, deal, artist_confirmed=True, status="artist_confirmed")
        crud.add_deal_event(db, deal_id, current_user.id, "artist_confirmed", message="Artist confirmed the deal receipt.")
        crud.create_notification(db, user_id=deal.buyer_id, actor_id=current_user.id, kind="deal_confirmed", media_id=deal.media_id)

    # Reload to check if both confirmed
    db.refresh(deal)
    if deal.buyer_confirmed and deal.artist_confirmed:
        crud.update_deal(db, deal, status="completed")
        crud.add_deal_event(db, deal_id, current_user.id, "completed", message="Deal fully confirmed. Contact information unlocked.")
        # Mark artwork as reserved and store agreed price
        media = crud.get_media_item(db, deal.media_id)
        if media:
            media.artwork_status = "reserved"
            media.fixed_price = deal.current_price  # store agreed price for sold label
            db.add(media)
            db.commit()

    return redirect_with_flash(f"/deal/{deal_id}/receipt", "Confirmed! Waiting for the other party." if deal.status != "completed" else "Deal complete! Contact information is now visible.", "success")
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
            deal = crud.get_deal_by_request(db, r.id)
            result.append({"req": r, "media": media, "buyer": buyer, "deal": deal})
        return result
    return render_template(request, "requests.html", db,
                           sent=enrich(sent), received=enrich(received))




# ═══════════════════════════════════════════
#  STAGE 3 — DEAL ROOM
# ═══════════════════════════════════════════

PREDEFINED_QUESTIONS = [
    ("shipping",   "Can this artwork be shipped to my location?"),
    ("dimensions", "What are the exact dimensions of this artwork?"),
    ("framing",    "Is framing included with this artwork?"),
    ("condition",  "What is the current condition of the artwork?"),
    ("photos",     "Can you share additional photos of this artwork?"),
    ("original",   "Is this the original artwork or a print?"),
    ("other",      "I have a custom question (see message below)."),
]

PREDEFINED_ANSWERS = [
    "Shipping is available.",
    "Shipping is not available.",
    "Framing is included.",
    "Framing is not included.",
    "Dimensions are listed in the artwork description.",
    "I can provide additional photos on request.",
    "This is the original artwork.",
    "This is a high-quality print.",
]


def _deal_access(deal: models.Deal, current_user: models.User) -> bool:
    return current_user.id in (deal.buyer_id, deal.artist_id) or getattr(current_user, "is_admin", False)


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
    # Update request status
    crud.update_request_status(db, request_id, "accepted")
    # Create deal room
    deal = crud.get_deal_by_request(db, request_id)
    if not deal:
        deal = crud.create_deal(
            db,
            buy_request_id=request_id,
            media_id=req.media_id,
            buyer_id=req.buyer_id,
            artist_id=current_user.id,
            current_price=req.offer_price,
            last_actor_id=req.buyer_id,
        )
    crud.create_notification(db, user_id=req.buyer_id, actor_id=current_user.id, kind="request_accepted", media_id=req.media_id)
    return redirect_with_flash(f"/deal/{deal.id}", "Request accepted. Deal room is now open.", "success")


@app.get("/deal/{deal_id}")
def deal_room(deal_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return redirect_with_flash("/login", "Please sign in.", "info")
    deal = crud.get_deal(db, deal_id)
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    if not _deal_access(deal, current_user):
        raise HTTPException(status_code=403, detail="Access denied")
    media = crud.get_media_item(db, deal.media_id)
    events = crud.get_deal_events(db, deal_id)
    buyer = db.query(models.User).filter(models.User.id == deal.buyer_id).first()
    artist = db.query(models.User).filter(models.User.id == deal.artist_id).first()
    # Enrich events with actor usernames
    enriched = []
    for ev in events:
        actor = db.query(models.User).filter(models.User.id == ev.actor_id).first()
        enriched.append({"ev": ev, "actor": actor})
    is_buyer = current_user.id == deal.buyer_id
    return render_template(
        request, "deal_room.html", db,
        deal=deal,
        media=media,
        events=enriched,
        buyer=buyer,
        artist=artist,
        is_buyer=is_buyer,
        current_user=current_user,
        predefined_questions=PREDEFINED_QUESTIONS,
        predefined_answers=PREDEFINED_ANSWERS,
    )


@app.post("/deal/{deal_id}/offer")
def deal_make_offer(deal_id: int, request: Request, amount: str = Form(...), message: str = Form(""), db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    deal = crud.get_deal(db, deal_id)
    if not deal or not _deal_access(deal, current_user):
        raise HTTPException(status_code=403)
    if deal.status not in ("negotiating", "agreed"):
        return redirect_with_flash(f"/deal/{deal_id}", "This deal is no longer in negotiation.", "info")
    try:
        price = int(amount.strip())
        if price < 1:
            raise ValueError
    except ValueError:
        return redirect_with_flash(f"/deal/{deal_id}", "Please enter a valid offer amount.", "error")
    is_buyer = current_user.id == deal.buyer_id
    kind = "offer" if is_buyer else "counter"
    crud.update_deal(db, deal, current_price=price, status="negotiating", last_actor_id=current_user.id)
    crud.add_deal_event(db, deal_id, current_user.id, kind, amount=price, message=message.strip()[:200] or None)
    other_id = deal.artist_id if is_buyer else deal.buyer_id
    crud.create_notification(db, user_id=other_id, actor_id=current_user.id, kind="deal_offer", media_id=deal.media_id)
    return redirect_with_flash(f"/deal/{deal_id}", "Offer sent.", "success")


@app.post("/deal/{deal_id}/accept-price")
def deal_accept_price(deal_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    deal = crud.get_deal(db, deal_id)
    if not deal or not _deal_access(deal, current_user):
        raise HTTPException(status_code=403)
    if deal.status not in ("negotiating",):
        return redirect_with_flash(f"/deal/{deal_id}", "Nothing to accept.", "info")
    crud.update_deal(db, deal, status="agreed")
    crud.add_deal_event(db, deal_id, current_user.id, "accept_price", message=f"₹{deal.current_price:,} accepted.")
    other_id = deal.artist_id if current_user.id == deal.buyer_id else deal.buyer_id
    crud.create_notification(db, user_id=other_id, actor_id=current_user.id, kind="deal_agreed", media_id=deal.media_id)
    return redirect_with_flash(f"/deal/{deal_id}", "Price accepted! You can now create the deal receipt.", "success")


@app.post("/deal/{deal_id}/question")
def deal_ask_question(deal_id: int, request: Request, question_key: str = Form(""), custom_message: str = Form(""), db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    deal = crud.get_deal(db, deal_id)
    if not deal or not _deal_access(deal, current_user):
        raise HTTPException(status_code=403)
    if deal.status == "cancelled":
        return redirect_with_flash(f"/deal/{deal_id}", "This deal is cancelled.", "info")
    # Find predefined question text
    q_text = next((q[1] for q in PREDEFINED_QUESTIONS if q[0] == question_key), None)
    message = q_text if q_text and question_key != "other" else custom_message.strip()[:200]
    if not message:
        return redirect_with_flash(f"/deal/{deal_id}", "Please enter a question.", "error")
    crud.add_deal_event(db, deal_id, current_user.id, "question", message=message)
    other_id = deal.artist_id if current_user.id == deal.buyer_id else deal.buyer_id
    crud.create_notification(db, user_id=other_id, actor_id=current_user.id, kind="deal_question", media_id=deal.media_id)
    return redirect_with_flash(f"/deal/{deal_id}", "Question sent.", "success")


@app.post("/deal/{deal_id}/answer")
def deal_answer(deal_id: int, request: Request, answer_text: str = Form(""), custom_answer: str = Form(""), db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    deal = crud.get_deal(db, deal_id)
    if not deal or not _deal_access(deal, current_user):
        raise HTTPException(status_code=403)
    message = answer_text.strip() if answer_text.strip() else custom_answer.strip()[:200]
    if not message:
        return redirect_with_flash(f"/deal/{deal_id}", "Please enter an answer.", "error")
    crud.add_deal_event(db, deal_id, current_user.id, "answer", message=message)
    other_id = deal.artist_id if current_user.id == deal.buyer_id else deal.buyer_id
    crud.create_notification(db, user_id=other_id, actor_id=current_user.id, kind="deal_answer", media_id=deal.media_id)
    return redirect_with_flash(f"/deal/{deal_id}", "Answer sent.", "success")


@app.post("/deal/{deal_id}/cancel")
def deal_cancel(deal_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    deal = crud.get_deal(db, deal_id)
    if not deal or not _deal_access(deal, current_user):
        raise HTTPException(status_code=403)
    if deal.status in ("completed", "cancelled"):
        return redirect_with_flash(f"/deal/{deal_id}", "Deal is already closed.", "info")
    crud.update_deal(db, deal, status="cancelled")
    crud.add_deal_event(db, deal_id, current_user.id, "cancel", message="Deal cancelled.")
    other_id = deal.artist_id if current_user.id == deal.buyer_id else deal.buyer_id
    crud.create_notification(db, user_id=other_id, actor_id=current_user.id, kind="deal_cancelled", media_id=deal.media_id)
    return redirect_with_flash("/requests", "Deal cancelled.", "success")


@app.get("/api/media", response_model=list[schemas.MediaRead])
def api_media_list(db: Session = Depends(get_db)):
    return crud.get_media_list(db)


@app.get("/api/media/{media_id}", response_model=schemas.MediaRead)
def api_media_item(media_id: int, db: Session = Depends(get_db)):
    media_item = crud.get_media_item(db, media_id)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found.")
    return media_item
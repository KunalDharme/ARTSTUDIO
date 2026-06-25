import os
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./media.db")

# Railway gives postgres:// but SQLAlchemy needs postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

IS_POSTGRES = DATABASE_URL.startswith("postgresql")

if IS_POSTGRES:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=5, max_overflow=10)
else:
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_db() -> None:
    from . import models  # noqa: F401
    Base.metadata.create_all(bind=engine)

    # SQLite-only column migrations — Postgres handles schema via create_all
    if IS_POSTGRES:
        return

    inspector = inspect(engine)
    tables = inspector.get_table_names()

    if "media_items" in tables:
        cols = [c["name"] for c in inspector.get_columns("media_items")]
        with engine.begin() as conn:
            if "tags" not in cols:
                conn.execute(text("ALTER TABLE media_items ADD COLUMN tags VARCHAR(255)"))
            if "uploader_id" not in cols:
                conn.execute(text("ALTER TABLE media_items ADD COLUMN uploader_id INTEGER"))
            if "sale_status" not in cols:
                conn.execute(text("ALTER TABLE media_items ADD COLUMN sale_status VARCHAR(20) DEFAULT 'showcase'"))
            if "fixed_price" not in cols:
                conn.execute(text("ALTER TABLE media_items ADD COLUMN fixed_price INTEGER"))
            if "min_price" not in cols:
                conn.execute(text("ALTER TABLE media_items ADD COLUMN min_price INTEGER"))
            if "max_price" not in cols:
                conn.execute(text("ALTER TABLE media_items ADD COLUMN max_price INTEGER"))
            if "artwork_status" not in cols:
                conn.execute(text("ALTER TABLE media_items ADD COLUMN artwork_status VARCHAR(20) DEFAULT 'available'"))

    if "users" in tables:
        cols = [c["name"] for c in inspector.get_columns("users")]
        with engine.begin() as conn:
            if "is_admin" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0"))
            if "is_banned" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN is_banned BOOLEAN DEFAULT 0"))
            if "is_verified" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN is_verified BOOLEAN DEFAULT 1"))
            if "whatsapp" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN whatsapp VARCHAR(30)"))
            if "telegram" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN telegram VARCHAR(60)"))

    if "deals" in tables:
        cols = [c["name"] for c in inspector.get_columns("deals")]
        with engine.begin() as conn:
            if "last_actor_id" not in cols:
                conn.execute(text("ALTER TABLE deals ADD COLUMN last_actor_id INTEGER"))
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = "sqlite:///./media.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_db() -> None:
    # import models to ensure all table metadata is registered
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    if "media_items" in inspector.get_table_names():
        current_columns = [column["name"] for column in inspector.get_columns("media_items")]
        with engine.begin() as conn:
            if "tags" not in current_columns:
                conn.execute(text("ALTER TABLE media_items ADD COLUMN tags VARCHAR(255)"))
            if "uploader_id" not in current_columns:
                conn.execute(text("ALTER TABLE media_items ADD COLUMN uploader_id INTEGER"))
    if "users" in inspector.get_table_names():
        user_columns = [column["name"] for column in inspector.get_columns("users")]
        with engine.begin() as conn:
            if "is_admin" not in user_columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0"))
            if "is_banned" not in user_columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN is_banned BOOLEAN DEFAULT 0"))
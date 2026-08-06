"""
SQLAlchemy engine/session setup. We use SQLite by default (zero setup for a
beginner) but DATABASE_URL can point to Postgres in production without any
code changes.
"""
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import get_settings

settings = get_settings()

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency that yields a DB session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from app import models  # noqa: F401 (ensures models are registered)
    Base.metadata.create_all(bind=engine)
    if settings.database_url.startswith("sqlite"):
        with engine.begin() as conn:
            columns = {
                row[1]
                for row in conn.exec_driver_sql("PRAGMA table_info(documents)").fetchall()
            }
            if "deleted_at" not in columns:
                conn.execute(text("ALTER TABLE documents ADD COLUMN deleted_at DATETIME"))

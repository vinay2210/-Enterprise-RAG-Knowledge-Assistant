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
            document_columns = {
                row[1]
                for row in conn.exec_driver_sql("PRAGMA table_info(documents)").fetchall()
            }
            if "deleted_at" not in document_columns:
                conn.execute(text("ALTER TABLE documents ADD COLUMN deleted_at DATETIME"))

            # ``create_all`` only creates new tables; it does not add fields to
            # an existing SQLite table.  The parent context column was added
            # after the first documents had already been indexed, leaving the
            # BM25 rebuild and parent-context lookup broken on those databases.
            chunk_columns = {
                row[1]
                for row in conn.exec_driver_sql("PRAGMA table_info(document_chunks)").fetchall()
            }
            if "parent_text" not in chunk_columns:
                conn.execute(text("ALTER TABLE document_chunks ADD COLUMN parent_text TEXT"))

            # Existing rows have no stored parent context.  Their child text is
            # still the most precise grounded context, and backfilling it makes
            # the entire current index searchable immediately after upgrade.
            conn.execute(text(
                "UPDATE document_chunks "
                "SET parent_text = text "
                "WHERE parent_text IS NULL OR parent_text = ''"
            ))

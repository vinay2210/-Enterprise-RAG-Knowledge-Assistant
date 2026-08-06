"""
SQLAlchemy ORM models.

Document      -> one row per file ingested from Google Drive.
DocumentChunk -> one row per chunk of a document (metadata mirror of what's
                 stored in the vector DB, so we can query/filter/delete
                 relationally without hitting Chroma for simple lookups).
ChatMessage   -> conversation history, so multi-turn chat and the
                 "conversation history" bonus feature both have a home.
UserToken     -> stores the Google OAuth refresh token per user session.
"""
import uuid
from datetime import datetime

from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey, Enum
from sqlalchemy.orm import relationship
import enum

from app.database import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


class DocumentStatus(str, enum.Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    EXTRACTING = "extracting"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    READY = "ready"
    FAILED = "failed"
    EMPTY = "empty"
    UNSUPPORTED = "unsupported"
    DELETED = "deleted"


class Document(Base):
    __tablename__ = "documents"

    id = Column(String, primary_key=True, default=gen_uuid)
    drive_file_id = Column(String, unique=True, index=True, nullable=False)
    file_name = Column(String, nullable=False)
    mime_type = Column(String, nullable=True)
    file_size_bytes = Column(Integer, default=0)
    drive_modified_time = Column(DateTime, nullable=True)  # used to detect updates
    status = Column(Enum(DocumentStatus), default=DocumentStatus.PENDING)
    error_message = Column(Text, nullable=True)
    page_count = Column(Integer, default=0)
    chunk_count = Column(Integer, default=0)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    indexed_at = Column(DateTime, nullable=True)
    deleted_at = Column(DateTime, nullable=True)

    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(String, primary_key=True, default=gen_uuid)
    document_id = Column(String, ForeignKey("documents.id"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    page_number = Column(Integer, nullable=True)
    text = Column(Text, nullable=False)
    token_count = Column(Integer, default=0)
    vector_id = Column(String, nullable=False)  # id used in the Chroma collection

    document = relationship("Document", back_populates="chunks")


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(String, primary_key=True, default=gen_uuid)
    title = Column(String, default="New chat")
    created_at = Column(DateTime, default=datetime.utcnow)

    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(String, primary_key=True, default=gen_uuid)
    session_id = Column(String, ForeignKey("chat_sessions.id"), nullable=False)
    role = Column(String, nullable=False)  # "user" | "assistant"
    content = Column(Text, nullable=False)
    citations_json = Column(Text, nullable=True)  # JSON-encoded list of {doc, page}
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("ChatSession", back_populates="messages")


class UserToken(Base):
    """Stores the single Google account's OAuth tokens for this local app."""
    __tablename__ = "user_tokens"

    id = Column(String, primary_key=True, default=gen_uuid)
    email = Column(String, unique=True, nullable=True)
    access_token = Column(Text, nullable=False)
    refresh_token = Column(Text, nullable=True)
    token_expiry = Column(DateTime, nullable=True)
    drive_folder_id = Column(String, nullable=True)
    connected_at = Column(DateTime, default=datetime.utcnow)

"""
Pydantic request/response schemas (the API's public contract).
Kept separate from ORM models so the DB shape can evolve independently of
what we expose over HTTP.
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


class DocumentOut(BaseModel):
    id: str
    drive_file_id: str
    file_name: str
    mime_type: Optional[str] = None
    status: str
    error_message: Optional[str] = None
    page_count: int
    chunk_count: int
    uploaded_at: datetime
    indexed_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AuthStatusOut(BaseModel):
    connected: bool
    email: Optional[str] = None
    drive_folder_id: Optional[str] = None


class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str
    file_filter: Optional[List[str]] = None  # file names from @mentions, empty = global search
    top_k: int = 6


class Citation(BaseModel):
    document_id: str
    file_name: str
    page_number: Optional[int] = None
    chunk_index: int
    snippet: str
    score: float


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    citations: List[Citation]


class SyncTriggerOut(BaseModel):
    triggered: bool
    files_found: int

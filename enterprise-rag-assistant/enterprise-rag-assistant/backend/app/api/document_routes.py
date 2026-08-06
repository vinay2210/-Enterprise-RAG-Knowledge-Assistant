"""Manual upload endpoint (useful for testing without wiring up Drive first)."""
import uuid

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Document, DocumentStatus
from app.drive.drive_service import DriveService
from app.rag.pipeline import process_document
from app.config import get_settings

router = APIRouter(prefix="/api/documents", tags=["documents"])
settings = get_settings()

EXT_TO_MIME = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain",
    "md": "text/markdown",
}


class _LocalFileDrive:
    """Duck-types DriveService.download_file so pipeline.process_document can
    ingest a locally uploaded file without touching Google Drive at all -
    handy for local testing before OAuth is configured."""
    def __init__(self, content: bytes):
        self.content = content

    def download_file(self, file_id: str) -> bytes:
        return self.content


@router.post("/upload")
async def upload_document(file: UploadFile = File(...), db: Session = Depends(get_db)):
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in EXT_TO_MIME:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: .{ext}")

    content = await file.read()
    size_mb = len(content) / (1024 * 1024)
    if size_mb > settings.max_file_size_mb:
        raise HTTPException(status_code=400, detail=f"File exceeds {settings.max_file_size_mb}MB limit")

    doc = Document(
        drive_file_id=f"local-{uuid.uuid4()}",
        file_name=file.filename,
        mime_type=EXT_TO_MIME[ext],
        file_size_bytes=len(content),
        status=DocumentStatus.PENDING,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    process_document(db, doc, _LocalFileDrive(content))
    db.refresh(doc)
    return {"id": doc.id, "status": doc.status, "chunk_count": doc.chunk_count}

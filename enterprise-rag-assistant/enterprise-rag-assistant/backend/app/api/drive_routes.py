"""Drive sync + document listing/deletion endpoints."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from app.database import get_db
from app.drive.sync import run_sync
from app.models import Document, DocumentStatus
from app.rag import vector_store
from app.rag.bm25_retriever import get_bm25_index
from app.schemas import DocumentOut, SyncTriggerOut
from app.utils.logger import logger

router = APIRouter(prefix="/api/drive", tags=["drive"])


@router.post("/sync", response_model=SyncTriggerOut)
def trigger_sync(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Kicks off an immediate sync. Large folders can take a while (500+ page
    PDFs take real time to embed), so we run it in the background and let the
    frontend poll GET /api/documents for live status instead of blocking here."""
    try:
        # Run inline for the file-discovery part (fast) but the heavy
        # per-document pipeline work inside run_sync already updates each
        # Document's status as it goes, so polling works even mid-sync.
        background_tasks.add_task(_safe_sync)
        return SyncTriggerOut(triggered=True, files_found=0)
    except Exception as e:
        logger.error(f"Sync trigger failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _safe_sync():
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        run_sync(db)
    except Exception as e:
        logger.exception(f"Background sync failed: {e}")
    finally:
        db.close()


@router.get("/documents", response_model=list[DocumentOut])
def list_documents(db: Session = Depends(get_db)):
    return (
        db.query(Document)
        .filter(Document.status != DocumentStatus.DELETED)
        .order_by(Document.uploaded_at.desc())
        .all()
    )


@router.get("/deleted-documents", response_model=list[DocumentOut])
def list_deleted_documents(db: Session = Depends(get_db)):
    return (
        db.query(Document)
        .filter(Document.status == DocumentStatus.DELETED)
        .order_by(Document.deleted_at.desc().nullslast(), Document.uploaded_at.desc())
        .all()
    )


@router.get("/history", response_model=list[DocumentOut])
def list_history(db: Session = Depends(get_db)):
    return db.query(Document).order_by(Document.uploaded_at.desc()).all()


@router.delete("/documents/{document_id}")
def delete_document(document_id: str, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    vector_store.delete_document(document_id)
    get_bm25_index().delete_document(document_id)
    doc.status = DocumentStatus.DELETED
    doc.deleted_at = datetime.utcnow()
    doc.error_message = None
    db.commit()
    return {"deleted": True}


@router.delete("/deleted-documents/{document_id}")
def delete_deleted_document(document_id: str, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == document_id, Document.status == DocumentStatus.DELETED).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Deleted document not found")
    vector_store.delete_document(document_id)
    get_bm25_index().delete_document(document_id)
    db.delete(doc)
    db.commit()
    return {"deleted": True}

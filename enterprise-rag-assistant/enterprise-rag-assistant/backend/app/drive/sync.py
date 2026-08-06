"""
Sync job: polls the 'AI Knowledge Base' Drive folder, diffs it against what
we already know about in SQLite, and pushes new/updated files through the
RAG pipeline. Also removes documents (and their vectors) that were deleted
from Drive, so the index never goes stale.

Runs both on-demand (POST /api/drive/sync) and on a background schedule
(APScheduler, started from main.py) - satisfying "poll Google Drive
periodically for new or updated files".
"""
from datetime import datetime

from dateutil import parser as dtparser
from sqlalchemy.orm import Session

from app.auth.google_oauth import get_valid_credentials
from app.drive.drive_service import DriveService
from app.models import Document, DocumentStatus
from app.rag import vector_store
from app.rag.pipeline import process_document
from app.config import get_settings
from app.utils.logger import logger

settings = get_settings()


def run_sync(db: Session) -> int:
    """Returns the number of files found in the Drive folder (new + existing)."""
    creds = get_valid_credentials(db)
    if not creds:
        logger.warning("Sync skipped: Google account not connected.")
        return 0

    drive = DriveService(creds)

    from app.models import UserToken
    token_row = db.query(UserToken).first()
    folder_id = token_row.drive_folder_id

    candidate_folders = drive.find_folders_by_name(settings.drive_folder_name)
    if not candidate_folders:
        folder_id = drive.find_or_create_folder(settings.drive_folder_name)
        token_row.drive_folder_id = folder_id
        db.commit()
        drive_files = drive.list_files_in_folder(folder_id)
    else:
        folder_files_by_id = {}
        for folder in candidate_folders:
            folder_files_by_id[folder["id"]] = drive.list_files_in_folder(folder["id"])

        def folder_sort_key(folder):
            count = len(folder_files_by_id.get(folder["id"], []))
            is_current = folder["id"] == folder_id
            return (count, is_current)

        best_folder = max(candidate_folders, key=folder_sort_key)
        best_files = folder_files_by_id[best_folder["id"]]

        if best_folder["id"] != folder_id:
            logger.info(
                "Switching Google Drive sync to the most populated '%s' folder: %s",
                settings.drive_folder_name,
                best_folder["id"],
            )
            folder_id = best_folder["id"]
            token_row.drive_folder_id = folder_id
            db.commit()

        drive_files = best_files

    drive_file_ids = {f["id"] for f in drive_files}

    # --- Handle deletions: a doc we have indexed but that's gone from Drive ---
    existing_docs = db.query(Document).all()
    for doc in existing_docs:
        if doc.status == DocumentStatus.DELETED:
            continue
        if doc.drive_file_id.startswith("local-"):
            continue
        if doc.drive_file_id not in drive_file_ids:
            logger.info(f"'{doc.file_name}' removed from Drive - marking deleted.")
            vector_store.delete_document(doc.id)
            doc.status = DocumentStatus.DELETED
            doc.deleted_at = datetime.utcnow()
            doc.error_message = None
    db.commit()

    # --- Handle new / updated files ---
    for f in drive_files:
        modified_time = dtparser.isoparse(f["modifiedTime"]).replace(tzinfo=None)
        existing = db.query(Document).filter(Document.drive_file_id == f["id"]).first()

        if existing is not None and existing.status == DocumentStatus.DELETED:
            logger.info(
                f"Drive file '{f['name']}' previously deleted in app but still exists in Drive; re-indexing."
            )
            existing.status = DocumentStatus.PENDING
            existing.error_message = None
            existing.deleted_at = None
            existing.drive_modified_time = modified_time
            db.commit()
            process_document(db, existing, drive)
            continue

        if existing is None:
            if not DriveService.is_supported(f.get("mimeType", "")):
                # Record it as unsupported so the UI can show *why* it was skipped,
                # rather than silently ignoring it.
                doc = Document(
                    drive_file_id=f["id"],
                    file_name=f["name"],
                    mime_type=f.get("mimeType"),
                    file_size_bytes=int(f.get("size", 0) or 0),
                    drive_modified_time=modified_time,
                    status=DocumentStatus.UNSUPPORTED,
                    error_message=f"Unsupported file type: {f.get('mimeType')}",
                )
                db.add(doc)
                db.commit()
                continue

            doc = Document(
                drive_file_id=f["id"],
                file_name=f["name"],
                mime_type=f.get("mimeType"),
                file_size_bytes=int(f.get("size", 0) or 0),
                drive_modified_time=modified_time,
                status=DocumentStatus.PENDING,
            )
            db.add(doc)
            db.commit()
            db.refresh(doc)
            logger.info(f"New file detected: '{doc.file_name}' - starting pipeline")
            process_document(db, doc, drive)

        elif existing.drive_modified_time and modified_time > existing.drive_modified_time:
            logger.info(f"Updated file detected: '{existing.file_name}' - re-indexing")
            vector_store.delete_document(existing.id)
            existing.drive_modified_time = modified_time
            existing.status = DocumentStatus.PENDING
            db.commit()
            process_document(db, existing, drive)

    return len(drive_files)

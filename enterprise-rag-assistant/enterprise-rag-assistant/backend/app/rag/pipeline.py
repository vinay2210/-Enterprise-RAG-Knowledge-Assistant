"""
The Automatic RAG Pipeline, matching the assignment's diagram exactly:

  New Document -> Download -> Extract Text -> Clean Text -> Chunk Document
  -> Generate Embeddings -> Store in Vector Database -> Ready for Retrieval

This module orchestrates the other rag/* modules and updates Document rows
in SQLite so the frontend can show live per-file status (pending, embedding,
ready, failed, etc). Every stage is wrapped so one failure marks the
document FAILED with a message instead of crashing the sync job.
"""
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Document, DocumentChunk, DocumentStatus
from app.rag import extractor, chunker, vector_store
from app.rag.embeddings import get_embedder
from app.drive.drive_service import DriveService
from app.utils.logger import logger


def process_document(db: Session, document: Document, drive: DriveService) -> None:
    try:
        # ---- Download ----
        document.status = DocumentStatus.DOWNLOADING
        db.commit()
        file_bytes = drive.download_file(document.drive_file_id)

        size_mb = len(file_bytes) / (1024 * 1024)
        from app.config import get_settings
        if size_mb > get_settings().max_file_size_mb:
            raise ValueError(f"File is {size_mb:.1f}MB, exceeds max allowed size.")

        # ---- Extract + Clean ----
        document.status = DocumentStatus.EXTRACTING
        db.commit()
        ext = DriveService.extension_for(document.mime_type)
        if not ext:
            document.status = DocumentStatus.UNSUPPORTED
            document.error_message = f"Unsupported mime type: {document.mime_type}"
            db.commit()
            return

        try:
            pages = extractor.extract(ext, file_bytes)
        except extractor.EmptyDocumentError as e:
            document.status = DocumentStatus.EMPTY
            document.error_message = str(e)
            db.commit()
            return
        del file_bytes  # free memory before chunking large docs

        document.page_count = len(pages)

        # ---- Chunk ----
        document.status = DocumentStatus.CHUNKING
        db.commit()
        chunks = chunker.chunk_pages(pages)
        del pages
        if not chunks:
            document.status = DocumentStatus.EMPTY
            document.error_message = "No chunkable text found."
            db.commit()
            return

        # ---- Embed (batched to bound memory on 500+ page documents) ----
        document.status = DocumentStatus.EMBEDDING
        db.commit()
        embedder = get_embedder()
        embed_batch_size = 128
        all_embeddings: list[list[float]] = []
        for i in range(0, len(chunks), embed_batch_size):
            batch_texts = [c.text for c in chunks[i:i + embed_batch_size]]
            try:
                batch_vectors = embedder.embed(batch_texts)
            except Exception as e:
                raise RuntimeError(f"Embedding generation failed: {e}")
            all_embeddings.extend(batch_vectors)

        # ---- Store in Vector DB ----
        vector_ids = vector_store.upsert_chunks(document.id, document.file_name, chunks, all_embeddings)

        # Mirror chunk metadata in SQL for fast relational lookups/deletes.
        db.query(DocumentChunk).filter(DocumentChunk.document_id == document.id).delete()
        for c, vid in zip(chunks, vector_ids):
            db.add(DocumentChunk(
                document_id=document.id,
                chunk_index=c.chunk_index,
                page_number=c.page_number,
                text=c.text,
                token_count=c.token_count,
                vector_id=vid,
            ))

        document.chunk_count = len(chunks)
        document.status = DocumentStatus.READY
        document.error_message = None
        document.indexed_at = datetime.utcnow()
        db.commit()
        logger.info(f"Document '{document.file_name}' indexed: {len(chunks)} chunks, {document.page_count} pages")

    except Exception as e:
        logger.exception(f"Failed to process document {document.file_name}: {e}")
        document.status = DocumentStatus.FAILED
        document.error_message = str(e)[:1000]
        db.commit()

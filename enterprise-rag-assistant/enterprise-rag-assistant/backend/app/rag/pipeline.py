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
from app.rag.bm25_retriever import get_bm25_index
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
        chunks = chunker.chunk_pages(
            pages,
            child_chunk_size=get_settings().chunk_size_tokens,
            child_overlap=get_settings().chunk_overlap_tokens,
        )
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
        # A modified document may now contain fewer chunks than its old version.
        # Delete the old vector and sparse-index entries before writing the new
        # set so obsolete passages can never be returned for a 500-page file.
        vector_store.delete_document(document.id)
        bm25_index = get_bm25_index()
        bm25_index.delete_document(document.id)
        vector_ids = vector_store.upsert_chunks(document.id, document.file_name, chunks, all_embeddings)

        # Mirror chunk metadata in SQL for fast relational lookups/deletes.
        db.query(DocumentChunk).filter(DocumentChunk.document_id == document.id).delete()
        bm25_dicts = []
        for c, vid in zip(chunks, vector_ids):
            parent_txt = getattr(c, "parent_text", c.text)
            db.add(DocumentChunk(
                document_id=document.id,
                chunk_index=c.chunk_index,
                page_number=c.page_number,
                text=c.text,
                parent_text=parent_txt,
                token_count=c.token_count,
                vector_id=vid,
            ))
            bm25_dicts.append({
                "vector_id": vid,
                "text": c.text,
                "parent_text": parent_txt,
                "document_id": document.id,
                "file_name": document.file_name,
                "page_number": c.page_number,
                "chunk_index": c.chunk_index,
            })

        # ---- Index in BM25 Sparse Index ----
        bm25_index.add_chunks(bm25_dicts)

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


def rebuild_bm25_index(db: Session) -> None:
    """Populates BM25 index from active ready document chunks on server startup."""
    try:
        active_docs = db.query(Document).filter(Document.status == DocumentStatus.READY).all()
        active_doc_ids = [d.id for d in active_docs]
        if not active_doc_ids:
            return

        doc_map = {d.id: d.file_name for d in active_docs}
        sql_chunks = db.query(DocumentChunk).filter(DocumentChunk.document_id.in_(active_doc_ids)).all()

        bm25_dicts = []
        for sc in sql_chunks:
            bm25_dicts.append({
                "vector_id": sc.vector_id,
                "text": sc.text,
                "parent_text": sc.parent_text or sc.text,
                "document_id": sc.document_id,
                "file_name": doc_map.get(sc.document_id, "Document"),
                "page_number": sc.page_number,
                "chunk_index": sc.chunk_index,
            })

        get_bm25_index().add_chunks(bm25_dicts)
        logger.info(f"Rebuilt BM25 index with {len(bm25_dicts)} chunks across {len(active_docs)} documents.")
    except Exception as e:
        logger.warning(f"Failed to rebuild BM25 index on startup: {e}")

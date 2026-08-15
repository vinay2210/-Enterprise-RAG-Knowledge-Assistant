"""
Vector store wrapper around ChromaDB (local, persistent, zero external
services to run - important for a beginner setting this up in VS Code).

Swapping to Qdrant/Weaviate/FAISS later only touches this file: the rest of
the app calls upsert_chunks() / query() / delete_document().
"""
from functools import lru_cache

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import get_settings
from app.rag.embeddings import get_embedder
from app.utils.logger import logger

settings = get_settings()

# ChromaDB has a metadata value size limit. We cap parent_text stored in
# metadata to avoid silent truncation or errors. The full parent_text is
# always available in the SQL DocumentChunk table for LLM context assembly.
_MAX_METADATA_TEXT_CHARS = 4000


@lru_cache
def get_chroma_client():
    return chromadb.PersistentClient(
        path=settings.chroma_persist_dir,
        settings=ChromaSettings(anonymized_telemetry=False),
    )


@lru_cache
def get_collection():
    client = get_chroma_client()
    return client.get_or_create_collection(
        name=settings.chroma_collection_name,
        metadata={"hnsw:space": "cosine"},
    )


def upsert_chunks(document_id: str, file_name: str, chunks: list, embeddings: list[list[float]]) -> list[str]:
    """chunks: list[app.rag.chunker.Chunk]. Returns the vector_id assigned to each chunk."""
    collection = get_collection()
    ids = [f"{document_id}::{c.chunk_index}" for c in chunks]
    metadatas = [
        {
            "document_id": document_id,
            "file_name": file_name,
            "chunk_index": c.chunk_index,
            "page_number": c.page_number,
            # Truncate parent_text for metadata to avoid Chroma size limits.
            # Full parent_text is stored in the SQL DocumentChunk table.
            "parent_text": (getattr(c, "parent_text", c.text) or c.text)[:_MAX_METADATA_TEXT_CHARS],
            "section_title": getattr(c, "section_title", ""),
        }
        for c in chunks
    ]
    documents = [c.text for c in chunks]

    # Batch writes - large documents can produce thousands of chunks, and
    # Chroma (like most vector DBs) performs far better with bounded batches
    # than one giant call.
    batch_size = 256
    for i in range(0, len(ids), batch_size):
        collection.upsert(
            ids=ids[i:i + batch_size],
            embeddings=embeddings[i:i + batch_size],
            metadatas=metadatas[i:i + batch_size],
            documents=documents[i:i + batch_size],
        )
    logger.info(f"Upserted {len(ids)} chunks for document {document_id} ({file_name})")
    return ids


def query(query_text: str, top_k: int = 10, file_names: list[str] | None = None) -> list[dict]:
    try:
        collection = get_collection()
        collection_count = collection.count()
        if collection_count == 0:
            return []
        embedder = get_embedder()
        query_vector = embedder.embed_query(query_text)

        where = None
        if file_names:
            where = {"file_name": {"$in": file_names}} if len(file_names) > 1 else {"file_name": file_names[0]}

        results = collection.query(
            query_embeddings=[query_vector],
            # Chroma rejects a request larger than the collection.  A fixed
            # candidate pool (50+) is useful for large manuals, but must still
            # work while a small or newly uploaded document is the only one.
            n_results=min(top_k, collection_count),
            where=where,
        )

        hits = []
        ids = results.get("ids", [[]])[0]
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        dists = results.get("distances", [[]])[0]
        for id_, doc, meta, dist in zip(ids, docs, metas, dists):
            hits.append({
                "vector_id": id_,
                "text": doc,
                "parent_text": meta.get("parent_text", doc),
                "section_title": meta.get("section_title", ""),
                "document_id": meta.get("document_id"),
                "file_name": meta.get("file_name"),
                "chunk_index": meta.get("chunk_index"),
                "page_number": meta.get("page_number"),
                "score": round(1 - dist, 4),  # cosine distance -> similarity
                "retrieval_source": "dense",
            })
        return hits
    except Exception as exc:
        logger.warning("Vector search failed, returning no results: %s", exc)
        return []


def delete_document(document_id: str) -> None:
    """Removes every vector belonging to a document (used on file delete / re-sync)."""
    collection = get_collection()
    collection.delete(where={"document_id": document_id})
    logger.info(f"Deleted all vectors for document {document_id}")

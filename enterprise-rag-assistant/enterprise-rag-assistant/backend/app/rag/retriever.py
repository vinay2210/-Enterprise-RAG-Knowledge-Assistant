"""
Retrieval layer sitting between the vector store and the chat API.
Handles: global search, file-scoped (@filename) search, multi-document
search, and turns raw vector hits into Citation-ready dicts.
"""
from app.rag import vector_store
from app.utils.logger import logger


def retrieve(question: str, top_k: int = 6, file_filter: list[str] | None = None) -> list[dict]:
    hits = vector_store.query(question, top_k=top_k, file_names=file_filter)
    logger.debug(f"Retrieved {len(hits)} chunks for query (file_filter={file_filter})")
    return hits

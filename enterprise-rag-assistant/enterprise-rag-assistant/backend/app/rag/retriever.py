"""
Retrieval layer sitting between the vector store and the chat API.
Handles: global search, file-scoped (@filename) search, multi-document
search, and turns raw vector hits into Citation-ready dicts.

For large documents (500+ pages), this module:
  - Uses higher candidate counts for better recall
  - Enriches hits with full parent_text from the SQL mirror (avoiding Chroma metadata truncation)
  - Applies simple query expansion to improve semantic coverage
"""
import re
from app.rag import vector_store
from app.rag.bm25_retriever import get_bm25_index
from app.utils.logger import logger


def _reciprocal_rank_fusion(dense_hits: list[dict], bm25_hits: list[dict], k: int = 60) -> list[dict]:
    """Combines dense vector search and sparse BM25 search scores using Reciprocal Rank Fusion."""
    rrf_scores: dict[str, float] = {}
    doc_map: dict[str, dict] = {}

    for rank, hit in enumerate(dense_hits, start=1):
        vid = hit["vector_id"]
        rrf_scores[vid] = rrf_scores.get(vid, 0.0) + (1.0 / (k + rank))
        doc_map[vid] = hit

    for rank, hit in enumerate(bm25_hits, start=1):
        vid = hit["vector_id"]
        rrf_scores[vid] = rrf_scores.get(vid, 0.0) + (1.0 / (k + rank))
        if vid not in doc_map:
            doc_map[vid] = hit

    sorted_ids = sorted(rrf_scores.keys(), key=lambda vid: rrf_scores[vid], reverse=True)

    fused_results = []
    for vid in sorted_ids:
        item = dict(doc_map[vid])
        item["rrf_score"] = round(rrf_scores[vid], 5)
        fused_results.append(item)

    return fused_results


def _enrich_parent_text_from_sql(hits: list[dict]) -> list[dict]:
    """Replace potentially-truncated parent_text from Chroma metadata with the full
    version stored in the SQL DocumentChunk table. This is critical for large pages
    where Chroma metadata truncates the parent context."""
    if not hits:
        return hits

    try:
        from app.database import SessionLocal
        from app.models import DocumentChunk

        vector_ids = [h["vector_id"] for h in hits]
        db = SessionLocal()
        try:
            sql_chunks = db.query(DocumentChunk).filter(DocumentChunk.vector_id.in_(vector_ids)).all()
            sql_map = {sc.vector_id: sc for sc in sql_chunks}

            for hit in hits:
                sql_chunk = sql_map.get(hit["vector_id"])
                if sql_chunk and sql_chunk.parent_text:
                    hit["parent_text"] = sql_chunk.parent_text
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Failed to enrich parent_text from SQL, using Chroma metadata: {e}")

    return hits


def _expand_query(question: str) -> str:
    """Simple query expansion: extract key noun phrases and append them.
    This helps bridge vocabulary mismatches between user questions and document text,
    which is especially important for large documents with varied terminology."""
    # Remove common question words and stopwords to focus on content terms
    stopwords = {
        "what", "which", "where", "when", "who", "whom", "whose", "why", "how",
        "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "having",
        "do", "does", "did", "doing",
        "a", "an", "the", "and", "but", "or", "nor", "not", "no",
        "in", "on", "at", "to", "for", "of", "with", "by", "from",
        "as", "into", "through", "during", "before", "after",
        "about", "between", "above", "below",
        "can", "could", "would", "should", "shall", "will", "may", "might", "must",
        "it", "its", "this", "that", "these", "those",
        "i", "me", "my", "we", "us", "our", "you", "your", "he", "him", "his",
        "she", "her", "they", "them", "their",
        "tell", "explain", "describe", "define", "give", "list", "show",
        "please", "also", "just", "only", "very", "much", "more",
    }

    words = re.findall(r"\b[a-zA-Z0-9_]+\b", question.lower())
    key_terms = [w for w in words if w not in stopwords and len(w) > 2]

    if key_terms:
        # Append key terms to boost their weight in both vector and BM25 search
        expansion = " ".join(key_terms)
        return f"{question} {expansion}"
    return question


def retrieve(
    question: str,
    top_k: int = 10,
    file_filter: list[str] | None = None,
    strategy: str = "hybrid",
) -> list[dict]:
    """Retrieves context chunks using the selected strategy:
    - 'hybrid': Vector + BM25 keyword search fused with Reciprocal Rank Fusion (Recommended)
    - 'vector': Dense vector similarity only
    - 'bm25': BM25 keyword search only
    """
    # Use higher candidate pool for better recall on large documents
    # Search a deliberately wider pool before fusion.  With hundreds of pages,
    # top-6 alone is too narrow for dense retrieval to recover a relevant
    # section expressed with different wording.
    candidate_k = max(top_k * 10, 100)

    # Expand query for better coverage on large, terminology-rich documents
    expanded_question = _expand_query(question)

    if strategy == "vector":
        hits = vector_store.query(expanded_question, top_k=max(top_k, 15), file_names=file_filter)
    elif strategy == "bm25":
        bm25_index = get_bm25_index()
        hits = bm25_index.query(question, top_k=max(top_k, 15), file_names=file_filter)
    else:  # hybrid
        # Use expanded query for dense search (semantic), original for BM25 (exact keywords)
        dense_hits = vector_store.query(expanded_question, top_k=candidate_k, file_names=file_filter)
        bm25_index = get_bm25_index()
        bm25_hits = bm25_index.query(question, top_k=candidate_k, file_names=file_filter)

        fused = _reciprocal_rank_fusion(dense_hits, bm25_hits)
        hits = fused[:top_k]

    # Enrich with full parent_text from SQL (not truncated Chroma metadata)
    hits = _enrich_parent_text_from_sql(hits)

    # Deduplicate contiguous page contexts for clean prompt feeding
    seen_pages = set()
    deduped_hits = []
    for h in hits:
        page_key = (h.get("document_id"), h.get("page_number"), h.get("chunk_index"))
        if page_key not in seen_pages:
            seen_pages.add(page_key)
            deduped_hits.append(h)

    logger.debug(f"Retrieved {len(deduped_hits)} chunks using strategy '{strategy}' (file_filter={file_filter})")
    return deduped_hits

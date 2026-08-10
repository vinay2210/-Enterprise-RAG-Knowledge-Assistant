"""
Retrieval layer sitting between the vector store and the chat API.
Handles: global search, file-scoped (@filename) search, multi-document
search, and turns raw vector hits into Citation-ready dicts.
"""
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


def retrieve(
    question: str,
    top_k: int = 6,
    file_filter: list[str] | None = None,
    strategy: str = "hybrid",
) -> list[dict]:
    """Retrieves context chunks using the selected strategy:
    - 'hybrid': Vector + BM25 keyword search fused with Reciprocal Rank Fusion (Recommended)
    - 'vector': Dense vector similarity only
    - 'bm25': BM25 keyword search only
    """
    candidate_k = max(top_k * 4, 30)

    if strategy == "vector":
        hits = vector_store.query(question, top_k=max(top_k, 12), file_names=file_filter)
    elif strategy == "bm25":
        bm25_index = get_bm25_index()
        hits = bm25_index.query(question, top_k=max(top_k, 12), file_names=file_filter)
    else:  # hybrid
        dense_hits = vector_store.query(question, top_k=candidate_k, file_names=file_filter)
        bm25_index = get_bm25_index()
        bm25_hits = bm25_index.query(question, top_k=candidate_k, file_names=file_filter)

        fused = _reciprocal_rank_fusion(dense_hits, bm25_hits)
        hits = fused[:top_k]

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

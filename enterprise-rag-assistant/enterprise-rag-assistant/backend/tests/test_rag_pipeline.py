"""
Verification Test Script for RAG Pipeline Enhancements:
- Hierarchical Parent-Child Chunking
- BM25 Sparse Keyword Indexing
- Hybrid Retrieval (Dense Vector + BM25 via RRF)
- Large Document Scaling (Synthetic 500-page document test)
"""
import os
import sys

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.rag.extractor import PageText, _clean_text
from app.rag.chunker import chunk_pages
from app.rag.bm25_retriever import BM25Index
from app.rag.retriever import _reciprocal_rank_fusion, retrieve


def test_text_cleaning_and_hyphenation():
    raw_text = "This is an enter-\nprise document assistant.\n\nSection 1:\nDetails here."
    cleaned = _clean_text(raw_text)
    assert "enterprise" in cleaned, "Hyphenated word across line ending should be re-joined"
    print("[OK] Test 1 Passed: Text cleaning & hyphenation re-joining")


def test_hierarchical_chunking():
    pages = [
        PageText(page_number=1, text="Section 1: Architectural Foundation\n\nThis is a long paragraph explaining the core server design."),
        PageText(page_number=2, text="Section 2: Database Schema & Vector Indexes\n\nChromaDB stores fine-grained child vector embeddings."),
    ]
    chunks = chunk_pages(pages, child_chunk_size=20)
    assert len(chunks) >= 2
    for c in chunks:
        assert hasattr(c, "parent_text"), "Chunk must contain parent_text"
        assert c.parent_text != "", "parent_text must not be empty"
        assert c.page_number in (1, 2)
    print(f"[OK] Test 2 Passed: Hierarchical chunking generated {len(chunks)} child chunks with parent contexts")


def test_bm25_sparse_indexing_and_query():
    index = BM25Index()
    test_chunks = [
        {
            "vector_id": "doc1::0",
            "text": "The secret security protocol code is SEC-994821.",
            "parent_text": "Section 4: Security Protocols. The secret security protocol code is SEC-994821. Keep strictly confidential.",
            "document_id": "doc1",
            "file_name": "security_guide.pdf",
            "page_number": 4,
            "chunk_index": 0,
        },
        {
            "vector_id": "doc1::1",
            "text": "General user onboarding procedure for new employees.",
            "parent_text": "Section 1: Onboarding procedure.",
            "document_id": "doc1",
            "file_name": "security_guide.pdf",
            "page_number": 1,
            "chunk_index": 1,
        },
    ]
    index.add_chunks(test_chunks)

    # Exact technical code query
    results = index.query("SEC-994821", top_k=1)
    assert len(results) == 1
    assert results[0]["vector_id"] == "doc1::0"
    assert results[0]["score"] > 0
    print("[OK] Test 3 Passed: BM25 sparse index accurately retrieved exact technical code 'SEC-994821'")


def test_reciprocal_rank_fusion():
    dense_hits = [
        {"vector_id": "c1", "file_name": "doc.pdf", "page_number": 1, "chunk_index": 0, "text": "A"},
        {"vector_id": "c2", "file_name": "doc.pdf", "page_number": 2, "chunk_index": 1, "text": "B"},
    ]
    bm25_hits = [
        {"vector_id": "c2", "file_name": "doc.pdf", "page_number": 2, "chunk_index": 1, "text": "B"},
        {"vector_id": "c3", "file_name": "doc.pdf", "page_number": 3, "chunk_index": 2, "text": "C"},
    ]
    fused = _reciprocal_rank_fusion(dense_hits, bm25_hits)
    assert len(fused) == 3
    # c2 appeared in both lists, so its fused score should be highest!
    assert fused[0]["vector_id"] == "c2", f"c2 should rank #1 in RRF fusion, got {fused[0]['vector_id']}"
    print("[OK] Test 4 Passed: Reciprocal Rank Fusion (RRF) correctly boosts overlapping high-rank candidates")


def test_500_page_scaling():
    pages = [
        PageText(
            page_number=i,
            text=f"Chapter {i}: Enterprise Operations & System Metrics for Page {i}.\n\nDetailed operational logs for telemetry node {i * 17}."
        )
        for i in range(1, 501)
    ]
    chunks = chunk_pages(pages, child_chunk_size=100)
    assert len(chunks) >= 500, f"Expected at least 500 chunks for 500 pages, got {len(chunks)}"

    bm25 = BM25Index()
    dicts = [
        {
            "vector_id": f"large_doc::{c.chunk_index}",
            "text": c.text,
            "parent_text": c.parent_text,
            "document_id": "large_doc",
            "file_name": "enterprise_manual.pdf",
            "page_number": c.page_number,
            "chunk_index": c.chunk_index,
        }
        for c in chunks
    ]
    bm25.add_chunks(dicts)

    # Search for specific query in page 420
    hits = bm25.query("telemetry node 7140", top_k=3)  # 420 * 17 = 7140
    assert len(hits) > 0
    assert hits[0]["page_number"] == 420
    print(f"[OK] Test 5 Passed: 500-page document processed ({len(chunks)} chunks indexed), query hit Page {hits[0]['page_number']} instantly")


if __name__ == "__main__":
    print("--- RUNNING RAG PIPELINE ENHANCEMENT VERIFICATION ---")
    test_text_cleaning_and_hyphenation()
    test_hierarchical_chunking()
    test_bm25_sparse_indexing_and_query()
    test_reciprocal_rank_fusion()
    test_500_page_scaling()
    print("--- ALL VERIFICATION TESTS PASSED SUCCESSFULLY! ---")

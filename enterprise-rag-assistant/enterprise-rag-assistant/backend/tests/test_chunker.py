"""Unit tests for the chunking strategy - run with: pytest"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.rag.chunker import chunk_pages
from app.rag.extractor import PageText


def test_short_page_becomes_single_chunk():
    pages = [PageText(page_number=1, text="This is a short sentence.")]
    chunks = chunk_pages(pages, chunk_size=500, overlap=50)
    assert len(chunks) == 1
    assert chunks[0].page_number == 1


def test_long_page_splits_into_multiple_overlapping_chunks():
    long_text = " ".join(["word"] * 2000)  # forces multiple chunks at chunk_size=500
    pages = [PageText(page_number=3, text=long_text)]
    chunks = chunk_pages(pages, chunk_size=500, overlap=50)
    assert len(chunks) > 1
    assert all(c.page_number == 3 for c in chunks)
    # chunk_index should be sequential starting at 0
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_multiple_pages_keep_independent_page_numbers():
    pages = [
        PageText(page_number=1, text="Page one content."),
        PageText(page_number=2, text="Page two content."),
    ]
    chunks = chunk_pages(pages, chunk_size=500, overlap=50)
    page_numbers = {c.page_number for c in chunks}
    assert page_numbers == {1, 2}


def test_empty_pages_produce_no_chunks():
    chunks = chunk_pages([], chunk_size=500, overlap=50)
    assert chunks == []

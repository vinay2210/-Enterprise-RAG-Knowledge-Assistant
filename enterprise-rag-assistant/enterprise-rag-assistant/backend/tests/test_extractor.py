"""Unit tests for text extraction - run with: pytest"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from app.rag.extractor import extract_txt, extract_markdown, EmptyDocumentError


def test_extract_txt_returns_single_page():
    pages = extract_txt(b"Hello world, this is a test document.")
    assert len(pages) == 1
    assert pages[0].page_number == 1
    assert "Hello world" in pages[0].text


def test_extract_txt_rejects_empty_file():
    with pytest.raises(EmptyDocumentError):
        extract_txt(b"   \n\n   ")


def test_extract_markdown_strips_tags():
    pages = extract_markdown(b"# Title\n\nSome **bold** text.")
    assert "Title" in pages[0].text
    assert "<" not in pages[0].text

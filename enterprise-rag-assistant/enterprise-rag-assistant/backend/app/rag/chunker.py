"""
Chunking strategy for large documents.

Design decision (explained in README too): we chunk with a token-aware
sliding window PER PAGE, not across the whole document at once. Reasons:
  1. Keeps every chunk attributable to exactly one page number -> accurate
     citations, which the assignment explicitly requires.
  2. Avoids loading a 500-page document's full text into one giant string
     for chunking - we process page by page, so peak memory stays bounded
     regardless of document length.
  3. Overlap (default 75 tokens) preserves context across chunk boundaries
     so we don't split a sentence's meaning in half at retrieval time.

We use tiktoken purely as a consistent, fast token counter (not tied to any
one LLM) - chunk sizes are defined in tokens rather than characters because
token count is what actually determines embedding/LLM context usage.
"""
from dataclasses import dataclass

import tiktoken

from app.rag.extractor import PageText
from app.config import get_settings

settings = get_settings()
_encoding = tiktoken.get_encoding("cl100k_base")


@dataclass
class Chunk:
    chunk_index: int
    page_number: int
    text: str
    token_count: int


def _split_page_into_chunks(page_text: str, chunk_size: int, overlap: int) -> list[str]:
    tokens = _encoding.encode(page_text)
    if len(tokens) <= chunk_size:
        return [page_text]

    chunks = []
    start = 0
    while start < len(tokens):
        end = min(start + chunk_size, len(tokens))
        chunk_tokens = tokens[start:end]
        chunks.append(_encoding.decode(chunk_tokens))
        if end == len(tokens):
            break
        start = end - overlap  # step forward, keeping `overlap` tokens of context
    return chunks


def chunk_pages(
    pages: list[PageText],
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> list[Chunk]:
    chunk_size = chunk_size or settings.chunk_size_tokens
    overlap = overlap or settings.chunk_overlap_tokens

    chunks: list[Chunk] = []
    idx = 0
    for page in pages:
        for piece in _split_page_into_chunks(page.text, chunk_size, overlap):
            piece = piece.strip()
            if not piece:
                continue
            chunks.append(
                Chunk(
                    chunk_index=idx,
                    page_number=page.page_number,
                    text=piece,
                    token_count=len(_encoding.encode(piece)),
                )
            )
            idx += 1
    return chunks

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
import re
from dataclasses import dataclass, field

import tiktoken

from app.rag.extractor import PageText
from app.config import get_settings

settings = get_settings()
_encoding = tiktoken.get_encoding("cl100k_base")


@dataclass
class Chunk:
    chunk_index: int
    page_number: int
    text: str  # Child chunk text (high precision for vector indexing)
    parent_text: str  # Enclosing parent context (fed to LLM for rich context)
    token_count: int
    section_title: str = ""


def _count_tokens(text: str) -> int:
    return len(_encoding.encode(text))


def _extract_heading(paragraph: str) -> str:
    """Find title/heading pattern like # Heading, Section 1:, 1.2 Title, etc."""
    line = paragraph.strip().split("\n")[0]
    if line.startswith("#"):
        return line.lstrip("#").strip()
    if re.match(r"^(section|chapter|\d+(\.\d+)*)\b", line, re.IGNORECASE):
        return line[:60].strip()
    return ""


def chunk_pages(
    pages: list[PageText],
    child_chunk_size: int | None = None,
    child_overlap: int | None = None,
    parent_chunk_size: int = 1000,
) -> list[Chunk]:
    """Hierarchical & Structural Chunking:
    - Splits document into semantic paragraphs/sections.
    - Creates compact Child Chunks (default ~250 tokens) for vector similarity precision.
    - Binds each child chunk to a Parent Context (up to ~1000 tokens / page context) so the LLM
      gets full sentence/paragraph structures without losing page attribution.
    """
    child_chunk_size = child_chunk_size or 250
    child_overlap = child_overlap or 50

    chunks: list[Chunk] = []
    global_idx = 0

    for page in pages:
        page_text = page.text.strip()
        if not page_text:
            continue

        # Split page into structural paragraphs
        paragraphs = [p.strip() for p in re.split(r"\n\n+", page_text) if p.strip()]
        current_section = f"Page {page.page_number}"

        for i, para in enumerate(paragraphs):
            heading = _extract_heading(para)
            if heading:
                current_section = heading

            # Determine Parent Context (the paragraph itself or surrounding paragraphs on the page)
            parent_context = page_text
            para_tokens = _encoding.encode(para)

            if len(para_tokens) <= child_chunk_size:
                child_text = para
                chunks.append(
                    Chunk(
                        chunk_index=global_idx,
                        page_number=page.page_number,
                        text=child_text,
                        parent_text=parent_context,
                        token_count=len(para_tokens),
                        section_title=current_section,
                    )
                )
                global_idx += 1
            else:
                # Large paragraph: sliding window child chunks inside the paragraph context
                start = 0
                while start < len(para_tokens):
                    end = min(start + child_chunk_size, len(para_tokens))
                    piece_tokens = para_tokens[start:end]
                    child_text = _encoding.decode(piece_tokens).strip()

                    if child_text:
                        chunks.append(
                            Chunk(
                                chunk_index=global_idx,
                                page_number=page.page_number,
                                text=child_text,
                                parent_text=parent_context,
                                token_count=len(piece_tokens),
                                section_title=current_section,
                            )
                        )
                        global_idx += 1

                    if end == len(para_tokens):
                        break
                    start = end - child_overlap

    return chunks

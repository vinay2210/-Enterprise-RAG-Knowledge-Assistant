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
    parent_chunk_size: int = 1500,
    # Backwards-compatible names used by the existing tests and any external callers.
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> list[Chunk]:
    """Create overlapping, page-scoped child chunks with local parent context.

    A parent context must always contain the child chunk it belongs to.  Using the
    first ``parent_chunk_size`` tokens of an entire page breaks this invariant for
    a match near the end of a dense PDF page: retrieval finds the right child, but
    the LLM receives unrelated text from the beginning of that page.  This is
    especially harmful in long manuals.  Instead, each parent is a window centred
    on its child, while still retaining page-level citations.
    """
    child_chunk_size = child_chunk_size or chunk_size or settings.chunk_size_tokens
    child_overlap = child_overlap if child_overlap is not None else overlap
    child_overlap = settings.chunk_overlap_tokens if child_overlap is None else child_overlap

    if child_chunk_size <= 0:
        raise ValueError("child_chunk_size must be greater than zero")
    if child_overlap < 0 or child_overlap >= child_chunk_size:
        raise ValueError("child_overlap must be at least zero and smaller than child_chunk_size")
    parent_chunk_size = max(parent_chunk_size, child_chunk_size)

    chunks: list[Chunk] = []
    global_idx = 0

    # Keep neighbouring pages available for a small amount of boundary context.
    page_texts: dict[int, str] = {}
    for page in pages:
        page_text = page.text.strip()
        if page_text:
            page_texts[page.page_number] = page_text

    for page in pages:
        page_text = page.text.strip()
        if not page_text:
            continue

        page_tokens = _encoding.encode(page_text)
        if not page_tokens:
            continue

        prev_page_text = page_texts.get(page.page_number - 1, "")
        next_page_text = page_texts.get(page.page_number + 1, "")

        # Associate each child with its closest preceding structural heading.
        headings: list[tuple[int, str]] = [(0, f"Page {page.page_number}")]
        offset = 0
        for paragraph in (p.strip() for p in re.split(r"\n\n+", page_text) if p.strip()):
            heading = _extract_heading(paragraph)
            if heading:
                headings.append((offset, heading))
            offset += len(_encoding.encode(paragraph))

        start = 0
        while start < len(page_tokens):
            end = min(start + child_chunk_size, len(page_tokens))
            child_tokens = page_tokens[start:end]
            child_text = _encoding.decode(child_tokens).strip()

            # Centre the context around the retrieved child, rather than always
            # taking text from the top of the page.
            side_context = max((parent_chunk_size - len(child_tokens)) // 2, 0)
            parent_start = max(0, start - side_context)
            parent_end = min(len(page_tokens), end + side_context)
            parent_tokens = page_tokens[parent_start:parent_end]

            # If the local context hits a page boundary, spend only spare budget
            # on neighbouring text.  The matching child is never trimmed away.
            spare = parent_chunk_size - len(parent_tokens)
            parent_parts: list[str] = []
            if parent_start == 0 and prev_page_text and spare > 0:
                previous = _encoding.encode(prev_page_text)[-min(spare, 120):]
                if previous:
                    parent_parts.append("[...from previous page] " + _encoding.decode(previous).strip())
                    spare -= len(previous)
            parent_parts.append(_encoding.decode(parent_tokens).strip())
            if parent_end == len(page_tokens) and next_page_text and spare > 0:
                following = _encoding.encode(next_page_text)[:min(spare, 120)]
                if following:
                    parent_parts.append("[continues on next page...] " + _encoding.decode(following).strip())

            section_title = next((title for position, title in reversed(headings) if position <= start), headings[0][1])
            if child_text:
                chunks.append(
                    Chunk(
                        chunk_index=global_idx,
                        page_number=page.page_number,
                        text=child_text,
                        parent_text="\n\n".join(parent_parts),
                        token_count=len(child_tokens),
                        section_title=section_title,
                    )
                )
                global_idx += 1

            if end == len(page_tokens):
                break
            start = end - child_overlap

    return chunks

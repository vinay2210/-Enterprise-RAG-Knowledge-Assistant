"""
Text extraction for PDF, DOCX, TXT, and Markdown.

Returns a list of (page_number, text) tuples so downstream chunking can
retain page-level provenance for citations. TXT/MD don't have real pages,
so we treat them as a single "page 1" - callers should not assume every
file has more than one page.
"""
from dataclasses import dataclass

from pypdf import PdfReader
import docx
import markdown as md_lib
import re
import io


class ExtractionError(Exception):
    pass


class EmptyDocumentError(Exception):
    pass


@dataclass
class PageText:
    page_number: int
    text: str


def _clean_text(text: str) -> str:
    """Normalize whitespace, drop control chars, collapse repeated blank lines."""
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_pdf(file_bytes: bytes) -> list[PageText]:
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
    except Exception as e:
        raise ExtractionError(f"Corrupted or unreadable PDF: {e}")

    pages = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            raw = page.extract_text() or ""
        except Exception:
            raw = ""  # a single bad page shouldn't kill the whole document
        cleaned = _clean_text(raw)
        if cleaned:
            pages.append(PageText(page_number=i, text=cleaned))

    if not pages:
        raise EmptyDocumentError("PDF contains no extractable text (may be scanned/image-only).")
    return pages


def extract_docx(file_bytes: bytes) -> list[PageText]:
    try:
        document = docx.Document(io.BytesIO(file_bytes))
    except Exception as e:
        raise ExtractionError(f"Corrupted or unreadable DOCX: {e}")

    # DOCX has no reliable page boundaries via python-docx, so we synthesize
    # "pages" every ~45 paragraphs purely to keep citations short and useful.
    paras = [p.text for p in document.paragraphs if p.text.strip()]
    if not paras:
        raise EmptyDocumentError("DOCX contains no text.")

    pages = []
    chunk_size = 45
    for i in range(0, len(paras), chunk_size):
        page_num = i // chunk_size + 1
        text = _clean_text("\n".join(paras[i:i + chunk_size]))
        if text:
            pages.append(PageText(page_number=page_num, text=text))
    return pages


def extract_txt(file_bytes: bytes) -> list[PageText]:
    try:
        text = file_bytes.decode("utf-8", errors="ignore")
    except Exception as e:
        raise ExtractionError(f"Could not decode text file: {e}")
    cleaned = _clean_text(text)
    if not cleaned:
        raise EmptyDocumentError("Text file is empty.")
    return [PageText(page_number=1, text=cleaned)]


def extract_markdown(file_bytes: bytes) -> list[PageText]:
    try:
        raw = file_bytes.decode("utf-8", errors="ignore")
        html = md_lib.markdown(raw)
        text = re.sub(r"<[^>]+>", " ", html)  # strip tags, keep prose
    except Exception as e:
        raise ExtractionError(f"Could not parse Markdown: {e}")
    cleaned = _clean_text(text)
    if not cleaned:
        raise EmptyDocumentError("Markdown file is empty.")
    return [PageText(page_number=1, text=cleaned)]


EXTRACTORS = {
    "pdf": extract_pdf,
    "docx": extract_docx,
    "txt": extract_txt,
    "md": extract_markdown,
}


def extract(file_extension: str, file_bytes: bytes) -> list[PageText]:
    fn = EXTRACTORS.get(file_extension)
    if not fn:
        raise ExtractionError(f"Unsupported file type: {file_extension}")
    return fn(file_bytes)

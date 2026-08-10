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
    """Normalize whitespace, join line-broken words, collapse extra blank lines while preserving paragraph breaks."""
    if not text:
        return ""
    text = text.replace("\x00", "")
    # Join hyphenated words split across lines
    text = re.sub(r"(\w+)-\n(\w+)", r"\1\2", text)
    # Replace non-breaking spaces and tabs with standard space
    text = text.replace("\xa0", " ").replace("\t", " ")
    # Replace single line breaks inside paragraphs with single spaces, preserving double line breaks
    lines = text.split("\n")
    cleaned_lines = []
    current_para = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current_para:
                cleaned_lines.append(" ".join(current_para))
                current_para = []
        else:
            current_para.append(stripped)
    if current_para:
        cleaned_lines.append(" ".join(current_para))

    result = "\n\n".join(cleaned_lines)
    result = re.sub(r"[ \t]+", " ", result)
    return result.strip()


def extract_pdf(file_bytes: bytes) -> list[PageText]:
    pages = []
    # 1. Try PyMuPDF (fitz) - high-speed, preserves reading order and text blocks across 500+ pages
    try:
        import fitz
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        for i, page in enumerate(doc, start=1):
            raw = page.get_text("text") or ""
            cleaned = _clean_text(raw)
            if cleaned:
                pages.append(PageText(page_number=i, text=cleaned))
    except Exception as exc:
        pages = []

    # 2. Fallback to pypdf if PyMuPDF fails
    if not pages:
        try:
            reader = PdfReader(io.BytesIO(file_bytes))
            for i, page in enumerate(reader.pages, start=1):
                try:
                    raw = page.extract_text(layout_mode_space_vertically=False) or page.extract_text() or ""
                except Exception:
                    raw = ""
                cleaned = _clean_text(raw)
                if cleaned:
                    pages.append(PageText(page_number=i, text=cleaned))
        except Exception as e:
            raise ExtractionError(f"Corrupted or unreadable PDF: {e}")

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

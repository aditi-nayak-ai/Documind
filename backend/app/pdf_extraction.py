import io
import logging
import re

import pdfplumber
import pytesseract
from pdf2image import convert_from_bytes
from pypdf import PdfReader

from app.exceptions import ExtractionError

logger = logging.getLogger("documind")

MIN_EXTRACTED_CHARS = 100
# A page with less real text than this is treated as "pypdf basically
# found nothing here" and gets an OCR pass -- typically a scanned page
# or one that's mostly an embedded image. Higher than 0 so a short
# title/section-header page ("Chapter 3") doesn't trigger a needless
# OCR call; low enough that a genuinely empty/image page still does.
MIN_PAGE_CHARS_BEFORE_OCR = 20


def _extract_tables_as_text(pdf_bytes: bytes) -> dict:
    """Return {page_index: table_text} for every page with at least one
    detected table, rendered as simple " | "-delimited rows so it flows
    into the same char-based chunker as regular paragraph text below.

    This is additive and pdfplumber-only -- the primary text extraction
    in extract_text() below still runs through pypdf, unchanged, so
    chunking/overlap behavior already calibrated against pypdf's exact
    whitespace conventions (see chunk_text's docstring) isn't disturbed
    for the common case of a PDF with no tables.
    """
    tables_by_page = {}
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for i, page in enumerate(pdf.pages):
                tables = page.extract_tables()
                if not tables:
                    continue
                rendered = []
                for table in tables:
                    for row in table:
                        cells = [str(c).strip() if c is not None else "" for c in row]
                        if any(cells):
                            rendered.append(" | ".join(cells))
                if rendered:
                    tables_by_page[i] = "[Table]\n" + "\n".join(rendered)
    except Exception as e:  # noqa: BLE001 -- deliberate: table detection is a best-effort enhancement, not required for ingest to succeed
        logger.warning("Table extraction failed, continuing with plain text only", extra={"error": str(e)})
    return tables_by_page


def _ocr_page(pdf_bytes: bytes, page_index: int) -> str:
    """Best-effort OCR for a single page pypdf found little/no text on.
    Rendered at 200 DPI -- a middle ground between OCR accuracy and
    per-page render time, since this runs synchronously during ingest.
    Any failure (tesseract/poppler not installed, corrupt page image,
    etc.) is swallowed: OCR is a fallback, not a requirement, and the
    caller keeps whatever pypdf already found for that page.
    """
    try:
        images = convert_from_bytes(pdf_bytes, dpi=200, first_page=page_index + 1, last_page=page_index + 1)
        if not images:
            return ""
        return pytesseract.image_to_string(images[0]) or ""
    except Exception as e:  # noqa: BLE001 -- deliberate: OCR is a fallback, not a requirement; a missing tesseract/poppler binary or a corrupt page must not fail the whole ingest
        logger.warning("OCR fallback failed for page", extra={"page": page_index, "error": str(e)})
        return ""


def extract_text(contents: bytes) -> str:
    """Extract all readable text from a PDF's raw bytes.

    Three sources are combined per page: pypdf's plain-text extraction
    (primary, unchanged from before), pdfplumber's table detection
    (tables pypdf flattens or drops entirely), and a tesseract OCR pass
    for any page pypdf found almost nothing on (scanned/image pages).

    Raises ExtractionError (a ValueError subclass, see exceptions.py) if
    the combined result is still too short to be useful.
    """
    reader = PdfReader(io.BytesIO(contents), strict=False)
    tables_by_page = _extract_tables_as_text(contents)

    page_texts = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if len(text.strip()) < MIN_PAGE_CHARS_BEFORE_OCR:
            ocr_text = _ocr_page(contents, i)
            if len(ocr_text.strip()) > len(text.strip()):
                text = ocr_text
        table_text = tables_by_page.get(i)
        if table_text:
            text = (text + "\n\n" + table_text) if text.strip() else table_text
        page_texts.append(text)

    full_text = "".join(page_texts)

    if len(full_text.strip()) < MIN_EXTRACTED_CHARS:
        raise ExtractionError(
            "Could not extract readable text from this PDF. "
            "It may be a scanned or image-only document — try a text-based PDF instead."
        )
    return full_text


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 80) -> list:
    """Split text into chunks for embedding.

    Two things worth knowing about this implementation:
      1. Long paragraphs are split on word boundaries instead of a blind
         `para[i:i+chunk_size]` slice, so words are never cut in half.
      2. A second pass prepends a small tail of each chunk onto the next
         one (`overlap` chars). Without this, a fact sitting right at a
         chunk boundary could end up split across two chunks and not
         fully present in either -- with fixed top_k=5 retrieval, that
         made it structurally unrecoverable, not just harder to find.
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    raw_chunks = []
    current = ""

    def push_current():
        if current:
            raw_chunks.append(current.strip())

    for para in paragraphs:
        if len(para) > chunk_size:
            push_current()
            current = ""
            words = para.split(" ")
            piece = ""
            for word in words:
                candidate = f"{piece} {word}".strip()
                if len(candidate) > chunk_size and piece:
                    raw_chunks.append(piece.strip())
                    piece = word
                else:
                    piece = candidate
            current = piece
            continue
        candidate = f"{current} {para}".strip()
        if len(candidate) <= chunk_size:
            current = candidate
        else:
            push_current()
            current = para
    push_current()

    if not overlap or len(raw_chunks) < 2:
        return raw_chunks

    overlapped = [raw_chunks[0]]
    for i in range(1, len(raw_chunks)):
        tail = _word_safe_tail(raw_chunks[i - 1], overlap)
        overlapped.append((tail + " " + raw_chunks[i]).strip() if tail else raw_chunks[i])
    return overlapped


def _word_safe_tail(chunk: str, overlap: int) -> str:
    """Return roughly the last `overlap` characters of chunk, trimmed so it
    starts at a word boundary instead of mid-word.

    A plain chunk[-overlap:] slice cuts by character count with no regard
    for word breaks, so on real (non-paragraph-marked) PDF text it started
    mid-word at 20 of 27 chunk boundaries in testing -- e.g. a chunk could
    begin "enue increas..." instead of "revenue increas...". This trims
    off that partial leading word instead of keeping it.

    Checks for ANY whitespace character, not just " ": pypdf inserts "\\n"
    between lines within what was one paragraph on the page, not only
    between paragraphs, so a plain `.find(" ")` still missed those breaks
    in testing (2 of 27 boundaries) and this exists to catch them too.
    """
    if len(chunk) <= overlap:
        return chunk  # the whole chunk already starts at a word boundary
    tail = chunk[-overlap:]
    match = re.search(r"\s", tail)
    if match is None:
        return ""  # single word longer than `overlap`; nothing safe to carry over
    return tail[match.end():].lstrip()

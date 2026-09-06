import io

from pypdf import PdfReader

from app.exceptions import ExtractionError

MIN_EXTRACTED_CHARS = 100


def extract_text(contents: bytes) -> str:
    """Extract all readable text from a PDF's raw bytes.

    Raises ExtractionError (a ValueError subclass, see exceptions.py) if
    the result is too short to be useful -- typically a scanned or
    image-only PDF with no embedded text layer.
    """
    reader = PdfReader(io.BytesIO(contents), strict=False)
    full_text = "".join(page.extract_text() or "" for page in reader.pages)

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
         fully present in either -- with fixed top_k=3 retrieval, that
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
        tail = raw_chunks[i - 1][-overlap:]
        overlapped.append((tail + " " + raw_chunks[i]).strip())
    return overlapped

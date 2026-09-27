"""Tests for the table-extraction and OCR-fallback additions in
app/pdf_extraction.py.

OCR itself is mocked rather than exercised for real: it depends on the
tesseract/poppler system binaries (installed in the Dockerfile for
production, but not part of this repo's CI environment), so a test that
actually shells out to them would be slow and would fail in CI for a
reason that has nothing to do with the code under test. What's tested
instead is the logic around OCR -- that it's called only for near-empty
pages, and that its result is used when it is called -- which is the
part that can actually regress.
"""

import io

import pytest


def _reportlab_table_pdf(rows):
    """Build a real PDF containing one bordered table via reportlab's
    Table flowable -- a GRID style draws actual ruling lines, which is
    what pdfplumber's table detector looks for. A Table alone (no other
    text) also naturally exercises the near-empty-page OCR path further
    down, since pdfplumber table cells aren't picked up by pypdf's
    extract_text() the way paragraph text is.
    """
    pytest.importorskip("reportlab")
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    table = Table(rows)
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, (0, 0, 0))]))
    doc.build([table])
    return buffer.getvalue()


def test_tables_are_extracted_as_text():
    from app import pdf_extraction

    rows = [
        ["Region", "Q3 Revenue", "Growth"],
        ["North", "$4.2M", "12%"],
        ["South", "$3.1M", "8%"],
    ]
    pdf_bytes = _reportlab_table_pdf(rows)

    tables_by_page = pdf_extraction._extract_tables_as_text(pdf_bytes)

    assert 0 in tables_by_page
    rendered = tables_by_page[0]
    assert rendered.startswith("[Table]")
    for row in rows:
        for cell in row:
            assert cell in rendered


def test_extract_text_includes_table_content_for_a_table_only_pdf():
    """A page that's *only* a table has almost nothing for pypdf's plain
    extract_text() to find -- without the table-extraction addition,
    this would previously come back too short and raise ExtractionError.
    """
    from app import pdf_extraction

    rows = [["Metric", "Value"]] + [[f"row{i}", str(i * 7)] for i in range(20)]
    pdf_bytes = _reportlab_table_pdf(rows)

    text = pdf_extraction.extract_text(pdf_bytes)

    assert "[Table]" in text
    assert "row5" in text
    assert "35" in text  # 5 * 7, from the row5 line


def test_table_extraction_failure_does_not_block_plain_text(monkeypatch):
    """pdfplumber failing to parse a PDF (malformed input, unsupported
    feature, etc.) must degrade to "no tables found", not break the
    primary pypdf extraction path.
    """
    import pdfplumber

    from app import pdf_extraction

    def boom(*args, **kwargs):
        raise ValueError("simulated pdfplumber failure")

    monkeypatch.setattr(pdfplumber, "open", boom)

    pytest.importorskip("reportlab")
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(100, 750, "This is plain readable text with no tables at all. " * 5)
    c.save()
    buf.seek(0)

    text = pdf_extraction.extract_text(buf.getvalue())
    assert "plain readable text" in text


def test_ocr_used_when_page_text_is_near_empty(monkeypatch):
    from app import pdf_extraction

    monkeypatch.setattr(pdf_extraction, "_extract_tables_as_text", lambda contents: {})
    monkeypatch.setattr(
        pdf_extraction, "_ocr_page", lambda contents, page_index: "Text recovered via OCR from a scanned page. " * 5
    )

    pytest.importorskip("reportlab")
    from reportlab.pdfgen import canvas

    # A PDF with one blank page -- pypdf will find nothing on it, which
    # should trigger the OCR fallback. (An empty reportlab Canvas with no
    # showPage() call produces a PDF with zero pages, not a blank one, so
    # showPage() is required here to get a real near-empty page to test.)
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.showPage()
    c.save()
    buf.seek(0)

    text = pdf_extraction.extract_text(buf.getvalue())
    assert "recovered via OCR" in text


def test_ocr_not_used_when_page_already_has_enough_text(monkeypatch):
    """OCR is comparatively slow (renders the page to an image, then runs
    tesseract on it) -- it must stay off the hot path for the common
    case of a normal text PDF, not just be correct when it does run.
    """
    from app import pdf_extraction

    calls = []
    monkeypatch.setattr(pdf_extraction, "_extract_tables_as_text", lambda contents: {})
    monkeypatch.setattr(pdf_extraction, "_ocr_page", lambda contents, page_index: calls.append(page_index) or "")

    pytest.importorskip("reportlab")
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(100, 750, "Plenty of real extractable text on this page already. " * 5)
    c.save()
    buf.seek(0)

    pdf_extraction.extract_text(buf.getvalue())
    assert calls == []

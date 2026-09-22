"""Unit tests for ChatEngine._chunk_text.
 
Pure logic, no DB/network involved -- these should run in milliseconds.
"""
 
import pytest
 
 
def test_empty_text_returns_no_chunks(chat_engine):
    assert chat_engine._chunk_text("") == []
 
 
def test_short_text_returns_single_chunk(chat_engine):
    text = "This is a short paragraph well under the chunk size."
    chunks = chat_engine._chunk_text(text, chunk_size=500, overlap=80)
    assert len(chunks) == 1
    assert chunks[0] == text
 
 
def test_long_single_word_is_not_lost(chat_engine):
    """A single 'word' longer than chunk_size (e.g. a URL or hash) must
    still show up in the output rather than being silently dropped by the
    word-boundary splitting logic."""
    long_word = "x" * 2000
    chunks = chat_engine._chunk_text(long_word, chunk_size=500, overlap=0)
    assert "".join(chunks).replace(" ", "") != ""
    assert long_word[:100] in "".join(chunks)
 
 
def test_words_are_never_split_mid_word(chat_engine):
    """Regression guard for the word-boundary fix described in the source
    comment -- a naive text[i:i+chunk_size] slice would cut words in half."""
    words = [f"word{i}" for i in range(300)]
    text = " ".join(words)
    chunks = chat_engine._chunk_text(text, chunk_size=50, overlap=0)
    for chunk in chunks:
        for token in chunk.split(" "):
            if token:
                assert token in words, f"Found a token that isn't a whole word: {token!r}"
 
 
def test_no_chunk_exceeds_size_plus_overlap(chat_engine):
    text = " ".join(f"word{i}" for i in range(500))
    chunk_size, overlap = 200, 50
    chunks = chat_engine._chunk_text(text, chunk_size=chunk_size, overlap=overlap)
    for chunk in chunks:
        assert len(chunk) <= chunk_size + overlap + 10  # small slack for the joining space
 
 
def test_overlap_prepends_tail_of_previous_chunk(chat_engine):
    """This is the behavior the source comment calls out explicitly: a fact
    sitting at a chunk boundary must appear in full in at least one chunk,
    not be split across two with neither containing it whole.
 
    Step 4 note: this used to assert chunks[i].startswith(prev_tail[:10])
    where prev_tail was a raw chunks[i-1][-30:] character slice -- i.e. it
    encoded the mid-word-cut bug as the expected, correct behavior. The
    fix trims that slice to a word boundary, so the exact characters
    carried over changed; what must still hold is the actual guarantee
    from the comment above: the LAST WHOLE WORD of the previous chunk
    reappears as the first word of the next one.
    """
    text = " ".join(f"word{i}" for i in range(300))
    chunks_no_overlap = chat_engine._chunk_text(text, chunk_size=100, overlap=0)  # the raw chunks
    chunks = chat_engine._chunk_text(text, chunk_size=100, overlap=30)
    assert len(chunks) == len(chunks_no_overlap) >= 2
    for i in range(1, len(chunks)):
        # The carried-over words (whatever fits, word-boundary aligned,
        # within the last 30 chars of the PREVIOUS raw chunk) must be a
        # real, contiguous suffix of that raw chunk...
        overlap_words = chunks[i].split(" ")[: -len(chunks_no_overlap[i].split(" "))]
        assert overlap_words, "expected some overlap text to be carried over"
        assert chunks_no_overlap[i - 1].endswith(" ".join(overlap_words))
        # ...and every one of those words must be a whole word from the
        # source, never a character-level fragment of one.
        for word in overlap_words:
            assert word in text.split(" "), f"carried-over fragment is not a whole word: {word!r}"
 
 
def test_zero_overlap_produces_no_duplication(chat_engine):
    text = " ".join(f"word{i}" for i in range(300))
    chunks = chat_engine._chunk_text(text, chunk_size=100, overlap=0)
    rejoined = " ".join(chunks)
    for i in range(300):
        assert rejoined.count(f"word{i} ") <= 2
 
 
def test_paragraph_breaks_are_respected_when_they_fit(chat_engine):
    text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
    chunks = chat_engine._chunk_text(text, chunk_size=500, overlap=0)
    assert len(chunks) == 1
    assert "First paragraph." in chunks[0]
    assert "Third paragraph." in chunks[0]
 
 
# ---- Step 4: the overlap slice must respect word boundaries ---------------
#
# Real PDF text almost never contains "\n\n" (pypdf uses single "\n" both
# within and between paragraphs), so the code above never sees a genuine
# multi-word paragraph to split -- the whole document becomes one long
# "paragraph" and goes through the safe word-boundary splitter. That part
# was never actually broken. The bug was downstream: the OVERLAP step took
# `chunk[-overlap:]`, a raw character slice with no regard for word or
# even line breaks, and prepended it to the next chunk -- so a chunk could
# begin "enue increased ..." instead of "revenue increased ...".
 
 
def test_overlap_never_starts_mid_word(chat_engine):
    words = [f"lexeme{i}" for i in range(400)]
    text = " ".join(words)
    chunks = chat_engine._chunk_text(text, chunk_size=200, overlap=60)
    assert len(chunks) > 3  # otherwise this test isn't exercising the overlap logic at all
    for chunk in chunks[1:]:
        first_token = chunk.split(" ", 1)[0]
        assert first_token in words, f"chunk started mid-word: {first_token!r}"
 
 
def test_overlap_never_starts_mid_word_across_newlines(chat_engine):
    """Regression test for the exact bug found in production: pypdf wraps
    a line with a plain '\\n' instead of a space (e.g. it produced the
    literal run "quarterly\\nrevenue" from one continuous sentence), and a
    boundary check that only looked for ' ' missed that break and still
    cut 2 of 27 real-document chunks mid-word.
 
    Every 4th word here is joined to the next with '\\n' instead of ' ',
    mimicking that line-wrap pattern, while most of the text still uses
    plain spaces -- real extracted text is never ALL newlines with zero
    spaces (see test_paragraph_breaks_are_respected_when_they_fit for
    that boundary, which is a separate, pre-existing limitation)."""
    words = [f"lexeme{i}" for i in range(400)]
    parts = []
    for i, word in enumerate(words):
        parts.append(word)
        parts.append("\n" if i % 4 == 3 else " ")
    text = "".join(parts)
    chunks = chat_engine._chunk_text(text, chunk_size=200, overlap=60)
    assert len(chunks) > 3
    import re
 
    for chunk in chunks[1:]:
        first_token = re.split(r"\s+", chunk.strip(), maxsplit=1)[0]
        assert first_token in words, f"chunk started mid-word across a newline: {first_token!r}"
 
 
def test_overlap_drops_tail_when_no_boundary_exists(chat_engine):
    """A single word/token longer than `overlap` (a URL, a hash, a run of
    reportlab-glued text) has no safe place to cut -- the fix must drop it
    rather than reproduce the mid-word bug."""
    text = "short " + ("x" * 500) + " next-real-word and more text after that"
    chunks = chat_engine._chunk_text(text, chunk_size=100, overlap=30)
    for chunk in chunks[1:]:
        assert not chunk.startswith("x" * 10), f"leaked a mid-token slice: {chunk[:20]!r}"
 
 
def test_no_source_word_is_lost_by_the_overlap_fix(chat_engine):
    """The fix must not silently drop real content -- every word in the
    source must still appear in at least one chunk."""
    words = [f"tok{i}" for i in range(500)]
    text = " ".join(words)
    chunks = chat_engine._chunk_text(text, chunk_size=150, overlap=40)
    covered = set(" ".join(chunks).split())
    missing = set(words) - covered
    assert not missing, f"words dropped entirely: {sorted(missing)[:5]}"
 
 
def test_reportlab_pdf_produces_zero_mid_word_overlap_cuts(chat_engine, monkeypatch):
    """End-to-end regression test using the exact scenario that first
    surfaced this bug: a real PDF (built with reportlab, read with pypdf),
    chunked with the production defaults (chunk_size=500, overlap=80)."""
    import io
    import re
 
    pytest.importorskip("reportlab")
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer
 
    from app import pdf_extraction
 
    style = getSampleStyleSheet()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    story = []
    paragraph_text = (
        "The quarterly revenue increased substantially across every region because "
        "customers renewed their annual contracts earlier than expected and the sales "
        "team closed several enterprise deals. "
    ) * 6
    for section in range(3):
        story.append(Paragraph(f"Section {section + 1} heading", style["Heading2"]))
        for _ in range(4):
            story.append(Paragraph(paragraph_text, style["BodyText"]))
            story.append(Spacer(1, 12))
        story.append(PageBreak())
    doc.build(story)
 
    text = pdf_extraction.extract_text(buffer.getvalue())
    chunks = pdf_extraction.chunk_text(text, 500, 80)  # production defaults
    source_tokens = set(re.split(r"\s+", text.strip()))
 
    assert len(chunks) > 10  # sanity: this document does produce multiple chunks
    for chunk in chunks[1:]:
        first_token = re.split(r"\s+", chunk.strip())[0]
        assert first_token in source_tokens, f"mid-word chunk boundary: {first_token!r}"

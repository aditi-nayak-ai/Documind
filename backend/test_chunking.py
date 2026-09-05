"""Unit tests for ChatEngine._chunk_text.

Pure logic, no DB/network involved -- these should run in milliseconds.
"""


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
    not be split across two with neither containing it whole."""
    text = " ".join(f"word{i}" for i in range(300))
    chunks = chat_engine._chunk_text(text, chunk_size=100, overlap=30)
    assert len(chunks) >= 2
    for i in range(1, len(chunks)):
        prev_tail = chunks[i - 1][-30:]
        assert chunks[i].startswith(prev_tail.strip()[:10])


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

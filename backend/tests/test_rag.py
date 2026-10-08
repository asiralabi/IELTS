"""Pure unit tests for the RAG layer (no LLM, no qdrant, no fastembed)."""

from app.rag.ingest import chunk_text, clean_text
from app.rag.retriever import retrieve_context
from app.rag.store import get_vector_store, set_vector_store
from tests.conftest import MockVectorStore


class TestCleanText:
    def test_collapses_whitespace(self):
        assert clean_text("hello    world\n\n  again") == "hello world again"

    def test_drops_page_numbers(self):
        raw = "First page text\n12\fSecond page text\nPage 13\f14\nThird page text"
        cleaned = clean_text(raw)
        assert "12" not in cleaned
        assert "13" not in cleaned
        assert "14" not in cleaned
        assert "First page text" in cleaned
        assert "Second page text" in cleaned
        assert "Third page text" in cleaned

    def test_normalises_smart_quotes(self):
        assert clean_text("‘quoted’ “value”") == "'quoted' \"value\""


class TestChunkText:
    def test_empty_text_gives_no_chunks(self):
        assert chunk_text("", chunk_size=40, overlap=10) == []

    def test_respects_size_and_overlap_and_covers_text(self):
        words = [f"w{i}" for i in range(100)]
        text = " ".join(words)
        chunk_size, overlap = 40, 10
        words_per_chunk = chunk_size * 3 // 4  # 30, mirrors ingest.py heuristic
        overlap_words = overlap * 3 // 4  # 7

        chunks = chunk_text(text, chunk_size=chunk_size, overlap=overlap)
        assert len(chunks) > 1

        # approximate size respected
        for chunk in chunks:
            assert len(chunk.split()) <= words_per_chunk

        # consecutive chunks overlap by overlap_words words
        first, second = chunks[0].split(), chunks[1].split()
        assert first[-overlap_words:] == second[:overlap_words]

        # full coverage, in order, no gaps
        step = words_per_chunk - overlap_words
        reconstructed = chunks[0].split()
        for chunk in chunks[1:]:
            reconstructed.extend(chunk.split()[overlap_words:])
        # sliding window may re-cover the tail; reconstructed must start with all words
        assert reconstructed[: len(words)] == words
        assert chunks[-1].split()[-1] == words[-1]

    def test_short_text_single_chunk(self):
        assert chunk_text("just a few words", chunk_size=650, overlap=100) == [
            "just a few words"
        ]


class TestRetrieveContext:
    def test_formats_numbered_block(self):
        previous = get_vector_store()
        set_vector_store(MockVectorStore())
        try:
            context = retrieve_context("band descriptors")
            assert context == "[1] (seed) band descriptor snippet"
        finally:
            set_vector_store(previous)

    def test_empty_results_give_empty_string(self):
        class EmptyStore(MockVectorStore):
            def search(self, query, top_k=None, source=None):
                return []

        previous = get_vector_store()
        set_vector_store(EmptyStore())
        try:
            assert retrieve_context("anything") == ""
        finally:
            set_vector_store(previous)


class _DeadStore(MockVectorStore):
    """A store whose every search fails, like a suspended Qdrant Cloud cluster."""

    def search(self, *args, **kwargs):
        raise ConnectionResetError("[Errno 104] Connection reset by peer")


def test_retrieve_context_degrades_when_store_is_down():
    original = get_vector_store()
    try:
        set_vector_store(_DeadStore())
        assert retrieve_context("band descriptors outage probe") == ""
        # The outage is not cached: once the store is back, the same query
        # is answered from it.
        set_vector_store(MockVectorStore())
        assert "band descriptor snippet" in retrieve_context("band descriptors outage probe")
    finally:
        set_vector_store(original)

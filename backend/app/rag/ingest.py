import re
import unicodedata
from collections import Counter
from pathlib import Path

from app.config import settings
from app.rag.store import get_vector_store

_PAGE_NUM_RE = re.compile(r"^\s*(?:page\s+)?\d{1,4}\s*$", re.IGNORECASE)
_PAGE_BREAK = "\f"


def extract_pdf_text(path: str) -> str:
    import fitz

    with fitz.open(path) as doc:
        return _PAGE_BREAK.join(page.get_text() for page in doc)


def clean_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = (
        text.replace("‘", "'")
        .replace("’", "'")
        .replace("“", '"')
        .replace("”", '"')
        .replace("–", "-")
        .replace("—", "-")
        .replace("­", "")
    )
    pages = text.split(_PAGE_BREAK)
    repeated: set[str] = set()
    if len(pages) > 3:
        line_counts: Counter[str] = Counter()
        for page in pages:
            for line in {ln.strip() for ln in page.splitlines() if ln.strip()}:
                line_counts[line] += 1
        threshold = len(pages) * 0.3
        repeated = {line for line, n in line_counts.items() if n > threshold}
    kept: list[str] = []
    for page in pages:
        for line in page.splitlines():
            stripped = line.strip()
            if not stripped or _PAGE_NUM_RE.match(stripped) or stripped in repeated:
                continue
            kept.append(stripped)
    return re.sub(r"\s+", " ", " ".join(kept)).strip()


def chunk_text(
    text: str, chunk_size: int | None = None, overlap: int | None = None
) -> list[str]:
    chunk_size = chunk_size if chunk_size is not None else settings.rag_chunk_size
    overlap = overlap if overlap is not None else settings.rag_chunk_overlap
    words_per_chunk = max(chunk_size * 3 // 4, 1)
    overlap_words = min(max(overlap * 3 // 4, 0), words_per_chunk - 1)
    words = text.split()
    if not words:
        return []
    chunks: list[str] = []
    step = words_per_chunk - overlap_words
    for start in range(0, len(words), step):
        chunk = words[start : start + words_per_chunk]
        chunks.append(" ".join(chunk))
        if start + words_per_chunk >= len(words):
            break
    return chunks


def ingest_pdf(path: str, source_name: str | None = None) -> int:
    source = source_name or Path(path).stem
    text = clean_text(extract_pdf_text(path))
    chunks = [
        {"text": c, "source": source, "metadata": {"kind": "pdf"}}
        for c in chunk_text(text)
    ]
    return get_vector_store().index_chunks(chunks)


def ingest_markdown(path: str, source_name: str | None = None) -> int:
    source = source_name or Path(path).stem
    text = Path(path).read_text(encoding="utf-8")
    chunks = [
        {"text": c, "source": source, "metadata": {"kind": "markdown"}}
        for c in chunk_text(text)
    ]
    return get_vector_store().index_chunks(chunks)


def seed_knowledge_base() -> int:
    store = get_vector_store()
    if store.count() > 0:
        return 0
    seed_dir = Path(__file__).resolve().parent / "seed"
    total = 0
    for md_file in sorted(seed_dir.glob("*.md")):
        total += ingest_markdown(str(md_file))
    return total

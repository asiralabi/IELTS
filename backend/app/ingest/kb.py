"""Knowledge-base ingestion helpers for Cambridge IELTS content.

Produces three chunk kinds that the RAG retriever can search on:
  * passage         — a full reading passage
  * qa_pair         — one question (or question block) paired with its answer
  * raw_page        — cleaned page text (fallback for grammar/style examples)

Also wraps OCR (Tesseract via pytesseract) with an on-disk page cache so
scanned Cambridge PDFs can be ingested and re-ingested without paying the
OCR cost twice.
"""

from __future__ import annotations

import io
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import fitz

from app.config import settings
from app.rag.ingest import chunk_text, clean_text

_TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
OCR_CACHE_DIR = Path("data/ocr_cache")


# ---------------------------------------------------------------------------
# OCR


def _configure_tesseract() -> None:
    import pytesseract

    if os.path.exists(_TESSERACT_PATH):
        pytesseract.pytesseract.tesseract_cmd = _TESSERACT_PATH


def _ocr_page(pdf: Path, page_no_1based: int, dpi: int = 250) -> str:
    import pytesseract
    from PIL import Image

    cache_root = OCR_CACHE_DIR / pdf.stem
    cache_root.mkdir(parents=True, exist_ok=True)
    cache_path = cache_root / f"p{page_no_1based:04d}.txt"
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8")

    with fitz.open(pdf) as doc:
        page = doc[page_no_1based - 1]
        pix = page.get_pixmap(dpi=dpi)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
    text = pytesseract.image_to_string(img)
    cache_path.write_text(text, encoding="utf-8")
    return text


def pdf_is_image_based(pdf: Path, sample_pages: int = 8) -> bool:
    """Heuristic: sample early pages; if the mean non-whitespace char count is
    below a threshold, treat as scanned."""
    with fitz.open(pdf) as doc:
        n = min(sample_pages, doc.page_count)
        if n == 0:
            return False
        total = 0
        for i in range(n):
            total += len((doc[i].get_text() or "").strip())
    return total / n < 200


def extract_pdf_text_with_ocr(pdf: Path, progress: bool = True) -> list[str]:
    """Return per-page text. Runs OCR on pages whose native extraction is empty
    or extremely sparse. Cached to disk under data/ocr_cache."""
    _configure_tesseract()
    with fitz.open(pdf) as doc:
        page_count = doc.page_count
        raw_pages = [(doc[i].get_text() or "") for i in range(page_count)]

    pages: list[str] = []
    for i, native in enumerate(raw_pages, start=1):
        if len(native.strip()) >= 60:
            pages.append(native)
            continue
        if progress:
            print(f"  OCR {pdf.stem} p{i}/{page_count}", flush=True)
        pages.append(_ocr_page(pdf, i))
    return pages


# ---------------------------------------------------------------------------
# Text cleaning


def clean_page_text(text: str) -> str:
    """Cleaner variant that keeps sentence structure (unlike rag.ingest.clean_text
    which collapses everything into one line)."""
    text = unicodedata.normalize("NFKC", text)
    replacements = {"‘": "'", "’": "'", "“": '"', "”": '"',
                    "–": "-", "—": "-", "­": ""}
    for a, b in replacements.items():
        text = text.replace(a, b)
    lines: list[str] = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s:
            continue
        if re.fullmatch(r"(?:page\s+)?\d{1,4}", s, re.IGNORECASE):
            continue
        lines.append(s)
    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# Structured chunks from parsed CambridgeTest records


@dataclass
class KBChunk:
    text: str
    source: str
    metadata: dict[str, Any]


RE_QUESTION_TYPE_HINTS: list[tuple[str, re.Pattern[str]]] = [
    ("matching_headings",       re.compile(r"most suitable heading", re.I)),
    ("true_false_notgiven",     re.compile(r"TRUE.*FALSE.*NOT GIVEN", re.I | re.S)),
    ("yes_no_notgiven",         re.compile(r"YES.*NO.*NOT GIVEN", re.I | re.S)),
    ("sentence_completion",     re.compile(r"complete the sentences?", re.I)),
    ("summary_completion",      re.compile(r"complete the summary", re.I)),
    ("note_completion",         re.compile(r"complete the notes?", re.I)),
    ("table_completion",        re.compile(r"complete the table", re.I)),
    ("flowchart_completion",    re.compile(r"complete the flow-?chart", re.I)),
    ("form_completion",         re.compile(r"complete the form", re.I)),
    ("multiple_choice",         re.compile(r"choose the correct letter", re.I)),
    ("matching_information",    re.compile(r"which paragraph (contains|has)", re.I)),
    ("matching_features",       re.compile(r"match each .* with", re.I)),
    ("short_answer",            re.compile(r"answer the questions? below", re.I)),
]


def _guess_question_type(instruction_text: str) -> str:
    for name, rx in RE_QUESTION_TYPE_HINTS:
        if rx.search(instruction_text):
            return name
    return "unknown"


def _answers_for_range(answer_key: dict[str, str], lo: int, hi: int) -> dict[str, str]:
    return {str(q): answer_key[str(q)] for q in range(lo, hi + 1) if str(q) in answer_key}


def chunks_from_cambridge_test(test: dict[str, Any]) -> Iterable[KBChunk]:
    """Yield passage / qa_pair / transcript chunks from a parsed CambridgeTest."""
    book_id = test["book_id"]
    book_title = test["book_title"]
    test_number = test["test_number"]
    source = f"{book_id}-test{test_number}"
    base_meta = {"book_id": book_id, "book_title": book_title, "test_number": test_number}

    # Reading passages + Q&A
    r_key = test["reading"].get("answer_key") or {}
    for passage in test["reading"].get("passages", []):
        passage_text = passage.get("text", "").strip()
        if passage_text:
            yield KBChunk(
                text=f"[{book_title} Test {test_number} Reading Passage {passage['n']}]\n"
                     f"Title: {passage.get('title', '')}\n\n{passage_text}",
                source=source,
                metadata={**base_meta, "kind": "passage", "section": "reading",
                          "passage": passage["n"]},
            )
        for qb in passage.get("question_blocks", []):
            answers = _answers_for_range(r_key, qb["start"], qb["end"])
            qtype = _guess_question_type(qb.get("text", ""))
            body = qb.get("text", "").strip()
            if not body and not answers:
                continue
            answer_block = "\n".join(f"  Q{q}: {a}" for q, a in sorted(answers.items(), key=lambda x: int(x[0])))
            yield KBChunk(
                text=(
                    f"[{book_title} Test {test_number} Reading, Questions {qb['start']}-{qb['end']}]\n"
                    f"Question type: {qtype}\n\n{body}\n\nAnswer key:\n{answer_block or '  (unavailable)'}"
                ),
                source=source,
                metadata={**base_meta, "kind": "qa_pair", "section": "reading",
                          "question_start": qb["start"], "question_end": qb["end"],
                          "question_type": qtype},
            )

    # Listening — question blocks + answer key
    l_key = test["listening"].get("answer_key") or {}
    for part in test["listening"].get("parts", []):
        for qb in part.get("question_blocks", []):
            answers = _answers_for_range(l_key, qb["start"], qb["end"])
            qtype = _guess_question_type(qb.get("text", ""))
            body = qb.get("text", "").strip()
            if not body and not answers:
                continue
            answer_block = "\n".join(f"  Q{q}: {a}" for q, a in sorted(answers.items(), key=lambda x: int(x[0])))
            yield KBChunk(
                text=(
                    f"[{book_title} Test {test_number} Listening Part {part['n']}, Questions {qb['start']}-{qb['end']}]\n"
                    f"Question type: {qtype}\n\n{body}\n\nAnswer key:\n{answer_block or '  (unavailable)'}"
                ),
                source=source,
                metadata={**base_meta, "kind": "qa_pair", "section": "listening",
                          "part": part["n"], "question_start": qb["start"],
                          "question_end": qb["end"], "question_type": qtype},
            )

    # Writing prompts (small; keep as one chunk each for style/pattern retrieval)
    for task in test["writing"].get("tasks", []):
        prompt = task.get("prompt", "").strip()
        if not prompt:
            continue
        yield KBChunk(
            text=f"[{book_title} Test {test_number} Writing Task {task['n']}]\n\n{prompt}",
            source=source,
            metadata={**base_meta, "kind": "writing_prompt", "section": "writing",
                      "task": task["n"]},
        )

    # Speaking prompts
    for part in test["speaking"].get("parts", []):
        body = part.get("text", "").strip()
        if not body:
            continue
        yield KBChunk(
            text=f"[{book_title} Test {test_number} Speaking Part {part['n']}]\n\n{body}",
            source=source,
            metadata={**base_meta, "kind": "speaking_prompt", "section": "speaking",
                      "part": part["n"]},
        )


# ---------------------------------------------------------------------------
# Raw-text chunks from any PDF (with OCR fallback)


def chunks_from_pdf(pdf: Path, book_id: str, book_title: str) -> list[KBChunk]:
    pages = extract_pdf_text_with_ocr(pdf)
    cleaned = "\n\n".join(clean_page_text(p) for p in pages if p.strip())
    if not cleaned:
        return []
    text_chunks = chunk_text(cleaned)
    return [
        KBChunk(
            text=t,
            source=book_id,
            metadata={"book_id": book_id, "book_title": book_title, "kind": "raw_page"},
        )
        for t in text_chunks
    ]

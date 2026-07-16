"""Ingest all Cambridge books into the RAG knowledge base.

Runs three phases:

    1. `structured` — Pull parsed CambridgeTest rows from the DB and index
       passage / qa_pair / prompt chunks with rich metadata.
    2. `raw`        — For every book, extract cleaned page text (native or
       OCR) and index it as raw_page chunks for style/grammar retrieval.

OCR results are cached under `data/ocr_cache/` so re-runs are cheap.

Usage:
    python -m tools.ingest_kb                      # all phases, all books
    python -m tools.ingest_kb --phase structured   # DB-derived only, fast
    python -m tools.ingest_kb --phase raw          # raw text only
    python -m tools.ingest_kb --book cambridge-18  # one book only
    python -m tools.ingest_kb --clear              # wipe collection first
"""

from __future__ import annotations

import argparse
import json
import time

from app.database import SessionLocal, init_db
from app.ingest.catalog import FULL_CATALOG, BookEntry
from app.ingest.kb import (
    KBChunk,
    chunks_from_cambridge_test,
    chunks_from_pdf,
)
from app.models import CambridgeTest
from app.rag.store import get_vector_store

BATCH = 64


def _index(chunks: list[KBChunk]) -> int:
    if not chunks:
        return 0
    store = get_vector_store()
    total = 0
    for i in range(0, len(chunks), BATCH):
        batch = chunks[i : i + BATCH]
        payload = [
            {"text": c.text, "source": c.source, "metadata": c.metadata} for c in batch
        ]
        total += store.index_chunks(payload)
    return total


def phase_structured(only_book: str | None) -> None:
    init_db()
    session = SessionLocal()
    try:
        query = session.query(CambridgeTest)
        if only_book:
            query = query.filter(CambridgeTest.book_id == only_book)
        rows = query.order_by(CambridgeTest.book_id, CambridgeTest.test_number).all()
        print(f"[structured] {len(rows)} CambridgeTest rows to index")
        for row in rows:
            test = {
                "book_id": row.book_id,
                "book_title": row.book_title,
                "test_number": row.test_number,
                "reading": row.reading,
                "listening": row.listening,
                "writing": row.writing,
                "speaking": row.speaking,
            }
            chunks = list(chunks_from_cambridge_test(test))
            n = _index(chunks)
            print(f"  {row.book_id} test{row.test_number}: {n} chunks "
                  f"({sum(1 for c in chunks if c.metadata['kind']=='passage')} passages, "
                  f"{sum(1 for c in chunks if c.metadata['kind']=='qa_pair')} qa, "
                  f"{sum(1 for c in chunks if c.metadata['kind'] in ('writing_prompt','speaking_prompt'))} prompts)")
    finally:
        session.close()


def phase_raw(only_book: str | None, from_book: str | None = None) -> None:
    catalog = list(FULL_CATALOG)
    if from_book:
        ids = [b.book_id for b in catalog]
        if from_book in ids:
            catalog = catalog[ids.index(from_book):]
        else:
            print(f"[raw] --from-book {from_book!r} not in catalog, ignoring")
    if only_book:
        catalog = [b for b in catalog if b.book_id == only_book]
    print(f"[raw] {len(catalog)} books to process")
    for entry in catalog:
        if not entry.pdf_path.exists():
            print(f"  {entry.book_id}: MISSING {entry.pdf_path}")
            continue
        t0 = time.time()
        print(f"  {entry.book_id}: reading {entry.pdf_path.name}")
        try:
            chunks = chunks_from_pdf(entry.pdf_path, entry.book_id, entry.book_title)
        except Exception as e:
            print(f"    ERROR: {e}")
            continue
        n = _index(chunks)
        dt = time.time() - t0
        print(f"    -> {n} chunks in {dt:.1f}s")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=("structured", "raw", "all"), default="all")
    ap.add_argument("--book", help="only this book_id")
    ap.add_argument("--from-book", help="resume raw phase starting at this book_id")
    ap.add_argument("--clear", action="store_true", help="wipe collection first")
    args = ap.parse_args()

    if args.clear:
        print("Clearing vector store...")
        get_vector_store().clear()

    if args.phase in ("structured", "all"):
        phase_structured(args.book)
    if args.phase in ("raw", "all"):
        phase_raw(args.book, args.from_book)

    print(f"Vector store total points: {get_vector_store().count()}")


if __name__ == "__main__":
    main()

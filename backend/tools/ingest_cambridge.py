"""Ingest text-extractable Cambridge IELTS books into structured tests.

Usage:
    # Parse all catalog books, write JSON to data/cambridge_tests/, no DB write.
    python tools/ingest_cambridge.py --dry-run

    # Parse and upsert into the SQLite database.
    python tools/ingest_cambridge.py

    # Parse a single book by id.
    python tools/ingest_cambridge.py --book cambridge-18

The command always writes a JSON snapshot per test to
`data/cambridge_tests/<book_id>_test<N>.json` so you can inspect the output
before it hits the DB. Warnings from the parser are surfaced per test.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.database import SessionLocal, init_db
from app.ingest.cambridge_book import BOOK_CATALOG, BookConfig, parse_book
from app.models import CambridgeTest

SNAPSHOT_DIR = Path("data/cambridge_tests")


def _snapshot(test: dict[str, Any]) -> Path:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOT_DIR / f"{test['book_id']}_test{test['test_number']}.json"
    path.write_text(json.dumps(test, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _upsert(session, test: dict[str, Any]) -> str:
    existing = (
        session.query(CambridgeTest)
        .filter_by(book_id=test["book_id"], test_number=test["test_number"])
        .one_or_none()
    )
    fields = {
        "book_title": test["book_title"],
        "source_pdf": test["source_pdf"],
        "reading": test["reading"],
        "listening": test["listening"],
        "writing": test["writing"],
        "speaking": test["speaking"],
        "warnings": test["warnings"],
    }
    if existing is None:
        session.add(
            CambridgeTest(
                book_id=test["book_id"], test_number=test["test_number"], **fields
            )
        )
        return "inserted"
    for k, v in fields.items():
        setattr(existing, k, v)
    return "updated"


def _summarise(test: dict[str, Any]) -> str:
    r_p = len(test["reading"]["passages"])
    r_k = len(test["reading"].get("answer_key") or {})
    l_p = len(test["listening"]["parts"])
    l_k = len(test["listening"].get("answer_key") or {})
    w_t = len(test["writing"]["tasks"])
    s_p = len(test["speaking"]["parts"])
    return (
        f"reading[passages={r_p} key={r_k}/40] "
        f"listening[parts={l_p} key={l_k}/40] "
        f"writing[tasks={w_t}] speaking[parts={s_p}]"
    )


def run(book_id: str | None, dry_run: bool) -> None:
    if not dry_run:
        init_db()
    session = None if dry_run else SessionLocal()
    try:
        for cfg in BOOK_CATALOG:
            if book_id and cfg.book_id != book_id:
                continue
            print(f"=== {cfg.book_id} :: {cfg.pdf_path} ===")
            if not cfg.pdf_path.exists():
                print(f"  MISSING PDF, skipping")
                continue
            try:
                tests = parse_book(cfg)
            except RuntimeError as e:
                print(f"  ERROR: {e}")
                continue
            for t in tests:
                snap = _snapshot(t)
                action = "dry-run" if dry_run else _upsert(session, t)
                print(f"  test {t['test_number']}: {action}  -> {snap}")
                print(f"    {_summarise(t)}")
                for w in t["warnings"]:
                    print(f"    WARN: {w}")
        if session is not None:
            session.commit()
    finally:
        if session is not None:
            session.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", help="only process this book_id (e.g. cambridge-18)")
    ap.add_argument("--dry-run", action="store_true", help="do not write to DB")
    args = ap.parse_args()
    run(args.book, args.dry_run)


if __name__ == "__main__":
    main()

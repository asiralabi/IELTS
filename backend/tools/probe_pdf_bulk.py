"""Quick health-check across all Cambridge PDFs: is each page text-based
or image-based? Reports non-empty-text page counts and total chars per book."""

from __future__ import annotations

import sys
from pathlib import Path

import fitz

BOOKS_ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("books/ielts book")


def scan(pdf: Path) -> tuple[int, int, int]:
    doc = fitz.open(pdf)
    pages = doc.page_count
    non_empty = 0
    total_chars = 0
    for page in doc:
        t = page.get_text().strip()
        if t:
            non_empty += 1
            total_chars += len(t)
    doc.close()
    return pages, non_empty, total_chars


def main() -> None:
    pdfs = sorted(BOOKS_ROOT.rglob("*.pdf"))
    print(f"{'book':<40} {'pages':>5} {'text_pages':>10} {'chars':>10}")
    print("-" * 70)
    for pdf in pdfs:
        try:
            p, ne, cc = scan(pdf)
        except Exception as e:
            print(f"{pdf.name[:40]:<40} ERROR {e}")
            continue
        ratio = ne / p if p else 0
        flag = " IMAGE?" if ratio < 0.3 else ""
        print(f"{pdf.name[:40]:<40} {p:>5} {ne:>10} {cc:>10}{flag}")


if __name__ == "__main__":
    main()

"""Render the figures Cambridge actually prints, next to the text that sets them.

The books in `books/ielts book/` are page scans — one image per page, no text
layer — so a figure cannot be found by parsing the PDF. It can be found by
searching the OCR text the ingester already cached in `data/ocr_cache/`, which
is keyed by book and page, and then rendering that page back out of the PDF.

The output is an atlas: one PNG per figure task, each paired with the
instruction line that introduces it and the numbered gaps it carries. That is
the ground truth for "does our generated figure look like the exam's" — a
question no unit test can answer.

Usage: PYTHONIOENCODING=utf-8 python tools/cambridge_figure_atlas.py [--dpi 130]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
OCR = ROOT / "data" / "ocr_cache"
BOOKS = ROOT / "books" / "ielts book"
OUT = ROOT / "tools" / "_atlas"

# The instruction lines Cambridge uses to introduce a figure. OCR is noisy, so
# each is matched loosely and the label carries the figure family we care about.
TASKS: list[tuple[str, str]] = [
    (r"label the diagram", "diagram"),
    (r"complete the diagram", "diagram"),
    (r"label the plan", "plan"),
    (r"label the map", "map"),
    (r"complete the flow[\s-]*chart", "flow"),
    (r"complete the notes", "notes"),
    (r"complete the table", "table"),
    (r"choose the correct picture", "picture"),
]
PATTERNS = [(re.compile(p, re.I), kind) for p, kind in TASKS]

# Which PDF each OCR directory came from — the ingester named the cache after
# the PDF stem, so the match is by stem, not by book number.
def pdf_for(stem: str) -> Path | None:
    for pdf in BOOKS.rglob("*.pdf"):
        if pdf.stem == stem:
            return pdf
    return None


def instruction_context(text: str, match: re.Match) -> str:
    """The instruction plus the lines around it, which name the figure."""
    start = max(0, match.start() - 220)
    return " ".join(text[start : match.end() + 420].split())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dpi", type=int, default=130)
    ap.add_argument("--kinds", default="", help="comma-separated subset")
    args = ap.parse_args()

    wanted = {k.strip() for k in args.kinds.split(",") if k.strip()}
    OUT.mkdir(parents=True, exist_ok=True)
    index: list[dict] = []
    zoom = args.dpi / 72.0

    for book_dir in sorted(OCR.iterdir()):
        if not book_dir.is_dir():
            continue
        pdf_path = pdf_for(book_dir.name)
        if pdf_path is None:
            print(f"!! no pdf for {book_dir.name}", file=sys.stderr)
            continue
        doc = fitz.open(pdf_path)
        for page_file in sorted(book_dir.glob("p*.txt")):
            text = page_file.read_text(encoding="utf-8", errors="ignore")
            for pattern, kind in PATTERNS:
                m = pattern.search(text)
                if not m:
                    continue
                if wanted and kind not in wanted:
                    continue
                # OCR files are 1-based (p0001.txt is doc page 0).
                page_no = int(page_file.stem[1:]) - 1
                if not (0 <= page_no < len(doc)):
                    continue
                slug = f"{book_dir.name}_p{page_no:04d}_{kind}".replace(" ", "-")
                png = OUT / f"{slug}.png"
                pix = doc[page_no].get_pixmap(matrix=fitz.Matrix(zoom, zoom))
                pix.save(png)
                index.append(
                    {
                        "book": book_dir.name,
                        "page": page_no,
                        "kind": kind,
                        "png": str(png.relative_to(ROOT)),
                        "instruction": instruction_context(text, m),
                    }
                )
                break  # one task per page is enough to find the figure
        doc.close()

    (OUT / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    by_kind: dict[str, int] = {}
    for row in index:
        by_kind[row["kind"]] = by_kind.get(row["kind"], 0) + 1
    print(f"{len(index)} figure pages -> {OUT}")
    for kind, n in sorted(by_kind.items(), key=lambda kv: -kv[1]):
        print(f"  {n:3d}  {kind}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

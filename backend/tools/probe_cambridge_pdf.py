"""Probe a Cambridge IELTS PDF: dumps page count, per-page top line, and
locations of the anchor phrases we plan to use as section boundaries.

Usage:
    python tools/probe_cambridge_pdf.py "books/ielts book/Cambridge IELTS 15 Academic/Cambridge 15 Academic.pdf"
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import fitz

ANCHORS = [
    r"^\s*Test\s+[1-4]\s*$",
    r"^\s*TEST\s+[1-4]\s*$",
    r"^\s*LISTENING\b",
    r"^\s*READING\b",
    r"^\s*WRITING\b",
    r"^\s*SPEAKING\b",
    r"^\s*SECTION\s+[1-4]\b",
    r"^\s*PART\s+[1-4]\b",
    r"^\s*Reading Passage\s+[1-3]",
    r"^\s*READING PASSAGE\s+[1-3]",
    r"^\s*Questions?\s+\d+\s*[-–]\s*\d+",
    r"^\s*Answer key\b",
    r"^\s*ANSWER KEY\b",
    r"^\s*Listening and Reading Answer Keys?",
]
ANCHOR_RES = [re.compile(p) for p in ANCHORS]


def probe(pdf_path: Path) -> None:
    doc = fitz.open(pdf_path)
    print(f"# {pdf_path.name}  pages={doc.page_count}")
    print()
    for i, page in enumerate(doc, start=1):
        text = page.get_text()
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        top = lines[0][:80] if lines else "<empty>"
        hits: list[str] = []
        for ln in lines[:40]:
            for r in ANCHOR_RES:
                if r.match(ln):
                    hits.append(ln[:80])
                    break
        if hits or i <= 10:
            print(f"p{i:>4}: {top}")
            for h in hits[:6]:
                print(f"        -> {h}")
    doc.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    probe(Path(sys.argv[1]))

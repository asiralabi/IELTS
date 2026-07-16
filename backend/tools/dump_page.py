"""Dump raw text of a single PDF page."""

import sys
from pathlib import Path

import fitz


def main() -> None:
    if len(sys.argv) != 3:
        print("usage: python tools/dump_page.py <pdf> <page_num_1based>")
        sys.exit(1)
    pdf = Path(sys.argv[1])
    n = int(sys.argv[2])
    doc = fitz.open(pdf)
    text = doc[n - 1].get_text()
    doc.close()
    sys.stdout.buffer.write(text.encode("utf-8", errors="replace"))


if __name__ == "__main__":
    main()

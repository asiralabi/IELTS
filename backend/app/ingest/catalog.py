"""Full catalog of Cambridge IELTS books on disk (all 20)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BookEntry:
    book_id: str
    book_title: str
    pdf_path: Path


BOOKS_ROOT = Path("books/ielts book")

FULL_CATALOG: list[BookEntry] = [
    BookEntry("cambridge-1",  "Cambridge IELTS 1",
              BOOKS_ROOT / "Cambridge IELTS 01/Cambridge IELTS 01/Cambridge Practice Tests for IELTS 1.pdf"),
    BookEntry("cambridge-2",  "Cambridge IELTS 2",
              BOOKS_ROOT / "Cambridge IELTS 02/Cambridge  IELTS 02/Cambridge Practice Tests for IELTS 2.pdf"),
    BookEntry("cambridge-3",  "Cambridge IELTS 3",
              BOOKS_ROOT / "Cambridge IELTS 03/Cambridge  IELTS 03/Cambridge Practice Tests for IELTS 3.pdf"),
    BookEntry("cambridge-4",  "Cambridge IELTS 4",
              BOOKS_ROOT / "Cambridge IELTS 04/Cambridge  IELTS 04/Cambridge Practice Tests for IELTS 4.pdf"),
    BookEntry("cambridge-5",  "Cambridge IELTS 5",
              BOOKS_ROOT / "Cambridge IELTS 05/Cambridge  IELTS 05/Cambridge_IELTS_5_with_Answers.pdf"),
    BookEntry("cambridge-6-t1", "Cambridge IELTS 6 (Test 1)",
              BOOKS_ROOT / "Cambridge IELTS 06/Cambridge IELTS 06/Cambridge.IELTS.6.Tests.With.Answers/Cambridge ielts 6_test1.pdf"),
    BookEntry("cambridge-6-t2", "Cambridge IELTS 6 (Test 2)",
              BOOKS_ROOT / "Cambridge IELTS 06/Cambridge IELTS 06/Cambridge.IELTS.6.Tests.With.Answers/Cambridge ielts 6_test2.pdf"),
    BookEntry("cambridge-6-t3", "Cambridge IELTS 6 (Test 3)",
              BOOKS_ROOT / "Cambridge IELTS 06/Cambridge IELTS 06/Cambridge.IELTS.6.Tests.With.Answers/Cambridge ielts 6_test3.pdf"),
    BookEntry("cambridge-6-t4", "Cambridge IELTS 6 (Test 4)",
              BOOKS_ROOT / "Cambridge IELTS 06/Cambridge IELTS 06/Cambridge.IELTS.6.Tests.With.Answers/Cambridge ielts 6_test4.pdf"),
    BookEntry("cambridge-7",  "Cambridge IELTS 7",
              BOOKS_ROOT / "Cambridge IELTS 07/Cambridge  IELTS 07/ielts7.pdf"),
    BookEntry("cambridge-8",  "Cambridge IELTS 8",
              BOOKS_ROOT / "Cambridge IELTS 08/Cambridge IELTS 08/Cambridge IELTS 8.pdf"),
    BookEntry("cambridge-9",  "Cambridge IELTS 9",
              BOOKS_ROOT / "Cambridge IELTS 09/Cambridge IELTS 09/Cambridge IELTS 9.pdf"),
    BookEntry("cambridge-10", "Cambridge IELTS 10",
              BOOKS_ROOT / "Cambridge IELTS 10/Cambridge-IELTS-10-Ebook.pdf"),
    BookEntry("cambridge-11", "Cambridge IELTS 11 Academic",
              BOOKS_ROOT / "Cambridge IELTS 11- Academic/IELTS Cambridge Book 11.pdf"),
    BookEntry("cambridge-12", "Cambridge IELTS 12 Academic",
              BOOKS_ROOT / "Cambridge IELTS 12 - Academic/Cambridge IELTS 12 PDF.pdf"),
    BookEntry("cambridge-13", "Cambridge IELTS 13 Academic",
              BOOKS_ROOT / "Cambridge IELTS 13 Academic/IELTS Cambridge 13.pdf"),
    BookEntry("cambridge-14", "Cambridge IELTS 14 Academic",
              BOOKS_ROOT / "Cambridge IELTS 14 Academic/IELTS Cambridge IELTS 14.pdf"),
    BookEntry("cambridge-15", "Cambridge IELTS 15 Academic",
              BOOKS_ROOT / "Cambridge IELTS 15 Academic/Cambridge 15 Academic.pdf"),
    BookEntry("cambridge-16", "Cambridge IELTS 16 Academic",
              BOOKS_ROOT / "Cambridge IELTS 16 Academic/Cambridge 16.pdf"),
    BookEntry("cambridge-17", "Cambridge IELTS 17 Academic",
              BOOKS_ROOT / "Cambridge IELTS 17 Academic/Cambridge 17.pdf"),
    BookEntry("cambridge-18", "Cambridge IELTS 18 Academic",
              BOOKS_ROOT / "Cambridge IELTS 18 Academic/Cambridge 18.pdf"),
    BookEntry("cambridge-19", "Cambridge IELTS 19 Academic",
              BOOKS_ROOT / "Cambridge IELTS 19 Academic/Cambridge 19.pdf"),
    BookEntry("cambridge-21", "Cambridge IELTS 21",
              BOOKS_ROOT / "IELTS Cambridge Book 21.pdf"),
]

"""Cambridge IELTS book parser.

Extracts one full IELTS test at a time from a text-extractable Cambridge PDF
into a structured dict:

    {
      "book_id": "cambridge-18",
      "book_title": "Cambridge IELTS 18 Academic",
      "test_number": 1,
      "source_pdf": "...",
      "reading":   {"raw_text", "passages":[{n,title,text,question_blocks}], "answer_key":{}},
      "listening": {"raw_text", "parts":[{n,question_blocks}], "answer_key":{}},
      "writing":   {"raw_text", "tasks":[{n,prompt}]},
      "speaking":  {"raw_text", "parts":[{n,text}]},
      "warnings":  [str, ...],
    }

Design notes
------------
- Boundary detection: we walk the PDF's pages in order and use section anchors
  (LISTENING / READING / WRITING / SPEAKING) plus test-boundary hints
  ("Test N" / "TEST N" / "Audioscripts") to slice up to four tests per book.
- Answer keys sit at the back of the book and are parsed by the number-answer
  pattern (a bare integer followed by its answer on adjacent lines).
- The parser is intentionally conservative. When it can't be sure, it drops a
  string into `warnings` rather than guessing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import fitz

from app.config import settings
from app.ingest.pdf_images import ExtractedImage, extract_book_images

# ---------------------------------------------------------------------------
# Regex patterns

RE_TEST_NUM = re.compile(r"^\s*(?:PRACTICE\s+)?(?:TEST|Test)\s+([1-4])\s*$")
RE_LISTENING = re.compile(r"^\s*LISTENING\s*$")
RE_READING = re.compile(r"^\s*READING\s*$")
RE_WRITING = re.compile(r"^\s*WRITING\s*$")
RE_SPEAKING = re.compile(r"^\s*SPEAKING\s*$")
RE_READING_PASSAGE = re.compile(r"^\s*READING PASSAGE\s+([1-3])\b")
RE_LIST_SECTION = re.compile(r"^\s*(?:SECTION|PART)\s+([1-4])\b")
RE_LISTENING_SECTION_FALLBACK = re.compile(r"^\s*SECTION\s+1\b")
RE_QUESTION_RANGE = re.compile(r"^\s*Questions?\s+(\d+)\s*[-–]\s*(\d+)\b")
RE_WRITING_TASK = re.compile(r"^\s*WRITING TASK\s+([12])\b")
RE_SPEAKING_PART = re.compile(r"^\s*PART\s+([1-3])\b", re.IGNORECASE)

RE_AUDIOSCRIPT_HDR = re.compile(r"^\s*(?:Audioscripts?|Tapescripts?)\s*$", re.IGNORECASE)
RE_ANSWER_KEY_HDR = re.compile(
    r"(Listening\s+and\s+Reading\s+answer\s+keys?"
    r"|^\s*Answer\s+keys?\b"  # matches "Answer key with extra explanations" etc.
    r"|^\s*LISTENING\s+KEYS?\s*$"
    r"|^\s*READING\s+KEYS?\s*$)",
    re.IGNORECASE,
)

RE_GENERAL_TRAINING = re.compile(r"General\s+Training", re.IGNORECASE)

# Listening PART 1 always covers Questions 1-10; Reading Passage 1 uses
# 1-13/14 and Speaking is unnumbered. So a lone "Questions 1-10" (or 1 to 10)
# on a page with no READING/WRITING/SPEAKING marker is a strong signal that
# we're at the top of the listening section. Used for modern Cambridge books
# (15+) that drop the standalone "LISTENING" header page.
RE_QUESTIONS_1_10 = re.compile(r"\bQuestions?\s+1\s*(?:-|–|to)\s*10\b", re.IGNORECASE)

# "Contents" (table-of-contents) pages list back-matter section titles as
# entries — Audioscripts, Answer keys — which collides with the back-matter
# heuristic. Detect the ToC explicitly so we can suppress the false positive.
RE_CONTENTS_HDR = re.compile(r"^\s*Contents\s*$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Page abstraction


@dataclass
class Page:
    number: int  # 1-based
    text: str
    lines: list[str]

    @property
    def top_lines(self) -> list[str]:
        return self.lines[:60]


_ROMAN_HEADER_RX = re.compile(
    r"\b(PART|SECTION|PASSAGE|TASK)\s+(IV|III|II|I)\b",
    re.IGNORECASE,
)
_ROMAN_MAP = {"I": "1", "II": "2", "III": "3", "IV": "4"}


def _normalize_ocr_romans(ln: str) -> str:
    """OCR frequently reads header digits as roman numerals (e.g. ``WRITING
    TASK I`` for ``WRITING TASK 1``, ``SECTION IV`` for ``SECTION 4``).
    Normalize these back to Arabic digits so the section-anchor regexes
    match without every one growing a roman-numeral variant."""

    def sub(m: re.Match[str]) -> str:
        return f"{m.group(1)} {_ROMAN_MAP[m.group(2).upper()]}"

    ln = _ROMAN_HEADER_RX.sub(sub, ln)
    # ``Questions I-10`` / ``Questions I to 10`` etc. — only fires when the
    # trailing digit anchors us to the listening block.
    ln = re.sub(
        r"\bQuestions?\s+I\s*([-–]|\bto\b)\s*10\b",
        r"Questions 1\1 10",
        ln,
        flags=re.IGNORECASE,
    )
    return ln


_LEADING_JUNK_RX = re.compile(r"^[^A-Za-z0-9@]+")


def _clean_line(ln: str) -> str:
    ln = (
        ln.replace("‘", "'")
        .replace("’", "'")
        .replace("“", '"')
        .replace("”", '"')
        .replace("–", "-")
        .replace("—", "-")
        .strip()
    )
    # OCR often prepends stray glyphs (``& WRITING TASK 1``, ``: LISTENING``,
    # ``' Questions 1-10``) that block ``^\s*ANCHOR`` regexes. Strip a run of
    # leading non-alphanumeric characters — only when a real token follows.
    if ln and not ln[0].isalnum() and ln[0] != "@":
        stripped = _LEADING_JUNK_RX.sub("", ln)
        if stripped:
            ln = stripped
    return _normalize_ocr_romans(ln)


def load_pages(pdf_path: Path, *, allow_ocr: bool = True) -> list[Page]:
    """Load pages as native text; when a page's native text is empty/sparse and
    ``allow_ocr`` is set, fall back to the cached OCR extraction from
    ``app.ingest.kb.extract_pdf_text_with_ocr`` (Tesseract, disk-cached under
    ``data/ocr_cache/<pdf-stem>/pNNNN.txt``).

    This lets the structural parser handle scanned Cambridge PDFs (C5–C17,
    C19, C21) using the same OCR cache the raw-page RAG phase already built.
    """
    pages: list[Page] = []
    if allow_ocr:
        from app.ingest.kb import extract_pdf_text_with_ocr

        page_texts = extract_pdf_text_with_ocr(pdf_path, progress=False)
        for i, raw in enumerate(page_texts, start=1):
            lines = [_clean_line(l) for l in raw.splitlines() if _clean_line(l)]
            pages.append(Page(number=i, text=raw, lines=lines))
        return pages
    with fitz.open(pdf_path) as doc:
        for i, page in enumerate(doc, start=1):
            raw = page.get_text() or ""
            lines = [_clean_line(l) for l in raw.splitlines() if _clean_line(l)]
            pages.append(Page(number=i, text=raw, lines=lines))
    return pages


# ---------------------------------------------------------------------------
# Boundary detection


@dataclass
class TestBoundary:
    test_number: int
    listening_start: int
    reading_start: int
    writing_start: int
    speaking_start: int
    end: int  # exclusive


def _is_general_training_page(page: Page) -> bool:
    joined = "\n".join(page.top_lines[:6])
    return bool(RE_GENERAL_TRAINING.search(joined))


def _page_has_line_match(page: Page, patterns: tuple[re.Pattern[str], ...]) -> bool:
    return any(any(rx.match(ln) for rx in patterns) for ln in page.top_lines)


L_ANCHORS = (RE_LISTENING,)
L_CONTENT_ANCHORS = (RE_LIST_SECTION,)  # SECTION 1 / PART 1
R_ANCHORS = (RE_READING, RE_READING_PASSAGE)
W_ANCHORS = (RE_WRITING, RE_WRITING_TASK)
S_ANCHORS = (RE_SPEAKING,)


def _looks_like_back_matter(page: Page) -> bool:
    """A real back-matter page starts with Audioscripts/Tapescripts/Answer key
    right at the top and typically also has a TEST N header on the same page."""
    top = page.top_lines[:8]
    # Table-of-contents pages list Audioscripts/Answer keys as chapter entries.
    # Skip them explicitly.
    if any(RE_CONTENTS_HDR.match(ln) for ln in page.top_lines[:15]):
        return False
    hdr_hit = any(RE_AUDIOSCRIPT_HDR.match(ln) or RE_ANSWER_KEY_HDR.search(ln) for ln in top)
    if not hdr_hit:
        return False
    test_hit = any(RE_TEST_NUM.match(ln) for ln in page.top_lines[:40])
    return test_hit


def _page_markers(page: Page) -> set[str]:
    """Return the set of section markers present on this page ({'L','R','W','S'})."""
    if _is_general_training_page(page):
        return set()
    hits: set[str] = set()
    if _page_has_line_match(page, L_ANCHORS):
        hits.add("L")
    if _page_has_line_match(page, R_ANCHORS):
        hits.add("R")
    if _page_has_line_match(page, W_ANCHORS):
        hits.add("W")
    if _page_has_line_match(page, S_ANCHORS):
        hits.add("S")
    if "L" not in hits:
        for ln in page.top_lines:
            if RE_LISTENING_SECTION_FALLBACK.match(ln):
                hits.add("L")
                break
    # Modern books (Cambridge 15+) drop the "LISTENING" header and jump
    # straight to "PART 1 / Questions 1-10". Treat a lone "Questions 1-10"
    # as a listening anchor only when no other section marker is present on
    # the page — otherwise it could collide with a reading page.
    if "L" not in hits and not hits:
        for ln in page.top_lines:
            if RE_QUESTIONS_1_10.search(ln):
                hits.add("L")
                break
    return hits


def detect_test_boundaries(pages: list[Page]) -> list[TestBoundary]:
    """Walk pages as a state machine collecting L→R→W→S sequences.

    Accepts either explicit section headers (LISTENING/READING/…) or their
    content-page equivalents (SECTION 1/READING PASSAGE 1/WRITING TASK 1),
    which is what the older Cambridge books use.
    """
    boundaries: list[TestBoundary] = []
    current: dict[str, int] = {}
    state = "WAIT_L"
    transitions = {
        "WAIT_L": ("L", "WAIT_R"),
        "WAIT_R": ("R", "WAIT_W"),
        "WAIT_W": ("W", "WAIT_S"),
        "WAIT_S": ("S", "WAIT_L"),
    }
    max_page = len(pages) + 1

    for p in pages:
        if len(boundaries) == 4:
            break
        # If we hit the real back-matter section, stop hunting for tests.
        if _looks_like_back_matter(p):
            break
        mks = _page_markers(p)
        if not mks:
            continue
        # Advance the state machine greedily across all markers found on this
        # page, in section order. This handles pages that pack WRITING TASK 2
        # and SPEAKING onto one page (old books).
        for section in ("L", "R", "W", "S"):
            if section not in mks:
                continue
            expected, next_state = transitions[state]
            if section == expected:
                current[expected] = p.number
                state = next_state
                if state == "WAIT_L" and len(current) == 4:
                    boundaries.append(
                        TestBoundary(
                            test_number=len(boundaries) + 1,
                            listening_start=current["L"],
                            reading_start=current["R"],
                            writing_start=current["W"],
                            speaking_start=current["S"],
                            end=max_page,
                        )
                    )
                    current = {}
                    break
            elif section == "L" and state != "WAIT_L":
                # If a fresh test's LISTENING appears while we were still waiting
                # for SPEAKING, close the previous test with an empty speaking
                # slot (common in older Cambridge books). speaking_start=end so
                # the writing slice captures every page after WRITING TASK 1
                # rather than collapsing to empty.
                if state == "WAIT_S" and {"L", "R", "W"} <= current.keys():
                    boundaries.append(
                        TestBoundary(
                            test_number=len(boundaries) + 1,
                            listening_start=current["L"],
                            reading_start=current["R"],
                            writing_start=current["W"],
                            speaking_start=p.number,
                            end=p.number,
                        )
                    )
                current = {"L": p.number}
                state = "WAIT_R"
                break

    # If the book ended and we still had a test in flight, close it too.
    if state == "WAIT_S" and {"L", "R", "W"} <= current.keys() and len(boundaries) < 4:
        boundaries.append(
            TestBoundary(
                test_number=len(boundaries) + 1,
                listening_start=current["L"],
                reading_start=current["R"],
                writing_start=current["W"],
                speaking_start=max_page,
                end=max_page,
            )
        )

    if not boundaries:
        return []

    # Patch `end` for each boundary.
    for i, b in enumerate(boundaries[:-1]):
        b.end = boundaries[i + 1].listening_start
    # Last boundary ends at the first back-matter or general-training page after speaking_start.
    last = boundaries[-1]
    tail_end = max_page
    for p in pages[last.speaking_start :]:  # 0-based slice: everything past speaking_start
        if _looks_like_back_matter(p) or _is_general_training_page(p):
            tail_end = p.number
            break
    last.end = tail_end
    return boundaries


# ---------------------------------------------------------------------------
# Section content extraction


def _slice(pages: list[Page], start_1based: int, end_exclusive_1based: int) -> list[Page]:
    return pages[start_1based - 1 : end_exclusive_1based - 1]


def _joined_text(pages: list[Page]) -> str:
    return "\n".join(p.text for p in pages).strip()


def _split_question_blocks(
    section_lines: list[str],
    line_pages: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Group section lines into question blocks based on 'Questions X-Y' markers.

    When ``line_pages`` is provided (a parallel list of 1-based page numbers per
    line), each block also carries ``pages: [start_page, end_page]`` so callers
    can attach page-scoped visuals.
    """
    blocks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for i, ln in enumerate(section_lines):
        m = RE_QUESTION_RANGE.match(ln)
        page_num = line_pages[i] if line_pages is not None else None
        if m:
            start_q, end_q = int(m.group(1)), int(m.group(2))
            if current and current["start"] == start_q and current["end"] == end_q:
                continue
            current = {
                "start": start_q,
                "end": end_q,
                "lines": [],
                "line_pages": [] if line_pages is not None else None,
                "header_page": page_num,
            }
            blocks.append(current)
            continue
        if current is not None:
            current["lines"].append(ln)
            if current["line_pages"] is not None and page_num is not None:
                current["line_pages"].append(page_num)

    out: list[dict[str, Any]] = []
    for b in blocks:
        block: dict[str, Any] = {
            "start": b["start"],
            "end": b["end"],
            "text": " ".join(b["lines"]).strip(),
        }
        if b["line_pages"] is not None:
            pages = b["line_pages"] or ([b["header_page"]] if b["header_page"] else [])
            if pages:
                block["pages"] = [min(pages), max(pages)]
        out.append(block)
    return out


def extract_reading(
    pages: list[Page],
    b: TestBoundary,
    page_images: dict[int, list[ExtractedImage]] | None = None,
    claimed: set[str] | None = None,
) -> dict[str, Any]:
    if claimed is None:
        claimed = set()
    section = _slice(pages, b.reading_start, b.writing_start)
    all_lines: list[str] = []
    all_line_pages: list[int] = []
    for p in section:
        for ln in p.lines:
            all_lines.append(ln)
            all_line_pages.append(p.number)

    passages: list[dict[str, Any]] = []
    passage_starts: list[int] = []
    for idx, ln in enumerate(all_lines):
        if RE_READING_PASSAGE.match(ln):
            passage_starts.append(idx)

    for i, p_idx in enumerate(passage_starts):
        end_idx = passage_starts[i + 1] if i + 1 < len(passage_starts) else len(all_lines)
        block_lines = all_lines[p_idx:end_idx]
        block_pages = all_line_pages[p_idx:end_idx]
        first_q = next(
            (j for j, l in enumerate(block_lines) if RE_QUESTION_RANGE.match(l)), None
        )
        passage_body_lines = block_lines[1:first_q] if first_q else block_lines[1:]
        passage_body_pages = block_pages[1:first_q] if first_q else block_pages[1:]
        title = next(
            (
                l
                for l in passage_body_lines[:20]
                if len(l) > 3 and not l.lower().startswith("you should spend")
            ),
            "",
        )
        passage_text = " ".join(
            l for l in passage_body_lines if not l.lower().startswith("you should spend")
        ).strip()
        question_blocks = _split_question_blocks(
            block_lines[first_q:] if first_q else [],
            block_pages[first_q:] if first_q else [],
        )
        passage: dict[str, Any] = {
            "n": int(RE_READING_PASSAGE.match(block_lines[0]).group(1)),
            "title": title,
            "text": passage_text,
            "question_blocks": question_blocks,
        }
        if passage_body_pages:
            passage["pages"] = [min(passage_body_pages), max(passage_body_pages)]
        # Blocks claim page-scoped figures first; the passage picks up leftovers.
        for qb in question_blocks:
            _attach(
                qb,
                _collect_visuals(
                    qb.get("pages") or passage.get("pages"), page_images, claimed
                ),
            )
        _attach(passage, _collect_visuals(passage.get("pages"), page_images, claimed))
        passages.append(passage)

    return {
        "page_range": [b.reading_start, b.writing_start - 1],
        "raw_text": _joined_text(section),
        "passages": passages,
    }


def extract_listening(
    pages: list[Page],
    b: TestBoundary,
    page_images: dict[int, list[ExtractedImage]] | None = None,
    claimed: set[str] | None = None,
) -> dict[str, Any]:
    if claimed is None:
        claimed = set()
    section = _slice(pages, b.listening_start, b.reading_start)
    all_lines: list[str] = []
    all_line_pages: list[int] = []
    for p in section:
        for ln in p.lines:
            all_lines.append(ln)
            all_line_pages.append(p.number)

    parts: list[dict[str, Any]] = []
    part_starts: list[tuple[int, int]] = []
    for idx, ln in enumerate(all_lines):
        m = RE_LIST_SECTION.match(ln)
        if m:
            part_starts.append((idx, int(m.group(1))))

    seen: set[int] = set()
    uniq_starts: list[tuple[int, int]] = []
    for idx, n in part_starts:
        if n in seen:
            continue
        seen.add(n)
        uniq_starts.append((idx, n))

    for i, (p_idx, part_n) in enumerate(uniq_starts):
        end_idx = uniq_starts[i + 1][0] if i + 1 < len(uniq_starts) else len(all_lines)
        block_lines = all_lines[p_idx:end_idx]
        block_pages = all_line_pages[p_idx:end_idx]
        question_blocks = _split_question_blocks(block_lines, block_pages)
        part: dict[str, Any] = {"n": part_n, "question_blocks": question_blocks}
        if block_pages:
            part["pages"] = [min(block_pages), max(block_pages)]
        for qb in question_blocks:
            _attach(
                qb,
                _collect_visuals(
                    qb.get("pages") or part.get("pages"), page_images, claimed
                ),
            )
        parts.append(part)

    return {
        "page_range": [b.listening_start, b.reading_start - 1],
        "raw_text": _joined_text(section),
        "parts": parts,
    }


def extract_writing(
    pages: list[Page],
    b: TestBoundary,
    page_images: dict[int, list[ExtractedImage]] | None = None,
    claimed: set[str] | None = None,
) -> dict[str, Any]:
    if claimed is None:
        claimed = set()
    section = _slice(pages, b.writing_start, b.speaking_start)
    all_lines: list[str] = []
    all_line_pages: list[int] = []
    for p in section:
        for ln in p.lines:
            all_lines.append(ln)
            all_line_pages.append(p.number)

    tasks: list[dict[str, Any]] = []
    task_indices: list[tuple[int, int]] = []
    for i, ln in enumerate(all_lines):
        m = RE_WRITING_TASK.match(ln)
        if m:
            task_indices.append((i, int(m.group(1))))
    for i, (idx, n) in enumerate(task_indices):
        end_idx = task_indices[i + 1][0] if i + 1 < len(task_indices) else len(all_lines)
        task_pages = all_line_pages[idx + 1 : end_idx]
        task: dict[str, Any] = {
            "n": n,
            "prompt": " ".join(all_lines[idx + 1 : end_idx]).strip(),
        }
        if task_pages:
            task["pages"] = [min(task_pages), max(task_pages)]
        # IELTS Academic Writing Task 2 is an opinion/discussion essay — never
        # illustrated. Skip visual attachment so a chart bleeding from Task 1's
        # page doesn't get mislabelled as the Task 2 prompt.
        if n != 2:
            _attach(task, _collect_visuals(task.get("pages"), page_images, claimed))
        tasks.append(task)
    return {
        "page_range": [b.writing_start, b.speaking_start - 1],
        "raw_text": _joined_text(section),
        "tasks": tasks,
    }


def extract_speaking(pages: list[Page], b: TestBoundary) -> dict[str, Any]:
    section = _slice(pages, b.speaking_start, b.end)
    all_lines = [ln for p in section for ln in p.lines]
    parts: list[dict[str, Any]] = []
    part_indices: list[tuple[int, int]] = []
    for i, ln in enumerate(all_lines):
        m = RE_SPEAKING_PART.match(ln)
        if m:
            part_indices.append((i, int(m.group(1))))
    for i, (idx, n) in enumerate(part_indices):
        end_idx = part_indices[i + 1][0] if i + 1 < len(part_indices) else len(all_lines)
        parts.append({"n": n, "text": " ".join(all_lines[idx + 1 : end_idx]).strip()})
    return {
        "page_range": [b.speaking_start, b.end - 1],
        "raw_text": _joined_text(section),
        "parts": parts,
    }


# ---------------------------------------------------------------------------
# Visual attachment

def _collect_visuals(
    page_range: list[int] | None,
    page_images: dict[int, list[ExtractedImage]] | None,
    claimed: set[str],
) -> list[dict[str, Any]]:
    if not page_range or not page_images:
        return []
    start, end = page_range[0], page_range[1]
    seen_urls: set[str] = set()
    out: list[dict[str, Any]] = []
    for p in range(start, end + 1):
        for img in page_images.get(p, []):
            if img.url in claimed or img.url in seen_urls:
                continue
            seen_urls.add(img.url)
            out.append(img.to_visual(alt=f"Figure on page {img.page}"))
    claimed.update(seen_urls)
    return out


def _attach(node: dict[str, Any], visuals: list[dict[str, Any]]) -> None:
    if not visuals:
        return
    node["visuals"] = visuals
    node["visual"] = visuals[0]


# ---------------------------------------------------------------------------
# Answer-key extraction

RE_BARE_NUMBER = re.compile(r"^\s*(\d{1,2})\s*$")
RE_INLINE_ANSWER = re.compile(r"^\s*(\d{1,2})[\s.)]+(\S.*)$")
RE_INLINE_NUMBERED = re.compile(r"^\s*(\d{1,2})\b[\s.:)]+(.+?)\s*$")
# ``Section 1, Questions 1-10 Section 3, Questions 21-30`` or the equivalent
# ``Part 1, Questions 1-10 Part 3, Questions 21-30`` header signals a
# two-column key layout. We remember (left_range, right_range) from these
# lines so downstream splitting knows which columns to expect.
RE_COLUMN_HEADER = re.compile(
    r"(?:Section|Part)\s+\d+,?\s*Questions?\s+(\d{1,2})\s*[-–]\s*(\d{1,2})",
    re.IGNORECASE,
)


def _count_answer_signals(page: Page) -> int:
    """Cheap heuristic for "this page is an answer-key page": count lines
    that either are a bare 1-2 digit number (Cambridge 18-style column
    layout) OR start with a number followed by punctuation/whitespace
    (Cambridge 5/7/15-style tabular layout)."""
    n = 0
    for ln in page.lines:
        if re.match(r"^\s*\d{1,2}\s*$", ln):
            n += 1
        elif re.match(r"^\s*\d{1,2}[\s.):]", ln):
            n += 1
    return n


def _find_answer_key_pages(pages: list[Page]) -> list[Page]:
    """Return the pages that make up the answer-key section.

    Requires both (a) an ``Answer key`` / ``Listening keys`` / ``Reading
    keys`` header in the top band and (b) enough numbered lines that the
    page really is a key (not a table-of-contents entry). We do NOT stop at
    the first non-qualifying page — writing-sample pages sit between real
    key pages in some books, and skipping them cleanly is safer than
    breaking out of the scan.
    """
    out: list[Page] = []
    for p in pages:
        top = p.top_lines[:15]
        if any(RE_CONTENTS_HDR.match(ln) for ln in top):
            continue
        header_hit = any(RE_ANSWER_KEY_HDR.search(ln) for ln in top)
        if not header_hit:
            continue
        # Require both signals: an "Answer key" header AND either enough
        # numbered lines OR a column-range header ``Section N, Questions
        # X-Y``. Introductory/preface pages sometimes mention "Answer key"
        # in passing without carrying answers themselves.
        has_column_hdr = any(_range_from_header(ln) is not None for ln in p.lines)
        if _count_answer_signals(p) >= 8 or has_column_hdr:
            out.append(p)
    return out


def _split_columnar_line(line: str, left: range, right: range) -> list[tuple[int, str]]:
    """Split a two-column answer-key line into ``[(qnum, answer), ...]``.

    Handles cases like ``1 Jamieson 21 G``, ``11 A 31 shelter``, ``5 D 26 NO``.
    When only one number-answer pair is present (or the layout is single
    column), returns a single tuple. Numbers outside both column ranges are
    ignored — this keeps stray line numbers (page numbers, times like
    ``12.30``) from being mistaken for question ids.
    """
    matches = [(m.start(), m.end(), int(m.group(1))) for m in re.finditer(r"\b(\d{1,2})\b", line)]
    if not matches:
        return []

    def in_any(n: int) -> bool:
        return n in left or n in right

    valid = [m for m in matches if in_any(m[2])]
    if not valid:
        return []

    out: list[tuple[int, str]] = []
    for i, (_, end, num) in enumerate(valid):
        next_start = valid[i + 1][0] if i + 1 < len(valid) else len(line)
        answer = line[end:next_start].strip(" .:-)&\t")
        # Guard against ``&`` compound tokens like ``24&25 IN EITHER ORDER``:
        # the parser above sees Q24 followed by Q25 with almost nothing
        # between them — leave the empty first slot out.
        if answer:
            out.append((num, answer))
    return out


def _range_from_header(line: str) -> tuple[range, range] | None:
    """Look for ``Questions 1-10 ... Questions 21-30`` on the same line."""
    ms = list(RE_COLUMN_HEADER.finditer(line))
    if len(ms) >= 2:
        a, b = ms[0], ms[1]
        return (range(int(a.group(1)), int(a.group(2)) + 1),
                range(int(b.group(1)), int(b.group(2)) + 1))
    if len(ms) == 1:
        a = ms[0]
        return (range(int(a.group(1)), int(a.group(2)) + 1), range(0, 0))
    return None


def _extract_answers_from_page(page: Page) -> dict[str, str]:
    """Parse all Q-answer pairs from a single answer-key page.

    Combines two extractors — columnar/inline first (``1 Jamieson 21 G``,
    ``1 taxi/cab``), then a bare-number fallback (``1\\nA\\n2\\nB``) for
    the Cambridge 18 column layout where each number and its answer occupy
    separate OCR lines. Also tracks ``Section N, Questions X-Y`` headers so
    two-column splits know which ranges are legal.
    """
    left = range(1, 41)
    right = range(0, 0)
    answers: dict[str, str] = {}
    lines = page.lines
    for i, ln in enumerate(lines):
        hdr = _range_from_header(ln)
        if hdr is not None:
            left, right = hdr
            continue
        pairs = _split_columnar_line(ln, left, right)
        if pairs:
            for qn, ans in pairs:
                ans = ans.strip()
                if not ans or len(ans) > 80:
                    continue
                answers.setdefault(str(qn), ans)
            continue
        # Bare-number-then-answer-on-next-lines fallback (Cambridge 18 style).
        m = RE_BARE_NUMBER.match(ln)
        if not m:
            continue
        qn = int(m.group(1))
        if not (1 <= qn <= 40):
            continue
        parts: list[str] = []
        for j in range(i + 1, min(i + 5, len(lines))):
            nxt = lines[j]
            if RE_BARE_NUMBER.match(nxt) or _range_from_header(nxt):
                break
            if any(rx.search(nxt) for rx in (RE_ANSWER_KEY_HDR, RE_LISTENING, RE_READING)):
                break
            parts.append(nxt)
        ans = " ".join(parts).strip()
        if ans and len(ans) < 80:
            answers.setdefault(str(qn), ans)
    return answers


def _extract_answers_from_lines(lines: list[str], q_range: range) -> dict[str, str]:
    """Parse question-answer pairs from a stretch of lines.

    Handles two layouts:
      * bare number line followed by the answer on subsequent lines
        (Cambridge 18-style column-formatted keys)
      * `N   answer` on a single line
        (Cambridge 1/3-style tabular keys)
    """
    answers: dict[str, str] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        inline = RE_INLINE_ANSWER.match(line)
        if inline and int(inline.group(1)) in q_range:
            answers[inline.group(1)] = inline.group(2).strip()
            i += 1
            continue
        m = RE_BARE_NUMBER.match(line)
        if not m:
            i += 1
            continue
        qn = int(m.group(1))
        if qn not in q_range:
            i += 1
            continue
        j = i + 1
        parts: list[str] = []
        while j < len(lines) and j < i + 6:
            if RE_BARE_NUMBER.match(lines[j]) or RE_INLINE_ANSWER.match(lines[j]):
                break
            if any(rx.search(lines[j]) for rx in (RE_ANSWER_KEY_HDR, RE_LISTENING, RE_READING)):
                break
            parts.append(lines[j])
            j += 1
        if parts:
            answers[str(qn)] = " ".join(parts).strip()
        i = j if j > i else i + 1
    return answers


_RE_STANDALONE_LISTENING = re.compile(r"^\s*Listening\b(?!\s+and\s+Reading)", re.I)
_RE_STANDALONE_READING = re.compile(r"^\s*(?:Academic\s+)?Reading\b(?!\s+and\s+Listening|\s+Passage)", re.I)


def _page_kind(page: Page) -> str | None:
    """Classify an answer-key page as ``'L'`` (listening), ``'R'`` (reading),
    or ``None`` (ambiguous).

    Priority: a standalone ``LISTENING`` / ``READING`` / ``ACADEMIC READING``
    header in the top band. The combined section title ``Listening and
    Reading answer keys`` is explicitly excluded — otherwise every AK page
    would classify as ``L``. Falls back to counting section-header vs
    reading-passage mentions in the page body when the header is OCR-lost.
    """
    for ln in page.top_lines[:15]:
        if _RE_STANDALONE_LISTENING.match(ln):
            return "L"
        if _RE_STANDALONE_READING.match(ln):
            return "R"
    l = sum(
        1 for ln in page.lines
        if re.search(r"^(?:Section|Part)\s+\d,?\s*Questions", ln, re.I)
    )
    r = sum(1 for ln in page.lines if re.search(r"Reading\s+Passage", ln, re.I))
    if r > l and r >= 2:
        return "R"
    if l > r and l >= 2:
        return "L"
    return None


def _explicit_test_number(page: Page) -> int | None:
    """Return the ``Test N`` (or ``TEST N``) label if it appears in the top
    band of an answer-key page — used by books like Cambridge 18 that label
    each key page explicitly."""
    for ln in page.top_lines[:15]:
        m = RE_TEST_NUM.match(ln)
        if m:
            return int(m.group(1))
    return None


def _parse_ak_block(
    pages: list[Page], test_number: int
) -> tuple[dict[str, str], dict[str, str]]:
    """Fallback answer-key parser that groups by ``Test N`` header, splits
    into LISTENING/READING sub-blocks via section headers, and runs the
    bare-number-then-answer extractor. This is the pre-2026-07-09 logic —
    kept as a fallback because it handles books like Cambridge 1 whose
    answer-key section groups all L+R for a test under one ``Test N`` label
    on a single page rather than alternating L/R pages."""
    ak_pages = _find_answer_key_pages(pages)
    if not ak_pages:
        return {}, {}

    lines_with_page: list[tuple[int, str]] = []
    for p in ak_pages:
        for ln in p.lines:
            lines_with_page.append((p.number, ln))

    test_start_idxs: list[int] = []
    for i, (_, ln) in enumerate(lines_with_page):
        m = RE_TEST_NUM.match(ln)
        if m and int(m.group(1)) == test_number:
            test_start_idxs.append(i)
    if not test_start_idxs:
        return {}, {}

    start = test_start_idxs[0]
    end = len(lines_with_page)
    for i in range(start + 1, len(lines_with_page)):
        m = RE_TEST_NUM.match(lines_with_page[i][1])
        if m and int(m.group(1)) != test_number:
            end = i
            break

    block = [ln for _, ln in lines_with_page[start:end]]
    l_start = next(
        (i for i, ln in enumerate(block) if _RE_STANDALONE_LISTENING.match(ln)), None
    )
    r_start = next(
        (i for i, ln in enumerate(block) if _RE_STANDALONE_READING.match(ln)), None
    )

    l_ans: dict[str, str] = {}
    r_ans: dict[str, str] = {}
    if l_start is not None:
        l_end = r_start if r_start and r_start > l_start else len(block)
        l_ans = _extract_answers_from_lines(block[l_start:l_end], range(1, 41))
    if r_start is not None:
        r_ans = _extract_answers_from_lines(block[r_start:], range(1, 41))
    return l_ans, r_ans


def parse_answer_key(
    pages: list[Page], test_number: int
) -> tuple[dict[str, str], dict[str, str], list[str]]:
    """Return (listening_answers, reading_answers, warnings)."""
    warnings: list[str] = []
    ak_pages = _find_answer_key_pages(pages)
    if not ak_pages:
        return {}, {}, ["answer-key section not found"]

    # Group answer-key pages by test using the canonical modern layout: each
    # test uses one LISTENING page followed by one READING page, in order —
    # (L1, R1, L2, R2, L3, R3, L4, R4). The Nth listening page is test N's
    # listening key; likewise for reading. This holds for every scanned
    # Cambridge book I've checked (5, 7, 10, 15, 17, 18, 19, 21). Books that
    # ALSO carry explicit ``Test N`` markers still classify the same way, so
    # we don't need a separate code path for them.
    per_test_L: dict[int, list[Page]] = {}
    per_test_R: dict[int, list[Page]] = {}
    l_pages = [p for p in ak_pages if _page_kind(p) == "L"]
    r_pages = [p for p in ak_pages if _page_kind(p) == "R"]
    for idx, p in enumerate(l_pages, start=1):
        per_test_L.setdefault(idx, []).append(p)
    for idx, p in enumerate(r_pages, start=1):
        per_test_R.setdefault(idx, []).append(p)

    listening_answers: dict[str, str] = {}
    reading_answers: dict[str, str] = {}

    for p in per_test_L.get(test_number, []):
        for k, v in _extract_answers_from_page(p).items():
            listening_answers.setdefault(k, v)
    for p in per_test_R.get(test_number, []):
        for k, v in _extract_answers_from_page(p).items():
            reading_answers.setdefault(k, v)

    # Merge in any answers the block-based fallback finds. This helps books
    # (Cambridge 1, 2, 11) whose answer keys aren't laid out as alternating
    # L/R pages but instead as ``Test N`` blocks each containing both
    # sections. Sequential answers take precedence — the fallback only fills
    # gaps.
    fb_l, fb_r = _parse_ak_block(pages, test_number)
    for k, v in fb_l.items():
        listening_answers.setdefault(k, v)
    for k, v in fb_r.items():
        reading_answers.setdefault(k, v)

    if not listening_answers:
        warnings.append(f"no listening answers parsed for test {test_number}")
    if not reading_answers:
        warnings.append(f"no reading answers parsed for test {test_number}")
    return listening_answers, reading_answers, warnings


# ---------------------------------------------------------------------------
# Book-level entry point


@dataclass
class BookConfig:
    book_id: str
    book_title: str
    pdf_path: Path
    warnings: list[str] = field(default_factory=list)
    # When a book PDF actually contains a single test (e.g. Cambridge 6 is
    # split into four per-test PDFs), pin the parsed test to this number
    # instead of the auto-assigned index-1 order.
    force_test_number: int | None = None
    allow_ocr: bool = True


def parse_book(config: BookConfig) -> list[dict[str, Any]]:
    """Parse all detectable Academic tests from a Cambridge PDF."""
    pages = load_pages(config.pdf_path, allow_ocr=config.allow_ocr)
    boundaries = detect_test_boundaries(pages)
    if not boundaries:
        raise RuntimeError(
            f"No complete Academic tests detected in {config.pdf_path.name}. "
            "The PDF may be image-based or use an unrecognised format."
        )

    # Scanned PDFs store each page as one giant image — extracting them would
    # attach the entire page as a "visual" to every question, which is noise.
    # Skip image extraction on image-based books; native-text books extract
    # question-scoped figures as before.
    from app.ingest.kb import pdf_is_image_based

    if pdf_is_image_based(config.pdf_path):
        page_images: dict[int, list[ExtractedImage]] = {}
    else:
        assets_root = Path(settings.assets_dir) / config.book_id
        try:
            page_images = extract_book_images(
                pdf_path=config.pdf_path,
                out_dir=assets_root,
                url_prefix=f"/assets/{config.book_id}",
            )
        except Exception as exc:
            page_images = {}
            config.warnings.append(f"image extraction failed: {exc}")

    tests: list[dict[str, Any]] = []
    for b in boundaries:
        effective_test_number = config.force_test_number or b.test_number
        listening_key, reading_key, ak_warnings = parse_answer_key(
            pages, effective_test_number
        )
        claimed: set[str] = set()
        listening = extract_listening(pages, b, page_images, claimed)
        reading = extract_reading(pages, b, page_images, claimed)
        writing = extract_writing(pages, b, page_images, claimed)
        speaking = extract_speaking(pages, b)
        listening["answer_key"] = listening_key
        reading["answer_key"] = reading_key

        warnings = list(config.warnings) + list(ak_warnings)
        if len(reading["passages"]) != 3:
            warnings.append(
                f"expected 3 reading passages, found {len(reading['passages'])}"
            )
        if len(listening["parts"]) != 4:
            warnings.append(
                f"expected 4 listening parts, found {len(listening['parts'])}"
            )
        if listening_key and len(listening_key) != 40:
            warnings.append(f"listening answer key has {len(listening_key)}/40 entries")
        if reading_key and len(reading_key) != 40:
            warnings.append(f"reading answer key has {len(reading_key)}/40 entries")

        tests.append(
            {
                "book_id": config.book_id,
                "book_title": config.book_title,
                "test_number": effective_test_number,
                "source_pdf": str(config.pdf_path),
                "reading": reading,
                "listening": listening,
                "writing": writing,
                "speaking": speaking,
                "warnings": warnings,
            }
        )
    return tests


# ---------------------------------------------------------------------------
# Known text-extractable books (path relative to backend/)

_C6_ROOT = "books/ielts book/Cambridge IELTS 06/Cambridge IELTS 06/Cambridge.IELTS.6.Tests.With.Answers"


def _c6(n: int) -> BookConfig:
    return BookConfig(
        book_id=f"cambridge-6-t{n}",
        book_title=f"Cambridge IELTS 6 (Test {n})",
        pdf_path=Path(f"{_C6_ROOT}/Cambridge ielts 6_test{n}.pdf"),
        force_test_number=n,
    )


BOOK_CATALOG: list[BookConfig] = [
    BookConfig(
        book_id="cambridge-1",
        book_title="Cambridge IELTS 1",
        pdf_path=Path("books/ielts book/Cambridge IELTS 01/Cambridge IELTS 01/Cambridge Practice Tests for IELTS 1.pdf"),
    ),
    BookConfig(
        book_id="cambridge-2",
        book_title="Cambridge IELTS 2",
        pdf_path=Path("books/ielts book/Cambridge IELTS 02/Cambridge  IELTS 02/Cambridge Practice Tests for IELTS 2.pdf"),
    ),
    BookConfig(
        book_id="cambridge-3",
        book_title="Cambridge IELTS 3",
        pdf_path=Path("books/ielts book/Cambridge IELTS 03/Cambridge  IELTS 03/Cambridge Practice Tests for IELTS 3.pdf"),
    ),
    BookConfig(
        book_id="cambridge-4",
        book_title="Cambridge IELTS 4",
        pdf_path=Path("books/ielts book/Cambridge IELTS 04/Cambridge  IELTS 04/Cambridge Practice Tests for IELTS 4.pdf"),
    ),
    BookConfig(
        book_id="cambridge-5",
        book_title="Cambridge IELTS 5",
        pdf_path=Path("books/ielts book/Cambridge IELTS 05/Cambridge  IELTS 05/Cambridge_IELTS_5_with_Answers.pdf"),
    ),
    _c6(1),
    _c6(2),
    _c6(3),
    _c6(4),
    BookConfig(
        book_id="cambridge-7",
        book_title="Cambridge IELTS 7",
        pdf_path=Path("books/ielts book/Cambridge IELTS 07/Cambridge  IELTS 07/ielts7.pdf"),
    ),
    BookConfig(
        book_id="cambridge-8",
        book_title="Cambridge IELTS 8",
        pdf_path=Path("books/ielts book/Cambridge IELTS 08/Cambridge IELTS 08/Cambridge IELTS 8.pdf"),
    ),
    BookConfig(
        book_id="cambridge-9",
        book_title="Cambridge IELTS 9",
        pdf_path=Path("books/ielts book/Cambridge IELTS 09/Cambridge IELTS 09/Cambridge IELTS 9.pdf"),
    ),
    BookConfig(
        book_id="cambridge-10",
        book_title="Cambridge IELTS 10",
        pdf_path=Path("books/ielts book/Cambridge IELTS 10/Cambridge-IELTS-10-Ebook.pdf"),
    ),
    BookConfig(
        book_id="cambridge-11",
        book_title="Cambridge IELTS 11 Academic",
        pdf_path=Path("books/ielts book/Cambridge IELTS 11- Academic/IELTS Cambridge Book 11.pdf"),
    ),
    BookConfig(
        book_id="cambridge-12",
        book_title="Cambridge IELTS 12 Academic",
        pdf_path=Path("books/ielts book/Cambridge IELTS 12 - Academic/Cambridge IELTS 12 PDF.pdf"),
    ),
    BookConfig(
        book_id="cambridge-13",
        book_title="Cambridge IELTS 13 Academic",
        pdf_path=Path("books/ielts book/Cambridge IELTS 13 Academic/IELTS Cambridge 13.pdf"),
    ),
    BookConfig(
        book_id="cambridge-14",
        book_title="Cambridge IELTS 14 Academic",
        pdf_path=Path("books/ielts book/Cambridge IELTS 14 Academic/IELTS Cambridge IELTS 14.pdf"),
    ),
    BookConfig(
        book_id="cambridge-15",
        book_title="Cambridge IELTS 15 Academic",
        pdf_path=Path("books/ielts book/Cambridge IELTS 15 Academic/Cambridge 15 Academic.pdf"),
    ),
    BookConfig(
        book_id="cambridge-16",
        book_title="Cambridge IELTS 16 Academic",
        pdf_path=Path("books/ielts book/Cambridge IELTS 16 Academic/Cambridge 16.pdf"),
    ),
    BookConfig(
        book_id="cambridge-17",
        book_title="Cambridge IELTS 17 Academic",
        pdf_path=Path("books/ielts book/Cambridge IELTS 17 Academic/Cambridge 17.pdf"),
    ),
    BookConfig(
        book_id="cambridge-18",
        book_title="Cambridge IELTS 18 Academic",
        pdf_path=Path("books/ielts book/Cambridge IELTS 18 Academic/Cambridge 18.pdf"),
    ),
    BookConfig(
        book_id="cambridge-19",
        book_title="Cambridge IELTS 19 Academic",
        pdf_path=Path("books/ielts book/Cambridge IELTS 19 Academic/Cambridge 19.pdf"),
    ),
    BookConfig(
        book_id="cambridge-21",
        book_title="Cambridge IELTS 21",
        pdf_path=Path("books/ielts book/IELTS Cambridge Book 21.pdf"),
    ),
]

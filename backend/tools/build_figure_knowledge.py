"""Distil what the exam's figures KNOW, into something the engine can retrieve.

The books are grounding, never content: a student sees AI output, and no
Cambridge page is ever rendered to them. So this does not copy figures. It
reads the OCR of every page that carries one and writes down the CONVENTIONS —
how long a callout runs, where the blank sits in the sentence, what gets
numbered and what gets named, how many parts a cross-section carries, which
subjects the exam actually draws — as records the generator can retrieve while
it is building a figure of its own about something else entirely.

Two stages, so a bad run costs one of them and not both:

  --extract   one focused LLM call per figure page -> data/figure_knowledge/*.json
  --ingest    those records -> the vector store, under source "figure-conventions"

`--extract` needs the hosted model. `--ingest` needs the qdrant lock, so stop
the backend first.

Usage:
  PYTHONIOENCODING=utf-8 python tools/build_figure_knowledge.py --extract
  PYTHONIOENCODING=utf-8 python tools/build_figure_knowledge.py --ingest
  PYTHONIOENCODING=utf-8 python tools/build_figure_knowledge.py --extract --limit 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.llm.client import get_llm_client
from app.llm.prompts import FIGURE_KNOWLEDGE_SYSTEM

ROOT = Path(__file__).resolve().parents[1]
OCR = ROOT / "data" / "ocr_cache"
OUT = ROOT / "data" / "figure_knowledge"

SOURCE = "figure-conventions"

# The rubric lines Cambridge uses to introduce a figure. Same list the atlas
# uses; kept here so this tool does not depend on the atlas having been run.
TASKS = [
    (r"label the (diagram|plan|map)", "labelled"),
    (r"complete the (diagram|flow[\s-]*chart|flowchart)", "completion"),
    (r"complete the (notes|table|form|summary)", "block"),
    (r"choose the correct (picture|diagram)", "picture"),
]
PATTERNS = [re.compile(p, re.I) for p, _ in TASKS]

# A page whose OCR is this short lost its figure to the scan; asking about it
# spends a call to be told "is_figure": false.
_MIN_CHARS = 220


def pages() -> list[tuple[str, int, str]]:
    """(book, page number, OCR text) for every page that introduces a figure."""
    found: list[tuple[str, int, str]] = []
    for book_dir in sorted(OCR.iterdir()):
        if not book_dir.is_dir():
            continue
        for page_file in sorted(book_dir.glob("p*.txt")):
            text = page_file.read_text(encoding="utf-8", errors="ignore")
            if len(text) < _MIN_CHARS:
                continue
            if any(p.search(text) for p in PATTERNS):
                found.append((book_dir.name, int(page_file.stem[1:]), text))
    return found


def _path(record_or_book, page: int | None = None) -> Path:
    """Where one page's record lives. Also the resume marker."""
    if isinstance(record_or_book, dict):
        book, page = record_or_book["book"], record_or_book["page"]
    else:
        book = record_or_book
    return OUT / f"{book}_p{int(page):04d}.json".replace(" ", "-")


async def distil(book: str, page: int, text: str, sem: asyncio.Semaphore) -> dict | None:
    async with sem:
        try:
            # Hosted: the fine-tuned checkpoint answers in its trained shape,
            # which is a practice set, not an analysis. Uncapped for the same
            # reason the figure draw is — this returns a whole structured
            # record and a reasoning model spends budget before it writes.
            reply = await get_llm_client(
                "generator", skip_finetune=True
            ).complete_json(
                FIGURE_KNOWLEDGE_SYSTEM,
                [{"role": "user", "content": f"Page text:\n{text[:6000]}"}],
            )
        except Exception as exc:
            print(f"  !! {book} p{page}: {type(exc).__name__}: {exc}", flush=True)
            return None
        reply["book"] = book
        reply["page"] = page
        if not reply.get("is_figure"):
            # Recorded as a miss rather than dropped, so a resumed run does not
            # pay again for every rubric page whose figure the scan lost.
            _path(reply).write_text(
                json.dumps({"is_figure": False, "book": book, "page": page}),
                encoding="utf-8",
            )
            return None
        # Written here rather than after the gather, so a crash or an
        # interrupt three hundred calls in costs the last call and not all of
        # them. The run is resumable for the same reason: `--extract` skips a
        # page whose record is already on disk.
        _path(reply).write_text(
            json.dumps(reply, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        return reply


async def extract(limit: int, concurrency: int) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    todo = pages()
    # Resume: a page already distilled is not paid for twice.
    done = sum(1 for b, p, _ in todo if _path(b, p).exists())
    todo = [(b, p, t) for b, p, t in todo if not _path(b, p).exists()]
    if limit:
        todo = todo[:limit]
    print(f"{len(todo)} pages to distil ({done} already on disk)")
    sem = asyncio.Semaphore(concurrency)
    records = await asyncio.gather(*(distil(b, p, t, sem) for b, p, t in todo))
    kept = [r for r in records if r]
    by_type = Counter(r.get("figure_type") for r in kept)
    print(f"\n{len(kept)} figure records -> {OUT}")
    for kind, n in by_type.most_common():
        print(f"  {n:4d}  {kind}")
    return 0


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


def _exemplar_text(r: dict) -> str:
    """One retrievable record: what this figure is, and how it is built.

    Written as prose rather than JSON because it is embedded and read by a
    model, and because the retriever formats chunks into a prompt as text.
    """
    lines = [
        f"FIGURE CONVENTION — {r.get('figure_type')} ({r.get('module')} paper)",
        f"Subject drawn: {r.get('subject')} [{r.get('subject_domain')}]",
    ]
    if r.get("title"):
        lines.append(f"Printed title: {r['title']}")
    if r.get("rubric"):
        lines.append(f"Rubric: {r['rubric']}")
    lines.append(
        f"Blanks: {r.get('gap_count')} · answers come from: {r.get('answer_source')}"
    )
    items = r.get("labelled_items") or []
    if items:
        lines.append("How the numbered items are written:")
        for it in items[:6]:
            if not isinstance(it, dict):
                continue
            lines.append(f"  - {it.get('text')}")
            if it.get("pattern"):
                lines.append(f"    shape: {it['pattern']} [{it.get('answer_kind')}]")
    fixed = [f for f in (r.get("fixed_labels") or []) if f]
    if fixed:
        lines.append("Printed, not numbered (what orients the candidate): "
                     + ", ".join(str(f) for f in fixed[:8]))
    for c in (r.get("conventions") or [])[:6]:
        lines.append(f"RULE: {c}")
    return "\n".join(lines)


def _summary_text(kind: str, rows: list[dict]) -> str:
    """The aggregate for one figure family — what is TYPICAL, with counts."""
    gaps = [r.get("gap_count") for r in rows if isinstance(r.get("gap_count"), int)]
    words = [
        len(re.sub(r"__\d+__", " ", str(it.get("text") or "")).split())
        for r in rows
        for it in (r.get("labelled_items") or [])
        if isinstance(it, dict)
    ]
    kinds = Counter(
        it.get("answer_kind")
        for r in rows
        for it in (r.get("labelled_items") or [])
        if isinstance(it, dict) and it.get("answer_kind")
    )
    domains = Counter(r.get("subject_domain") for r in rows if r.get("subject_domain"))
    lines = [
        f"FIGURE FAMILY SUMMARY — {kind}",
        f"Measured over {len(rows)} real Cambridge figures.",
    ]
    if gaps:
        lines.append(
            f"Blanks per figure: {min(gaps)}-{max(gaps)}, "
            f"typically {sorted(gaps)[len(gaps)//2]}."
        )
    if words:
        srt = sorted(words)
        lines.append(
            f"Words per numbered item, excluding the blank: {min(words)}-{max(words)}, "
            f"median {srt[len(srt)//2]}."
        )
    if kinds:
        lines.append(
            "What the blanks ask for: "
            + ", ".join(f"{k} ({n})" for k, n in kinds.most_common(6))
        )
    if domains:
        lines.append(
            "Subjects the exam draws: "
            + ", ".join(f"{k}" for k, _ in domains.most_common(8))
        )
    seen: list[str] = []
    for r in rows:
        for c in r.get("conventions") or []:
            c = str(c).strip()
            if c and c not in seen:
                seen.append(c)
    for c in seen[:14]:
        lines.append(f"RULE: {c}")
    return "\n".join(lines)


def ingest() -> int:
    from app.rag.store import get_vector_store

    records = [
        json.loads(p.read_text(encoding="utf-8")) for p in sorted(OUT.glob("*.json"))
    ]
    # The misses are resume markers, not knowledge.
    records = [r for r in records if r.get("is_figure")]
    if not records:
        print("no records — run --extract first")
        return 1

    by_kind: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_kind[str(r.get("figure_type") or "other")].append(r)

    chunks = [
        {"text": _exemplar_text(r), "source": SOURCE,
         "metadata": {"figure_type": r.get("figure_type"), "module": r.get("module")}}
        for r in records
    ]
    # The aggregates go in as chunks of their own, so a query about a figure
    # family can retrieve the family's shape as well as three examples of it.
    chunks += [
        {"text": _summary_text(kind, rows), "source": SOURCE,
         "metadata": {"figure_type": kind, "module": "both"}}
        for kind, rows in sorted(by_kind.items())
    ]

    store = get_vector_store()
    before = store.count()
    n = store.index_chunks(chunks)
    print(f"indexed {n} chunks under source={SOURCE!r}")
    print(f"collection: {before} -> {store.count()} points")
    for kind, rows in sorted(by_kind.items()):
        print(f"  {len(rows):4d}  {kind}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--extract", action="store_true")
    ap.add_argument("--ingest", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--concurrency", type=int, default=4)
    args = ap.parse_args()
    if args.extract:
        return asyncio.run(extract(args.limit, args.concurrency))
    if args.ingest:
        return ingest()
    ap.error("pass --extract or --ingest")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Ask for each official IELTS question type and report what comes back.

`figure_sweep.py` does this for the figure a set carries. This does it for the
QUESTION TYPES themselves — the ten Listening prints and the eleven Reading
prints — because a type can be named in a prompt, known to a validator and
still never actually be produced, and nothing else in the repo would notice.

Three things are checked per type, and they fail differently:

  refused    the set did not survive its own trainer at all
  produced   it holds at least one question of the type REQUESTED — a model
             that quietly substitutes `sentence_completion` for
             `matching_features` leaves a student who never meets that type
  usable     every question carries text, an answer, and (for a choice type)
             its own options, and the whole set passes the section validator

Needs the qdrant lock, so stop the backend first.

Usage:
  PYTHONIOENCODING=utf-8 python tools/question_type_sweep.py
  PYTHONIOENCODING=utf-8 python tools/question_type_sweep.py --only matching
  PYTHONIOENCODING=utf-8 python tools/question_type_sweep.py --rounds 2
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents import listening_trainer as lt
from app.agents import reading_trainer as rt
from app.agents.answerability import canon, qtype

OUT = Path("tools/_qtypes")

# (slug, module, requested type, topic). The topic does real work, the same way
# it does in `figure_sweep`: asked with no steer the model reaches for the same
# subject every time, and a type like `matching_features` needs a subject with
# several named people to match against or it cannot be written at all.
JOBS: list[tuple[str, str, str, str]] = [
    # ---- Listening: the ten the exam prints -------------------------------
    ("l_multiple_choice", "listening", "multiple_choice",
     "a tutor explaining three options for a student research project"),
    ("l_matching", "listening", "matching",
     "two students deciding who will take which task in a group presentation"),
    ("l_map", "listening", "map_labelling",
     "a warden describing the layout of a country park to new volunteers"),
    ("l_diagram", "listening", "diagram_label_completion",
     "a guide explaining the parts of a hand-operated coffee grinder"),
    ("l_form", "listening", "form_completion",
     "a caller booking a place on a weekend photography course"),
    ("l_notes", "listening", "note_completion",
     "a talk introducing a volunteer beach-cleaning scheme"),
    ("l_table", "listening", "table_completion",
     "a tutor comparing four field-trip options by cost and date"),
    ("l_flow", "listening", "flow_chart_completion",
     "two students planning the stages of a soil experiment"),
    ("l_summary", "listening", "summary_completion",
     "a lecturer summarising how a city reduced its traffic congestion"),
    ("l_sentence", "listening", "sentence_completion",
     "a museum guide describing how a Roman mosaic was lifted and restored"),
    ("l_short_answer", "listening", "short_answer",
     "an adviser answering questions about a student accommodation office"),
    # ---- Reading: the eleven the exam prints ------------------------------
    ("r_multiple_choice", "reading", "multiple_choice",
     "how the printing press changed the spread of scientific ideas"),
    ("r_tfng", "reading", "true_false_notgiven",
     "the discovery and industrial uses of natural rubber"),
    ("r_ynng", "reading", "yes_no_notgiven",
     "an argument about whether cities should ban private cars"),
    ("r_match_info", "reading", "matching_information",
     "how four early writing systems differed in materials and use"),
    ("r_match_head", "reading", "matching_headings",
     "why cities are planting trees to cool their streets"),
    ("r_match_feat", "reading", "matching_features",
     "four named researchers and their competing theories of memory"),
    ("r_match_end", "reading", "matching_sentence_endings",
     "how coral reefs recover after a bleaching event"),
    ("r_sentence", "reading", "sentence_completion",
     "the excavation of a Roman town and what it revealed"),
    ("r_summary", "reading", "summary_completion",
     "the domestication of the horse and its effect on trade"),
    ("r_note", "reading", "note_completion",
     "how household water use changed across four decades"),
    ("r_table", "reading", "table_completion",
     "four materials used in early bridge building"),
    ("r_flow", "reading", "flow_chart_completion",
     "how sea salt is harvested and refined for the table"),
    ("r_diagram", "reading", "diagram_label_completion",
     "the structure of a termite mound and how it ventilates itself"),
    ("r_short_answer", "reading", "short_answer",
     "the history of the Antarctic research stations"),
]

# Types whose question is unanswerable without the list of things to choose
# from. TFNG/YNNG are choice types too, but the exam prints their three words
# in the rubric rather than as an options array, so they are excluded here.
_NEEDS_OPTIONS = {canon(t) for t in (
    "multiple_choice", "matching", "matching_information", "matching_headings",
    "matching_features", "matching_sentence_endings", "picture_choice",
)}


def audit(want: str, result: dict, module: str) -> list[str]:
    """Everything wrong with this set that the type sweep is asking about."""
    faults: list[str] = []
    questions = [q for q in (result.get("questions") or []) if isinstance(q, dict)]
    got = [qtype(q) for q in questions]
    if canon(want) not in got:
        seen = ", ".join(sorted(set(got))) or "nothing"
        faults.append(f"asked for {want}, got {seen}")

    key = result.get("answer_key") or {}
    for q in questions:
        num = str(q.get("number"))
        if qtype(q) in _NEEDS_OPTIONS and not q.get("options"):
            faults.append(f"Q{num} ({q.get('type')}) carries no options")
        if not str(q.get("question") or "").strip():
            faults.append(f"Q{num} has no question text")
        if not str(key.get(num) or "").strip():
            faults.append(f"Q{num} has no answer")

    validate = rt.validate_practice if module == "reading" else lt.validate_part
    problem = validate(result)
    if problem:
        faults.append(f"invalid: {problem}")
    return faults


async def one(slug, module, want, topic, sem) -> dict:
    async with sem:
        trainer = rt if module == "reading" else lt
        t0 = time.time()
        try:
            result = await trainer.create_practice(
                question_types=[want], topic=topic)
        except Exception as exc:
            reason = str(exc).replace("\n", " ")[:130]
            refused = getattr(exc, "result", None)
            if isinstance(refused, dict):
                (OUT / f"{slug}.REFUSED.json").write_text(
                    json.dumps({"reason": str(exc), "set": refused},
                               ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"  REFUSED {slug:20} {time.time() - t0:6.1f}s  {reason}",
                  flush=True)
            return {"slug": slug, "want": want, "state": "refused",
                    "faults": [reason]}

        faults = audit(want, result, module)
        (OUT / f"{slug}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        n = len(result.get("questions") or [])
        if faults:
            print(f"  FAULT   {slug:20} {time.time() - t0:6.1f}s  {n:>2}q  "
                  f"{faults[0][:96]}", flush=True)
            for extra in faults[1:4]:
                print(f"          {'':20}        {extra[:96]}", flush=True)
            return {"slug": slug, "want": want, "state": "fault",
                    "faults": faults}
        print(f"  ok      {slug:20} {time.time() - t0:6.1f}s  {n:>2}q",
              flush=True)
        return {"slug": slug, "want": want, "state": "ok", "faults": []}


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--rounds", type=int, default=1)
    ap.add_argument("--concurrency", type=int, default=5)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="    ~ %(message)s")
    for noisy in ("httpx", "openai", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    OUT.mkdir(parents=True, exist_ok=True)

    jobs = [j for j in JOBS if args.only in j[0] or args.only in j[2]]
    sem = asyncio.Semaphore(args.concurrency)
    rows: list[dict] = []
    started = time.time()
    for rnd in range(1, args.rounds + 1):
        tag = "" if args.rounds == 1 else f"_r{rnd}"
        print(f"\n== round {rnd}: {len(jobs)} types ==", flush=True)
        rows += await asyncio.gather(
            *(one(s + tag, m, w, t, sem) for s, m, w, t in jobs))

    ok = [r for r in rows if r["state"] == "ok"]
    print(f"\n{len(ok)} of {len(rows)} types clean in "
          f"{(time.time() - started) / 60:.1f} min")
    for state in ("refused", "fault"):
        bad = [r for r in rows if r["state"] == state]
        if bad:
            print(f"\n{state.upper()} ({len(bad)}):")
            for r in bad:
                print(f"  {r['slug']:22} {r['faults'][0][:112]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

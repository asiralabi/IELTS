"""Generate one live set per figure type and report what came back.

`tools/figure_coverage.py` proves a figure is REACHABLE — a prompt asks for it,
a validator knows it, a renderer draws it. It cannot say whether what comes
back is any good, or how often the set is refused and regenerated. This does:
it makes the same `create_practice` call a student's request makes, once per
figure type across both papers, and prints the refusal reason for each failure.

The refusal rate is the number that matters for production. A refused set costs
a whole regeneration, which is invisible behind the warm pool and painful
without it.

Needs the qdrant lock, so stop the backend first.

Usage:
  PYTHONIOENCODING=utf-8 python tools/figure_sweep.py
  PYTHONIOENCODING=utf-8 python tools/figure_sweep.py --only diagram
  PYTHONIOENCODING=utf-8 python tools/figure_sweep.py --rounds 2 --concurrency 6
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
from app.agents._diagram import diagram_error, is_diagram
from app.agents.answerability import RefusedSet
from app.agents._figure_pass import figure_richness

OUT = Path("tools/_gallery")

# (slug, module, question types, topic)
#
# The topic does real work: asked for a diagram with no steer the model reaches
# for the same machine every time, and naming the subject is how the LAYOUTS
# get exercised — strata for `layers`, a life cycle for `cycle`.
JOBS: list[tuple[str, str, list[str], str]] = [
    ("r_diagram_machine", "reading", ["diagram_label_completion"],
     "how a lock on a canal raises a boat between two water levels"),
    ("r_diagram_crosssec", "reading", ["diagram_label_completion"],
     "the structure of a termite mound and how it ventilates itself"),
    ("r_diagram_layers", "reading", ["diagram_label_completion"],
     "what the layers of ice in an Antarctic core reveal about past climates"),
    ("r_diagram_cycle", "reading", ["diagram_label_completion"],
     "the life cycle of the monarch butterfly and its migration"),
    ("r_diagram_apparatus", "reading", ["diagram_label_completion"],
     "the Victorian deep-sea diving suit and how air reached the diver"),
    ("r_flow", "reading", ["flow_chart_completion"],
     "how sea salt is harvested and refined for the table"),
    ("r_map", "reading", ["map_labelling"],
     "the excavated layout of the Roman town of Silchester"),
    ("r_table", "reading", ["table_completion"],
     "how four early writing systems differed in materials and use"),
    ("r_notes", "reading", ["note_completion"],
     "why cities are planting trees to cool their streets"),
    ("r_summary", "reading", ["summary_completion"],
     "the discovery and industrial uses of natural rubber"),
    ("r_chart", "reading", ["chart_completion"],
     "how household water use in one country changed across four decades"),
    ("r_pie", "reading", ["chart_completion"],
     "what share of the world's freshwater sits in ice, groundwater and rivers"),
    ("l_diagram", "listening", ["diagram_label_completion"],
     "a guide explaining the parts of a hand-operated coffee grinder"),
    ("l_map", "listening", ["map_labelling"],
     "a warden describing the layout of a country park to new volunteers"),
    ("l_flow", "listening", ["flow_chart_completion"],
     "two students planning the stages of a soil experiment"),
    ("l_form", "listening", ["form_completion"],
     "a caller booking a place on a weekend photography course"),
    ("l_table", "listening", ["table_completion"],
     "a tutor comparing four field-trip options by cost and date"),
    ("l_notes", "listening", ["note_completion"],
     "a talk introducing a volunteer beach-cleaning scheme"),
    ("l_pictures", "listening", ["picture_choice"],
     "a technician describing which way round a water filter is fitted"),
    ("l_chart", "listening", ["chart_completion"],
     "a lecturer talking through visitor numbers at a museum by month"),
]


async def one(slug, module, types, topic, sem) -> dict:
    async with sem:
        trainer = rt if module == "reading" else lt
        t0 = time.time()
        try:
            result = await trainer.create_practice(question_types=types, topic=topic)
        except Exception as exc:
            reason = str(exc).replace("\n", " ")[:150]
            # 🔬 The refused set is the whole point of catching this. A
            # sweep that saves only what PASSES reports a failure it cannot
            # explain: the two picture-choice refusals of 2026-09-01 left
            # nothing to look at, so the second route the count rule misses
            # stayed a guess. `RefusedSet` carries the set past the raise;
            # written beside its reason, the next one is diagnosable offline.
            refused = getattr(exc, "result", None)
            if isinstance(refused, dict):
                (OUT / f"{slug}.REFUSED.json").write_text(
                    json.dumps({"reason": str(exc), "set": refused},
                               ensure_ascii=False, indent=1),
                    encoding="utf-8",
                )
            kept = " [saved]" if isinstance(refused, dict) else ""
            print(f"  FAIL {slug:22} {time.time() - t0:6.1f}s{kept}  {reason}",
                  flush=True)
            return {"slug": slug, "ok": False, "reason": reason,
                    "saved": isinstance(refused, dict)}
        secs = time.time() - t0
        visual = result.get("visual") or {}
        kind = visual.get("kind") if isinstance(visual, dict) else None
        rich = figure_richness(visual) if is_diagram(visual) else None
        (OUT / f"{slug}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"  ok   {slug:22} {secs:6.1f}s  kind={kind} richness={rich}", flush=True)
        return {"slug": slug, "ok": True, "kind": kind}


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--rounds", type=int, default=1)
    ap.add_argument("--concurrency", type=int, default=6)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="    ~ %(message)s")
    for noisy in ("httpx", "openai", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    OUT.mkdir(parents=True, exist_ok=True)

    jobs = [j for j in JOBS if args.only in j[0]]
    sem = asyncio.Semaphore(args.concurrency)
    rows: list[dict] = []
    started = time.time()
    for rnd in range(1, args.rounds + 1):
        tag = "" if args.rounds == 1 else f"_r{rnd}"
        print(f"\n== round {rnd}: {len(jobs)} sets ==", flush=True)
        rows += await asyncio.gather(
            *(one(s + tag, m, t, top, sem) for s, m, t, top in jobs)
        )

    bad = [r for r in rows if not r["ok"]]
    mins = (time.time() - started) / 60
    print(f"\n{len(rows) - len(bad)} of {len(rows)} clean "
          f"({len(bad) / len(rows) * 100:.0f}% refused) in {mins:.1f} min")
    for r in bad:
        mark = "" if r.get("saved") else "   (raised before the gate; not saved)"
        print(f"  FAIL {r['slug']:22} {r['reason'][:130]}{mark}")
    if any(r.get("saved") for r in bad):
        print(f"\n  refused sets written to {OUT}/*.REFUSED.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

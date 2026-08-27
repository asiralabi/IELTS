"""Audit the reading passage a live figure harness just wrote.

`_diag_plan_live.py reading` only reports `reading_has_visual` — it does not
check the thing `84c426c` fixes (the answers being words the passage never
used), nor the one still-open defect (the figure printing the very label it
asks the student to supply). Both are read off the saved JSON here, so no
second hosted call is paid for.

Handles the grid figure and the flow chart, and REFUSES anything else rather
than reporting a clean audit of a figure it cannot read. That is not caution
for its own sake: this harness scored a paper 23/23 on 2026-08-23 while the
diagram beside it was numbered against the wrong questions, because it checked
that a visual existed rather than that the figure answered for itself. A check
that cannot fail proves nothing.

Usage: PYTHONIOENCODING=utf-8 python tools/figure_audit.py [saved.json]
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents._diagram import (  # noqa: E402
    diagram_texts,
    is_diagram,
    self_answering_labels,
)
from app.agents._flow import flow_steps, self_answering_steps  # noqa: E402
from app.agents.answerability import GAP_FILL_TYPES, qtype  # noqa: E402
from app.agents.reading_trainer import (  # noqa: E402
    _non_verbatim_answers,
    _span_tokens,
)

SAVED = Path(__file__).resolve().parent / "_diag_plan_live" / "reading_passage.json"


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else SAVED
    if not path.exists():
        print(f"no saved passage at {path}")
        return 2
    result = json.loads(path.read_text(encoding="utf-8"))

    passage = str(result.get("passage") or "")
    questions = result.get("questions") or []
    answer_key = result.get("answer_key") or {}
    visual = result.get("visual")

    print(f"title={result.get('title')!r}")
    print(f"passage words={len(passage.split())}")
    print(f"questions={len(questions)} types={sorted({qtype(q) for q in questions})}")

    print("\n--- 84c426c: are the keyed answers words the passage uses? ---")
    gapfill = [q for q in questions if qtype(q) in GAP_FILL_TYPES]
    if not passage.strip():
        # `_non_verbatim_answers` returns [] on an empty passage, so without
        # this the line below reads "every gap-fill answer appears in the
        # passage" for a listening set that has no passage at all. That is a
        # check that cannot fail, printed in green.
        missing = []
        print("  NOT CHECKED — this set has no passage. A listening set keys "
              "its answers to the script, which this audit does not read.")
    else:
        missing = _non_verbatim_answers(result)
        print(f"gap-fill questions={len(gapfill)}  non-verbatim answers={len(missing)}"
              f"  (validator refuses at >=2)")
        for number, answer in missing:
            print(f"  MISSING  Q{number} = {answer!r}")
        if not missing:
            print("  every gap-fill answer appears in the passage")

    print("\n--- open issue: does the figure print the answer it asks for? ---")
    if not isinstance(visual, dict):
        print("  no visual on the set")
        return 1
    kind = str(visual.get("kind") or "").lower()
    print(f"  kind={kind!r} title={visual.get('title')!r}")

    if kind == "flow":
        selfanswering = audit_flow(visual, answer_key)
        print(f"\nnon_verbatim={len(missing)} self_answering={len(selfanswering)}")
        return 0 if not missing and not selfanswering else 1
    if kind != "plan":
        print(f"  CANNOT AUDIT a {kind!r} figure — this tool reads a grid or a "
              "flow chart. Refusing rather than reporting a clean run.")
        return 2

    grid = visual.get("grid") or []
    for row in grid:
        print("    " + " | ".join(f"{c or '.':^18}" for c in row))

    printed = {}
    for r, row in enumerate(grid):
        for c, cell in enumerate(row):
            text = str(cell or "").strip()
            if text:
                printed.setdefault(" ".join(_span_tokens(text)), []).append((r, c))

    selfanswering = []
    for q in questions:
        if not isinstance(q, dict):
            continue
        number = str(q.get("number"))
        answer = str(answer_key.get(number) or "").strip()
        if not answer:
            continue
        norm = " ".join(_span_tokens(answer))
        if norm and norm in printed:
            selfanswering.append((number, answer, printed[norm]))

    if selfanswering:
        for number, answer, cells in selfanswering:
            print(f"  SELF-ANSWERING  Q{number} = {answer!r} printed at {cells}")
    else:
        print("  no keyed answer is printed on the grid")

    print(f"\nnon_verbatim={len(missing)} self_answering={len(selfanswering)}")
    return 0 if not missing and not selfanswering else 1


def audit_diagram(visual: dict, answer_key: dict) -> list[tuple[str, str, str]]:
    """A drawn figure printing the answer it asks for.

    The third costume of the same defect, after the grid cell and the flow box.
    A diagram carries orientation labels beside its numbered ones -- "Thread
    guide" and "Bobbin" sit on the sewing machine so the student knows which
    way up it is -- and nothing stops one of them being the very word another
    gap is keyed to.
    """
    print(f"  layout={visual.get('layout')!r}")
    for line in diagram_texts(visual):
        print(f"    {line}")
    hits = self_answering_labels(visual, answer_key)
    if hits:
        for gap, answer, where in hits:
            print(f"  SELF-ANSWERING  Q{gap} = {answer!r} printed in {where!r}")
    else:
        print("  no keyed answer is printed on the figure")
    return hits


def audit_flow(visual: dict, answer_key: dict) -> list[tuple[str, str, int]]:
    """A box printing another box's answer — the flow chart's version of the
    self-answering grid cell. Returns the (gap, answer, box number) triples.

    Not refused by `flow_error` on purpose: the grid figure had the identical
    failure and a hard check would have made that path ungeneratable — three
    hosted samples self-answered three times out of three — so the guard there
    is a repair. Whether a chart needs the same is a live measurement, and this
    is where it is taken.
    """
    for i, step in enumerate(flow_steps(visual), start=1):
        print(f"    {i:>2}. {step}")
    out = self_answering_steps(visual, answer_key)
    if out:
        for gap, answer, box in out:
            print(f"  SELF-ANSWERING  gap {gap} = {answer!r} printed in box {box}")
    else:
        print("  no keyed answer is printed in another box")
    return out


if __name__ == "__main__":
    sys.exit(main())

"""Audit the reading passage `_diag_plan_live.py reading` just wrote.

That harness only reports `reading_has_visual` — it does not check the thing
`84c426c` fixes (the answers being words the passage never used), nor the one
still-open defect (the grid printing the very label it asks the student to
supply). Both are read off the saved JSON here, so no second hosted call is
paid for.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
    missing = _non_verbatim_answers(result)
    gapfill = [q for q in questions if qtype(q) in GAP_FILL_TYPES]
    print(f"gap-fill questions={len(gapfill)}  non-verbatim answers={len(missing)}"
          f"  (validator refuses at >=2)")
    for number, answer in missing:
        print(f"  MISSING  Q{number} = {answer!r}")
    if not missing:
        print("  every gap-fill answer appears in the passage")

    print("\n--- open issue: does the grid print the answer it asks for? ---")
    if not isinstance(visual, dict):
        print("  no visual on the set")
        return 1
    print(f"  kind={visual.get('kind')!r} title={visual.get('title')!r}")
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


if __name__ == "__main__":
    sys.exit(main())

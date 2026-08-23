"""Global question renumbering, shared by both sections' full tests.

A part or passage is generated with local numbers starting at 1. In a full test
the second one has to continue where the first stopped, and the answer key,
the per-answer metadata and any `__n__` table cell have to move with it — miss
one and the set marks a student against the wrong question.

Listening's parts are a fixed ten, so its offsets are known up front. Reading's
are not: the corpus writes 8 questions at the mode but ranges 6-15, so a
reading full test has to accumulate the offset from what each passage actually
returned.
"""

import re

# A table cell the student writes into, as the trainers emit it.
BLANK_RE = re.compile(r"^__(\d+)__$")

# A diagram question names the gap it points at ("Label 6 on the diagram: ..."),
# which is the wording prompts.py prescribes. The number in that phrase has to
# move with the question for the same reason the `__n__` cell does.
LABEL_RE = re.compile(r"(?i)\b(label\s+)(\d+)\b")


def _relabel(text: str, old: str, new: str) -> str:
    """Point a diagram question's "Label N" at its new number.

    Only the question's OWN old number is rewritten -- a passage about the 3
    stages of something must not have its prose renumbered too.
    """
    return LABEL_RE.sub(
        lambda m: f"{m.group(1)}{new}" if m.group(2) == old else m.group(0), text
    )


def renumber(result: dict, offset: int) -> dict:
    """Shift one part's questions to global numbering, in place.

    Questions are renumbered positionally rather than by the number they carry,
    which is deliberate: the model mislabels them often enough that trusting
    its numbering would reintroduce the hole this exists to close.
    """
    questions = result.get("questions") or []
    answer_key = result.get("answer_key") or {}
    mapping: dict[str, str] = {}
    new_questions = []
    for i, q in enumerate(questions):
        if not isinstance(q, dict):
            continue
        new_number = offset + i + 1
        old_number = str(q.get("number"))
        mapping[old_number] = str(new_number)
        moved = {**q, "number": new_number}
        if isinstance(q.get("question"), str):
            moved["question"] = _relabel(
                q["question"], old_number, str(new_number)
            )
        new_questions.append(moved)
    result["questions"] = new_questions
    result["answer_key"] = {
        mapping.get(str(k), str(k)): v for k, v in answer_key.items()
    }

    # Keep the answer-number-keyed metadata dicts aligned with the renumbering.
    for meta_key in ("accepted_variants", "answer_positions"):
        meta = result.get(meta_key)
        if isinstance(meta, dict):
            result[meta_key] = {
                mapping.get(str(k), str(k)): v for k, v in meta.items()
            }

    visual = result.get("visual")
    if isinstance(visual, dict):
        if visual.get("chart_type") == "table":
            for row in visual.get("series") or []:
                if not isinstance(row, dict):
                    continue
                for cell in row.get("data") or []:
                    if isinstance(cell, list) and len(cell) >= 2:
                        m = BLANK_RE.match(str(cell[1]))
                        if m:
                            old_n = m.group(1)
                            cell[1] = f"__{mapping.get(old_n, old_n)}__"

        # A reading diagram is a `plan`, whose gaps live in grid cells rather
        # than table series. The renderer prints the bare number ("1 ......"),
        # so a grid left behind shows a student sitting question 14 a gap
        # labelled 1. Only a full test renumbers, which is why a single
        # passage -- where the two numberings coincide -- never showed it.
        for row in visual.get("grid") or []:
            if not isinstance(row, list):
                continue
            for i, cell in enumerate(row):
                m = BLANK_RE.match(str(cell))
                if m:
                    old_n = m.group(1)
                    row[i] = f"__{mapping.get(old_n, old_n)}__"
    return result

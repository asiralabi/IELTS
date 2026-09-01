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

# The mid-sentence gap a flow chart puts in a step. Imported rather than
# restated so the renumbering and the validator can never disagree about what
# counts as a gap.
from app.agents._diagram import renumber_diagram
from app.agents._flow import FLOW_GAP_RE
from app.agents._notes import renumber_notes

# A table cell the student writes into, as the trainers emit it.
BLANK_RE = re.compile(r"^__(\d+)__$")

# A diagram question names the gap it points at ("Label 6 on the diagram: ..."),
# which is the wording prompts.py prescribes. The number in that phrase has to
# move with the question for the same reason the `__n__` cell does.
LABEL_RE = re.compile(r"(?i)\b(label\s+)(\d+)\b")


def _move_gaps(text: str, mapping: dict[str, str]) -> str:
    """Move every `__n__` in one string to its question's new number.

    A single pass off the mapping, so a chain like 1->2, 2->3 cannot renumber
    the same gap twice — the reason `renumber_diagram` is written this way too.
    """
    return FLOW_GAP_RE.sub(
        lambda m: f"__{mapping.get(m.group(1), m.group(1))}__", text
    )


def _relabel(text: str, old: str, new: str) -> str:
    """Point a diagram question's "Label N" at its new number.

    Only the question's OWN old number is rewritten -- a passage about the 3
    stages of something must not have its prose renumbered too.
    """
    return LABEL_RE.sub(
        lambda m: f"{m.group(1)}{new}" if m.group(2) == old else m.group(0), text
    )


# Question numbers appear inside the validators' own complaints, so a
# before/after comparison has to mask them: the same objection about a
# different number is the same objection.
_DIGITS = re.compile(r"\d+")


def renumber_checked(result: dict, offset: int, validate) -> dict:
    """Renumber, and refuse a set the renumbering itself broke.

    A part is validated where it is generated and renumbered somewhere else, so
    until now nothing checked the result of the move. That is exactly how a
    `plan` grid left at local numbering reached a live paper: every passage had
    passed at full strictness, and the only step after that gate was the one
    that broke them. Re-running the section's own validator afterwards closes
    the whole class, not just the grid.

    Differential on purpose. The baseline is taken immediately before the move,
    so a complaint the set already carried is never blamed on renumbering and
    a paper is never discarded for a reason that predates it.
    """
    before = validate(result)
    renumber(result, offset)
    after = validate(result)
    if after and _DIGITS.sub("#", after) != _DIGITS.sub("#", before or ""):
        raise ValueError(
            f"renumbering to offset {offset} broke this set: {after}"
        )
    return result


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
                        # Substituted in place, not matched from the start.
                        # The exam puts the blank INSIDE a phrase — Cambridge
                        # 19 Test 2 prints "using an app or by 7 .........." —
                        # and an anchored match skips every such cell, so a
                        # full test would move the question to global numbering
                        # and leave the cell showing its local one. That is the
                        # bug `b089b4a` fixed for the diagram, one figure over.
                        cell[1] = _move_gaps(str(cell[1]), mapping)

        # A reading diagram is a `plan`, whose gaps live in grid cells rather
        # than table series. The renderer prints the bare number ("1 ......"),
        # so a grid left behind shows a student sitting question 14 a gap
        # labelled 1. Only a full test renumbers, which is why a single
        # passage -- where the two numberings coincide -- never showed it.
        for row in visual.get("grid") or []:
            if not isinstance(row, list):
                continue
            for i, cell in enumerate(row):
                if BLANK_RE.match(str(cell)) or FLOW_GAP_RE.search(str(cell)):
                    row[i] = _move_gaps(str(cell), mapping)

        # A flow chart's gaps sit inside a sentence rather than owning a whole
        # cell, so they are substituted in place instead of matched from the
        # start. Same failure if missed as the grid had: the chain would number
        # its boxes 1, 2, 3 beside questions 14, 15, 16.
        steps = visual.get("steps")
        if isinstance(steps, list):
            visual["steps"] = [
                FLOW_GAP_RE.sub(
                    lambda m: f"__{mapping.get(m.group(1), m.group(1))}__",
                    str(step),
                )
                if isinstance(step, str) else step
                for step in steps
            ]

        # The drawn diagram carries its gaps in two places -- a part's printed
        # name and a callout's text -- and both move. Same failure class as the
        # grid's: a leader line pointing at "1 ........" beside question 14.
        renumber_diagram(visual, mapping)

        # And the printed notes/summary block, whose gaps sit inside its lines.
        # Same failure class as every other figure's: a block numbering its
        # gaps 1, 2, 3 beside questions 14, 15, 16.
        renumber_notes(visual, mapping)
    return result

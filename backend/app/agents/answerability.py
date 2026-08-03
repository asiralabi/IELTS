"""Shared answerability checks for generated practice sets.

Both trainers pass these through `complete_json(validate=...)`, and
`tools/build_dataset.py` reuses the same trainer validators when exporting, so
a set that reaches a student and a set that becomes a training target are held
to one standard.
"""

import json
import re

def canon(name: str) -> str:
    """Canonical key for a question type.

    The system prompts declare snake_case but the teacher also emits display
    forms like "True/False/Not Given", so anything short of stripping every
    non-alphanumeric leaves those unmatched — and an unmatched type silently
    skips the checks written for it.
    """
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


def qtype(q: dict) -> str:
    return canon(q.get("type"))


# Completion types the teacher writes as a printed block ("complete the notes
# below"). Nothing in the frontend renders such a block — `question-list.tsx`
# shows only question text plus options — so the context has to be inline.
STRUCTURE_TYPES = {canon(t) for t in (
    "summary_completion",
    "note_completion",
    "flow_chart_completion",
    "table_completion",
    "form_completion",
)}

# A gap the student writes into: underscores, or the dotted leader a real exam
# paper prints. Three dots are an ellipsis, so a leader needs four.
_GAP_MARKER = re.compile(r"__+|\.{4,}")


def visual_slots(visual: object) -> set[str]:
    """Question numbers the `visual` object supplies a fillable cell for."""
    if not visual:
        return set()
    return set(re.findall(r"__(\d+)__", json.dumps(visual, ensure_ascii=False)))


def is_self_contained(text: str) -> bool:
    """True if the item can be answered without the printed block it names.

    Either it shows its own gap, or it is a direct question ("What did the
    Greeks add to the alphabet?") — mistyped as a completion type, but the
    student can still answer it from the passage or script alone.
    """
    return bool(_GAP_MARKER.search(text)) or text.rstrip().endswith("?")


def dangling_structure_error(questions: list, visual: object, source: str) -> str | None:
    """Reject a completion item that points at a block the student never sees."""
    slots = visual_slots(visual)
    for q in questions:
        if not isinstance(q, dict) or qtype(q) not in STRUCTURE_TYPES:
            continue
        if q.get("options") or str(q.get("number")) in slots:
            continue
        if is_self_contained(str(q.get("question") or "")):
            continue
        return (
            f"question {q.get('number')} ({q.get('type')}) points at a summary/note/"
            "table/flow chart that the student never sees — nothing renders one. "
            "Rewrite it to carry its own context with the gap shown as ______, "
            f"e.g. \"NO MORE THAN TWO WORDS. {source}\". Or emit a `visual` table "
            f"with a matching __{q.get('number')}__ cell."
        )
    return None

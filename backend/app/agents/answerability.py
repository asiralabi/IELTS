"""Shared answerability checks for generated practice sets.

Both trainers pass these through `complete_json(validate=...)`, so a set that
reaches a student is held to this standard.

Export is aligned with generation: `build_dataset._is_answerable` runs each
section's own validator, so a set the runtime would have retried never becomes
a training target either. Listening ran on a weaker inline check until the
multi-task retrain, because the shipped single-task checkpoint had been trained
against what that looser filter produced and tightening it mid-life would have
desynced the committed jsonl from the model.
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

# Labelling types the figure DEFINES rather than merely illustrates. A
# completion item can inline its own gap and survive without the block it
# names; these cannot, because the answer is a position on the drawing.
MAP_TYPES = {canon(t) for t in ("map_labelling", "plan_labelling")}

# A gap the student writes into: underscores, or the dotted leader a real exam
# paper prints. Three dots are an ellipsis, so a leader needs four.
_GAP_MARKER = re.compile(r"__+|\.{4,}")


_WORD_TO_INT = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


def parse_word_limit(value: object) -> int | None:
    """Integer word cap from a `word_limit` field.

    Both contracts declare it an int, but the teacher often answers with the
    rubric sentence instead ('NO MORE THAN TWO WORDS AND/OR A NUMBER'). A bare
    int() on that raises, and the caller that swallows the error then skips the
    cap check entirely — so read the phrasing rather than trusting the type.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().lower()
    if not text:
        return None
    digits = re.search(r"\d+", text)
    if digits:
        return int(digits.group())
    for word, n in _WORD_TO_INT.items():
        if re.search(rf"\b{word}\b", text):
            return n
    return None


# Top-level keys that belong to exactly one section's contract. A multi-task
# fine-tune is trained on both schemas from one adapter, so the failure to
# catch is a Reading set that grows an `audio_script` — or a Listening set that
# answers with a `passage`. Either is unservable: the wrong page renders it.
_SECTION_KEYS = {
    "reading": {"passage"},
    "listening": {
        "blueprint", "audio_script", "speakers",
        "accepted_variants", "answer_positions",
    },
}


def cross_section_error(result: dict, section: str) -> str | None:
    """Reject a set that answers in the other section's schema."""
    foreign = sorted(
        key
        for other, keys in _SECTION_KEYS.items()
        if other != section
        for key in keys
        if result.get(key)
    )
    if foreign:
        return (
            f"this is an IELTS {section.title()} set but it carries "
            f"{', '.join(foreign)} — those belong to a different section's "
            f"contract. Return only the keys the {section.title()} schema "
            "declares."
        )
    # Reading has no map renderer; only Listening's map_labelling uses one.
    if section == "reading":
        visual = result.get("visual")
        if isinstance(visual, dict) and str(visual.get("kind", "")).lower() == "map":
            return (
                "`visual` is a map, which the Reading page cannot render. A "
                "Reading visual must be a table object or null."
            )
    return None


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


def missing_map_error(questions: list, visual: object) -> str | None:
    """Reject map/plan labelling with no map to label.

    `dangling_structure_error` lets a question off if it ends in '?', which is
    right for a completion item mistyped as one but wrong here: "What is the
    location marked as point C?" is circular without the drawing, and the
    corpus keys it 'C'. So there is no escape hatch.
    """
    if isinstance(visual, dict) and str(visual.get("kind", "")).lower() == "map":
        return None
    numbers = [str(q.get("number")) for q in questions
               if isinstance(q, dict) and qtype(q) in MAP_TYPES]
    if not numbers:
        return None
    return (
        f"question(s) {', '.join(numbers)} ask the student to label a map or "
        "plan, but `visual` carries no map — there is nothing to read a "
        "position off, so they cannot be answered. Emit a map `visual` whose "
        "lettered features are the ones the questions ask about, or use a "
        "question type that needs no drawing."
    )


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

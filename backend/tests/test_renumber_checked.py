"""Renumbering is the one step a set takes after its validation gate.

Every passage passes `validate_practice` at full strictness inside
`create_practice`, and every listening part passes `_validate_full_test_part`
inside `create_part` — and then a full test renumbers them, unchecked. That is
how a `plan` grid left at local numbering reached a live paper on 2026-08-23:
the validator that would have caught it never ran again.

The guard is differential so a set is never discarded for a complaint it
already carried before the move.
"""

import pytest

from app.agents._numbering import renumber_checked
from app.agents.reading_trainer import validate_practice


def _set():
    return {
        "questions": [
            {"number": 1, "type": "true_false_notgiven", "question": "A claim."},
            {"number": 2, "type": "true_false_notgiven", "question": "Another."},
        ],
        "answer_key": {"1": "TRUE", "2": "FALSE"},
    }


def test_a_clean_renumbering_passes_through():
    result = renumber_checked(_set(), 13, lambda r: None)

    assert [q["number"] for q in result["questions"]] == [14, 15]
    assert sorted(result["answer_key"]) == ["14", "15"]


def test_a_set_the_move_broke_is_refused():
    """The whole point: a complaint that appears only after renumbering."""
    seen = []

    def validate(r):
        seen.append(r["questions"][0]["number"])
        return "the figure points at a question that does not exist" \
            if len(seen) > 1 else None

    with pytest.raises(ValueError, match="renumbering to offset 13 broke this set"):
        renumber_checked(_set(), 13, validate)


def test_a_complaint_the_set_already_had_is_not_blamed_on_the_move():
    """A pre-existing objection must not cost a 25-minute paper. This is the
    case that decides whether the guard is safe to ship at all."""
    result = renumber_checked(
        _set(), 13, lambda r: "all 2 answers are 'TRUE'; a real block mixes them"
    )

    assert [q["number"] for q in result["questions"]] == [14, 15]


def test_the_same_complaint_about_a_moved_number_is_the_same_complaint():
    """Validators name the offending question, and that number is exactly what
    just changed. Compared raw, every numbered complaint would look new."""
    def validate(r):
        return f"question {r['questions'][0]['number']} has empty question text"

    result = renumber_checked(_set(), 13, validate)

    assert result["questions"][0]["number"] == 14


def test_a_different_complaint_after_the_move_is_still_caught():
    """Masking the digits must not mask a genuinely different objection."""
    calls = []

    def validate(r):
        calls.append(1)
        return ("question 1 has empty question text" if len(calls) == 1
                else "question 14 points at a structure the student never sees")

    with pytest.raises(ValueError, match="broke this set"):
        renumber_checked(_set(), 13, validate)


def test_the_real_validator_accepts_a_real_renumbering():
    """Wired against validate_practice itself, not a stand-in."""
    practice = {
        "title": "Hives",
        "passage": (
            "The hive is built around a set of brood cells where the queen "
            "lays her eggs. Above them the workers draw out the honeycomb, "
            "the wax lattice in which food is stored. Air moves through a "
            "ventilation shaft that the workers keep clear. " * 40
        ),
        "questions": [
            {"number": 1, "type": "diagram_label_completion", "word_limit": 2,
             "question": "NO MORE THAN TWO WORDS. Label 1 on the diagram: "
                         "where the queen lays her eggs."},
            {"number": 2, "type": "diagram_label_completion", "word_limit": 2,
             "question": "NO MORE THAN TWO WORDS. Label 2 on the diagram: "
                         "the wax lattice that stores food."},
            {"number": 3, "type": "diagram_label_completion", "word_limit": 2,
             "question": "NO MORE THAN TWO WORDS. Label 3 on the diagram: "
                         "what the workers keep clear."},
        ],
        "answer_key": {"1": "brood cells", "2": "honeycomb",
                       "3": "ventilation shaft"},
        "visual": {"kind": "plan", "title": "Hive",
                   "grid": [["__1__", ""], ["__2__", ""], ["__3__", ""]]},
    }
    assert validate_practice(practice, judge_headings=False) is None

    result = renumber_checked(practice, 13, validate_practice)

    assert [q["number"] for q in result["questions"]] == [14, 15, 16]
    assert result["visual"]["grid"] == [["__14__", ""], ["__15__", ""],
                                        ["__16__", ""]]
    assert validate_practice(result, judge_headings=False) is None


def test_it_catches_the_bug_that_shipped(monkeypatch):
    """The regression this exists for. Renumbering as it behaved before
    `b089b4a` -- questions and key moved, `plan` grid left behind -- must be
    refused rather than shipped, which is what happened on 2026-08-23.
    """
    import app.agents._numbering as numbering

    def renumber_without_the_grid(result, offset):
        """The pre-b089b4a behaviour, reduced to what matters here."""
        mapping = {}
        moved = []
        for i, q in enumerate(result.get("questions") or []):
            mapping[str(q.get("number"))] = str(offset + i + 1)
            moved.append({**q, "number": offset + i + 1})
        result["questions"] = moved
        result["answer_key"] = {mapping.get(str(k), str(k)): v
                                for k, v in (result.get("answer_key") or {}).items()}
        return result

    monkeypatch.setattr(numbering, "renumber", renumber_without_the_grid)

    practice = {
        "title": "Hives",
        "passage": ("The hive is built around a set of brood cells where the "
                    "queen lays her eggs. Above them the workers draw out the "
                    "honeycomb, the wax lattice in which food is stored. Air "
                    "moves through a ventilation shaft they keep clear. " * 40),
        "questions": [
            {"number": 1, "type": "diagram_label_completion", "word_limit": 2,
             "question": "NO MORE THAN TWO WORDS. Label 1 on the diagram: "
                         "where the queen lays her eggs."},
            {"number": 2, "type": "diagram_label_completion", "word_limit": 2,
             "question": "NO MORE THAN TWO WORDS. Label 2 on the diagram: "
                         "the wax lattice that stores food."},
            {"number": 3, "type": "diagram_label_completion", "word_limit": 2,
             "question": "NO MORE THAN TWO WORDS. Label 3 on the diagram: "
                         "what the workers keep clear."},
        ],
        "answer_key": {"1": "brood cells", "2": "honeycomb",
                       "3": "ventilation shaft"},
        "visual": {"kind": "plan", "title": "Hive",
                   "grid": [["__1__", ""], ["__2__", ""], ["__3__", ""]]},
    }
    # It is valid before the move -- which is exactly why nothing caught it.
    assert validate_practice(practice, judge_headings=False) is None

    with pytest.raises(ValueError, match="broke this set"):
        renumber_checked(practice, 13, validate_practice)

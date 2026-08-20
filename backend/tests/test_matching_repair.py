"""A matching block written as one question is unpacked, not regenerated.

The teacher writes the whole block as a single item and keys the entire mapping
against it — "Emma: Introduction, Jack: Data analysis, Sarah: Drafting" — which
the student, who has one box, can never be marked on. 58 of the 89 matching
questions in the listening corpus read that way, and 43 of the 66 units
carrying a block have exactly one question in it, so it is the shape rather
than an accident.

The pairing is sound; only the packing is wrong, and unpacking it needs no
model call. These tests are about which pair each question keeps and what it is
then offered to choose between.
"""

import pytest

from app.agents.answerability import unmarkable_matching_error
from app.agents.listening_trainer import (
    _matching_pairs,
    _repair_compound_matching,
    validate_part,
)

MAPPING = ("Emma: Introduction and literature review, Jack: Data analysis, "
           "Sarah: Drafting the report")

RUBRIC = "Match each student with their task."


def _set(numbers, answer, options=None):
    """A block of matching questions all keyed with the same answer string."""
    return {
        "questions": [
            {"number": n, "type": "matching", "question": RUBRIC,
             **({"options": list(options)} if options else {})}
            for n in numbers
        ],
        "answer_key": {str(n): answer for n in numbers},
    }


def test_a_value_carrying_a_comma_stays_in_one_piece():
    """Splitting on every comma would tear "Interviews with local residents,
    Analysis of imagery" into two pairs, one of them with no left-hand side."""
    pairs = _matching_pairs(
        "Eastbourne - Field observations, Brighton - Interviews with locals, "
        "some of them elderly, Hastings - Analysis of imagery"
    )

    assert pairs == [
        ("Eastbourne", "Field observations"),
        ("Brighton", "Interviews with locals, some of them elderly"),
        ("Hastings", "Analysis of imagery"),
    ]


def test_a_value_of_its_own_colon_keeps_it():
    """"Route A: $10 million" splits at the first separator, not the last."""
    assert _matching_pairs("Route A: $10 million, Route B: $8 million") == [
        ("Route A", "$10 million"),
        ("Route B", "$8 million"),
    ]


def test_one_question_holding_a_whole_block_keeps_one_pair():
    """The live shape. The other right-hand sides become what it chooses
    between, which is what a real paper prints."""
    result = _set([24], MAPPING)

    _repair_compound_matching(result)

    q = result["questions"][0]
    assert q["question"] == f"{RUBRIC} Emma"
    assert q["options"] == [
        "Introduction and literature review", "Data analysis", "Drafting the report",
    ]
    assert result["answer_key"]["24"] == "Introduction and literature review"


def test_a_block_of_two_takes_a_pair_each():
    """Both were keyed with the same mapping, so both would otherwise ask the
    same thing and mark the same way."""
    result = _set([24, 25], MAPPING)

    _repair_compound_matching(result)

    asked = [q["question"] for q in result["questions"]]
    assert asked == [f"{RUBRIC} Emma", f"{RUBRIC} Jack"]
    assert list(result["answer_key"].values()) == [
        "Introduction and literature review", "Data analysis",
    ]


def test_options_naming_the_speakers_turn_the_question_round():
    """"Which speaker said this" is a real matching shape: the printed list is
    the left column, so the answer has to stay inside it."""
    result = _set(
        [24], "SPEAKER A: Multimedia, SPEAKER B: Handouts",
        options=["SPEAKER A", "SPEAKER B", "SPEAKER C"],
    )

    _repair_compound_matching(result)

    q = result["questions"][0]
    assert q["question"] == f"{RUBRIC} Multimedia"
    assert q["options"] == ["SPEAKER A", "SPEAKER B", "SPEAKER C"]
    assert result["answer_key"]["24"] == "SPEAKER A"


def test_a_block_with_fewer_pairs_than_questions_is_left_alone():
    """Handing two questions one pair would key one of them to nothing. The
    caller re-validates, so it fails loudly instead."""
    result = _set([24, 25], "Emma: Introduction")
    before = [q["question"] for q in result["questions"]]

    _repair_compound_matching(result)

    assert [q["question"] for q in result["questions"]] == before


def test_the_variants_written_against_the_old_answer_are_dropped():
    """They describe a mapping that no longer exists, and marking accepts
    them — so a student writing the whole mapping would still be right."""
    result = _set([24], MAPPING)
    result["accepted_variants"] = {"24": ["Emma: Introduction, Jack: Data analysis"]}

    _repair_compound_matching(result)

    assert result["accepted_variants"] == {}


def test_an_unrepaired_mapping_fails_validation():
    """What is left after the repair is an item whose correct choice was never
    offered — 7 of the 89 corpus questions — and no code can guess which it
    was meant to be."""
    problem = unmarkable_matching_error(
        [{"number": 24, "type": "matching", "question": RUBRIC,
          "options": ["Emma - Introduction", "Jack - Conclusion"]}],
        {"24": "Sarah - Drafting"},
    )

    assert "not one of its options" in problem


@pytest.mark.parametrize("judge_matching", [True, False])
def test_the_check_is_skipped_on_the_way_in(judge_matching):
    """The set is let in and repaired afterwards, so complaining about the
    packing during generation would spend a retry on something already about to
    be fixed — the same bargain judge_structure makes."""
    result = _set([1, 2], MAPPING)
    result["questions"].append(
        {"number": 3, "type": "short_answer", "question": "Who chairs the group?"})
    result["answer_key"]["3"] = "Emma"

    problem = validate_part(result, judge_matching=judge_matching)

    assert (problem is not None) is judge_matching

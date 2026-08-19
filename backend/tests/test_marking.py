"""The runtime evaluator prompt must stay identical to what the checkpoints saw.

A fine-tuned evaluator fed a shape it was never trained on degrades quietly
instead of erroring, so this is the only thing that would catch the drift.
"""

import functools
import importlib.util
import sys
from pathlib import Path

import pytest

from app.agents._marking import (
    band_from_40,
    evaluator_user_turn,
    mark_answers,
    resolve_choice,
    speaking_band,
    writing_band,
)
from app.agents.listening_trainer import _LISTENING_BAND_TABLE
from app.agents.reading_trainer import _READING_BAND_TABLE
from app.llm.prompts import EVALUATOR_SYSTEM, READING_EVALUATOR_SYSTEM

BACKEND = Path(__file__).resolve().parents[1]

QUESTION = {
    "number": 3,
    "question": "Where is the induction meeting held?",
    "type": "short_answer",
}
OFFICIAL = "main hall"
VARIANTS = ["the main hall"]


@functools.cache
def _build_dataset():
    spec = importlib.util.spec_from_file_location(
        "build_dataset", BACKEND / "tools" / "build_dataset.py"
    )
    module = importlib.util.module_from_spec(spec)
    # `SectionSpec` is a dataclass under `from __future__ import annotations`,
    # so dataclasses resolves its annotations via sys.modules at class-creation
    # time. Registering before exec is what makes the import work at all.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "section, system",
    [("reading", READING_EVALUATOR_SYSTEM), ("listening", EVALUATOR_SYSTEM)],
    ids=["reading", "listening"],
)
def test_runtime_user_turn_matches_training_record(section, system):
    build_dataset = _build_dataset()
    spec = build_dataset.SECTIONS[section]
    assert spec.evaluator_system is system

    records = build_dataset._evaluator_records(
        {
            "questions": [QUESTION],
            "answer_key": {"3": OFFICIAL},
            "accepted_variants": {"3": VARIANTS},
        },
        spec,
    )
    assert records, "expected the exporter to emit evaluator records"

    trained = records[0]["messages"]
    assert trained[0]["content"] == system
    assert evaluator_user_turn("3", QUESTION, OFFICIAL, VARIANTS, OFFICIAL) == (
        trained[1]["content"]
    )


def test_blank_and_missing_variants_use_the_trained_sentinels():
    turn = evaluator_user_turn("3", QUESTION, OFFICIAL, [], "")
    assert "Accepted Variants: none" in turn
    assert turn.endswith("Student Answer: (blank)")


def test_missing_question_text_falls_back_to_the_number():
    assert evaluator_user_turn("7", {}, OFFICIAL, [], "x").startswith("Question: Question 7\n")


CHOICE_Q = {
    "number": 1,
    "type": "multiple_choice",
    "question": "What is the name of the restaurant?",
    "options": ["Subway", "Coffee shop", "University Restaurant"],
}


async def _mark(official, student):
    """Mark one multiple_choice answer.

    A correct click must be settled by the clerical pre-pass, never handed to
    the evaluator: on CPU that costs seconds per answer, and the evaluator is
    given no options to resolve a letter with.
    """
    return await mark_answers(
        {"questions": [CHOICE_Q], "answer_key": {"1": official}},
        {"1": student},
        EVALUATOR_SYSTEM,
        _LISTENING_BAND_TABLE,
    )


@pytest.mark.parametrize(
    "official, student",
    [
        # The listening convention: key names the option text, student clicks C.
        ("University Restaurant", "C"),
        # The reading convention: key names the letter.
        ("C", "C"),
        # Both letters, and a key that spells out what the student clicked.
        ("C", "University Restaurant"),
    ],
    ids=["text-keyed", "letter-keyed", "inverted"],
)
async def test_correct_choice_is_marked_correct_under_either_convention(official, student):
    """The frontend sends the option letter, so a text-keyed answer never
    matched: 829 of 845 listening multiple_choice questions are text-keyed, and
    the evaluator's trained user turn carries no options to resolve it with."""
    result = await _mark(official, student)
    assert result["score"] == 1
    row = result["results"][0]
    assert row["correct"] is True
    # Settled clerically rather than sent to the evaluator.
    assert row["explanation"] == "Matches the official answer under IELTS marking."
    # The student is shown the option, never the bare letter.
    assert row["correct_answer"] == "University Restaurant"


async def test_wrong_choice_is_still_wrong():
    result = await _mark("University Restaurant", "A")
    assert result["score"] == 0
    assert result["results"][0]["student_answer"] == "Subway"


async def test_a_distractor_listed_as_a_variant_does_not_mark_a_wrong_click_correct():
    """The teacher fills accepted_variants with the other options on 9 corpus
    questions. Resolving the student's letter to option text would make those
    match, so a listed question ignores variants entirely — its answer space is
    closed, and the frontend renders it as buttons."""
    result = await mark_answers(
        {
            "questions": [CHOICE_Q],
            "answer_key": {"1": "University Restaurant"},
            "accepted_variants": {"1": ["Subway"]},
        },
        {"1": "A"},
        EVALUATOR_SYSTEM,
        _LISTENING_BAND_TABLE,
    )
    assert result["score"] == 0


def test_resolve_choice_leaves_non_choice_answers_alone():
    """Gap-fill answers have no options, and a single letter is a real answer
    for map_labelling — which carries no options array either."""
    assert resolve_choice({}, "B") == "B"
    assert resolve_choice({"options": []}, "B") == "B"
    assert resolve_choice(CHOICE_Q, "Subway") == "Subway"
    # Out of range: three options, so D denotes nothing.
    assert resolve_choice(CHOICE_Q, "D") == "D"


def test_reading_is_marked_harder_than_listening_at_the_same_raw_score():
    # 32/40 is Reading 7.0 but Listening 7.5 — a shared table would hide this.
    assert band_from_40(32, 40, _READING_BAND_TABLE) == 7.0
    assert band_from_40(32, 40, _LISTENING_BAND_TABLE) == 7.5
    assert band_from_40(0, 0, _READING_BAND_TABLE) == 0.0
    # Short sets scale to the 40-question table rather than being marked raw.
    assert band_from_40(13, 14, _READING_BAND_TABLE) == 8.5


def test_writing_weights_task_two_double():
    # An unweighted mean would call this 7.0 and hand the student half a band
    # they did not earn — Task 2 is worth twice Task 1 in the official scheme.
    assert writing_band(8.0, 6.0) == 6.5
    assert writing_band(6.0, 8.0) == 7.5
    # One task attempted is banded on that task, not averaged against a blank.
    assert writing_band(None, 6.5) == 6.5
    assert writing_band(6.5, None) == 6.5
    assert writing_band(None, None) is None


def test_speaking_averages_its_parts_unweighted():
    assert speaking_band([6.0, 7.0, 7.0]) == 6.5
    assert speaking_band([5.0]) == 5.0
    assert speaking_band([]) is None

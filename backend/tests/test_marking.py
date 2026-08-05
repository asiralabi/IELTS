"""The runtime evaluator prompt must stay identical to what the checkpoints saw.

A fine-tuned evaluator fed a shape it was never trained on degrades quietly
instead of erroring, so this is the only thing that would catch the drift.
"""

import functools
import importlib.util
import sys
from pathlib import Path

import pytest

from app.agents._marking import band_from_40, evaluator_user_turn
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


def test_reading_is_marked_harder_than_listening_at_the_same_raw_score():
    # 32/40 is Reading 7.0 but Listening 7.5 — a shared table would hide this.
    assert band_from_40(32, 40, _READING_BAND_TABLE) == 7.0
    assert band_from_40(32, 40, _LISTENING_BAND_TABLE) == 7.5
    assert band_from_40(0, 0, _READING_BAND_TABLE) == 0.0
    # Short sets scale to the 40-question table rather than being marked raw.
    assert band_from_40(13, 14, _READING_BAND_TABLE) == 8.5

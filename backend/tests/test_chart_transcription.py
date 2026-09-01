"""A chart question the student can answer with the passage covered up.

A bar, line or pie chart prints every value it holds — unlike a table, whose
whole point is the cell it leaves blank. So it is fatally easy to ask "According
to the chart, the average daily water use for bathing is ______" and key it to
the number already drawn on the bar. That tests transcription, not reading, and
the figure has replaced the passage instead of supporting it.

Measured live 2026-08-28 over the figure gallery: one reading set wrote NINE of
these in a row, a listening set wrote six, a pie set wrote three, and every one
validated clean. The prompt now forbids it; this is the half that cannot be
skimmed.
"""

import pytest

from app.agents.answerability import chart_transcription_error


def _chart(chart_type="bar"):
    return {
        "kind": "chart",
        "chart_type": chart_type,
        "title": "Average daily household water use per person",
        "series": [
            {
                "name": "Litres",
                "data": [["Bathing", 58.0], ["Cooking", 12.5], ["Garden", 9.0]],
            }
        ],
    }


def _questions(*numbers):
    return [
        {"number": n, "type": "chart_completion",
         "question": f"According to the chart, the figure for item {n} is ______."}
        for n in numbers
    ]


def test_a_block_of_copied_numbers_is_refused():
    result = {
        "visual": _chart(),
        "questions": _questions(1, 2, 3),
        "answer_key": {"1": "58", "2": "12.5", "3": "9"},
    }
    problem = chart_transcription_error(result) or ""
    assert "copying a number the chart already prints" in problem
    assert "1, 2, 3" in problem


def test_one_reading_off_question_is_allowed():
    """The exam does set a single read-the-figure item; a block is the fault."""
    result = {
        "visual": _chart(),
        "questions": _questions(1, 2, 3),
        "answer_key": {"1": "58", "2": "rainfall", "3": "seasonal demand"},
    }
    assert chart_transcription_error(result) is None


def test_questions_needing_the_passage_pass():
    result = {
        "visual": _chart(),
        "questions": _questions(1, 2, 3),
        "answer_key": {
            "1": "metered supply",
            "2": "drought restrictions",
            "3": "leakage",
        },
    }
    assert chart_transcription_error(result) is None


@pytest.mark.parametrize("chart_type", ["bar", "line", "pie"])
def test_every_drawn_chart_is_judged(chart_type):
    result = {
        "visual": _chart(chart_type),
        "questions": _questions(1, 2, 3),
        "answer_key": {"1": "58", "2": "12.5", "3": "9"},
    }
    assert chart_transcription_error(result) is not None


def test_a_table_is_exempt():
    """Its answers are the cells it does NOT print — the opposite arrangement."""
    result = {
        "visual": _chart("table"),
        "questions": _questions(1, 2, 3),
        "answer_key": {"1": "58", "2": "12.5", "3": "9"},
    }
    assert chart_transcription_error(result) is None


def test_a_set_with_no_chart_is_untouched():
    assert chart_transcription_error({"visual": None, "questions": []}) is None
    assert chart_transcription_error(
        {"visual": {"kind": "diagram"}, "questions": []}
    ) is None


def test_a_number_written_differently_is_still_a_copy():
    """`span_tokens` folds the spelling, so "58" and "58.0" are one answer."""
    result = {
        "visual": _chart(),
        "questions": _questions(1, 2),
        "answer_key": {"1": "58.0", "2": "12.5"},
    }
    assert chart_transcription_error(result) is not None

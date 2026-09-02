"""Chart questions the student answers with the recording switched off.

🔬 `l_chart_r3`, 2026-09-02. A line chart of monthly museum visitors, nine
questions, seven of them proper — the reason for the July dip, the category
behind the August rise, the increase expected next year — and two that read
March and September straight off the line. `chart_transcription_error` refused
the part, the corrective retry came back with the same two, and a 521-word
script, its audio, the chart and seven working questions went in the bin.

The rule tolerates ONE such question, because reading a value off a figure is a
task the exam does set. So the surplus is deleted and the set keeps its seven.
"""

import json
from pathlib import Path

import pytest

from app.agents import listening_trainer as lt
from app.agents._figure_pass import drop_chart_transcriptions
from app.agents.answerability import chart_transcription_error, chart_transcriptions

_ARTIFACT = (
    Path(__file__).resolve().parents[1]
    / "tools" / "_gallery" / "l_chart_r3.REFUSED.json"
)


def _chart_set() -> dict:
    """The refused artifact's shape: real questions, plus two transcriptions."""
    return {
        "title": "Museum visitor numbers",
        "audio_script": "LECTURER: " + " ".join(["visitors"] * 700),
        "visual": {
            "kind": "chart",
            "chart_type": "line",
            "title": "Monthly visitor numbers 2023",
            "x_label": "Month",
            "y_label": "Visitors",
            "series": [
                {
                    "name": "Visitors",
                    "data": [
                        ["January", 120000], ["March", 150000],
                        ["July", 190000], ["September", 230000],
                        ["December", 300000],
                    ],
                }
            ],
        },
        # Seven questions the recording answers, then the two the chart does —
        # the artifact's own proportions, which matter: the repair stops where
        # a set stops being one.
        "questions": [
            {"number": 1, "type": "chart_completion", "options": None,
             "question": "ONE WORD. The reason given for the dip in July was ______."},
            {"number": 2, "type": "chart_completion", "options": None,
             "question": "NO MORE THAN THREE WORDS. The category behind the "
                         "August rise was ______."},
            {"number": 3, "type": "chart_completion", "options": None,
             "question": "ONE WORD. The busiest month was ______."},
            {"number": 4, "type": "chart_completion", "options": None,
             "question": "ONE WORD AND/OR A NUMBER. The total for the first "
                         "half of the year was ______."},
            {"number": 5, "type": "chart_completion", "options": None,
             "question": "ONE WORD AND/OR A NUMBER. The monthly average was ______."},
            {"number": 6, "type": "chart_completion", "options": None,
             "question": "ONE WORD. The exhibition that opened in October was "
                         "about ______."},
            {"number": 7, "type": "chart_completion", "options": None,
             "question": "ONE WORD AND/OR A NUMBER. The rise expected next "
                         "year is ______ per cent."},
            {"number": 8, "type": "chart_completion", "options": None,
             "question": "ONE WORD AND/OR A NUMBER. The number of visitors in "
                         "March was ______."},
            {"number": 9, "type": "chart_completion", "options": None,
             "question": "ONE WORD AND/OR A NUMBER. The number of visitors in "
                         "September was ______."},
        ],
        "answer_key": {"1": "heatwave", "2": "school groups", "3": "December",
                       "4": "960000", "5": "215000", "6": "textiles", "7": "5",
                       "8": "150000", "9": "230000"},
        "accepted_variants": {"1": ["heat wave"], "9": ["230,000"]},
        "answer_positions": {str(n): n / 10 for n in range(1, 10)},
    }


def test_both_transcriptions_are_seen():
    assert chart_transcriptions(_chart_set()) == ["8", "9"]
    assert "question(s) 8, 9" in (chart_transcription_error(_chart_set()) or "")


def test_the_surplus_goes_and_the_first_stays():
    """One reading-off question is a task the exam sets, and the rule says so
    by tolerating it. Deleting both would take a legal question with it."""
    r = _chart_set()
    assert drop_chart_transcriptions(r) == ["9"]
    assert chart_transcription_error(r) is None
    assert "March" in r["questions"][7]["question"]
    assert r["answer_key"]["8"] == "150000"
    assert all("September" not in q["question"] for q in r["questions"])


def test_the_set_is_renumbered_contiguously():
    r = _chart_set()
    # A question after the deleted one, so there is something to move up.
    r["questions"].append(
        {"number": 10, "type": "chart_completion", "options": None,
         "question": "ONE WORD. The month with the longest opening hours was "
                     "______."})
    r["answer_key"]["10"] = "August"
    drop_chart_transcriptions(r)
    assert [q["number"] for q in r["questions"]] == list(range(1, 10))
    # The question that followed the deletion moves up, and its answer moves
    # with it — the student is marked on what they were asked.
    assert r["questions"][8]["question"].endswith("hours was ______.")
    assert r["answer_key"]["9"] == "August"


def test_the_dropped_number_takes_its_metadata_with_it():
    """`renumber` maps the numbers that SURVIVE, so an entry left behind under
    a dropped number collides with whatever renumbers onto it — and listening
    marks against `accepted_variants`, so the collision marks the student."""
    r = _chart_set()
    r["questions"].append(
        {"number": 10, "type": "chart_completion", "options": None,
         "question": "ONE WORD. The month with the longest opening hours was "
                     "______."})
    r["answer_key"]["10"] = "August"
    r["accepted_variants"]["10"] = ["Aug"]
    r["answer_positions"]["10"] = 0.95
    drop_chart_transcriptions(r)
    # Gone, rather than left under a number the question that moved up carries.
    assert r["accepted_variants"] == {"1": ["heat wave"], "9": ["Aug"]}
    assert sorted(r["answer_positions"], key=int) == [
        str(n) for n in range(1, 10)
    ]


def test_a_set_with_one_reading_off_question_is_untouched():
    r = _chart_set()
    r["questions"] = r["questions"][:8]
    del r["answer_key"]["9"]
    assert chart_transcription_error(r) is None
    assert drop_chart_transcriptions(r) == []
    assert len(r["questions"]) == 8


def test_a_table_is_exempt():
    """A table's answers are the cells it does NOT print — the opposite
    arrangement, and the reason the two are different question types."""
    r = _chart_set()
    r["visual"]["chart_type"] = "table"
    assert chart_transcriptions(r) == []
    assert drop_chart_transcriptions(r) == []


def test_the_part_costs_no_retry_on_the_way_in():
    r = _chart_set()
    assert "answered by copying a number" in (lt.validate_part(r) or "")
    assert lt._judge_reply(r) is None
    assert lt.validate_part(r) is None


def test_the_full_test_path_regenerates_instead():
    """A full-test part needs exactly ten questions, so a deletion there trades
    one refusal for another. The hook that path uses does not run this."""
    r = _chart_set()
    assert "answered by copying a number" in (lt._judge_full_test_reply(r) or "")
    assert len(r["questions"]) == 9


@pytest.mark.skipif(not _ARTIFACT.exists(),
                    reason="the saved sweep artifact is local")
def test_the_saved_artifact_replays_clean():
    """The refusal this repair was written from, end to end.

    `tools/_*` is gitignored, so the artifact is here on the machine that swept
    and absent everywhere else. Skipped rather than dropped: replaying the real
    thing is what proved the fixture above is the same fault.
    """
    part = json.loads(_ARTIFACT.read_text(encoding="utf-8"))["set"]
    assert "answered by copying a number" in (lt.validate_part(part) or "")
    assert lt._judge_reply(part) is None
    assert [q["number"] for q in part["questions"]] == list(range(1, 9))


def test_a_set_that_is_mostly_transcription_is_left_to_the_retry():
    """🔬 Live on the first sweep after this repair was written: a chart part
    came back with SIX questions read off the figure, and the deletion would
    have shipped a four-question set. That is not this repair's fault to fix —
    the rule's own words are that a block of them is a figure standing in for
    the passage — so the complaint stands and the part is written again."""
    r = _chart_set()
    for q in r["questions"][2:7]:
        # Key each to a value the chart draws, which is what makes it one.
        r["answer_key"][str(q["number"])] = "190000"
    assert len(chart_transcriptions(r)) == 7
    assert drop_chart_transcriptions(r) == []
    assert len(r["questions"]) == 9
    assert "answered by copying a number" in (lt.validate_part(r) or "")

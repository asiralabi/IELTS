"""One gap printed twice: on the part, and again in the callout that names it.

🔬 `r_diagram_apparatus` and `r_diagram_crosssec`, 2026-09-06, in the first
sweep after `openai/gpt-oss-120b` was retired (410 Gone) and
`nvidia/nemotron-3-super-120b-a12b` replaced it. The new model numbers a figure
BOTH ways at once: the part `helmet` is named `__1__`, and a callout on it
reads "The __1__ protects the diver's head and face" — for every gap on the
drawing. `diagram_error` refuses that, because one question then has two boxes.

Four of the seven refusals in a 40-set sweep were this one shape, and the
corrective retry reproduced it: the model is not slipping, it believes this is
how the exam prints a figure. The rule is judged on the way IN, so the set died
before any repair in the pipeline had a turn — hence `_judge_reply`.

The callout is the copy kept. It carries the clause saying which part is
wanted; a bare `__1__` on a shape does not, and `diagram_error` separately
demands that a part whose own name is the answer be left unnamed.
"""

from app.agents._diagram import diagram_error, drop_doubled_gap_markers


def _diver() -> dict:
    """The refused artifact's figure, trimmed to what the repair reads."""
    return {
        "visual": {
            "kind": "diagram",
            "title": "A Victorian standard diving dress",
            "layout": "machine",
            "parts": [
                {"id": "helmet", "form": "oval", "name": "__1__"},
                {"id": "breastplate", "form": "chamber", "name": "__2__"},
                {"id": "exvalve", "form": "valve", "name": "exhaust valve"},
                {"id": "ground", "form": "ground", "name": None},
            ],
            "labels": [
                {"at": "helmet", "text": "The __1__ protects the diver's head "
                                         "and face."},
                {"at": "breastplate", "text": "The __2__ supports the helmet "
                                              "and houses the valves."},
            ],
        },
        "questions": [
            {"number": n, "type": "diagram_label_completion",
             "question": f"NO MORE THAN TWO WORDS. Label {n} on the diagram."}
            for n in (1, 2)
        ],
        "answer_key": {"1": "helmet", "2": "breastplate"},
    }


def _error(r: dict) -> str:
    return diagram_error(r["visual"], r["questions"], r["answer_key"],
                         after_repairs=False) or ""


def test_the_doubled_figure_is_refused_before_the_repair():
    assert "twice" in _error(_diver())


def test_the_bare_gap_on_the_part_goes_and_the_callout_stays():
    r = _diver()
    assert drop_doubled_gap_markers(r) == [("helmet", "1"), ("breastplate", "2")]
    assert _error(r) == ""
    parts = {p["id"]: p for p in r["visual"]["parts"]}
    assert parts["helmet"]["name"] is None
    assert parts["breastplate"]["name"] is None
    # The gap survives where the student can tell what is being asked.
    assert [lb["text"] for lb in r["visual"]["labels"]] == [
        "The __1__ protects the diver's head and face.",
        "The __2__ supports the helmet and houses the valves.",
    ]


def test_a_part_carrying_a_real_name_is_left_alone():
    """Only a name that is NOTHING BUT the gap is safe to delete.

    Stripping "The __3__ valve" would leave "The valve" printed beside the gap
    keyed to `valve` — trading a doubled gap for a self-answering figure.
    """
    r = _diver()
    r["visual"]["parts"].append(
        {"id": "inlet", "form": "valve", "name": "The __3__ valve"})
    r["visual"]["labels"].append(
        {"at": "inlet", "text": "Air enters through the __3__."})
    r["questions"].append({"number": 3, "type": "diagram_label_completion",
                           "question": "NO MORE THAN TWO WORDS. Label 3."})
    r["answer_key"]["3"] = "inlet valve"
    assert ("inlet", "3") not in drop_doubled_gap_markers(r)
    assert r["visual"]["parts"][-1]["name"] == "The __3__ valve"


def test_a_gap_on_two_parts_is_left_to_the_redraw():
    """Nothing here can say which shape the question meant."""
    r = _diver()
    r["visual"]["parts"][1]["name"] = "__1__"
    r["visual"]["labels"] = [r["visual"]["labels"][0]]
    assert drop_doubled_gap_markers(r) == []


def test_a_gap_the_callouts_do_not_carry_is_left_alone():
    """With no callout holding it, deleting the part's gap orphans the question."""
    r = _diver()
    r["visual"]["labels"] = []
    assert drop_doubled_gap_markers(r) == []
    assert r["visual"]["parts"][0]["name"] == "__1__"


def test_two_callouts_on_one_gap_belong_to_the_other_repair():
    """`merge_doubled_callouts` folds those; this one must not race it."""
    r = _diver()
    r["visual"]["labels"].append(
        {"at": "helmet", "text": "The __1__ is bolted to the breastplate."})
    assert ("helmet", "1") not in drop_doubled_gap_markers(r)

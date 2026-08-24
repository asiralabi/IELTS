"""A flow chart box that prints the answer another box asks for.

Found live on 2026-08-25, on the first reading chart the engine ever wrote:
gap 2 keyed 'success' against a later box opening "Despite its success". The
student works down the chain, meets a blank, and finds the word for it printed
two boxes on.

Measured before choosing the guard, the way `65f38ab` chose the grid's:
5 live reading charts, 1 genuinely self-answering (20%), 1 gap in 20 (5%)
-- `tools/_diag_flow_selfanswer.py`, samples kept beside it.

It is a REPAIR, not a refusal. Refusing costs a whole hosted generation, and
the offending box usually carries a gap of its own so it cannot be dropped
either. Re-keying the gap -- the cure `_repair_duplicate_diagram_answers` uses
-- is wrong here: 'success' is the RIGHT answer for "its maiden flight, which
was a ___". The box moves, not the key.
"""

import asyncio

import pytest

from app.agents import _flow, listening_trainer, reading_trainer
from app.agents._flow import repair_self_answering_steps, self_answering_steps


def _dirty_chart():
    """The live shape, shortened: box 3 asks, box 4 answers."""
    return {
        "kind": "flow",
        "title": "The Development of the de Havilland Comet",
        "steps": [
            "The initial aim was to fly faster than propeller-driven planes",
            "The fuselage used a new material, which provided excellent __1__",
            "The first prototype made its maiden flight, which was a __2__",
            "Despite its success, a series of accidents raised concerns about "
            "the aircraft's __3__",
        ],
    }


def _dirty_key():
    return {"1": "strength", "2": "success", "3": "safety"}


def _clean_chart():
    return {
        "kind": "flow",
        "title": "Stages in the experiment",
        "steps": [
            "Select seeds of different __1__",
            "Measure and record the __2__ of each one",
            "Use a different __3__ for each seed and label it",
            "Investigate the findings",
        ],
    }


def _stub_rewriter(monkeypatch, replies):
    """Replace the one short call, and record what it was asked."""
    asked = []

    async def fake(step, banned, title, answer_key=None):
        asked.append((step, list(banned)))
        return replies.pop(0) if replies else None

    monkeypatch.setattr(_flow, "_rewrite_step", fake)
    return asked


# ---------------------------------------------------------------------------
# Detection


def test_a_box_printing_another_boxs_answer_is_found():
    assert self_answering_steps(_dirty_chart(), _dirty_key()) == [
        ("2", "success", 4)
    ]


def test_a_box_printing_its_own_gaps_answer_is_found():
    """Where this departs from the grid. A grid cell either IS the gap or is a
    label, so it cannot give its own answer away; a step is a sentence wrapped
    around its gap and can print the word right beside it."""
    chart = {
        "kind": "flow",
        "title": "t",
        "steps": [
            "The safety record, or __2__, was questioned",
            "The results are filed",
        ],
    }

    assert self_answering_steps(chart, {"2": "safety"}) == [("2", "safety", 1)]


def test_a_gap_marker_is_not_itself_searched():
    """`__2__` is stripped before matching — it never carries answer words, and
    leaving it in would make every box look like it mentioned a number."""
    chart = {
        "kind": "flow",
        "title": "t",
        "steps": ["Record the __2__ of each sample", "File the results"],
    }

    assert self_answering_steps(chart, {"2": "weight"}) == []


def test_the_match_respects_word_boundaries():
    """An unpadded substring match finds "six" inside "sixteen" -- the live
    listening chart keyed a gap 'six', so this is not hypothetical."""
    chart = {
        "kind": "flow",
        "title": "t",
        "steps": [
            "Write the report within __23__ months",
            "Sixteen copies are printed",
        ],
    }

    assert self_answering_steps(chart, {"23": "six"}) == []


def test_an_answer_of_nothing_but_function_words_is_not_a_match():
    """A live sample keyed gap 4 'of the' and gap 2 'to identify' -- the model
    had put every gap after a complete sentence and keyed the fragment that
    would have started the next clause. Those match almost any prose, and no
    rewrite can take "of the" out of a step. The keying is the defect there,
    and `flow_error` refuses it; this detector must not also fire and spend a
    call rewording a box for nothing."""
    chart = {
        "kind": "flow",
        "title": "t",
        "steps": [
            "The team defines the initial aim of the project __1__",
            "The team develops a prototype of the new food product",
        ],
    }

    assert self_answering_steps(chart, {"1": "of the"}) == []


def test_a_real_answer_containing_a_function_word_still_matches():
    """Only an answer that is ENTIRELY function words is ignored. "state of
    matter" carries content and must still be caught."""
    chart = {
        "kind": "flow",
        "title": "t",
        "steps": [
            "The sample changes its __1__",
            "Each state of matter is recorded",
        ],
    }

    assert self_answering_steps(chart, {"1": "state of matter"}) == [
        ("1", "state of matter", 2)
    ]


# ---------------------------------------------------------------------------
# The repair


def test_the_offending_box_is_reworded_and_the_gap_left_alone(monkeypatch):
    result = {"visual": _dirty_chart(), "answer_key": _dirty_key()}
    asked = _stub_rewriter(monkeypatch, [
        "Even so, a series of accidents raised concerns about the "
        "aircraft's __3__"
    ])

    changed = asyncio.run(repair_self_answering_steps(result))

    assert [box for box, _, _ in changed] == [4]
    assert asked[0][1] == ["success"]
    assert self_answering_steps(result["visual"], _dirty_key()) == []
    assert result["answer_key"] == _dirty_key()


def test_a_rewrite_that_loses_the_gap_is_refused(monkeypatch):
    """The gaps are the chart's coupling to the questions. Dropping one breaks
    the figure far worse than the duplicated word it was called to fix."""
    result = {"visual": _dirty_chart(), "answer_key": _dirty_key()}
    _stub_rewriter(monkeypatch, ["Even so, a series of accidents raised concerns"])
    before = list(result["visual"]["steps"])

    assert asyncio.run(repair_self_answering_steps(result)) == []
    assert result["visual"]["steps"] == before


def test_a_rewrite_that_keeps_the_word_is_refused(monkeypatch):
    result = {"visual": _dirty_chart(), "answer_key": _dirty_key()}
    _stub_rewriter(monkeypatch, [
        "Despite this success, accidents raised concerns about the "
        "aircraft's __3__"
    ])
    before = list(result["visual"]["steps"])

    assert asyncio.run(repair_self_answering_steps(result)) == []
    assert result["visual"]["steps"] == before


def test_a_rewrite_that_prints_a_different_gaps_answer_is_refused(monkeypatch):
    """Trading one self-answering box for another leaves the chart no better."""
    result = {"visual": _dirty_chart(), "answer_key": _dirty_key()}
    _stub_rewriter(monkeypatch, [
        "Even so, poor strength raised concerns about the aircraft's __3__"
    ])
    before = list(result["visual"]["steps"])

    assert asyncio.run(repair_self_answering_steps(result)) == []
    assert result["visual"]["steps"] == before


def test_an_unusable_reply_leaves_the_chart_as_it_was(monkeypatch):
    """No worse than not having tried -- the same bargain every other repair
    in the pipeline strikes."""
    result = {"visual": _dirty_chart(), "answer_key": _dirty_key()}
    _stub_rewriter(monkeypatch, [None])
    before = list(result["visual"]["steps"])

    assert asyncio.run(repair_self_answering_steps(result)) == []
    assert result["visual"]["steps"] == before


def test_two_offending_boxes_are_both_repaired(monkeypatch):
    """The first version compared each rewrite against the clash list as it
    ARRIVED, so once box 2 was fixed the check for box 4 saw a list that no
    longer matched and threw the good fix away."""
    chart = {
        "kind": "flow",
        "title": "t",
        "steps": [
            "The team measured the __1__ of each sample",
            "A second weight reading was taken for comparison",
            "The results were checked for __2__",
            "Any error was recorded in the log",
        ],
    }
    key = {"1": "weight", "2": "error"}
    result = {"visual": chart, "answer_key": key}
    _stub_rewriter(monkeypatch, [
        "A second reading was taken for comparison",
        "Any discrepancy was recorded in the log",
    ])

    changed = asyncio.run(repair_self_answering_steps(result))

    assert [box for box, _, _ in changed] == [2, 4]
    assert self_answering_steps(result["visual"], key) == []


def test_one_box_printing_two_answers_is_rewritten_once(monkeypatch):
    """Two clashes on one box are ONE rewrite: a second call would be handed
    the box as it arrived and would undo the first fix."""
    chart = {
        "kind": "flow",
        "title": "t",
        "steps": [
            "Measure the __1__ of each sample",
            "Check the results for __2__",
            "Both the weight and any error go in the log",
        ],
    }
    key = {"1": "weight", "2": "error"}
    result = {"visual": chart, "answer_key": key}
    asked = _stub_rewriter(monkeypatch, ["Both readings go in the log"])

    changed = asyncio.run(repair_self_answering_steps(result))

    assert len(asked) == 1
    assert sorted(asked[0][1]) == ["error", "weight"]
    assert [box for box, _, _ in changed] == [3]


def test_a_rewrite_that_answers_the_blank_is_retried(monkeypatch):
    """A rewrite can come back without its gap — `_rewrite_step` returns None
    when it cannot put the blank back, and the model's habitual failure is to
    resolve the gap rather than leave it. Each attempt is an independent
    sample, so trying again is worth far more than the short call costs."""
    result = {"visual": _dirty_chart(), "answer_key": _dirty_key()}
    asked = _stub_rewriter(monkeypatch, [
        "Even so, a series of accidents raised concerns about the "
        "aircraft's safety",
        "Even so, a series of accidents raised concerns about the "
        "aircraft's __3__",
    ])

    changed = asyncio.run(repair_self_answering_steps(result))

    assert len(asked) == 2
    assert [box for box, _, _ in changed] == [4]
    assert "__3__" in result["visual"]["steps"][3]


def test_the_retries_do_not_run_forever(monkeypatch):
    """A box that cannot be reworded must cost a bounded number of short calls
    and then be left alone, not loop."""
    result = {"visual": _dirty_chart(), "answer_key": _dirty_key()}
    asked = _stub_rewriter(monkeypatch, [
        "still a success __3__", "still a success __3__",
        "still a success __3__", "still a success __3__",
    ])

    assert asyncio.run(repair_self_answering_steps(result)) == []
    assert len(asked) == _flow._REWRITE_ATTEMPTS


def test_a_clean_chart_costs_no_call(monkeypatch):
    result = {"visual": _clean_chart(), "answer_key": {
        "1": "sizes", "2": "weight", "3": "container"}}
    asked = _stub_rewriter(monkeypatch, ["should never be used"])

    assert asyncio.run(repair_self_answering_steps(result)) == []
    assert asked == []


def test_the_repair_ignores_a_visual_that_is_not_a_chart(monkeypatch):
    result = {"visual": {"kind": "plan", "grid": [["A"]]}, "answer_key": {}}
    _stub_rewriter(monkeypatch, ["should never be used"])

    assert asyncio.run(repair_self_answering_steps(result)) == []


# ---------------------------------------------------------------------------
# The repair is actually reached
#
# A guard nothing calls is a guard that does not exist. These pin the wiring in
# each generation path, using the offline client conftest already installs.


@pytest.fixture()
def ran(monkeypatch):
    """Record every call to the repair, in every module that imports it."""
    calls = []

    async def spy(result):
        calls.append(result)
        return []

    for module in (_flow, reading_trainer, listening_trainer):
        monkeypatch.setattr(module, "repair_self_answering_steps", spy)
    return calls


def test_a_reading_passage_is_repaired_before_it_ships(ran):
    asyncio.run(reading_trainer.create_practice(topic="urban beekeeping"))

    assert ran, "create_practice never reached the flow chart repair"


def test_a_listening_practice_set_is_repaired_before_it_ships(ran):
    asyncio.run(listening_trainer.create_practice(topic="a sports centre"))

    assert ran, "create_practice never reached the flow chart repair"

"""A diagram plan that prints the label its own gap asks for gets it rubbed out.

The teacher draws the parts, leaves `__n__` where the student writes one in,
and then prints that part's name in a second cell as well — so the answer to
"the part that supports the fabric" is legible on the figure and the question
tests nothing. Three raw hosted samples did it three out of three times, and
the live verification run of 2026-08-23 did it once in three gaps, which is why
this is a repair and not a validator: refusing it would make the path
ungeneratable.

These tests are about which cell is erased. The gap is never touched, a name
that merely resembles the answer is left alone, and a set carrying no plan is
returned untouched.
"""

import pytest

from app.agents.reading_trainer import _blank_self_answering_cells


def _set(grid, answer_key, kind="plan"):
    return {
        "visual": {"kind": kind, "title": "Cross-section", "grid": grid},
        "questions": [
            {"number": int(n), "type": "diagram_label_completion",
             "question": f"NO MORE THAN TWO WORDS. Label {n}."}
            for n in answer_key
        ],
        "answer_key": dict(answer_key),
    }


def test_duplicate_of_the_answer_is_erased():
    """The live 2026-08-23 sample: `__3__` keyed 'Stitch plate', printed beside it."""
    result = _set(
        [["", "Bobbin", ""], ["", "__3__", "Stitch plate"]],
        {"3": "Stitch plate"},
    )
    assert _blank_self_answering_cells(result) == [("3", "Stitch plate")]
    assert result["visual"]["grid"] == [["", "Bobbin", ""], ["", "__3__", ""]]


def test_the_gap_itself_survives():
    """Erasing `__3__` would destroy the question instead of the giveaway."""
    result = _set([["__3__", "Stitch plate"]], {"3": "Stitch plate"})
    _blank_self_answering_cells(result)
    assert result["visual"]["grid"][0][0] == "__3__"


def test_a_part_the_questions_do_not_ask_for_stays_drawn():
    """Only a keyed answer is a giveaway; the rest of the figure is the figure."""
    result = _set(
        [["Spool of thread", "__1__"], ["Take-up lever", "Bobbin"]],
        {"1": "Thread guide"},
    )
    assert _blank_self_answering_cells(result) == []
    assert result["visual"]["grid"] == [
        ["Spool of thread", "__1__"], ["Take-up lever", "Bobbin"]
    ]


def test_casing_articles_and_punctuation_do_not_hide_a_duplicate():
    """`_span_tokens` normalisation is what makes the match honest."""
    result = _set(
        [["__2__", "the Tension Regulator."]],
        {"2": "Tension regulator"},
    )
    assert _blank_self_answering_cells(result) == [("2", "Tension regulator")]
    assert result["visual"]["grid"][0][1] == ""


def test_every_printing_of_the_answer_goes():
    """One erased cell and one left behind would still answer the question."""
    result = _set(
        [["__1__", "Thread guide"], ["Thread guide", "Bobbin"]],
        {"1": "Thread guide"},
    )
    erased = _blank_self_answering_cells(result)
    assert len(erased) == 2
    assert result["visual"]["grid"] == [["__1__", ""], ["", "Bobbin"]]


@pytest.mark.parametrize("visual", [
    None,
    {"kind": "table", "grid": [["__1__", "Stitch plate"]]},
    {"kind": "plan", "grid": "not a grid"},
])
def test_sets_without_a_plan_grid_are_untouched(visual):
    result = {"visual": visual, "questions": [], "answer_key": {"1": "Stitch plate"}}
    assert _blank_self_answering_cells(result) == []

"""The drawn labelled diagram — the figure that replaced the grid.

`prompts.py` used to answer `diagram_label_completion` with `kind: "plan"`, the
same grid the floor plan uses, so a live reading set titled "Cross-section of a
Sewing Machine" rendered as seven text boxes in a Tetris shape. These cover the
schema that replaced it: what normalisation settles, what `diagram_error`
refuses, what the self-answer blanking rubs out, and that the gaps follow their
questions into global numbering.
"""

import pytest

from app.agents._diagram import (
    APPARATUS,
    LAYOUTS,
    blank_self_answering_labels,
    diagram_error,
    diagram_gaps,
    diagram_layout,
    diagram_texts,
    is_diagram,
    normalize_diagram,
    renumber_diagram,
    self_answering_labels,
)
from app.agents._numbering import renumber
from app.agents.answerability import visual_slots


def turbine():
    """The shape a real reading diagram takes: named parts, numbered callouts."""
    return {
        "kind": "diagram",
        "title": "An Undersea Turbine",
        "layout": "apparatus",
        "parts": [
            {"id": "rotor", "form": "rotor"},
            {"id": "housing", "form": "chamber", "name": "Generator housing"},
            {"id": "tower", "form": "column"},
            {"id": "seabed", "form": "ground", "name": "Sea bed"},
        ],
        "labels": [
            {"at": "rotor", "text": "__23__", "side": "right"},
            {"at": "tower", "text": "__24__", "side": "left"},
            {"at": "seabed", "text": "__25__", "side": "right"},
        ],
    }


def questions(*numbers):
    return [
        {"number": n, "type": "diagram_label_completion", "question": f"Label {n}."}
        for n in numbers
    ]


def key(*pairs):
    return {str(n): v for n, v in pairs}


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------


def test_a_healthy_diagram_passes():
    v = turbine()
    assert is_diagram(v)
    assert diagram_error(v, questions(23, 24, 25),
                         key((23, "blades"), (24, "tower"), (25, "sea bed"))) is None


def test_gaps_are_found_wherever_they_are_printed():
    """A gap counts whether it sits in a callout or in a part's own name."""
    v = turbine()
    v["parts"][1]["name"] = "__26__"
    assert diagram_gaps(v) == ["26", "23", "24", "25"]


def test_visual_slots_sees_the_diagram_without_being_taught_it():
    """The engine's one gap census reads any figure, so a new kind is free."""
    assert visual_slots(turbine()) == {"23", "24", "25"}


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def test_an_unknown_layout_falls_back_rather_than_failing():
    """Refusing costs a hosted regeneration; an assembly is the general case."""
    v = turbine() | {"layout": "exploded-view"}
    assert diagram_layout(v) == APPARATUS
    assert normalize_diagram(v)["layout"] == APPARATUS


@pytest.mark.parametrize("layout", LAYOUTS)
def test_every_declared_layout_survives_normalisation(layout):
    v = turbine() | {"layout": layout}
    assert normalize_diagram(v)["layout"] == layout


def test_an_invented_form_falls_back_to_the_layouts_default():
    v = turbine()
    v["parts"][0]["form"] = "impeller-housing-assembly"
    assert normalize_diagram(v)["parts"][0]["form"] == "box"


def test_ids_are_slugged_so_a_label_still_finds_its_part():
    v = turbine()
    v["parts"][0]["id"] = "Rotor Blades"
    v["labels"][0]["at"] = "rotor blades"
    out = normalize_diagram(v)
    assert out["parts"][0]["id"] == "rotor_blades"
    assert out["labels"][0]["at"] == "rotor_blades"


def test_a_loose_gap_spelling_is_folded_to_the_one_the_renderer_reads():
    v = turbine()
    v["labels"][0]["text"] = "___23___"
    assert normalize_diagram(v)["labels"][0]["text"] == "__23__"


def test_a_label_pointing_at_nothing_is_dropped_by_normalisation():
    v = turbine()
    v["labels"].append({"at": "flywheel", "text": "__26__"})
    assert len(normalize_diagram(v)["labels"]) == 3


def test_an_attachment_to_a_part_that_does_not_exist_is_unhooked():
    """A dangling `to` would reach the renderer as a part hung on nothing."""
    v = turbine()
    v["parts"].append({"id": "cable", "form": "pipe", "attach": "left", "to": "hub"})
    out = normalize_diagram(v)["parts"][-1]
    assert "to" not in out and "attach" not in out


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_a_figure_with_one_part_is_not_a_diagram():
    v = turbine()
    v["parts"] = v["parts"][:1]
    v["labels"] = v["labels"][:1]
    assert "parts to draw" in (diagram_error(v, questions(23), key((23, "x"))) or "")


def test_a_callout_that_is_a_sentence_is_refused():
    v = turbine()
    v["labels"][0]["text"] = (
        "the rotating assembly which turns as the tidal current passes it"
    )
    assert "sentence" in (diagram_error(v, questions(24, 25),
                                        key((24, "a"), (25, "b"))) or "")


def test_a_callout_pointing_at_an_undrawn_part_is_refused():
    v = turbine()
    v["labels"][0]["at"] = "flywheel"
    assert "does not draw" in (
        diagram_error(v, questions(23, 24, 25),
                      key((23, "a"), (24, "b"), (25, "c"))) or ""
    )


def test_a_gap_no_question_asks_about_is_refused():
    """The invariant that became audit check #24: a figure drew gaps the
    questions did not point at, and the audit scored the paper 23/23."""
    v = turbine()
    assert "no question asks" in (
        diagram_error(v, questions(23, 24), key((23, "a"), (24, "b"))) or ""
    )


def test_a_gap_with_no_answer_is_refused():
    v = turbine()
    assert "no answer in the key" in (
        diagram_error(v, questions(23, 24, 25), key((23, "a"), (24, "b"))) or ""
    )


def test_the_same_gap_printed_twice_is_refused():
    v = turbine()
    v["parts"][1]["name"] = "__23__"
    assert "twice" in (
        diagram_error(v, questions(23, 24, 25),
                      key((23, "a"), (24, "b"), (25, "c"))) or ""
    )


def test_a_figure_with_no_text_at_all_is_refused():
    v = turbine()
    v["labels"] = []
    for part in v["parts"]:
        part.pop("name", None)
    assert "prints no labels" in (diagram_error(v, [], {}) or "")


def test_a_non_diagram_visual_is_not_this_validators_business():
    assert diagram_error({"kind": "flow", "steps": ["a"]}, [], {}) is None
    assert diagram_error(None, [], {}) is None


# ---------------------------------------------------------------------------
# Self-answering
# ---------------------------------------------------------------------------


def test_an_orientation_label_that_prints_another_gaps_answer_is_found():
    v = turbine()
    hits = self_answering_labels(v, key((23, "generator housing"), (24, "b"), (25, "c")))
    assert [h[0] for h in hits] == ["23"]


def test_a_whole_word_match_only():
    """An unpadded substring finds 'six' inside 'sixteen'; a live listening
    chart keyed a gap 'six'."""
    v = turbine()
    v["parts"][1]["name"] = "Sixteen blades"
    assert self_answering_labels(v, key((23, "six"))) == []


def test_the_offending_label_is_rubbed_out_not_the_gap():
    v = turbine()
    result = {"visual": v, "answer_key": key((23, "generator housing"),
                                             (24, "b"), (25, "c"))}
    assert blank_self_answering_labels(result)
    assert "Generator housing" not in diagram_texts(v)
    # Every gap survives: the student still has three boxes to write in.
    assert diagram_gaps(v) == ["23", "24", "25"]


def test_a_label_carrying_its_own_gap_is_left_alone():
    """Blanking it would take the gap with it and leave the question pointing
    at a part with no box — worse than the figure it started from."""
    v = turbine()
    v["labels"][0]["text"] = "__23__ blades"
    result = {"visual": v, "answer_key": key((23, "blades"))}
    assert blank_self_answering_labels(result) == []
    assert diagram_gaps(v) == ["23", "24", "25"]


# ---------------------------------------------------------------------------
# Renumbering — the class of bug that reached a live paper
# ---------------------------------------------------------------------------


def test_gaps_follow_their_questions_into_global_numbering():
    v = turbine()
    v["parts"][1]["name"] = "__26__"
    renumber_diagram(v, {"23": "14", "24": "15", "25": "16", "26": "17"})
    assert diagram_gaps(v) == ["17", "14", "15", "16"]


def test_a_renumbering_chain_never_moves_a_gap_twice():
    """1->2 and 2->3 applied in sequence would land gap 1 on 3."""
    v = turbine()
    v["labels"] = [{"at": "rotor", "text": "__1__"}, {"at": "tower", "text": "__2__"}]
    renumber_diagram(v, {"1": "2", "2": "3"})
    assert diagram_gaps(v) == ["2", "3"]


def test_renumber_carries_the_diagram_with_the_rest_of_the_set():
    result = {
        "questions": questions(1, 2, 3),
        "answer_key": key((1, "a"), (2, "b"), (3, "c")),
        "visual": {
            "kind": "diagram",
            "title": "t",
            "layout": "apparatus",
            "parts": [{"id": "a", "form": "column", "name": "__1__"},
                      {"id": "b", "form": "ground", "name": "Base"}],
            "labels": [{"at": "b", "text": "__2__"}, {"at": "a", "text": "__3__"}],
        },
    }
    renumber(result, 13)
    assert [q["number"] for q in result["questions"]] == [14, 15, 16]
    assert visual_slots(result["visual"]) == {"14", "15", "16"}
    assert sorted(result["answer_key"]) == ["14", "15", "16"]
    # The "Label N" phrasing moves too, or the student is sent to the wrong gap.
    assert result["questions"][0]["question"] == "Label 14."

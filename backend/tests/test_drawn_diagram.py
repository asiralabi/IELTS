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
    CYCLE,
    LAYERS,
    PANEL,
    SCENE,
    LAYOUTS,
    blank_gapped_part_names,
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
        # The callouts Cambridge actually prints around this figure: a clause
        # the passage supports with the blank inside it, not a bare number on
        # a leader line. Rendering the page (tools/cambridge_figure_atlas.py)
        # is what settled this.
        "labels": [
            {"at": "rotor",
             "text": "Sea life not in danger because blades are comparatively __23__",
             "side": "right"},
            {"at": "tower",
             "text": "Whole tower can be raised for __24__ and the removal of "
                     "seaweed from the blades",
             "side": "left"},
            {"at": "seabed",
             "text": "The tower is anchored to the __25__ beneath it",
             "side": "right"},
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
    """Refusing costs a hosted regeneration, so an unknown layout falls back.

    It falls back to `scene`, not `apparatus`: placing parts in two dimensions
    is the general case, and an assembly is the special case where every part
    happens to sit in one column. Checked against what the exam draws — a fire
    extinguisher, a Ferris wheel, a beehive — almost none of which is a column,
    and all of which came out as the same tower of vessels while `apparatus`
    was the default."""
    v = turbine() | {"layout": "exploded-view"}
    assert diagram_layout(v) == SCENE
    assert normalize_diagram(v)["layout"] == SCENE
    # An assembly is still honoured when it is asked for by name.
    assert diagram_layout(turbine() | {"layout": "apparatus"}) == APPARATUS


@pytest.mark.parametrize("layout", LAYOUTS)
def test_every_declared_layout_survives_normalisation(layout):
    v = turbine() | {"layout": layout}
    assert normalize_diagram(v)["layout"] == layout


def test_an_invented_form_falls_back_to_the_layouts_default():
    """...but only once the part's own name has been asked.

    `box` is documented as "the fallback for a part no other form fits, never
    the default", and a figure drawn entirely from it is REFUSED — the biggest
    single class in the 60-set sweep of 2026-09-01, 3 of 7. So an unusable form
    is a reason to read what the part is CALLED, not to give up on drawing it.
    """
    v = turbine()
    v["parts"][0]["form"] = "impeller-housing-assembly"
    # The part is tagged `rotor`, and `rotor` is a shape the renderer knows.
    assert normalize_diagram(v)["parts"][0]["form"] == "rotor"

    # And when the words name nothing the vocabulary has, `box` still stands.
    v = turbine()
    v["parts"][0] = {"id": "widget", "form": "impeller-housing-assembly"}
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


def test_a_callout_that_is_a_clause_is_accepted():
    """Cambridge prints clauses in its callouts, so we must too.

    This test used to assert the opposite, on a comment claiming "no exam
    diagram" prints a sentence. Cambridge 9 Test 3 prints "Whole tower can be
    raised for 23 .......... and the extraction of seaweed from the blades"
    around this very figure, and Cambridge 11, 8 and 7 print the same shape.
    The six-word cap it enforced was why our figures carried no passage
    context: it forbade the only place the context could go.
    """
    v = turbine()
    assert diagram_error(v, questions(23, 24, 25),
                         key((23, "a"), (24, "b"), (25, "c"))) is None


def test_a_callout_longer_than_the_exam_prints_is_refused():
    v = turbine()
    v["labels"][0]["text"] = "word " * 21 + "__23__"
    assert "longer than the exam prints" in (
        diagram_error(v, questions(23, 24, 25),
                      key((23, "a"), (24, "b"), (25, "c"))) or ""
    )


def test_a_figure_of_bare_blanks_is_refused():
    """The contextless figure the six-word cap used to force.

    A leader line pointing at a shape, with only "23 .........." at the end of
    it, asks the student to name the shape from nothing. The exam does that
    only where a lettered answer box supplies the options.
    """
    v = turbine()
    for i, n in enumerate((23, 24, 25)):
        v["labels"][i]["text"] = f"__{n}__"
    assert "bare blank" in (
        diagram_error(v, questions(23, 24, 25),
                      key((23, "a"), (24, "b"), (25, "c"))) or ""
    )


def test_two_parts_given_the_same_cell_are_settled_apart():
    """Geometry the generator can get wrong is not the generator's to keep.

    Live 2026-08-28: a vertical-farm cross-section dropped a `valve` on top of
    its water tank, so "Water tank" and "Sensor unit" printed across each
    other. The prompt says two parts must never share a cell and the renderer
    believed it. Settled here instead of refused — refusing costs a whole
    hosted regeneration, and a part nudged one cell along is still in roughly
    the right place.
    """
    v = {
        "kind": "diagram", "title": "t", "layout": SCENE,
        "parts": [
            {"id": "col", "form": "column", "col": 1, "row": 0, "w": 2, "h": 2},
            {"id": "tank", "form": "tank", "col": 1, "row": 2},
            {"id": "sensor", "form": "valve", "col": 1, "row": 2},
            {"id": "pump", "form": "disc", "col": 2, "row": 2},
        ],
        "labels": [{"at": "tank", "text": "The __1__ holds the solution"}],
    }
    parts = normalize_diagram(v)["parts"]
    seen: dict[tuple[int, int], str] = {}
    for p in parts:
        for c in range(p["col"], p["col"] + p["w"]):
            for r in range(p["row"], p["row"] + p["h"]):
                assert (c, r) not in seen, f"{p['id']} still overlaps {seen[(c, r)]}"
                seen[(c, r)] = p["id"]


def test_the_ground_is_dropped_below_everything_that_stands_on_it():
    """"Sea bed" was printed in the middle of the foundation slab.

    The ground is the surface the drawing stands on, so it is not nudged
    sideways like any other part — it goes under the lot and spans the width,
    which is where the exam draws it.
    """
    v = {
        "kind": "diagram", "title": "t", "layout": SCENE,
        "parts": [
            {"id": "tower", "form": "column", "col": 1, "row": 0, "h": 2},
            {"id": "base", "form": "platform", "col": 0, "row": 2, "w": 3},
            {"id": "seabed", "form": "ground", "col": 0, "row": 1, "w": 4},
        ],
        "labels": [{"at": "tower", "text": "The __1__ carries the load"}],
    }
    ground = [p for p in normalize_diagram(v)["parts"] if p["form"] == "ground"][0]
    assert ground["row"] == 3
    assert ground["col"] == 0 and ground["w"] == 6


def test_two_nested_parts_on_the_same_sub_cell_are_settled_apart():
    """Live 2026-08-28: a `valve` sensor and a `tank` reservoir were both put
    inside one column on the same sub-cells, and the bowtie was drawn straight
    through "Water tank". Settled against the CONTAINER's 3x3 grid, not the
    scene's, so nothing leaves its shell."""
    v = {
        "kind": "diagram", "title": "t", "layout": SCENE,
        "parts": [
            {"id": "tower", "form": "column", "col": 1, "row": 0, "w": 3, "h": 3},
            {"id": "tank", "form": "tank", "in": "tower", "col": 1, "row": 2, "w": 3},
            {"id": "sensor", "form": "valve", "in": "tower", "col": 2, "row": 2},
        ],
        "labels": [{"at": "tank", "text": "The __1__ holds the solution"}],
    }
    nested = {p["id"]: p for p in normalize_diagram(v)["parts"] if p.get("in")}
    tank, sensor = nested["tank"], nested["sensor"]
    tank_cells = {
        (c, r)
        for c in range(tank["col"], tank["col"] + tank["w"])
        for r in range(tank["row"], tank["row"] + tank["h"])
    }
    assert (sensor["col"], sensor["row"]) not in tank_cells
    # Still inside the container's 3x3, so it is drawn in the tower.
    assert 0 <= sensor["col"] <= 2 and 0 <= sensor["row"] <= 2


def test_a_nested_part_keeps_its_sub_grid_cell():
    """`in` addresses a 3x3 grid of the CONTAINER, not the scene's grid.

    Settling it against the scene would move a yolk out of its shell.
    """
    v = {
        "kind": "diagram", "title": "t", "layout": SCENE,
        "parts": [
            {"id": "shell", "form": "oval", "col": 1, "row": 1},
            {"id": "yolk", "form": "disc", "in": "shell", "col": 1, "row": 1},
        ],
        "labels": [{"at": "yolk", "text": "The __1__ sits at the centre"}],
    }
    yolk = [p for p in normalize_diagram(v)["parts"] if p["id"] == "yolk"][0]
    assert (yolk["col"], yolk["row"]) == (1, 1)


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


def test_a_diagram_drawn_entirely_from_boxes_is_refused():
    """The complaint that prompted the `scene` rewrite: a vocabulary of plain
    rectangles renders a fire extinguisher and a Ferris wheel identically.
    `box` is the fallback for a part no other form fits, not the default."""
    v = turbine()
    for part in v["parts"]:
        part["form"] = "box"
    problem = diagram_error(v, questions(23, 24, 25),
                            key((23, "a"), (24, "b"), (25, "c")))
    assert "does not look like the thing it is of" in (problem or "")


def test_one_box_among_real_forms_is_fine():
    """Refused only when EVERY part is a box, so a genuinely box-shaped part
    still passes — a refusal costs a whole hosted regeneration."""
    v = turbine()
    v["parts"][0]["form"] = "box"
    assert diagram_error(v, questions(23, 24, 25),
                         key((23, "a"), (24, "b"), (25, "c"))) is None


def test_one_box_holding_a_number_is_allowed():
    """A single rectangular component is a real thing to number, and refusing
    it would cost a whole hosted regeneration."""
    v = turbine()
    v["parts"].append({"id": "unit", "form": "box", "name": "__26__"})
    assert diagram_error(v, questions(23, 24, 25, 26),
                         key((23, "a"), (24, "b"), (25, "c"), (26, "d"))) is None


def test_a_row_of_empty_boxes_holding_numbers_is_refused():
    """🔬 Live 2026-08-27: asked for a solar plant, the model drew three real
    parts and then a ROW of empty boxes underneath whose only content was
    `__1__`, `__2__`, `__3__` — filler to hang the numbers on. A student
    numbering a blank rectangle is being asked to name a shape that could be
    anything."""
    v = turbine()
    v["parts"].append({"id": "label1", "form": "box", "name": "__26__"})
    v["parts"].append({"id": "label2", "form": "box", "name": "__27__"})
    v["labels"] = v["labels"][:2]
    problem = diagram_error(v, questions(23, 24, 26, 27),
                            key((23, "a"), (24, "b"), (26, "c"), (27, "d")))
    assert "blank rectangles" in (problem or "")


def test_a_numbered_part_drawn_as_something_is_fine():
    """The pair: the schema's own example numbers a `chamber`, and that is the
    right way to do it."""
    v = turbine()
    v["parts"][1]["form"] = "chamber"
    v["parts"][1]["name"] = "__26__"
    assert diagram_error(v, questions(23, 24, 25, 26),
                         key((23, "a"), (24, "b"), (25, "c"), (26, "d"))) is None


# ---------------------------------------------------------------------------
# Containment and links — what makes a cross-section a cross-section
# ---------------------------------------------------------------------------


def egg():
    return {
        "kind": "diagram", "title": "Cross-section of an egg", "layout": "scene",
        "parts": [
            {"id": "shell", "form": "oval", "name": "Shell",
             "col": 0, "row": 0, "w": 3, "h": 2},
            {"id": "yolk", "form": "disc", "in": "shell", "col": 1, "row": 1,
             "name": "__1__"},
            {"id": "air", "form": "dome", "in": "shell", "col": 2, "row": 0},
        ],
        "labels": [{"at": "air", "text": "__2__"}],
        "links": [{"from": "shell", "to": "yolk", "style": "line"}],
    }


def test_a_part_can_be_drawn_inside_another():
    out = normalize_diagram(egg())
    assert [p.get("in") for p in out["parts"]] == [None, "shell", "shell"]


def test_a_container_that_does_not_exist_is_unhooked():
    """A dangling `in` would reach the renderer as a part drawn nowhere."""
    v = egg()
    v["parts"][1]["in"] = "nowhere"
    assert normalize_diagram(v)["parts"][1].get("in") is None


def test_a_part_inside_itself_is_unhooked():
    v = egg()
    v["parts"][1]["in"] = "yolk"
    assert normalize_diagram(v)["parts"][1].get("in") is None


def test_nesting_is_one_level_deep():
    """A part inside a part that is itself inside something has no box to be
    drawn in, and both would vanish. The exam never draws three deep."""
    v = egg()
    v["parts"].append({"id": "germ", "form": "disc", "in": "yolk"})
    out = normalize_diagram(v)
    assert out["parts"][-1].get("in") is None


def test_links_survive_and_resolve():
    out = normalize_diagram(egg())
    assert out["links"] == [
        {"from": "shell", "to": "yolk", "style": "line", "label": ""}
    ]


def test_a_link_to_a_part_that_does_not_exist_is_dropped():
    v = egg()
    v["links"].append({"from": "shell", "to": "nowhere"})
    assert len(normalize_diagram(v)["links"]) == 1


def test_a_link_style_nobody_knows_falls_back_to_a_plain_line():
    v = egg()
    v["links"][0]["style"] = "squiggle"
    assert normalize_diagram(v)["links"][0]["style"] == "line"


def test_a_gap_written_along_a_link_counts_and_moves():
    """A link label is printed text like any other: it can carry a gap, and the
    gap has to follow its question into global numbering."""
    v = normalize_diagram(egg())
    v["links"][0]["label"] = "__3__"
    assert "3" in diagram_gaps(v)
    renumber_diagram(v, {"1": "11", "2": "12", "3": "13"})
    assert v["links"][0]["label"] == "__13__"


def test_a_link_can_give_an_answer_away():
    v = normalize_diagram(egg())
    v["links"][0]["label"] = "Yolk"
    hits = self_answering_labels(v, {"1": "Yolk", "2": "b"})
    assert [h[0] for h in hits] == ["1"]


def test_a_cycle_of_named_stages_is_not_refused_as_filler():
    """`form` is not drawn in a cycle, so it cannot make a figure invalid.

    `_FORMS` gives `cycle` and `tree` an EMPTY vocabulary — the renderer works
    every shape out from the layout, and the part's `form` reaches the page
    nowhere. So a stage comes back as `box` whatever the model writes, and the
    filler-box rule refused the figure over a field with no effect on the
    picture. A live monarch-butterfly cycle died this way twice, on
    'caterpillar', 'chrysalis' and 'adult' — exactly the stages a cycle
    diagram is made of.
    """
    v = {
        "kind": "diagram", "title": "Life cycle of the monarch butterfly",
        "layout": "cycle",
        "parts": [
            {"id": "egg", "form": "box", "name": "Egg on milkweed"},
            {"id": "caterpillar", "form": "box", "name": "__1__"},
            {"id": "chrysalis", "form": "box", "name": "__2__"},
            {"id": "adult", "form": "box", "name": "__3__"},
        ],
        "labels": [],
    }
    assert diagram_error(v, questions(1, 2, 3),
                         key((1, "a"), (2, "b"), (3, "c"))) is None


def test_a_scene_of_filler_boxes_is_still_refused():
    """The exemption is for layouts that do not draw `form`, nothing wider."""
    v = {
        "kind": "diagram", "title": "t", "layout": SCENE,
        "parts": [
            {"id": "tank", "form": "tank", "col": 0, "row": 0},
            {"id": "a", "form": "box", "name": "__1__", "col": 1, "row": 0},
            {"id": "b", "form": "box", "name": "__2__", "col": 2, "row": 0},
        ],
        "labels": [],
    }
    assert "plain `box`es" in (
        diagram_error(v, questions(1, 2), key((1, "a"), (2, "b"))) or ""
    )


# ---------------------------------------------------------------------------
# What a passing figure could still do to a student
#
# 🔬 All four of these were found by rendering the 16 figures that survived
# `figure_sweep.py --only diagram --rounds 3` and looking at them
# (`tools/browser_shots/eye_*.png`, 2026-08-29). Every one of them PASSED the
# validators at the time. The refusal rate was 11%; the share of figures a
# student could actually answer was closer to half.
# ---------------------------------------------------------------------------


def test_a_part_named_in_the_singular_still_gives_a_plural_answer_away():
    """🔬 Live: part "Ventilation shaft" beside the answer `ventilation shafts`.

    Every check in this module compares `norm`ed text, and `norm` does not
    stem, so the giveaway sat one letter outside the rule.
    """
    v = turbine()
    v["parts"][1]["name"] = "Ventilation shaft"
    hits = self_answering_labels(v, key((23, "ventilation shafts")))
    assert [h[0] for h in hits] == ["23"]


def test_stemming_does_not_invent_a_match_between_unrelated_words():
    v = turbine()
    v["parts"][1]["name"] = "Generator housing"
    assert self_answering_labels(v, key((23, "house"))) == []


def test_a_question_with_no_gap_on_the_figure_is_refused():
    """🔬 Live: an ice core with one gap drawn for four questions. Q2-4 had
    nowhere on the drawing to be answered, and the set shipped."""
    v = turbine()
    v["labels"] = [v["labels"][0]]
    problem = diagram_error(
        v, questions(23, 24, 25),
        key((23, "blades"), (24, "tower"), (25, "sea bed")),
    ) or ""
    assert "no gap" in problem and "24" in problem


def test_a_blank_written_without_its_number_is_named_as_the_fault():
    """🔬 Live: all four callouts of a diving suit read "The _______ ...", so
    the figure rendered with no numbers at all. The message has to say which
    mistake it was, or the model's next attempt is a guess."""
    v = turbine()
    for label in v["labels"]:
        label["text"] = "The _______ does something useful"
    problem = diagram_error(
        v, questions(23, 24, 25),
        key((23, "blades"), (24, "tower"), (25, "sea bed")),
    ) or ""
    assert "__N__" in problem and "underscores" in problem


def test_a_question_the_diagram_does_not_ask_about_is_left_alone():
    """Only `diagram_label_completion` needs a gap on the drawing. A set that
    prints a figure beside other question types is not at fault."""
    v = turbine()
    other = [{"number": 26, "type": "short_answer", "question": "Why?"}]
    assert diagram_error(
        v, questions(23, 24, 25) + other,
        key((23, "blades"), (24, "tower"), (25, "sea bed"), (26, "because")),
    ) is None


def test_two_numbered_callouts_on_one_part_are_refused():
    """🔬 Live: a termite mound with 8 gaps on 4 parts — two leader lines into
    each shape, asking the student to name it twice."""
    v = turbine()
    v["labels"].append(
        {"at": "rotor", "text": "The __26__ turns as the tide runs", "side": "left"}
    )
    problem = diagram_error(
        v, questions(23, 24, 25, 26),
        key((23, "a"), (24, "b"), (25, "c"), (26, "d")),
    ) or ""
    assert "two numbered callouts" in problem


def test_one_callout_carrying_two_blanks_is_still_fine():
    """Cambridge prints exactly this: "the 25 .......... behind blades. This is
    known as 26 ..........". One line, one part, two blanks."""
    v = turbine()
    v["labels"][0]["text"] = "Blades are comparatively __23__, known as __26__"
    assert diagram_error(
        v, questions(23, 24, 25, 26),
        key((23, "a"), (24, "b"), (25, "c"), (26, "d")),
    ) is None


def test_an_ordinal_answer_is_refused():
    """🔬 Live: a monarch life cycle keyed `first stage`..`fourth stage`. No
    passage supplies an ordinal, so the student cannot answer it."""
    problem = diagram_error(
        turbine(), questions(23, 24, 25),
        key((23, "first stage"), (24, "b"), (25, "c")),
    ) or ""
    assert "names nothing the passage says" in problem


def test_a_real_term_that_happens_to_end_in_stage_is_kept():
    """The rule is for ordinals, not for the word 'stage'. 'pupal stage' is
    wording a passage really does supply."""
    assert diagram_error(
        turbine(), questions(23, 24, 25),
        key((23, "pupal stage"), (24, "b"), (25, "c")),
    ) is None


def test_the_two_faults_the_redraw_fixes_are_silent_on_the_way_in():
    """Both are worth refusing at the final gate and worth saying nothing about
    during generation. Judged on the way in they killed their set outright:
    the validate hook fires before the repair pipeline the rescue lives in, so
    the complaint bought a whole regeneration where the redraw buys the figure
    back for one call."""
    ungapped = turbine()
    ungapped["labels"] = [ungapped["labels"][0]]
    doubled = turbine()
    doubled["labels"].append(
        {"at": "rotor", "text": "The __26__ turns as the tide runs", "side": "left"}
    )
    for v, asked in ((ungapped, (23, 24, 25)), (doubled, (23, 24, 25, 26))):
        k = key(*[(n, f"a{n}") for n in asked])
        assert diagram_error(v, questions(*asked), k, after_repairs=False) is None
        assert diagram_error(v, questions(*asked), k) is not None


def test_an_ordinal_answer_is_refused_even_on_the_way_in():
    """No repair re-keys an answer, so the corrective retry is the only thing
    that can fix this one — staying silent would just ship it."""
    k = key((23, "first stage"), (24, "b"), (25, "c"))
    assert diagram_error(
        turbine(), questions(23, 24, 25), k, after_repairs=False
    ) is not None


def test_a_figure_with_no_gaps_at_all_is_still_worth_redrawing():
    """`redraw_diagram` read the numbers off the drawing and gave up when there
    were none — which is exactly the figure whose callouts wrote the blank as a
    bare row of underscores, and the one most worth redrawing."""
    from app.agents._diagram import labelling_numbers

    assert labelling_numbers(questions(23, 24, 25)) == ["23", "24", "25"]
    assert labelling_numbers(
        [{"number": 9, "type": "short_answer", "question": "?"}]
    ) == []


# ---------------------------------------------------------------------------
# Layout chosen from the subject
#
# 🔬 The model answered `layout` with `scene` on 31 of the 33 figures in the
# 2026-08-29 sweep — including all six runs that asked in so many words for
# "the life cycle of the monarch butterfly", which drew as a row of boxes
# standing on a lawn. Its choice carries no information, so the subject is
# read here instead.
# ---------------------------------------------------------------------------


def stages(title, *names, **extra):
    return {
        "kind": "diagram", "title": title, "layout": SCENE,
        "parts": [{"id": _slugish(n), "form": "box", "name": n} for n in names],
        "labels": [], **extra,
    }


def _slugish(name):
    return name.lower().replace(" ", "_").replace("-", "_")


def test_a_life_cycle_is_drawn_as_a_cycle():
    v = stages("Life cycle of the monarch butterfly", "Egg", "Larva", "Pupa")
    assert normalize_diagram(v)["layout"] == CYCLE


def test_a_typographic_hyphen_still_reads_as_a_life_cycle():
    """The model writes "life‑cycle" with U+2011, not a keyboard hyphen — as it
    does for "Cross‑section" and "Hand‑operated". An ASCII-only class matched
    none of the seven live monarch figures."""
    v = stages("Monarch butterfly life‑cycle stages", "Egg", "Larva", "Pupa")
    assert normalize_diagram(v)["layout"] == CYCLE


def test_strata_are_drawn_as_layers():
    v = stages("Cross-section of an Antarctic ice core", "Surface snow", "Firn", "Ice")
    assert normalize_diagram(v)["layout"] == LAYERS


def test_parts_named_as_layers_are_enough_on_their_own():
    v = stages("What a drill brings up", "Dust layer", "Ash band", "Bubble zone")
    assert normalize_diagram(v)["layout"] == LAYERS


def test_a_section_that_nests_a_part_stays_a_scene():
    """The band renderer stacks its parts and has nowhere to put a part drawn
    INSIDE another, so a cross-section that nests is a scene in section."""
    v = stages("Ice core layers in the drill barrel", "Barrel", "Dust layer", "Ash band")
    v["parts"][1]["in"] = "barrel"
    assert normalize_diagram(v)["layout"] == SCENE


def test_an_ordinary_cross_section_is_left_as_a_scene():
    v = stages("Cross-section of a termite mound", "Outer wall", "Chimney", "Gallery")
    assert normalize_diagram(v)["layout"] == SCENE


def test_a_layout_the_model_chose_is_never_overridden():
    """A model that names a layout has said something; this only fills in for
    the default it always picks."""
    v = stages("Life cycle of the monarch butterfly", "Egg", "Larva", "Pupa")
    v["layout"] = APPARATUS
    assert normalize_diagram(v)["layout"] == APPARATUS


def test_choosing_a_layout_never_loses_a_gap():
    """The switch changes the form vocabulary, and a form that falls back must
    not take the gap printed in the part's name with it."""
    v = stages("Life cycle of the monarch butterfly", "__1__", "Larva", "__2__")
    out = normalize_diagram(v)
    assert out["layout"] == CYCLE
    assert diagram_gaps(out) == ["1", "2"]


def test_an_ice_core_of_boxes_is_not_refused_before_it_becomes_layers():
    """🔬 `diagram_error` runs on the way IN, before `normalize_diagram` has
    settled the layout, so it has to judge the figure the normaliser will
    produce. An ice core arrives as `scene` with every part a `box` and was
    refused for being all boxes — while normalisation would have made it
    `layers`, where the band vocabulary has no `box` at all. One of the four
    failures in the 36-set sweep of 2026-08-29 died exactly that way."""
    v = stages(
        "Cross-section of an Antarctic ice core",
        "Surface snow", "Firn", "Dust layer", "Bedrock",
    )
    assert diagram_error(
        v, questions(1, 2, 3),
        key((1, "a"), (2, "b"), (3, "c")),
        after_repairs=False,
    ) is None


def test_a_scene_of_boxes_that_is_not_strata_is_still_refused():
    """The exemption follows the layout the figure will get, nothing wider."""
    v = stages("Cross-section of a canal lock", "Upper gate", "Chamber", "Lower gate")
    assert "drawn as a plain `box`" in (
        diagram_error(v, questions(1, 2, 3), key((1, "a"), (2, "b"), (3, "c"))) or ""
    )


# ---------------------------------------------------------------------------
# The figure names the part the gap asks for
#
# 🔬 46 times across the saved corpus of 2026-08-29, and the worst of the
# defects left: the model prints a SYNONYM of the answer as the part's name.
# A box labelled "Crank lever" carries a leader reading "The __3__ is the lever
# you turn to grind the beans" and the key says `handle`. A student who reads
# the figure writes "crank lever" and is marked wrong.
# ---------------------------------------------------------------------------


def test_the_name_goes_when_the_gap_asks_for_that_very_part():
    v = turbine()
    v["parts"][1]["name"] = "Crank lever"
    v["labels"][0] = {"at": "housing",
                      "text": "The __23__ is the lever you turn", "side": "right"}
    result = {"visual": v, "answer_key": key((23, "handle"), (24, "b"), (25, "c"))}
    assert [h[1] for h in blank_gapped_part_names(result)] == ["Crank lever"]
    assert "Crank lever" not in diagram_texts(v)
    # The question keeps its place on the drawing.
    assert "23" in diagram_gaps(v)


def test_a_blank_asking_about_a_named_part_is_left_alone():
    """Cambridge prints exactly this: a part it names, and a callout gapping a
    FACT about it. Only a blank that is the callout's subject is the fault."""
    v = turbine()
    v["parts"][1]["name"] = "Impurity layer"
    v["labels"][0] = {"at": "housing",
                      "text": "The impurity layer contains __23__ and ash",
                      "side": "right"}
    result = {"visual": v, "answer_key": key((23, "dust"))}
    assert blank_gapped_part_names(result) == []
    assert "Impurity layer" in diagram_texts(v)


def test_a_name_that_carries_its_own_gap_is_left_alone():
    """That name IS the question; blanking it would take the gap with it."""
    v = turbine()
    v["parts"][1]["name"] = "__26__ housing"
    v["labels"][0] = {"at": "housing", "text": "The __23__ turns", "side": "right"}
    result = {"visual": v, "answer_key": key((23, "rotor"), (26, "generator"))}
    assert blank_gapped_part_names(result) == []
    assert "26" in diagram_gaps(v)


def test_the_gate_catches_a_repair_that_did_not_run():
    v = turbine()
    v["parts"][1]["name"] = "Crank lever"
    v["labels"][0] = {"at": "housing", "text": "The __23__ is turned", "side": "right"}
    problem = diagram_error(
        v, questions(23, 24, 25), key((23, "handle"), (24, "b"), (25, "c"))
    ) or ""
    assert "asks the student to name that very part" in problem


def test_it_is_silent_on_the_way_in_because_the_repair_fixes_it():
    v = turbine()
    v["parts"][1]["name"] = "Crank lever"
    v["labels"][0] = {"at": "housing", "text": "The __23__ is turned", "side": "right"}
    assert diagram_error(
        v, questions(23, 24, 25), key((23, "handle"), (24, "b"), (25, "c")),
        after_repairs=False,
    ) is None


def test_a_blank_that_modifies_a_named_part_keeps_the_name():
    """🔬 "The __1__ gate holds back water at the higher level" wants an
    adjective — `upper` — and the part is still a gate, so "Lock gate" printed
    on it helps the student and gives nothing away. The first version of this
    rule read the anchor alone and deleted those names too, leaving a live
    canal lock as five blank rectangles."""
    v = turbine()
    v["parts"][1]["name"] = "Lock gate"
    v["labels"][0] = {"at": "housing",
                      "text": "The __23__ gate holds back water", "side": "right"}
    result = {"visual": v, "answer_key": key((23, "upper"))}
    assert blank_gapped_part_names(result) == []
    assert "Lock gate" in diagram_texts(v)


def test_the_modifier_exemption_reads_through_a_plural():
    v = turbine()
    v["parts"][1]["name"] = "Upper gates"
    v["labels"][0] = {"at": "housing",
                      "text": "The __23__ gate holds back water", "side": "right"}
    assert blank_gapped_part_names({"visual": v, "answer_key": key((23, "u"))}) == []


# ---------------------------------------------------------------------------
# Numbered parts the student cannot tell apart
#
# 🔬 Live 2026-08-29: a coffee grinder answered `layout: panel`, so its hopper,
# handle, chamber and container were all flattened to the panel vocabulary's
# `button`. Five identical circles, named nothing but `__1__`..`__5__`, no
# callouts, every answer the part's own id. It passed every check there was —
# the bare-callout rule reads `labels` and there were none, and the filler-box
# rule needs `form == "box"`.
# ---------------------------------------------------------------------------


def panel_of(*forms, names=None):
    names = names or [f"__{i + 1}__" for i in range(len(forms))]
    return {
        "kind": "diagram", "title": "Hand-operated coffee grinder",
        "layout": PANEL,
        "parts": [{"id": f"p{i}", "form": f, "name": n}
                  for i, (f, n) in enumerate(zip(forms, names))],
        "labels": [],
    }


def test_numbered_parts_drawn_as_the_same_shape_are_refused():
    v = panel_of("button", "button", "dial", "button", "button")
    problem = diagram_error(
        v, questions(1, 2, 3, 4, 5),
        key(*[(n, f"a{n}") for n in (1, 2, 3, 4, 5)]),
    ) or ""
    assert "same `button`" in problem


def test_a_panel_of_genuinely_different_controls_is_kept():
    """Cambridge 9 T2's "Water Heater" numbers its controls bare and is a real
    exam figure. A button, a switch and a light tell themselves apart."""
    v = panel_of("button", "switch", "light")
    assert diagram_error(
        v, questions(1, 2, 3), key((1, "reset button"), (2, "time"), (3, "light"))
    ) is None


def test_a_callout_carrying_the_context_answers_for_the_shapes():
    """The numbers may sit on the parts while the callouts explain them — that
    is the sewing machine, and it is fine."""
    v = panel_of("button", "button", "button")
    v["labels"] = [
        {"at": f"p{i}", "text": "pressed once to start the brewing cycle"}
        for i in range(3)
    ]
    assert diagram_error(
        v, questions(1, 2, 3), key((1, "a"), (2, "b"), (3, "c"))
    ) is None


def test_a_cycle_of_identical_stages_is_still_fine():
    """A ring orders its nodes, so a bare number there has the passage's own
    sequence to be matched against — and `_FORMS` gives `cycle` no vocabulary
    at all, so every stage shares a shape by construction."""
    v = panel_of("box", "box", "box") | {"layout": CYCLE,
                                          "title": "Life cycle of the monarch"}
    assert diagram_error(
        v, questions(1, 2, 3), key((1, "a"), (2, "b"), (3, "c"))
    ) is None


# ---------------------------------------------------------------------------
# Running out of attempts does not have to cost the set
# ---------------------------------------------------------------------------


def test_the_plainest_legal_redraw_is_kept_when_the_attempts_run_out():
    """🔬 2026-09-01: `r_diagram_machine_r6` was refused with three redraw
    attempts spent and a legal drawing among them — a rejected attempt was
    discarded whole, so the last word on the set was the broken figure the
    redraw existed to replace.

    Rejecting is how the next attempt learns; discarding is how the set is
    lost. They were the same line, and now they are not: a figure that fails
    only a QUALITY rule is still kept as the fallback.
    """
    import asyncio
    import json

    from app.agents import _figure_pass
    from app.llm.client import LLMClient, get_llm_client, set_llm_client

    # Two gaps, both sitting in a part's printed name and neither in a callout
    # — legal, and exactly what `too_plain` complains about.
    plain = {
        "kind": "diagram", "title": "A canal lock", "layout": "scene",
        "parts": [
            {"id": "chamber", "form": "tank", "name": "__1__", "col": 0, "row": 0},
            {"id": "gate", "form": "gate", "name": "__2__", "col": 1, "row": 0},
            {"id": "sill", "form": "box", "name": "Sill", "col": 2, "row": 0},
        ],
        "labels": [],
    }
    # The figure it replaces is itself unusable, so this is a rescue.
    broken = {
        "kind": "diagram", "title": "A canal lock", "layout": "scene",
        "parts": [
            {"id": "a", "form": "box", "name": "__1__", "col": 0, "row": 0},
            {"id": "b", "form": "box", "name": "__2__", "col": 1, "row": 0},
        ],
        "labels": [],
    }

    class Plain(LLMClient):
        is_finetune = False
        turns = 0

        async def complete(self, system, messages, **kw):
            raise AssertionError("nothing here expands prose")

        async def complete_json(self, system, messages, **kw):
            Plain.turns += 1
            return {"visual": json.loads(json.dumps(plain))}

    result = {
        "visual": json.loads(json.dumps(broken)),
        "questions": [
            {"number": 1, "type": "diagram_label_completion",
             "question": "The __1__ fills with water."},
            {"number": 2, "type": "diagram_label_completion",
             "question": "The __2__ seals the upper end."},
        ],
        "answer_key": {"1": "chamber", "2": "gate"},
    }
    previous = get_llm_client()
    set_llm_client(Plain())
    try:
        replaced = asyncio.run(
            _figure_pass.redraw_diagram(result, "A lock raises a boat."))
    finally:
        set_llm_client(previous)

    # Every attempt was spent and every one was REJECTED — the figure is kept
    # by the fallback, not by passing the judge.
    assert Plain.turns == _figure_pass._REDRAW_ATTEMPTS
    assert replaced, "a legal redraw was reached and must not be discarded"
    assert [p["id"] for p in result["visual"]["parts"]] == [
        "chamber", "gate", "sill"]


def test_a_redraw_the_free_repairs_would_cure_is_not_thrown_away():
    """🔬 The verification sweep of 2026-09-01: 11 of the 20 rejected redraws
    carried the same fault — the figure printing a part's name while that
    part's own gap asks for it — and `blank_gapped_part_names` deletes exactly
    that, deterministically, moments after the redraw returns.

    So the judge was refusing attempts the pipeline was about to cure for free.
    `r_diagram_machine` spent all three on it and was refused still holding the
    bare-underscore figure the redraw had been called to replace.

    The complaint stays — it is how the next attempt learns — but an attempt
    the free repairs would make legal is kept as a rescue rather than lost.
    """
    import asyncio
    import json

    from app.agents import _figure_pass
    from app.llm.client import LLMClient, get_llm_client, set_llm_client

    # Legal in every respect except one: 'Grinding chamber' is printed on the
    # part whose own gap asks the student to name it.
    named = {
        "kind": "diagram", "title": "A coffee grinder", "layout": "scene",
        "parts": [
            {"id": "chamber", "form": "chamber", "name": "Grinding chamber",
             "col": 0, "row": 0},
            {"id": "burr", "form": "disc", "name": "Burr", "col": 1, "row": 0},
            {"id": "crank", "form": "handle", "name": "Crank", "col": 2, "row": 0},
        ],
        "labels": [
            {"at": "chamber",
             "text": "The __1__ holds the beans before they are ground"},
            {"at": "burr",
             "text": "Beans are crushed by __2__ between the two discs"},
        ],
        "links": [{"from": "crank", "to": "burr", "style": "line"}],
    }
    broken = {
        "kind": "diagram", "title": "A coffee grinder", "layout": "scene",
        "parts": [
            {"id": "a", "form": "box", "name": "__1__", "col": 0, "row": 0},
            {"id": "b", "form": "box", "name": "__2__", "col": 1, "row": 0},
        ],
        "labels": [],
    }

    class Named(LLMClient):
        is_finetune = False
        turns = 0

        async def complete(self, system, messages, **kw):
            raise AssertionError("nothing here expands prose")

        async def complete_json(self, system, messages, **kw):
            Named.turns += 1
            return {"visual": json.loads(json.dumps(named))}

    result = {
        "visual": json.loads(json.dumps(broken)),
        "questions": [
            {"number": 1, "type": "diagram_label_completion",
             "question": "The __1__ holds the beans."},
            {"number": 2, "type": "diagram_label_completion",
             "question": "The beans are crushed by __2__."},
        ],
        "answer_key": {"1": "hopper", "2": "friction"},
    }
    previous = get_llm_client()
    set_llm_client(Named())
    try:
        replaced = asyncio.run(
            _figure_pass.redraw_diagram(result, "A hand grinder crushes beans."))
    finally:
        set_llm_client(previous)

    assert Named.turns == _figure_pass._REDRAW_ATTEMPTS, "every attempt rejected"
    assert replaced, "an attempt one free deletion from shipping was discarded"
    # Kept, and kept REPAIRED: the name that made it illegal is gone, the gap
    # and its callout stay, which is what `blank_gapped_part_names` promises.
    parts = {p["id"]: p.get("name", "") for p in result["visual"]["parts"]}
    assert parts["chamber"] == ""
    assert parts["burr"] == "Burr"
    assert any("__1__" in str(lb.get("text")) for lb in result["visual"]["labels"])


def test_the_redraw_asks_for_the_gaps_the_QUESTIONS_need():
    """🔬 The 60-set sweep of 2026-09-01 refused three sets on "1 gap(s) drawn
    for 4 question(s)" and not one on "must carry exactly" — so every reply had
    given the redraw precisely what it asked for, and what it asked for was
    wrong.

    `wanted` was read off the BROKEN drawing and only fell back to the
    questions when the drawing had no gaps at all. A figure carrying one gap
    for four questions is broken the same way, but its list was non-empty, so
    the model was told to draw that one gap, obeyed, passed `got != wanted` —
    and was then refused by `diagram_error` for the very deficiency the redraw
    had been called to fix. Three attempts, all doomed before the first call.
    """
    import asyncio
    import json

    from app.agents import _figure_pass
    from app.llm.client import LLMClient, get_llm_client, set_llm_client

    # One gap on the drawing, four questions asking for one each.
    starved = {
        "kind": "diagram", "title": "A canal lock", "layout": "scene",
        "parts": [
            {"id": "chamber", "form": "tank", "name": "Chamber", "col": 0, "row": 0},
            {"id": "valve", "form": "valve", "name": "Valve", "col": 1, "row": 0},
        ],
        "labels": [{"at": "chamber", "text": "Water enters through the __1__"}],
    }
    asked_for: list[str] = []

    class Watcher(LLMClient):
        is_finetune = False

        async def complete(self, system, messages, **kw):
            raise AssertionError("nothing here expands prose")

        async def complete_json(self, system, messages, **kw):
            asked_for.append(messages[0]["content"])
            # Give up immediately; the prompt is what is on trial.
            return {"visual": None}

    result = {
        "visual": json.loads(json.dumps(starved)),
        "questions": [
            {"number": n, "type": "diagram_label_completion",
             "question": f"Label __{n}__ on the diagram."}
            for n in (1, 2, 3, 4)
        ],
        "answer_key": {"1": "sluice", "2": "filling", "3": "balance", "4": "upper"},
    }
    previous = get_llm_client()
    set_llm_client(Watcher())
    try:
        asyncio.run(_figure_pass.redraw_diagram(result, "A lock raises a boat."))
    finally:
        set_llm_client(previous)

    assert asked_for, "the redraw never ran"
    prompt = asked_for[0]
    # Every question's gap is asked for, not just the one already drawn.
    for gap in ("__1__", "__2__", "__3__", "__4__"):
        assert gap in prompt, f"{gap} was never asked for"


# ---------------------------------------------------------------------------
# A part is drawn as the shape its own name says
# ---------------------------------------------------------------------------


def _mound():
    """`r_diagram_crosssec_r3` from the 2026-09-01 sweep, refused for boxes."""
    return {
        "kind": "diagram", "title": "Cross-section of a termite mound",
        "layout": "scene",
        "parts": [
            {"id": "chimney", "form": "box", "name": "Central chimney",
             "col": 1, "row": 0},
            {"id": "shaft", "form": "box", "name": "", "col": 1, "row": 1},
            {"id": "tunnel", "form": "box", "name": "Peripheral tunnel",
             "col": 0, "row": 1},
            {"id": "reservoir", "form": "box", "name": "Moisture reservoir",
             "col": 2, "row": 1},
            {"id": "ground", "form": "ground", "name": "", "col": 0, "row": 2, "w": 3},
        ],
        "labels": [
            {"at": "chimney", "text": "The upward __1__ that moves warm air out"},
            {"at": "reservoir", "text": "Stores __2__ for colony use"},
        ],
    }


def test_a_boxed_part_is_drawn_as_the_shape_its_name_says():
    """🔬 The biggest class in the 60-set sweep of 2026-09-01, 3 of 7: a figure
    drawn entirely from `box`. One was a termite mound whose parts were a
    chimney, a shaft, a tunnel and a reservoir — the vocabulary has a shape for
    every one of those, and nothing was missing but the lookup.
    """
    parts = {p["id"]: p["form"] for p in normalize_diagram(_mound())["parts"]}
    assert parts["chimney"] == "column"     # "a tall narrow upright"
    assert parts["shaft"] == "column"
    assert parts["tunnel"] == "pipe"        # "a narrow connector"
    assert parts["reservoir"] == "tank"


def test_the_box_refusal_lifts_once_the_parts_are_shaped():
    from app.agents._diagram import diagram_error

    questions = [{"number": n, "type": "diagram_label_completion",
                  "question": f"Label __{n}__"} for n in (1, 2)]
    key = {"1": "convection", "2": "water"}
    assert "plain `box`" in (diagram_error(_mound(), questions, key) or "")
    assert diagram_error(normalize_diagram(_mound()), questions, key) is None


def test_a_part_whose_tag_IS_a_form_keeps_that_form():
    """`r_diagram_machine_r2` tagged a part `filling_valve` and drew it as a
    box. It had already said what it was."""
    v = {"kind": "diagram", "layout": "scene",
         "parts": [{"id": "filling_valve", "form": "box", "col": 0, "row": 0},
                   {"id": "balance_cavity", "form": "box", "col": 1, "row": 0}],
         "labels": []}
    parts = {p["id"]: p["form"] for p in normalize_diagram(v)["parts"]}
    assert parts["filling_valve"] == "valve"
    assert parts["balance_cavity"] == "chamber"   # "a vessel"


def test_a_place_is_never_drawn_as_the_GROUND_line():
    """🔬 The first version of this read "Breeding ground" and drew the hatched
    ground line, which loses the part — and worse, slips a figure of nothing but
    boxes past the box rule, which excludes scenery from its count precisely so
    that cannot happen.

    `r_diagram_cycle_r2` is the honest refusal here: its parts are an
    overwintering site, a breeding ground and a stopover. Those are PLACES. The
    vocabulary has no shape for a place, the figure wanted to be a map, and
    refusing it says so.
    """
    from app.agents._diagram import diagram_error

    v = {"kind": "diagram", "layout": "scene",
         "parts": [{"id": "site1", "form": "box", "name": "Overwintering site",
                    "col": 0, "row": 0},
                   {"id": "site2", "form": "box", "name": "Breeding ground",
                    "col": 1, "row": 0},
                   {"id": "site3", "form": "box", "name": "Midway stopover",
                    "col": 2, "row": 0}],
         "labels": [{"at": "site1", "text": "Monarchs cluster to conserve __1__"}]}
    settled = normalize_diagram(v)
    assert [p["form"] for p in settled["parts"]] == ["box", "box", "box"]
    assert "plain `box`" in (diagram_error(
        settled, [{"number": 1, "type": "diagram_label_completion",
                   "question": "Label __1__"}], {"1": "heat"}) or "")


def _diving_suit() -> dict:
    """`r_diagram_apparatus_r1` from 2026-09-01, cut to its fault.

    Four questions; three answers printed as part names with no gap anywhere
    for them, one gap drawn properly.
    """
    return {
        "visual": {
            "kind": "diagram", "title": "A Victorian diving suit",
            "layout": "scene",
            "parts": [
                {"id": "pump", "form": "tank", "name": "surface pump",
                 "col": 0, "row": 0},
                {"id": "hose", "form": "hose", "name": "rubber hose",
                 "col": 1, "row": 0},
                {"id": "helmet", "form": "dome", "name": "helmet",
                 "col": 2, "row": 0},
                {"id": "valve", "form": "valve", "name": "__4__",
                 "col": 2, "row": 1},
            ],
            "labels": [],
        },
        "questions": [
            {"number": n, "type": "diagram_label_completion",
             "question": f"Label __{n}__ on the diagram."} for n in (1, 2, 3, 4)
        ],
        "answer_key": {"1": "surface pump", "2": "rubber hose",
                       "3": "helmet", "4": "non-return valve"},
    }


def test_a_printed_answer_becomes_the_gap_that_asks_for_it():
    """🔬 The last diagram refusal standing after the 2026-09-01 sweep, and the
    trapped subject `prompts.py` flags with a 🚨: every answer IS a part name.

    The figure had both faults at once — it printed three answers, and three
    questions had no gap to be written in. On a labelled diagram the numbered
    blank IS the part's missing name, so one rename cures both. The redraw
    spent all three attempts failing to and the set was thrown away.
    """
    from app.agents._diagram import diagram_error, gap_the_named_answers

    r = _diving_suit()
    assert "carries no gap" in (
        diagram_error(r["visual"], r["questions"], r["answer_key"]) or "")

    moved = gap_the_named_answers(r)
    assert [pid for pid, _ in moved] == ["pump", "hose", "helmet"]
    names = {p["id"]: p["name"] for p in r["visual"]["parts"]}
    assert names == {"pump": "__1__", "hose": "__2__",
                     "helmet": "__3__", "valve": "__4__"}
    assert diagram_error(r["visual"], r["questions"], r["answer_key"]) is None


def test_it_never_guesses_when_the_name_is_not_unique():
    """Two parts printing the same words name no single question, and a wrong
    gap marks a correct student wrong — the reason the bare-underscore
    renumbering was rejected outright."""
    from app.agents._diagram import gap_the_named_answers

    r = _diving_suit()
    r["visual"]["parts"][1]["name"] = "surface pump"     # now two of them
    moved = gap_the_named_answers(r)
    assert [pid for pid, _ in moved] == ["helmet"]
    assert r["visual"]["parts"][0]["name"] == "surface pump"
    assert r["visual"]["parts"][1]["name"] == "surface pump"


def test_a_question_that_already_has_its_gap_is_left_alone():
    from app.agents._diagram import gap_the_named_answers

    r = _diving_suit()
    # Gap 4 is already drawn; its answer must not be hunted for a second home.
    r["answer_key"]["4"] = "helmet"
    moved = gap_the_named_answers(r)
    assert ("helmet", "4") not in moved
    assert r["visual"]["parts"][3]["name"] == "__4__"

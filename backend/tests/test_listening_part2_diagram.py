"""Listening Part 2 draws a diagram on some papers, not a plan on every one.

Part 2 always called for the grid plan, so the engine could not produce a
listening equipment diagram at all — the "Water Heater" figure Cambridge prints
had no route into a generated paper. Part 2 now chooses per paper, the way
reading passage 2 already chooses between a diagram and a flow chart.

The rate is measured, not invented: `tools/_diag_listening_part2_figures.py`
counts 16 figures across the books' Part 2s — 10 maps, 5 plans and 1 diagram.
"""

import random

import pytest

from app.agents import listening_trainer as lt
from app.agents._diagram import MIN_LABELS, sparse_diagram_error
from app.agents.answerability import canon


def specs(n, seed=0):
    """The Part 2 specs drawn over n papers."""
    random.seed(seed)
    return [lt._part_spec(2)["types"] for _ in range(n)]


def test_part_2_can_draw_either_figure():
    assert set(specs(400)) == {
        lt._PART_SPECS[2]["types"],
        lt._PART2_DIAGRAM["types"],
    }


def test_the_plan_still_dominates_part_2():
    """The measurement that matters: the books print a plan or a map on 15 of
    16 Part 2 figures. Whatever the shipped share, the diagram must stay the
    minority — a paper set where most Part 2s are equipment is not IELTS."""
    drawn = specs(400)
    diagrams = sum(1 for t in drawn if t == lt._PART2_DIAGRAM["types"])
    assert 0 < diagrams < len(drawn) / 2


def test_the_share_is_the_documented_one():
    assert lt._PART2_DIAGRAM_SHARE == 0.25


@pytest.mark.parametrize("part", [1, 3, 4])
def test_no_other_part_varies(part):
    """Only Part 2 draws. A Part 4 that changed shape per paper would move the
    one part the fine-tuned checkpoint still generates."""
    assert {lt._part_spec(part)["types"] for _ in range(50)} == {
        lt._PART_SPECS[part]["types"]
    }


def test_the_diagram_spec_changes_the_TALK_not_just_the_figure():
    """A monologue about a site gives the student nowhere to hang a
    cross-section, so the format has to move with the figure."""
    plan, diagram = lt._PART_SPECS[2], lt._PART2_DIAGRAM
    assert plan["format"] != diagram["format"]
    assert "device" in diagram["format"].lower()
    assert "diagram_label_completion" in diagram["figure"]
    assert "map_labelling" not in diagram["types"]


def test_both_part_2_variants_still_route_hosted():
    """The checkpoint has never drawn either figure. Part 2 is in _FIGURE_PARTS
    whichever spec is drawn, so routing cannot depend on the coin flip."""
    assert 2 in lt._FIGURE_PARTS


def test_asking_for_a_diagram_on_a_single_part_routes_hosted_too():
    """A student naming the type gets the same treatment as a full test."""
    assert canon("diagram_label_completion") in lt._FIGURE_ASK
    assert canon("flow_chart_completion") in lt._FIGURE_ASK


# ---------------------------------------------------------------------------
# The shared label floor
# ---------------------------------------------------------------------------


def labelling(n):
    return [{"number": i, "type": "diagram_label_completion"} for i in range(n)]


def test_a_figure_numbering_too_few_parts_is_refused():
    assert "at least 3" in (sparse_diagram_error(labelling(2)) or "")


def test_a_figure_numbering_enough_parts_passes():
    assert sparse_diagram_error(labelling(MIN_LABELS)) is None


def test_a_set_with_no_diagram_questions_is_not_this_rules_business():
    assert sparse_diagram_error([]) is None
    assert sparse_diagram_error(None) is None


def _two_label_part():
    """A listening part that is sound in every other respect and numbers two
    parts. Built out in full on purpose: a stub set is refused by the first
    validator it meets, so a test asserting only `is not None` would pass
    without the rule under test ever running."""
    return {
        # Every keyed answer is spoken. Before the audibility rule landed this
        # script stopped at the time control, and adding the third label below
        # keyed a "power light" the recording never mentioned.
        "audio_script": (
            "SPEAKER: First press the reset button, then turn the time control "
            "dial, and watch for the power light above it."
        ),
        "questions": [
            {
                "number": 1,
                "type": "diagram_label_completion",
                "question": "NO MORE THAN TWO WORDS. Label 1 on the diagram: "
                            "the control pressed first ______.",
                "word_limit": 2,
            },
            {
                "number": 2,
                "type": "diagram_label_completion",
                "question": "NO MORE THAN TWO WORDS. Label 2 on the diagram: "
                            "the dial turned next ______.",
                "word_limit": 2,
            },
        ],
        "answer_key": {"1": "reset button", "2": "time control"},
        "visual": {
            "kind": "diagram", "title": "Heater", "layout": "panel",
            "parts": [
                {"id": "a", "form": "button", "name": "__1__"},
                {"id": "b", "form": "dial", "name": "__2__"},
                {"id": "c", "form": "light", "name": "Power"},
            ],
            "labels": [],
        },
    }


def test_listening_refuses_a_sparse_diagram_the_way_reading_does():
    """Both trainers call the one helper, so the thresholds cannot drift."""
    problem = lt.validate_part(
        _two_label_part(), judge_structure=False, judge_matching=False
    )
    assert "at least 3" in (problem or "")


def test_the_same_part_with_three_labels_is_accepted():
    """The other half of the pair. Without it the test above would pass on a
    set the validator refuses for some unrelated reason."""
    result = _two_label_part()
    result["questions"].append({
        "number": 3,
        "type": "diagram_label_completion",
        "question": "NO MORE THAN TWO WORDS. Label 3 on the diagram: the "
                    "indicator that lights up ______.",
        "word_limit": 2,
    })
    result["answer_key"]["3"] = "power light"
    result["visual"]["parts"][2]["name"] = "__3__"
    result["visual"]["parts"].append(
        {"id": "d", "form": "display", "name": "Display"}
    )
    assert lt.validate_part(
        result, judge_structure=False, judge_matching=False
    ) is None


# ---------------------------------------------------------------------------
# The defect the first live Part 2 actually produced
# ---------------------------------------------------------------------------


def _live_espresso_machine():
    """Listening Part 2, generated live 2026-08-27, first run to return a
    diagram: "How the AutoBarista Espresso Machine Works".

    Every part carried a printed name AND a numbered callout pointing at it, so
    the figure printed "Water Tank" beside the blank keyed 'water tank' -- four
    times over. `validate_part` passed it, because refusing a self-answering
    figure costs a regeneration for a fault one deletion fixes. Nothing was
    doing the deleting on the listening path.
    """
    return {
        "visual": {
                "kind": "diagram",
                "title": "AutoBarista Espresso Machine",
                "layout": "panel",
                "parts": [
                        {
                                "id": "tank",
                                "form": "button",
                                "name": "Water Tank"
                        },
                        {
                                "id": "grinder",
                                "form": "button",
                                "name": "Bean Grinder"
                        },
                        {
                                "id": "brewhead",
                                "form": "button",
                                "name": "Brew Head"
                        },
                        {
                                "id": "steam",
                                "form": "button",
                                "name": "Steam Wand"
                        },
                        {
                                "id": "panel",
                                "form": "display",
                                "name": "Control Panel"
                        }
                ],
                "labels": [
                        {
                                "at": "tank",
                                "text": "__11__",
                                "side": ""
                        },
                        {
                                "at": "grinder",
                                "text": "__12__",
                                "side": ""
                        },
                        {
                                "at": "brewhead",
                                "text": "__13__",
                                "side": ""
                        },
                        {
                                "at": "steam",
                                "text": "__14__",
                                "side": ""
                        }
                ]
        },
        "answer_key": {"11": "water tank", "12": "bean grinder", "13": "brew head", "14": "steam wand"},
    }


def test_the_live_figure_gave_away_every_one_of_its_answers():
    """Red without the repair. If this ever returns fewer than four, the
    detector changed and the regression below stops proving anything."""
    from app.agents._diagram import self_answering_labels
    result = _live_espresso_machine()
    hits = self_answering_labels(result["visual"], result["answer_key"])
    assert sorted(h[0] for h in hits) == ["11", "12", "13", "14"]


def test_listening_rubs_those_answers_off_the_figure():
    from app.agents._diagram import diagram_gaps, self_answering_labels
    result = _live_espresso_machine()
    lt._blank_diagram_answers(result)
    assert self_answering_labels(result["visual"], result["answer_key"]) == []
    # Every gap survives: the student still has four boxes to write in.
    assert diagram_gaps(result["visual"]) == ["11", "12", "13", "14"]


def test_the_orientation_label_that_gave_nothing_away_is_kept():
    """Blanking is not "clear the figure": the part with no callout of its own
    keeps its name, so the student can still tell what they are looking at."""
    result = _live_espresso_machine()
    lt._blank_diagram_answers(result)
    names = [p.get("name") for p in result["visual"]["parts"]]
    assert "Control Panel" in names


# ---------------------------------------------------------------------------
# A listening answer has to be AUDIBLE
# ---------------------------------------------------------------------------


def _machine_part(answer: str):
    """A Part 2 diagram keyed to `answer`, against a script that says
    "group head" and "rotary dial" in so many words."""
    return {
        "audio_script": (
            "SPEAKER: Water passes from the tank through the group head, and "
            "the rotary dial on the front selects the brewing mode."
        ),
        "visual": {
            "kind": "diagram", "title": "Espresso machine", "layout": "apparatus",
            "parts": [
                {"id": "tank", "form": "tank", "name": "Water tank"},
                {"id": "grouphead", "form": "disc"},
            ],
            "labels": [{"at": "grouphead", "text": "__11__"}],
        },
        "answer_key": {"11": answer},
    }


def test_an_answer_the_script_says_is_accepted():
    from app.agents._diagram import inaudible_diagram_error
    r = _machine_part("group head")
    assert inaudible_diagram_error(
        r["visual"], r["answer_key"], r["audio_script"]) is None


def test_the_part_id_slug_is_refused_as_an_answer():
    """Live Part 2, 2026-08-27: the model keyed 'grouphead' and 'steamwand'
    straight off the part ids, for parts the script calls "group head" and
    "steam wand". `id` is an internal tag sitting in the payload right beside
    the answer, which is the hazard the schema itself introduced."""
    from app.agents._diagram import inaudible_diagram_error
    r = _machine_part("grouphead")
    problem = inaudible_diagram_error(
        r["visual"], r["answer_key"], r["audio_script"])
    assert "never says" in (problem or "")
    assert "`id`" in (problem or "")


def test_a_plausible_but_unspoken_rewording_is_refused_too():
    """The second live case: the script says "rotary dial" throughout and the
    key read 'Mode dial'. A student writes what they hear and is marked wrong,
    so this is a real refusal and not an over-strict one."""
    from app.agents._diagram import inaudible_diagram_error
    r = _machine_part("Mode dial")
    assert "never says" in (
        inaudible_diagram_error(r["visual"], r["answer_key"], r["audio_script"]) or "")


def test_whole_words_only():
    """'head' must not be found inside 'group head' by accident, nor a gap
    keyed 'ea' pass because the script contains "head"."""
    from app.agents._diagram import inaudible_diagram_error
    r = _machine_part("ea")
    assert inaudible_diagram_error(
        r["visual"], r["answer_key"], r["audio_script"]) is not None


def test_no_script_means_the_rule_does_not_run():
    """Reading has its own verbatim rule against the passage; this one is the
    listening side and must not fire where there is no recording."""
    from app.agents._diagram import inaudible_diagram_error
    r = _machine_part("grouphead")
    assert inaudible_diagram_error(r["visual"], r["answer_key"], "") is None


def test_validate_part_refuses_the_inaudible_answer():
    """Three labels, not one: at one the sparse rule answers first and the
    audibility rule under test never runs."""
    r = _machine_part("grouphead")
    r["visual"]["parts"].append({"id": "dial", "form": "dial"})
    r["visual"]["parts"].append({"id": "tankslot", "form": "slot"})
    r["visual"]["labels"] += [
        {"at": "dial", "text": "__12__"}, {"at": "tankslot", "text": "__13__"}
    ]
    r["answer_key"].update({"12": "rotary dial", "13": "water tank"})
    r["questions"] = [
        {"number": n, "type": "diagram_label_completion", "word_limit": 2,
         "question": f"NO MORE THAN TWO WORDS. Label {n} on the diagram: the "
                     "part described ______."}
        for n in (11, 12, 13)
    ]
    assert "never says" in (
        lt.validate_part(r, judge_structure=False, judge_matching=False) or "")


def test_the_same_part_with_the_spoken_answer_is_accepted():
    """The pair for the test above: only the inaudible key changes."""
    r = _machine_part("group head")
    r["visual"]["parts"].append({"id": "dial", "form": "dial"})
    r["visual"]["parts"].append({"id": "tankslot", "form": "slot"})
    r["visual"]["labels"] += [
        {"at": "dial", "text": "__12__"}, {"at": "tankslot", "text": "__13__"}
    ]
    r["answer_key"].update({"12": "rotary dial", "13": "tank"})
    r["questions"] = [
        {"number": n, "type": "diagram_label_completion", "word_limit": 2,
         "question": f"NO MORE THAN TWO WORDS. Label {n} on the diagram: the "
                     "part described ______."}
        for n in (11, 12, 13)
    ]
    assert lt.validate_part(
        r, judge_structure=False, judge_matching=False) is None

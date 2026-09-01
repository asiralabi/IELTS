"""The printed notes block and the printed summary.

Cambridge names these more often than any other figure — "Complete the notes
below", "Complete the summary below" — and the engine could draw neither. The
prompts said so outright: "No summary or note block is printed on screen", so
every note item had to carry its own context inline and the student never saw
the block the rubric promised.

One kind covers both, because they are one shape with two typographies. These
cover what normalisation settles, what `notes_error` refuses, and that the gaps
follow their questions into global numbering.
"""

import pytest

from app.agents._notes import (
    NOTES_STYLE,
    SUMMARY_STYLE,
    blank_self_answering_lines,
    is_notes,
    normalize_notes,
    notes_error,
    notes_gaps,
    notes_lines,
    notes_style,
    renumber_notes,
    self_answering_lines,
)
from app.agents._numbering import renumber
from app.agents.answerability import visual_slots


def block(style=NOTES_STYLE):
    """The shape a real notes block takes: headed groups, gaps down the lines."""
    return {
        "kind": "notes",
        "style": style,
        "title": "Field trip to Bramley Farm",
        "sections": [
            {
                "heading": "Before the visit",
                "lines": [
                    "Bring waterproof boots and a __21__",
                    "Meet outside the library at 8.15am",
                ],
            },
            {
                "heading": "At the farm",
                "lines": [
                    "The tour begins in the dairy",
                    "Photography is not allowed in the __22__",
                ],
            },
        ],
    }


def questions(*numbers):
    return [
        {"number": n, "type": "note_completion", "question": f"Gap {n} is ______."}
        for n in numbers
    ]


def key(*pairs):
    return {str(n): v for n, v in pairs}


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------


def test_a_healthy_block_passes():
    v = block()
    assert is_notes(v)
    assert notes_error(v, questions(21, 22), key((21, "map"), (22, "barn"))) is None


def test_gaps_are_read_top_to_bottom():
    assert notes_gaps(block()) == ["21", "22"]


def test_lines_exclude_the_headings():
    lines = notes_lines(block())
    assert len(lines) == 4
    assert "Before the visit" not in lines


def test_visual_slots_sees_the_block_without_being_taught_it():
    assert visual_slots(block()) == {"21", "22"}


@pytest.mark.parametrize("style", [NOTES_STYLE, SUMMARY_STYLE])
def test_both_typographies_survive_normalisation(style):
    assert normalize_notes(block(style))["style"] == style


def test_an_unknown_style_falls_back_to_notes():
    """Headed short lines are readable whatever the content; prose set as notes
    is not, so the fallback goes the safe way."""
    assert notes_style(block("bullet-points")) == NOTES_STYLE


def test_blank_lines_are_dropped_rather_than_printed():
    v = block()
    v["sections"][0]["lines"].append("   ")
    assert len(normalize_notes(v)["sections"][0]["lines"]) == 2


def test_a_loose_gap_spelling_is_folded():
    v = block()
    v["sections"][0]["lines"][0] = "Bring boots and a ___21___"
    assert "__21__" in normalize_notes(v)["sections"][0]["lines"][0]


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_a_block_with_too_few_lines_is_refused():
    v = block()
    v["sections"] = [{"heading": "x", "lines": ["Only one line with __21__"]}]
    assert "lines to be worth printing" in (
        notes_error(v, questions(21), key((21, "a"))) or "")


def test_a_block_with_one_gap_is_refused():
    """A printed block for a single blank is a sentence with a hole in it."""
    v = block()
    v["sections"][1]["lines"][1] = "Photography is not allowed in the barn"
    assert "worth showing only for" in (
        notes_error(v, questions(21), key((21, "a"))) or "")


def test_gaps_out_of_order_are_refused():
    """The student reads top to bottom, so a gap numbered backwards sends them
    the wrong way — the rule the flow chart enforces on its chain."""
    v = block()
    v["sections"][0]["lines"][0] = "Bring waterproof boots and a __22__"
    v["sections"][1]["lines"][1] = "Photography is not allowed in the __21__"
    assert "out of order" in (
        notes_error(v, questions(21, 22), key((21, "a"), (22, "b"))) or "")


def test_the_same_gap_printed_twice_is_refused():
    v = block()
    v["sections"][1]["lines"][1] = "Photography is not allowed in the __21__"
    assert "twice" in (
        notes_error(v, questions(21), key((21, "a"))) or "")


def test_a_line_that_is_only_its_gap_is_refused():
    v = block()
    v["sections"][1]["lines"][1] = "__22__"
    assert "nothing but its gap" in (
        notes_error(v, questions(21, 22), key((21, "a"), (22, "b"))) or "")


def test_a_line_the_length_of_a_paragraph_is_refused():
    v = block()
    v["sections"][0]["lines"][1] = " ".join(["word"] * 60)
    assert "not a paragraph" in (
        notes_error(v, questions(21, 22), key((21, "a"), (22, "b"))) or "")


def test_a_gap_no_question_asks_about_is_refused():
    assert "no question asks" in (
        notes_error(block(), questions(21), key((21, "a"))) or "")


def test_a_gap_with_no_answer_is_refused():
    assert "no answer in the key" in (
        notes_error(block(), questions(21, 22), key((21, "a"))) or "")


def test_a_non_notes_visual_is_not_this_validators_business():
    assert notes_error({"kind": "flow", "steps": ["a"]}, [], {}) is None
    assert notes_error(None, [], {}) is None


# ---------------------------------------------------------------------------
# Self-answering
# ---------------------------------------------------------------------------


def test_a_line_printing_another_gaps_answer_is_found():
    """A notes block is denser than any other figure — a dozen short lines on
    one topic — so the odds of one line printing the word another asks for are
    higher here than anywhere else."""
    v = block()
    hits = self_answering_lines(v, key((21, "library"), (22, "b")))
    assert [h[0] for h in hits] == ["21"]


def test_a_whole_word_match_only():
    v = block()
    v["sections"][0]["lines"][1] = "Meet at sixteen Bramley Road"
    assert self_answering_lines(v, key((21, "six"))) == []


def test_only_a_heading_is_blanked_never_a_line():
    """A notes line is content: deleting one would take the student's context
    with it, which is worse than the block it started from. A heading is an
    orientation label in exactly the way a diagram callout is."""
    v = block()
    v["sections"][1]["heading"] = "Barn"
    result = {"visual": v, "answer_key": key((21, "a"), (22, "Barn"))}
    assert blank_self_answering_lines(result)
    assert v["sections"][1]["heading"] == ""
    assert len(notes_lines(v)) == 4


def test_a_line_giving_an_answer_away_is_left_for_a_human_to_judge():
    v = block()
    result = {"visual": v, "answer_key": key((21, "library"), (22, "b"))}
    assert blank_self_answering_lines(result) == []
    assert len(notes_lines(v)) == 4


# ---------------------------------------------------------------------------
# Renumbering
# ---------------------------------------------------------------------------


def test_gaps_follow_their_questions_into_global_numbering():
    v = block()
    renumber_notes(v, {"21": "31", "22": "32"})
    assert notes_gaps(v) == ["31", "32"]


def test_a_heading_carrying_a_gap_moves_too():
    v = block()
    v["sections"][0]["heading"] = "Before the __21__"
    v["sections"][0]["lines"][0] = "Bring waterproof boots"
    renumber_notes(v, {"21": "31", "22": "32"})
    assert notes_gaps(v) == ["31", "32"]


def test_a_renumbering_chain_never_moves_a_gap_twice():
    v = block()
    renumber_notes(v, {"21": "22", "22": "23"})
    assert notes_gaps(v) == ["22", "23"]


def test_renumber_carries_the_block_with_the_rest_of_the_set():
    result = {
        "questions": questions(1, 2),
        "answer_key": key((1, "map"), (2, "barn")),
        "visual": {
            "kind": "notes", "style": "notes", "title": "t",
            "sections": [{"heading": "h", "lines": ["Bring a __1__", "Avoid the __2__"]}],
        },
    }
    renumber(result, 30)
    assert [q["number"] for q in result["questions"]] == [31, 32]
    assert visual_slots(result["visual"]) == {"31", "32"}
    assert sorted(result["answer_key"]) == ["31", "32"]


# ---------------------------------------------------------------------------
# What the first live summary actually returned
# ---------------------------------------------------------------------------


def test_a_block_that_calls_itself_a_summary_is_still_a_notes_block():
    """Live 2026-08-27, the first summary this engine ever generated came back
    as `"kind": "summary"` — a reasonable thing for a model to write when the
    style it was given is "summary".

    🚨 `is_notes` gates the validator, the normaliser, the renumbering AND the
    repair, so an unfolded kind sails past every one of them and reaches the
    renderer as a shape it does not know."""
    v = block(SUMMARY_STYLE) | {"kind": "summary"}
    assert is_notes(v)
    out = normalize_notes(v)
    assert out["kind"] == "notes"
    assert out["style"] == SUMMARY_STYLE
    assert notes_gaps(out) == ["21", "22"]


def test_the_folded_kind_reaches_every_gate():
    v = block(SUMMARY_STYLE) | {"kind": "summary"}
    # the validator
    assert notes_error(v, questions(21, 22), key((21, "a"), (22, "b"))) is None
    # the renumbering
    renumber_notes(v, {"21": "31", "22": "32"})
    assert notes_gaps(v) == ["31", "32"]
    # the self-answer detector
    assert self_answering_lines(v, key((31, "library"))) != []


def test_a_kind_nobody_recognises_is_still_not_a_notes_block():
    """The folding is a short list of near-misses, not "anything goes" — a
    plan must not be dragged in and drawn as prose."""
    assert not is_notes({"kind": "plan", "grid": [["a"]]})
    assert not is_notes({"kind": "flow", "steps": ["a"]})


# ---------------------------------------------------------------------------
# Too many headings is untidy, not unusable
# ---------------------------------------------------------------------------


def _seven_sections() -> dict:
    """🔬 The one failure in the 25-type sweep of 2026-09-02: a listening
    note_completion set came back with seven headed groups and died on the way
    in, taking the script, the questions and the answer key with it."""
    return {
        "visual": {
            "kind": "notes", "style": "notes", "title": "Beach clean scheme",
            "sections": [
                {"heading": f"Section {i}",
                 "lines": [f"Line {i}a with a gap __{i}__", f"Line {i}b"]}
                for i in range(1, 8)
            ],
        },
        "questions": [
            {"number": i, "type": "note_completion",
             "question": f"NO MORE THAN TWO WORDS. Complete the notes: __{i}__"}
            for i in range(1, 8)
        ],
        "answer_key": {str(i): f"answer{i}" for i in range(1, 8)},
    }


def test_the_overflow_is_merged_not_refused():
    from app.agents._notes import _MAX_SECTIONS, fold_extra_sections, notes_sections

    r = _seven_sections()
    assert fold_extra_sections(r) == 1
    sections = notes_sections(r["visual"])
    assert len(sections) == _MAX_SECTIONS
    # Every line survives, in order — only a heading is spent.
    lines = [ln for s in sections for ln in s["lines"]]
    assert len(lines) == 14
    assert lines[-2:] == ["Line 7a with a gap __7__", "Line 7b"]


def test_every_gap_survives_the_fold():
    """A merged section that lost a gap would orphan its question, which is
    worse than the untidy block it replaced."""
    from app.agents._notes import fold_extra_sections, notes_lines

    r = _seven_sections()
    fold_extra_sections(r)
    text = " ".join(notes_lines(r["visual"]))
    for n in range(1, 8):
        assert f"__{n}__" in text


def test_a_block_within_the_limit_is_untouched():
    from app.agents._notes import fold_extra_sections

    r = _seven_sections()
    r["visual"]["sections"] = r["visual"]["sections"][:4]
    before = [dict(s) for s in r["visual"]["sections"]]
    assert fold_extra_sections(r) == 0
    assert r["visual"]["sections"] == before


def test_the_count_costs_no_retry_on_the_way_in():
    """The fold runs during normalisation, which is AFTER the way-in hook."""
    from app.agents._notes import notes_error

    r = _seven_sections()
    v, qs, key = r["visual"], r["questions"], r["answer_key"]
    assert "cannot carry 7 sections" in (notes_error(v, qs, key) or "")
    assert notes_error(v, qs, key, after_repairs=False) is None


def test_the_gate_still_refuses_a_block_the_fold_never_reached():
    """A count still over the limit at the final gate means the repair did not
    run, and that is worth refusing."""
    from app.agents._notes import notes_error

    r = _seven_sections()
    assert notes_error(r["visual"], r["questions"], r["answer_key"])

"""A reading diagram must follow its questions into global numbering.

`renumber` already carried `__n__` table cells and the answer key across, but a
`plan` grid and the "Label N" phrasing prompts.py prescribes were left behind.
That is invisible in single-passage practice, where a passage is numbered from
1 and the two numberings coincide; it only appears in a full test, where
passage 2 starts at 14. Found by generating a live paper on 2026-08-23: the
diagram printed gaps 1, 2, 3 beside questions 14, 15, 16.
"""

import json

from app.agents._numbering import renumber


def _diagram_set():
    """A passage shaped like the live one: three diagram gaps, then a TFNG."""
    return {
        "questions": [
            {
                "number": 1,
                "type": "diagram_label_completion",
                "question": "NO MORE THAN TWO WORDS. Label 1 on the diagram: "
                            "the structure where the queen bee lays her eggs.",
            },
            {
                "number": 2,
                "type": "diagram_label_completion",
                "question": "NO MORE THAN TWO WORDS. Label 2 on the diagram: "
                            "the area where the bees store their food.",
            },
            {
                "number": 3,
                "type": "diagram_label_completion",
                "question": "NO MORE THAN TWO WORDS. Label 3 on the diagram: "
                            "the shaft that ventilates the hive.",
            },
            {
                "number": 4,
                "type": "true_false_notgiven",
                "question": "Bees navigate by polarised light.",
            },
        ],
        "answer_key": {"1": "Brood cells", "2": "Honeycomb", "3": "Shaft",
                       "4": "TRUE"},
        "visual": {
            "kind": "plan",
            "title": "Cross-section of a Honey Bee Hive",
            "grid": [
                ["", "", "Entrance"],
                ["", "__1__", ""],
                ["", "", "__2__"],
                ["", "__3__", ""],
                ["", "", "Exit"],
            ],
        },
    }


def test_a_plan_grid_gap_follows_its_question_through_the_renumbering():
    """The gap the student writes into is addressed by number. Left at its
    local number, the figure points at a question that no longer exists."""
    result = renumber(_diagram_set(), 13)

    assert [q["number"] for q in result["questions"]] == [14, 15, 16, 17]
    grid = json.dumps(result["visual"]["grid"])
    for number in (14, 15, 16):
        assert f"__{number}__" in grid
    for number in (1, 2, 3):
        assert f"__{number}__" not in grid


def test_the_question_text_names_the_gap_it_now_points_at():
    """prompts.py requires the question to say which label it asks for. If the
    grid moves and the wording does not, question 14 asks for a label 1 that is
    no longer drawn -- worse than leaving both behind."""
    result = renumber(_diagram_set(), 13)

    assert "Label 14 on the diagram" in result["questions"][0]["question"]
    assert "Label 15 on the diagram" in result["questions"][1]["question"]
    assert "Label 16 on the diagram" in result["questions"][2]["question"]
    assert "Label 1 on" not in result["questions"][0]["question"]


def test_the_grid_and_the_question_text_agree_after_renumbering():
    """The invariant prompts.py states: every diagram question corresponds to
    exactly one `__<n>__` cell and those numbers match the answer key."""
    result = renumber(_diagram_set(), 13)

    grid = json.dumps(result["visual"]["grid"])
    for q in result["questions"]:
        if q["type"] != "diagram_label_completion":
            continue
        number = q["number"]
        assert f"__{number}__" in grid
        assert f"Label {number} " in q["question"]
        assert str(number) in result["answer_key"]


def test_renumbering_does_not_rewrite_numbers_that_are_not_the_label():
    """Only the question's own old number moves. A question that happens to
    mention other figures must survive untouched."""
    data = _diagram_set()
    data["questions"][0]["question"] = (
        "NO MORE THAN TWO WORDS. Label 1 on the diagram: the chamber that "
        "holds 3 combs and up to 2 queens."
    )
    result = renumber(data, 13)

    text = result["questions"][0]["question"]
    assert "Label 14 on the diagram" in text
    assert "holds 3 combs and up to 2 queens" in text


def test_a_zero_offset_leaves_a_single_passage_alone():
    """Single-passage practice renumbers with offset 0. Nothing may move, or
    the path that was always correct starts breaking."""
    before = _diagram_set()
    result = renumber(_diagram_set(), 0)

    assert result["questions"] == before["questions"]
    assert result["visual"]["grid"] == before["visual"]["grid"]
    assert result["answer_key"] == before["answer_key"]


def test_a_listening_plan_of_lettered_rooms_is_untouched():
    """Listening's plan holds room names and letters, never `__n__` gaps. The
    grid rewrite must be a no-op there rather than mangling the letters."""
    data = {
        "questions": [{"number": 1, "type": "map_labelling",
                       "question": "Which letter marks the cafe?"}],
        "answer_key": {"1": "B"},
        "visual": {"kind": "plan", "title": "Campus",
                   "grid": [["A", "corridor", "B"], ["C", "corridor", "D"]]},
    }
    result = renumber(data, 20)

    assert result["visual"]["grid"] == [["A", "corridor", "B"],
                                        ["C", "corridor", "D"]]
    assert result["questions"][0]["number"] == 21


# ---------------------------------------------------------------------------
# The same rule, one figure over: a table cell whose blank sits in a phrase
# ---------------------------------------------------------------------------


def _table_set():
    """A table shaped the way Cambridge prints one.

    Cambridge 19 Test 2 fills its cells with "using an app or by 7 .........."
    and "often listening to a 9 .......... of a song" — the blank inside a
    phrase, which is what tells the student what to write. `renumber` matched
    table cells with an ANCHORED regex, so every one of those was skipped: the
    question moved to global numbering and the cell kept its local number.
    """
    return {
        "questions": [
            {"number": 1, "type": "table_completion",
             "question": "ONE WORD ONLY. Complete the table."},
            {"number": 2, "type": "table_completion",
             "question": "ONE WORD ONLY. Complete the table."},
        ],
        "answer_key": {"1": "app", "2": "chorus"},
        "visual": {
            "kind": "chart",
            "chart_type": "table",
            "title": "A typical guitar lesson",
            "series": [
                {"name": "Tuning", "data": [["Notes", "using an app or by __1__"]]},
                {"name": "Songs", "data": [["Notes", "listening to a __2__ of a song"]]},
            ],
        },
    }


def test_a_phrase_cell_follows_its_question_into_global_numbering():
    result = _table_set()
    renumber(result, offset=13)
    cells = [
        row["data"][0][1] for row in result["visual"]["series"]
    ]
    assert cells == [
        "using an app or by __14__",
        "listening to a __15__ of a song",
    ]
    assert set(result["answer_key"]) == {"14", "15"}


def test_a_bare_blank_cell_still_follows_its_question():
    """The case that already worked, kept so the generalisation cannot lose it."""
    result = _table_set()
    result["visual"]["series"][0]["data"][0][1] = "__1__"
    renumber(result, offset=13)
    assert result["visual"]["series"][0]["data"][0][1] == "__14__"


def test_a_chain_of_renumbers_moves_each_cell_once():
    """1->2 and 2->3 in one pass, or the first gap is renumbered twice."""
    result = _table_set()
    renumber(result, offset=1)
    cells = [row["data"][0][1] for row in result["visual"]["series"]]
    assert cells == ["using an app or by __2__", "listening to a __3__ of a song"]

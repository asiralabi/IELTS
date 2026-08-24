"""The floor plan the generator emits carries semantics only — which room owns
which cell — so these cover the bookkeeping the renderer cannot fix for itself.
"""

from app.agents.answerability import unlettered_map_error, unnamed_place_error
from app.agents import reading_trainer
from app.agents.listening_trainer import _normalize_figure


def _plan(**overrides):
    visual = {
        "kind": "plan",
        "title": "Plan of the Community Centre",
        "grid": [
            ["Kitchen", "Kitchen", "A", "A"],
            ["corridor", "corridor", "corridor", "corridor"],
            ["B", "B", "Reception", "Reception"],
        ],
        "entrance": {"side": "left", "index": 1, "label": "Main entrance"},
    }
    visual.update(overrides)
    return {"visual": visual}


def test_a_ragged_grid_is_squared_off():
    """Rows of different lengths would leave the building with a torn edge."""
    result = _plan(grid=[["A", "A", "corridor"], ["B"], ["C", "C"]])

    _normalize_figure(result)

    assert [len(row) for row in result["visual"]["grid"]] == [3, 3, 3]
    assert result["visual"]["grid"][1] == ["B", "", ""]


def test_room_letters_are_upper_cased():
    """The answer key is written in capitals, so a lowercase cell would leave
    the letter the student writes matching no room on the plan."""
    result = _plan(grid=[["a", "a", "corridor", "b"]])

    _normalize_figure(result)

    assert result["visual"]["grid"][0] == ["A", "A", "corridor", "B"]


def test_a_room_written_in_two_places_is_absorbed_into_its_surroundings():
    """Two separate rooms lettered A give the question two right answers."""
    result = _plan(grid=[
        ["A", "A", "corridor", "Cafe"],
        ["corridor", "corridor", "corridor", "Cafe"],
        ["Cafe", "Cafe", "Cafe", "A"],
    ])

    _normalize_figure(result)

    grid = result["visual"]["grid"]
    assert grid[2][3] == "Cafe"
    assert sum(row.count("A") for row in grid) == 2


def test_separate_corridors_are_left_alone():
    """A plan may legitimately have two walkways; folding the smaller one into
    a room would wall off whatever opened onto it."""
    result = _plan(grid=[
        ["corridor", "A", "A", "corridor"],
        ["Hall", "Hall", "Hall", "Hall"],
    ])

    _normalize_figure(result)

    grid = result["visual"]["grid"]
    assert grid[0] == ["corridor", "A", "A", "corridor"]


def test_the_entrance_slides_along_to_the_nearest_corridor():
    """An entrance opening into a room reads as a mistake on a floor plan."""
    result = _plan(
        grid=[
            ["Kitchen", "Kitchen", "corridor", "A"],
            ["Hall", "Hall", "corridor", "A"],
        ],
        entrance={"side": "top", "index": 0, "label": "Way in"},
    )

    _normalize_figure(result)

    assert result["visual"]["entrance"] == {
        "side": "top",
        "index": 2,
        "label": "Way in",
    }


def test_an_entrance_on_a_side_with_no_corridor_moves_to_one_that_has():
    result = _plan(
        grid=[
            ["Kitchen", "Kitchen", "A", "A"],
            ["corridor", "corridor", "corridor", "corridor"],
            ["B", "B", "Reception", "Reception"],
        ],
        entrance={"side": "top", "index": 2},
    )

    _normalize_figure(result)

    entrance = result["visual"]["entrance"]
    assert entrance["side"] in ("left", "right")
    assert entrance["label"] == "Main entrance"


def test_an_empty_grid_drops_the_visual():
    """A plan with nothing on it renders as an empty box; better to show none."""
    result = _plan(grid=[["", ""], ["", ""]])

    _normalize_figure(result)

    assert result["visual"] is None


def test_a_visual_that_is_not_a_plan_is_untouched():
    result = {"visual": {"kind": "chart", "chart_type": "table", "series": []}}

    _normalize_figure(result)

    assert result["visual"]["kind"] == "chart"


def _asks(*texts):
    """Map questions numbered from 11, the way a part 2 numbers them."""
    return [{"number": 11 + i, "type": "map_labelling", "question": text}
            for i, text in enumerate(texts)]


PLAN = {
    "kind": "plan",
    "grid": [["A", "A", "corridor"], ["Reception", "Reception", "corridor"]],
}


def test_a_letter_the_plan_never_drew_is_rejected():
    """The teacher prints the real name of every place its questions ask
    about and keys letters it never drew, so the figure answers the very
    questions it was meant to pose. Measured on the first hosted part 2."""
    problem = unlettered_map_error(
        _asks("Where is the cafe?", "Where is the library?"),
        PLAN, {"11": "A", "12": "E"},
    )

    assert "Q12 keys E" in problem
    assert "A" in problem


def test_a_plan_carrying_every_keyed_letter_passes():
    problem = unlettered_map_error(
        _asks("Where is the cafe?"), PLAN, {"11": "A"},
    )

    assert problem is None


def test_a_map_answer_written_in_words_is_rejected():
    """A map question is answered with a letter. Keyed with the place's
    name instead, the student who correctly writes the letter is marked
    wrong — and the plan has no way to show a word."""
    problem = unlettered_map_error(
        _asks("Where is the cafe?"), PLAN, {"11": "Reception"},
    )

    assert "11" in problem


def test_the_blocks_rubric_alone_is_not_a_question():
    """The rubric is shared by every question in the block, so a question
    made of nothing else tells the student to write a letter without
    telling them which room to find."""
    problem = unnamed_place_error(
        _asks("Complete the plan below. Write the correct letter for each location.")
    )

    assert "give only the block" in problem


def test_the_same_question_under_two_numbers_is_one_question():
    problem = unnamed_place_error(
        _asks("Where is the cafe?", "Where is the  cafe?")
    )

    assert "11 and 12" in problem


def test_a_question_that_names_its_place_passes():
    """Both the exam's own shapes: the place as a stem, and a direct
    question. 320 of 321 corpus map questions read one of these ways."""
    assert unnamed_place_error(_asks("11  the cafe ......")) is None
    assert unnamed_place_error(_asks("Where is the cafe?")) is None
    assert unnamed_place_error(_asks("Write the letter for the cafe.")) is None


def test_questions_that_are_not_about_the_plan_are_left_alone():
    """A completion question shares its block's rubric too, and the form
    repair — not this check — is what gives it its gap."""
    shared = "Complete the notes below."
    questions = [
        {"number": 1, "type": "note_completion", "question": shared},
        {"number": 2, "type": "note_completion", "question": shared},
    ]

    assert unnamed_place_error(questions) is None


def _labelled_diagram(labels: int) -> dict:
    '''A reading set whose figure numbers `labels` of its parts.'''
    passage = ("The shuttle carries the lower thread beneath the plate. The "
               "bobbin holds that thread. The needle pierces the cloth above "
               "it. ") * 30
    return {
        "title": "The Sewing Machine",
        "passage": passage,
        "visual": {
            "kind": "plan",
            "title": "Cross-section of a sewing machine",
            "grid": [["Hand crank", "Gear system"],
                     [f"__{n}__" for n in range(1, labels + 1)]],
        },
        "questions": [
            {"number": n, "type": "diagram_label_completion",
             "question": f"NO MORE THAN TWO WORDS. Label {n} on the diagram.",
             "word_limit": 2}
            for n in range(1, labels + 1)
        ],
        "answer_key": {str(n): word for n, word in
                       enumerate(["shuttle", "bobbin", "needle"][:labels], start=1)},
    }


def test_a_diagram_numbering_one_part_is_refused():
    '''Measured live: a hosted passage drew a whole sewing machine and asked
    about one part of it. Cambridge never prints a figure for a single blank,
    and all five figure-bearing corpus sets number three or four.'''
    problem = reading_trainer.validate_practice(_labelled_diagram(1))

    assert "only 1 numbered part" in problem


def test_a_diagram_numbering_three_parts_passes():
    assert reading_trainer.validate_practice(_labelled_diagram(3)) is None

"""Picture choice — "Which diagram shows ...? A, B or C".

The exam prints two to four small line drawings and asks which matches what the
speaker described. It reuses the diagram vocabulary at small size, so the
schema is a diagram body per choice and the student answers with a LETTER
rather than by writing into a gap.
"""

from app.agents._diagram import (
    is_picture,
    normalize_picture,
    picture_choices,
    picture_error,
)


def pictures(n=3):
    """The same three parts in a different ARRANGEMENT, which is what makes a
    picture-choice question a question rather than three unrelated drawings.

    Each choice places its parts at explicit cells. Listing the same forms in a
    different order is NOT a different picture — the student sees the drawing,
    not the JSON — and a fixture that did only that was itself the defect the
    twin check exists to catch."""
    layouts = [
        [("tank", 0, 0), ("valve", 1, 0), ("disc", 2, 0)],
        [("tank", 0, 0), ("disc", 1, 0), ("valve", 2, 0)],
        [("valve", 0, 0), ("tank", 1, 0), ("disc", 2, 0)],
        [("disc", 0, 0), ("valve", 1, 0), ("tank", 2, 0)],
    ]
    return {
        "kind": "picture",
        "title": "Which shows the correct filter position?",
        "choices": [
            {"layout": "scene",
             "parts": [{"id": f"p{i}", "form": f, "col": c, "row": r}
                       for i, (f, c, r) in enumerate(cells)]}
            for cells in layouts[:n]
        ],
    }


def asked(answer):
    return (
        [{"number": 11, "type": "picture_choice",
          "question": "Which shows the correct filter position?",
          "options": ["A", "B", "C"]}],
        {"11": answer},
    )


def test_a_healthy_picture_choice_passes():
    v = normalize_picture(pictures())
    assert is_picture(v)
    qs, key = asked("B")
    assert picture_error(v, qs, key) is None


def test_letters_are_assigned_by_position_not_trusted():
    """The letter IS the answer, so a model that lettered them out of order
    would mark a correct student wrong. They are reassigned A, B, C."""
    v = pictures()
    v["choices"][0]["letter"] = "C"
    v["choices"][2]["letter"] = "A"
    assert [c["letter"] for c in normalize_picture(v)["choices"]] == ["A", "B", "C"]


def test_each_choice_is_normalised_through_the_diagram_normaliser():
    """A picture cannot drift away from what the diagram renderer can draw."""
    v = pictures()
    v["choices"][0]["parts"][0]["form"] = "impeller-housing-assembly"
    assert normalize_picture(v)["choices"][0]["parts"][0]["form"] == "box"


def test_one_picture_is_not_a_choice():
    v = normalize_picture(pictures(1))
    qs, key = asked("A")
    assert "pictures to choose between" in (picture_error(v, qs, key) or "")


def test_five_pictures_are_too_many():
    v = pictures(4)
    v["choices"].append(v["choices"][0])
    qs, key = asked("A")
    assert "pictures to choose between" in (
        picture_error(normalize_picture(v), qs, key) or "")


def test_a_picture_with_nothing_drawn_is_refused():
    """A blank box beside three real ones tells the student the answer."""
    v = pictures()
    v["choices"][1]["parts"] = []
    qs, key = asked("A")
    assert "to be a drawing at all" in (
        picture_error(normalize_picture(v), qs, key) or "")


def test_a_gap_on_a_picture_is_refused():
    """The student writes a letter here, so nothing on the pictures is written
    into — a `__n__` means the model has mixed two tasks together."""
    v = pictures()
    v["choices"][0]["parts"][0]["name"] = "__11__"
    qs, key = asked("A")
    assert "numbered gap" in (picture_error(normalize_picture(v), qs, key) or "")


def test_a_letter_no_picture_carries_is_refused():
    v = normalize_picture(pictures())
    qs, key = asked("D")
    assert "but the pictures printed are" in (picture_error(v, qs, key) or "")


def test_a_non_picture_visual_is_not_this_validators_business():
    assert picture_error({"kind": "diagram", "parts": []}, [], {}) is None
    assert picture_error(None, [], {}) is None


def test_choices_survive_as_drawable_bodies():
    """The renderer builds a diagram from each choice, so every one has to
    carry the three fields it reads."""
    for choice in picture_choices(normalize_picture(pictures())):
        assert choice["layout"]
        assert isinstance(choice["parts"], list) and choice["parts"]
        assert isinstance(choice["labels"], list)


# ---------------------------------------------------------------------------
# What the first live picture_choice request actually returned
# ---------------------------------------------------------------------------


def test_a_picture_question_with_no_pictures_is_refused():
    """Live 2026-08-27, the first time Listening was asked for this type: TWO
    picture_choice questions, each offering options A, B and C, and `visual`
    was null. "Which picture best shows the layout of the Formal Gardens?" is
    not answerable by any student without the pictures, so there is no escape
    hatch of the kind a completion item gets for inlining its own gap."""
    from app.agents._diagram import pictureless_error
    qs = [{"number": 1, "type": "picture_choice",
           "question": "Which picture best shows the layout?",
           "options": ["A", "B", "C"]}]
    assert "carries no pictures" in (pictureless_error(qs, None) or "")


def test_two_picture_questions_cannot_share_one_set_of_pictures():
    """A consequence of the schema rather than of the exam: a set carries ONE
    `visual`, so both questions would point at the same drawings."""
    from app.agents._diagram import normalize_picture, pictureless_error
    qs = [{"number": n, "type": "picture_choice", "question": "Which picture?",
           "options": ["A", "B", "C"]} for n in (1, 2)]
    assert "all picture_choice" in (
        pictureless_error(qs, normalize_picture(pictures())) or "")


def test_one_picture_question_with_its_pictures_is_fine():
    from app.agents._diagram import normalize_picture, pictureless_error
    qs = [{"number": 1, "type": "picture_choice", "question": "Which picture?",
           "options": ["A", "B", "C"]}]
    assert pictureless_error(qs, normalize_picture(pictures())) is None


def test_a_set_with_no_picture_questions_is_not_this_rules_business():
    from app.agents._diagram import pictureless_error
    assert pictureless_error(
        [{"number": 1, "type": "short_answer", "question": "x"}], None) is None


def test_two_identical_pictures_are_refused():
    """Two pictures the student cannot tell apart are two correct answers.

    🔬 Found live on the first picture-choice the model drew with placement:
    choices A and B were both [box, box, hose] at the same cells, against a
    question asking which irrigation system was most water-efficient."""
    from app.agents._diagram import normalize_picture, picture_error
    # TWO pictures, so there is no spare to delete: refusing is the only
    # option. With three the twin is dropped instead — see
    # `test_a_repeated_picture_is_dropped`, added 2026-08-29 when refusing a
    # repairable set was found to be the failure in two of three live sweeps.
    v = pictures(2)
    v["choices"][1] = dict(v["choices"][0])
    qs, key = asked("A")
    # Refused twice over, and the count is what it is told first: a two-picture
    # item is not an exam item at all. `exam_count=False` is how the gate that
    # runs after `drop_duplicate_pictures` asks, and the duplicate rule is
    # still what refuses it there.
    assert "not 2" in (picture_error(normalize_picture(v), qs, key) or "")
    assert "the same drawing" in (
        picture_error(normalize_picture(v), qs, key, exam_count=False) or "")


def test_a_picture_drawn_entirely_from_boxes_is_refused():
    """A drawing made of nothing but rectangles is a drawing of nothing —
    the complaint that prompted the whole scene rewrite."""
    from app.agents._diagram import normalize_picture, picture_error
    v = pictures(3)
    # Boxes at genuinely different cells, so the twin check is not what fires.
    for i, choice in enumerate(v["choices"]):
        choice["parts"] = [
            {"id": f"p{j}", "form": "box", "col": j, "row": (j + i) % 3}
            for j in range(3)
        ]
    qs, key = asked("A")
    assert "does not look like anything" in (
        picture_error(normalize_picture(v), qs, key) or "")


def test_the_same_drawing_written_in_a_different_ORDER_is_still_a_twin():
    """🔬 Live 2026-08-27: A listed [coil, box, box] and B listed [coil, box,
    box] at the same cells but in a different order. The first duplicate check
    compared the list as written and passed them; the student sees one
    drawing, and two correct answers."""
    from app.agents._diagram import drop_duplicate_pictures, picture_error
    v = pictures(3)
    v["choices"][1]["parts"] = list(reversed(v["choices"][0]["parts"]))
    qs, key = asked("A")
    # The order does not change what is DRAWN, so the repair sees the twin too
    # — which is the point: matching on the list as written missed it.
    r = {"visual": v, "questions": qs, "answer_key": key}
    assert drop_duplicate_pictures(r) == ["B"]
    # `exam_count=False`, because dropping the twin is what left two — this is
    # the question the post-repair gate asks.
    assert picture_error(
        r["visual"], qs, r["answer_key"], exam_count=False) is None


# ---------------------------------------------------------------------------
# A repeated picture is deleted, not refused
# ---------------------------------------------------------------------------


def _three_pictures(dupe: bool):
    """A, B, C — with B a copy of A when `dupe`."""
    a = [{"id": "tank", "form": "tank", "col": 0, "row": 0},
         {"id": "pipe", "form": "pipe", "col": 1, "row": 0}]
    b = list(a) if dupe else [
        {"id": "tank", "form": "tank", "col": 0, "row": 1},
        {"id": "pipe", "form": "pipe", "col": 0, "row": 0},
    ]
    c = [{"id": "tank", "form": "tank", "col": 1, "row": 1},
         {"id": "pipe", "form": "pipe", "col": 0, "row": 1}]
    return {
        "visual": {
            "kind": "picture",
            "title": "Which shows the correct filter position?",
            "choices": [
                {"letter": "A", "layout": "scene", "parts": a, "labels": []},
                {"letter": "B", "layout": "scene", "parts": b, "labels": []},
                {"letter": "C", "layout": "scene", "parts": c, "labels": []},
            ],
        },
        "questions": [
            {"number": 1, "type": "picture_choice",
             "question": "Which diagram is correct? A, B or C"}
        ],
        "answer_key": {"1": "C"},
    }


def test_a_repeated_picture_is_dropped():
    """Two identical drawings mean two correct answers and no markable set.

    Refusing it discards the script, the questions and the key as well —
    measured as the failure in two of three live sweeps. The drawings are
    identical, so deleting one loses nothing.
    """
    from app.agents._diagram import drop_duplicate_pictures, picture_error

    r = _three_pictures(dupe=True)
    assert drop_duplicate_pictures(r) == ["B"]
    letters = [c["letter"] for c in r["visual"]["choices"]]
    assert letters == ["A", "B"]
    # `exam_count=False`: the drop is what left two, and the gate that runs
    # after it accepts a markable set rather than discarding the generation.
    assert picture_error(r["visual"], r["questions"], r["answer_key"],
                         exam_count=False) is None


def test_the_answer_follows_the_re_lettering():
    """C became B when the old B was deleted."""
    from app.agents._diagram import drop_duplicate_pictures

    r = _three_pictures(dupe=True)
    drop_duplicate_pictures(r)
    assert r["answer_key"]["1"] == "B"


def test_an_answer_naming_the_deleted_copy_moves_to_its_twin():
    """They are the same drawing, so the survivor is equally correct."""
    from app.agents._diagram import drop_duplicate_pictures

    r = _three_pictures(dupe=True)
    r["answer_key"]["1"] = "B"
    drop_duplicate_pictures(r)
    assert r["answer_key"]["1"] == "A"


def test_the_question_stops_offering_a_letter_that_is_gone():
    from app.agents._diagram import drop_duplicate_pictures

    r = _three_pictures(dupe=True)
    drop_duplicate_pictures(r)
    assert "C" not in r["questions"][0]["question"]


def test_a_set_of_distinct_pictures_is_untouched():
    from app.agents._diagram import drop_duplicate_pictures

    r = _three_pictures(dupe=False)
    assert drop_duplicate_pictures(r) == []
    assert len(r["visual"]["choices"]) == 3


def test_two_pictures_are_never_reduced_to_one():
    """`_MIN_CHOICES` is 2 — a single picture is not a choice."""
    from app.agents._diagram import drop_duplicate_pictures

    r = _three_pictures(dupe=True)
    r["visual"]["choices"] = r["visual"]["choices"][:2]
    assert drop_duplicate_pictures(r) == []


# ---------------------------------------------------------------------------
# The exam prints three
# ---------------------------------------------------------------------------


def test_two_pictures_is_not_an_exam_item():
    """🔬 2026-09-01, eight live picture sets: six emitted three choices and
    every one was clean; both that emitted only two had drawn the same picture
    twice, and both were refused. Emitting two is not a second defect beside
    the duplicate — it is the same one, and it is cheap to refuse on the way
    in, where a corrective retry costs nothing that has been generated yet."""
    from app.agents._diagram import normalize_picture, picture_error

    v = pictures(2)
    # Genuinely different drawings, so the duplicate rule has nothing to say.
    v["choices"][1]["parts"][0]["row"] = 3
    qs, key = asked("A")
    assert "not 2" in (picture_error(normalize_picture(v), qs, key) or "")
    # And two is still MARKABLE, which is why the gate that runs after the
    # duplicate repair accepts it rather than discarding the generation.
    assert picture_error(
        normalize_picture(v), qs, key, exam_count=False) is None


def test_three_pictures_is_what_the_exam_prints():
    from app.agents._diagram import normalize_picture, picture_error

    qs, key = asked("A")
    assert picture_error(normalize_picture(pictures(3)), qs, key) is None


# ---------------------------------------------------------------------------
# Every picture the same drawing — the route the count rule did not close
# ---------------------------------------------------------------------------


def _all_the_same(n: int) -> dict:
    """`n` copies of one drawing, lettered A, B, C..."""
    parts = [{"id": "tank", "form": "tank", "col": 0, "row": 0},
             {"id": "pipe", "form": "pipe", "col": 1, "row": 0}]
    return {
        "visual": {
            "kind": "picture",
            "title": "Which shows the correct filter position?",
            "choices": [{"letter": chr(ord("A") + i), "layout": "scene",
                         "parts": [dict(p) for p in parts], "labels": []}
                        for i in range(n)],
        },
        "questions": [{"number": 1, "type": "picture_choice",
                       "question": "Which diagram is correct? A, B or C"}],
        "answer_key": {"1": "A"},
    }


def test_three_pictures_of_the_same_thing_are_refused_on_the_way_in():
    """🔬 Live 2026-09-01, twice in one sweep — and it is what the count fix
    turned the two-picture twin INTO.

    Asking the prompt for three pictures stopped the model emitting two. It did
    not stop it drawing the same thing three times, and this rule was keyed on
    the COUNT: three choices, so the duplicate check did not run and the set
    passed clean on the way in. What refused it was the gate after the figure
    work, by which point a whole generation had been spent.
    """
    from app.agents._diagram import normalize_picture, picture_error

    r = _all_the_same(3)
    qs, key = r["questions"], r["answer_key"]
    problem = picture_error(normalize_picture(r["visual"]), qs, key) or ""
    assert "the same drawing" in problem
    # Named for what it is: not a twin among three, but one drawing printed
    # three times. The message is the corrective retry's instruction.
    assert "all 3 pictures" in problem


def test_the_repair_does_not_manufacture_the_twin_it_reports():
    """The half-collapse was the defect, not the model's drawing.

    `drop_duplicate_pictures` stopped at its floor of two and handed the gate a
    set whose A and B were still identical — so the refusal named a pair the
    repair had just created, and the real fault (three drawings of one thing)
    never appeared in any log. It drops nothing when deletion cannot cure it.
    """
    from app.agents._diagram import drop_duplicate_pictures, picture_error

    r = _all_the_same(3)
    assert drop_duplicate_pictures(r) == []
    assert len(r["visual"]["choices"]) == 3
    assert "the same drawing" in (
        picture_error(r["visual"], r["questions"], r["answer_key"],
                      exam_count=False) or "")


def test_a_repeat_is_still_dropped_while_something_different_survives():
    """The rule is the number of DISTINCT drawings, not the number of letters:
    four choices with three alike still collapse to a markable pair."""
    from app.agents._diagram import drop_duplicate_pictures, picture_error

    r = _all_the_same(4)
    r["visual"]["choices"][3]["parts"][0]["col"] = 2
    assert drop_duplicate_pictures(r) == ["B", "C"]
    assert [c["letter"] for c in r["visual"]["choices"]] == ["A", "B"]
    assert picture_error(r["visual"], r["questions"], r["answer_key"],
                         exam_count=False) is None


def test_the_answer_survives_a_full_collapse():
    """Two copies deleted, and a key naming either still points at the drawing
    the student would have picked."""
    from app.agents._diagram import drop_duplicate_pictures

    r = _all_the_same(4)
    r["visual"]["choices"][3]["parts"][0]["col"] = 2
    r["answer_key"]["1"] = "C"          # the second copy of A
    drop_duplicate_pictures(r)
    assert r["answer_key"]["1"] == "A"
    assert "A or B" in r["questions"][0]["question"]

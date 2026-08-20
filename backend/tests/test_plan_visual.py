"""The floor plan the generator emits carries semantics only — which room owns
which cell — so these cover the bookkeeping the renderer cannot fix for itself.
"""

from app.agents.listening_trainer import _normalize_plan_visual


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

    _normalize_plan_visual(result)

    assert [len(row) for row in result["visual"]["grid"]] == [3, 3, 3]
    assert result["visual"]["grid"][1] == ["B", "", ""]


def test_room_letters_are_upper_cased():
    """The answer key is written in capitals, so a lowercase cell would leave
    the letter the student writes matching no room on the plan."""
    result = _plan(grid=[["a", "a", "corridor", "b"]])

    _normalize_plan_visual(result)

    assert result["visual"]["grid"][0] == ["A", "A", "corridor", "B"]


def test_a_room_written_in_two_places_is_absorbed_into_its_surroundings():
    """Two separate rooms lettered A give the question two right answers."""
    result = _plan(grid=[
        ["A", "A", "corridor", "Cafe"],
        ["corridor", "corridor", "corridor", "Cafe"],
        ["Cafe", "Cafe", "Cafe", "A"],
    ])

    _normalize_plan_visual(result)

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

    _normalize_plan_visual(result)

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

    _normalize_plan_visual(result)

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

    _normalize_plan_visual(result)

    entrance = result["visual"]["entrance"]
    assert entrance["side"] in ("left", "right")
    assert entrance["label"] == "Main entrance"


def test_an_empty_grid_drops_the_visual():
    """A plan with nothing on it renders as an empty box; better to show none."""
    result = _plan(grid=[["", ""], ["", ""]])

    _normalize_plan_visual(result)

    assert result["visual"] is None


def test_a_visual_that_is_not_a_plan_is_untouched():
    result = {"visual": {"kind": "chart", "chart_type": "table", "series": []}}

    _normalize_plan_visual(result)

    assert result["visual"]["kind"] == "chart"

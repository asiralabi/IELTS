"""Writing Task 1 map tasks — two plans of one place, and what changed.

Measured over 71 real Cambridge Task 1 tasks on 2026-08-24: 15.5% name a map
or plan, second only to charts, and the generator was forbidden from producing
one. The prohibition ("the LLM cannot draw those") predated `PlanBlock`, which
listening has drawn since August.

The Listening plan letters its rooms so the recording can be what tells you
which is which. A Task 1 map must NOT: the student is describing the place,
not identifying it, so an area called "B" gives them nothing to write.
"""

import pytest

from app.agents._plan import comparison_error, named_areas, normalize_plan
from app.agents.question_generator import _task1_figure_problem
from app.agents.writing_examiner import format_plan_data


def _plan(title, grid):
    return {"kind": "plan", "title": title, "grid": grid}


BEFORE = _plan("Sports centre, 2005", [
    ["Car park", "Car park", "Reception", "Reception"],
    ["path", "path", "path", "path"],
    ["Sports hall", "Sports hall", "Cafe", "Changing rooms"],
    ["Sports hall", "Sports hall", "Cafe", "Changing rooms"],
])
AFTER = _plan("Sports centre, today", [
    ["Car park", "Car park", "Reception", "Reception"],
    ["path", "path", "path", "path"],
    ["Swimming pool", "Swimming pool", "Gym", "Changing rooms"],
    ["Swimming pool", "Swimming pool", "Gym", "Changing rooms"],
])


def test_named_areas_ignores_walkways_and_blanks():
    assert named_areas(BEFORE) == [
        "Car park", "Reception", "Sports hall", "Cafe", "Changing rooms",
    ]


def test_a_walkway_is_folded_to_the_one_token_the_renderer_draws():
    """The renderer matches the literal "corridor". An outdoor map naturally
    says path or road, so the wording is folded here rather than teaching the
    frontend a second word."""
    cleaned = normalize_plan(_plan("Park", [
        ["Lawn", "path", "Pond"],
        ["Lawn", "road", "Pond"],
    ]))

    assert cleaned["grid"] == [["Lawn", "corridor", "Pond"],
                               ["Lawn", "corridor", "Pond"]]


def test_a_good_pair_is_accepted():
    assert comparison_error([BEFORE, AFTER]) is None


def test_a_lettered_area_is_refused():
    """The Listening convention, which means the opposite thing here."""
    lettered = _plan("Sports centre, today", [
        ["Car park", "Car park", "Reception", "Reception"],
        ["path", "path", "path", "path"],
        ["A", "A", "B", "Changing rooms"],
        ["A", "A", "B", "Changing rooms"],
    ])

    problem = comparison_error([BEFORE, lettered])

    assert problem is not None
    assert "instead of naming it" in problem


def test_two_plans_of_different_sizes_are_refused():
    smaller = _plan("Sports centre, today", [["Gym", "Gym", "Cafe"]])

    problem = comparison_error([BEFORE, smaller])

    assert problem is not None and "different sizes" in problem


def test_a_pair_with_nothing_in_common_is_refused():
    """Two unrelated maps are not one place at two times."""
    unrelated = _plan("A farm, today", [
        ["Barn", "Barn", "Field", "Field"],
        ["path", "path", "path", "path"],
        ["Pond", "Pond", "Orchard", "Orchard"],
        ["Pond", "Pond", "Orchard", "Orchard"],
    ])

    problem = comparison_error([BEFORE, unrelated])

    assert problem is not None and "share no area" in problem


def test_a_pair_with_nothing_changed_is_refused():
    """A task with no change has nothing for 150 words to describe."""
    problem = comparison_error([BEFORE, _plan("Sports centre, today", BEFORE["grid"])])

    assert problem is not None and "no change to describe" in problem


def test_one_plan_is_not_a_map_task():
    assert comparison_error([BEFORE]) is not None
    assert comparison_error(BEFORE) is not None


class TestTask1FigureGate:
    def test_a_map_task_passes_and_is_normalised(self):
        result = {"visuals": [dict(BEFORE), dict(AFTER)]}

        assert _task1_figure_problem(result) is None
        # The walkway wording is folded on the way through.
        assert result["visuals"][0]["grid"][1] == ["corridor"] * 4
        assert result["visual"] is None

    def test_a_chart_task_still_passes(self):
        result = {"visual": {"kind": "chart", "chart_type": "bar",
                             "series": [{"name": "a", "data": [["x", 1]]}]}}

        assert _task1_figure_problem(result) is None

    def test_a_task_with_no_figure_at_all_is_refused(self):
        problem = _task1_figure_problem({"visual": None})

        assert problem is not None and "must carry a figure" in problem

    def test_a_broken_pair_is_refused_rather_than_silently_dropped(self):
        problem = _task1_figure_problem({"visuals": [dict(BEFORE), dict(BEFORE)]})

        assert problem is not None and "no change to describe" in problem


class TestExaminerSeesTheMap:
    def test_the_examiner_is_told_what_changed(self):
        """It marks Task Achievement against what the student saw, so it has to
        be shown the same thing — and the changes ARE the content."""
        block = format_plan_data([BEFORE, AFTER])

        assert "Sports centre, 2005" in block
        assert "Sports centre, today" in block
        assert "Present in both: Car park, Changing rooms, Reception" in block
        assert "Gone by the second plan: Cafe, Sports hall" in block
        assert "New in the second plan: Gym, Swimming pool" in block

    @pytest.mark.parametrize("bad", [None, [], [BEFORE], "x", [BEFORE, {"kind": "chart"}]])
    def test_anything_unusable_renders_as_nothing(self, bad):
        """Same bargain as format_chart_data: never raise into an evaluation."""
        assert format_plan_data(bad) == ""

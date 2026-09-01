"""The flow chart figure, in both papers.

The exam prints the process a passage or a Part 3 discussion describes as a
chain of boxes read top to bottom, with some of the words inside them numbered.
Nothing could draw one until now: the reading prompt allowed only a table or a
plan, and `_PART_SPECS[3]` said "No figure is needed - set `visual` to null".

Shapes here are taken from the 12 real charts in the parsed Cambridge books
(`tools/_diag_flow_chart_shape.py`), not invented: 4-10 boxes, 3-7 gaps, gaps
ascending down a single unbranched chain.
"""

import pytest

from app.agents import listening_trainer, reading_trainer
from app.agents._flow import flow_error, flow_gaps, flow_steps, normalize_flow
from app.agents._numbering import renumber
from app.agents.answerability import dangling_completions, visual_slots


def _chart(steps=None, title="Stages in the experiment"):
    return {
        "kind": "flow",
        "title": title,
        "steps": steps
        or [
            "Select seeds of different __1__",
            "Measure and record the __2__ and size of each one",
            "Use a different __3__ for each seed and label it",
            "After about three weeks, record the height of the plant",
            "Investigate the findings",
        ],
    }


def _questions(numbers=(1, 2, 3)):
    return [
        {
            "number": n,
            "type": "flow_chart_completion",
            "question": f"ONE WORD ONLY. Complete step {n} of the flow chart.",
            "word_limit": 1,
        }
        for n in numbers
    ]


def _key(numbers=(1, 2, 3)):
    return {str(n): f"answer{n}" for n in numbers}


# ---------------------------------------------------------------------------
# The shape itself


def test_a_well_formed_chart_passes():
    assert flow_error(_chart(), _questions(), _key()) is None


def test_a_visual_that_is_not_a_flow_chart_is_not_judged():
    """flow_error runs on every set, so it has to be silent about the plan and
    the table - both of which have their own checks and neither of which has a
    `steps` list to read."""
    plan = {"kind": "plan", "title": "Community Centre", "grid": [["A", "A"]]}

    assert flow_error(plan, _questions(), _key()) is None
    assert flow_error(None, _questions(), _key()) is None


def test_a_chain_of_two_is_refused():
    problem = flow_error(
        _chart(["First, gather the __1__", "Then record the __2__"]),
        _questions((1, 2)),
        _key((1, 2)),
    )

    assert problem and "2 step(s)" in problem


def test_gaps_must_run_down_the_chain():
    """The student reads top box to bottom box, so a chart numbered 1, 3, 2
    sends them backwards mid-figure. Every one of the 12 real charts ascends."""
    problem = flow_error(
        _chart([
            "Select seeds of different __1__",
            "Use a different __3__ for each seed",
            "Measure and record the __2__ of each one",
            "Investigate the findings",
        ]),
        _questions(),
        _key(),
    )

    assert problem and "ascend" in problem


def test_a_box_that_is_only_its_gap_is_refused():
    """A blank with no stage around it cannot be answered from the passage -
    the student is not told what part of the process they are filling in."""
    problem = flow_error(
        _chart([
            "Select seeds of different __1__",
            "__2__",
            "Use a different __3__ for each seed and label it",
            "Investigate the findings",
        ]),
        _questions(),
        _key(),
    )

    assert problem and "step(s) 2" in problem


def test_two_gaps_may_not_share_a_number():
    problem = flow_error(
        _chart([
            "Select seeds of different __1__",
            "Measure and record the __2__ of each one",
            "Use a different __2__ for each seed",
            "Investigate the findings",
        ]),
        _questions((1, 2)),
        _key((1, 2)),
    )

    assert problem and "more than once" in problem


def test_a_chart_with_two_gaps_is_a_drawing_not_a_question_block():
    """The same floor `ad0e767` put under the diagram: the least Cambridge ever
    prints is three."""
    problem = flow_error(
        _chart([
            "Select seeds of different __1__",
            "Measure and record the __2__ of each one",
            "Investigate the findings",
        ]),
        _questions((1, 2)),
        _key((1, 2)),
    )

    assert problem and "at least 3" in problem


def test_a_gap_with_no_question_is_refused():
    problem = flow_error(_chart(), _questions((1, 2)), _key((1, 2)))

    assert problem and "no question" in problem


def test_a_gap_with_no_answer_is_refused():
    problem = flow_error(_chart(), _questions(), _key((1, 2)))

    assert problem and "answer_key" in problem


def test_a_gap_keyed_with_a_sentence_fragment_is_refused():
    """A live chart (2026-08-25) put every gap AFTER an already complete step
    and keyed the fragment that would have begun the next clause -- "The team
    defines the initial aim of the project ______" answered 'to create'.
    Structurally that set is perfect: 4 gaps, ascending, each with a question
    and a key. Only the answers give it away.

    Refused rather than repaired, unlike the self-answering box: re-keying a
    gap whose POSITION is wrong does not fix the step. Scoped to the chart, so
    it refuses nothing that was ever trained on.
    """
    problem = flow_error(
        _chart([
            "The team defines the initial aim of the project __1__",
            "The team analyses the data to identify trends __2__",
            "The team develops a prototype of the new product __3__",
            "The team launches the product",
        ]),
        _questions(),
        {"1": "to create", "2": "to identify", "3": "of the"},
    )

    assert problem and "sentence fragments" in problem
    assert "'to create'" in problem


def test_an_ordinary_answer_is_not_mistaken_for_a_fragment():
    """The rule is the infinitive marker, the relative pronouns and the bare
    copula -- NOT every sentence-continuing word. A prepositional answer is
    legitimate ("when should you book? / in advance"), and the wide form
    refuses two such answers in the corpus."""
    assert flow_error(
        _chart([
            "Book the tickets __1__",
            "Collect them with a __2__ at the desk",
            "Travel on the __3__ service",
            "Keep the receipt",
        ]),
        _questions(),
        {"1": "in advance", "2": "library card", "3": "express"},
    ) is None


# ---------------------------------------------------------------------------
# Normalisation


def test_normalize_drops_an_empty_box_and_folds_the_gap_form():
    cleaned = normalize_flow({
        "kind": "flow",
        "title": "  Assignment plan  ",
        "steps": [
            "Decide on the research question",
            "   ",
            "Choose a ___4___ of students",
        ],
    })

    assert cleaned["title"] == "Assignment plan"
    assert cleaned["steps"] == [
        "Decide on the research question",
        "Choose a __4__ of students",
    ]


def test_normalize_leaves_a_plan_alone():
    assert normalize_flow({"kind": "plan", "grid": [["A"]]}) is None


def test_a_listening_part_cleans_whichever_figure_it_came_back_with():
    """`_normalize_figure` was `_normalize_plan_visual` and returned early on
    anything that was not a grid, so a chart would have reached the student
    with its blank boxes and its `___4___` gaps intact."""
    part = {"visual": {
        "kind": "flow",
        "title": "Assignment plan",
        "steps": ["Decide on the ___26___", "", "Analyse the results"],
    }}

    listening_trainer._normalize_figure(part)

    assert part["visual"]["steps"] == [
        "Decide on the __26__",
        "Analyse the results",
    ]


def test_a_listening_part_still_cleans_its_plan():
    part = {"visual": {
        "kind": "plan",
        "title": "Community Centre",
        "grid": [["A", "A", "corridor"], ["B", "B", "corridor"]],
    }}

    listening_trainer._normalize_figure(part)

    assert part["visual"]["kind"] == "plan"
    assert part["visual"]["grid"]


def test_the_gap_form_normalize_writes_is_the_one_visual_slots_reads():
    """`visual_slots` regexes the serialised figure, and everything downstream
    - the dangling check, the renumbering - asks it which questions the figure
    supplies. A cleaned chart it could not read would silently supply none."""
    cleaned = normalize_flow({
        "kind": "flow",
        "title": "Assignment plan",
        "steps": ["Choose a ___4___ of students", "Analyse the results"],
    })

    assert visual_slots(cleaned) == {"4"}


# ---------------------------------------------------------------------------
# What the chart buys the questions


def test_a_chart_answers_the_question_that_points_at_it():
    """Without a figure a flow_chart_completion item must inline its own gap,
    because nothing renders the block it names. The chart is the other way out
    of that - and the corpus needs both, since 6 of the 227 reading sets write
    the inline form and none of them draws a chart."""
    pointing = [{
        "number": 1,
        "type": "flow_chart_completion",
        "question": "ONE WORD ONLY. Complete the flow chart below.",
    }]

    assert dangling_completions(pointing, None)
    assert not dangling_completions(pointing, _chart())


# ---------------------------------------------------------------------------
# Renumbering - the bug b089b4a fixed for the grid, on the new figure


def test_a_charts_gaps_follow_its_questions_into_global_numbering():
    """The grid shipped gaps 1, 2, 3 beside questions 14, 15, 16 because only a
    table cell was ever rewritten. A flow chart's gaps sit mid-sentence, so
    they need substituting rather than matching, and would have been left
    behind in exactly the same way."""
    result = {
        "questions": _questions(),
        "answer_key": _key(),
        "visual": _chart(),
    }

    renumber(result, 13)

    assert flow_gaps(result["visual"]) == ["14", "15", "16"]
    assert flow_steps(result["visual"])[0] == "Select seeds of different __14__"
    assert sorted(result["answer_key"]) == ["14", "15", "16"]


def test_renumbering_leaves_a_number_that_is_not_a_gap_alone():
    """A step reading "After 3 weeks" is prose, not a gap. Only the `__n__`
    form moves - the same restraint `_relabel` shows on "Label N"."""
    result = {
        "questions": _questions((1,)),
        "answer_key": _key((1,)),
        "visual": _chart([
            "After 3 weeks, record the __1__",
            "Investigate the findings",
        ]),
    }

    renumber(result, 20)

    assert flow_steps(result["visual"])[0] == "After 3 weeks, record the __21__"


def test_the_renumbered_chart_still_passes_its_own_validator():
    result = {
        "questions": _questions(),
        "answer_key": _key(),
        "visual": _chart(),
    }

    renumber(result, 26)

    assert flow_error(
        result["visual"], result["questions"], result["answer_key"]
    ) is None


# ---------------------------------------------------------------------------
# Both trainers route and steer it


def test_listening_part_three_asks_for_a_chart():
    """The spec used to say "No figure is needed - set `visual` to null", which
    is why Part 3 was one of the three open figure gaps."""
    spec = listening_trainer._PART_SPECS[3]

    assert "flow" in spec["figure"].lower()
    assert "no figure is needed" not in spec["figure"].lower()


def test_every_part_that_asks_for_a_figure_skips_the_checkpoint():
    """0 of the 212 listening SFT sets write a flow_chart_completion question,
    so the checkpoint has never seen one - the same reason parts 1 and 2 route
    hosted."""
    canon = listening_trainer.canon

    assert 3 in listening_trainer._FIGURE_PARTS
    assert canon("flow_chart_completion") in listening_trainer._FIGURE_ASK


def test_a_reading_flow_chart_ask_routes_off_the_checkpoint():
    assert reading_trainer._needs_a_figure(["flow_chart_completion"])


@pytest.mark.parametrize(
    "system", ["READING_TRAINER_SYSTEM", "LISTENING_TRAINER_SYSTEM"]
)
def test_both_prompts_describe_the_schema_the_renderer_reads(system):
    """A figure kind the prompt never describes cannot be generated, which is
    what made this a backend job rather than a renderer one."""
    from app.llm import prompts

    text = getattr(prompts, system)

    assert '"kind": "flow"' in text
    assert '"steps"' in text


# ---------------------------------------------------------------------------
# The lettered flow chart — the other half of what the exam prints
# ---------------------------------------------------------------------------


def _lettered_chart():
    """"Choose FIVE answers from the box and write the correct letter, A-H."

    Of the 12 real Cambridge flow charts distilled into
    `data/figure_knowledge/`, 5 are answered from a lettered box against 5 from
    the text. The engine allowed only the write-in form, so the model kept
    producing the commoner one and `flow_error` kept refusing it: a bare "A"
    has no content word, so `_fragment_answer` flagged it. Two live listening
    sets died that way on 2026-08-28.
    """
    return {
        "visual": {
            "kind": "flow",
            "title": "Mouse feeding experiment",
            "steps": [
                "Choose mice which are all the same __1__",
                "Divide the mice into two groups, each with a different __2__",
                "Put each group in a separate cage",
                "Place them in a weighing chamber to prevent __3__",
            ],
        },
        "questions": [
            {"number": n, "type": "flow_chart_completion",
             "question": "Choose the correct letter.",
             "options": ["size", "escape", "age", "water"]}
            for n in (1, 2, 3)
        ],
        "answer_key": {"1": "A", "2": "C", "3": "B"},
    }


def test_a_lettered_answer_is_accepted_when_the_question_offers_letters():
    r = _lettered_chart()
    assert flow_error(r["visual"], r["questions"], r["answer_key"]) is None


def test_a_lettered_answer_with_no_options_is_still_refused():
    """A blank with nothing to choose from is what the refusal is for."""
    r = _lettered_chart()
    for q in r["questions"]:
        q.pop("options")
    assert "fragments" in (
        flow_error(r["visual"], r["questions"], r["answer_key"]) or ""
    )


def test_the_write_in_form_is_unaffected():
    r = _lettered_chart()
    for q in r["questions"]:
        q.pop("options")
    r["answer_key"] = {"1": "age", "2": "diet", "3": "escape"}
    assert flow_error(r["visual"], r["questions"], r["answer_key"]) is None

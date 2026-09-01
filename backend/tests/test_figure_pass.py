"""The second pass that draws the figure, and the callout rewrite beside it.

Measured 2026-08-27 over five live reading sets: three figures usable, none
ever using containment, and the failures all the same shape — a `pump` drawn
as a plain `box`, nothing joined to anything, a bare `__1__` for a callout.
The one-pass prompt has to write a passage, questions, an answer key and a
figure at once, and the figure is what it skims.

These cover the two things that make a second pass safe rather than merely
different: it is JUDGED before it is kept, and it never leaves the set worse
than it found it.
"""

import asyncio

import pytest

from app.agents import _figure_pass
from app.agents._figure_pass import (
    already_good,
    figure_richness,
    redraw_diagram,
    repair_self_answering_callouts,
)


class _Stub:
    """Stands in for the generator client and records what it was sent."""

    is_finetune = False

    def __init__(self, replies, key="visual"):
        self.replies = list(replies)
        self.key = key
        self.prompts: list[str] = []
        self.systems: list[str] = []

    async def complete_json(self, system, messages, **kwargs):
        self.systems.append(system)
        self.prompts.append(messages[0]["content"])
        if not self.replies:
            return {self.key: None}
        return {self.key: self.replies.pop(0)}


def _use(monkeypatch, replies, key="visual"):
    stub = _Stub(replies, key)
    monkeypatch.setattr(_figure_pass, "get_llm_client", lambda *a, **k: stub)
    return stub


# The figure a first pass returns: real enough to ship, poor enough to be worth
# redrawing — two forms, nothing joined, and bare blanks for callouts.
def thin():
    return {
        "kind": "diagram",
        "title": "Cross-section of a vertical farm",
        "layout": "scene",
        "parts": [
            {"id": "trays", "form": "platform", "col": 0, "row": 0},
            {"id": "pump", "form": "box", "col": 1, "row": 0},
            {"id": "tank", "form": "tank", "col": 0, "row": 1},
            {"id": "floor", "form": "ground", "col": 0, "row": 2, "w": 3},
        ],
        "labels": [
            {"at": "trays", "text": "Seedlings sit on the __1__"},
            {"at": "pump", "text": "Water is moved by the __2__"},
            {"at": "tank", "text": "Solution is held in the __3__"},
        ],
    }


# What a good second pass returns: more distinct forms, parts joined by a pipe
# and one drawn INSIDE another, callouts carrying a clause each.
def rich():
    return {
        "kind": "diagram",
        "title": "Cross-section of a vertical farm",
        "layout": "scene",
        "parts": [
            {"id": "trays", "form": "stack", "name": "Growing trays",
             "col": 1, "row": 0},
            {"id": "lamp", "form": "panel", "col": 2, "row": 0},
            {"id": "pump", "form": "disc", "col": 2, "row": 1},
            {"id": "tank", "form": "tank", "col": 1, "row": 1},
            {"id": "solution", "form": "liquid", "in": "tank",
             "col": 1, "row": 1},
            {"id": "floor", "form": "ground", "col": 0, "row": 2, "w": 4},
        ],
        "links": [{"from": "tank", "to": "trays", "style": "pipe"}],
        "labels": [
            {"at": "trays", "text": "Seedlings are raised on the __1__ under lights"},
            {"at": "pump", "text": "The __2__ lifts solution to the upper level"},
            {"at": "tank", "text": "Nutrient solution collects in the __3__ below"},
        ],
    }


def questions(*numbers):
    return [
        {"number": n, "type": "diagram_label_completion",
         "question": f"NO MORE THAN TWO WORDS. Label {n}."}
        for n in numbers
    ]


KEY = {"1": "shelves", "2": "circulation pump", "3": "reservoir"}


def result_with(visual):
    return {
        "passage": "A vertical farm stacks its shelves under lamps. A "
                   "circulation pump lifts solution from the reservoir.",
        "questions": questions(1, 2, 3),
        "answer_key": dict(KEY),
        "visual": visual,
    }


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def test_richness_counts_the_three_measured_defects():
    forms, joins, context = figure_richness(thin())
    # `box` and `ground` are excluded: a drawing of nothing but boxes standing
    # on hatching is the complaint, and counting the hatching hid it.
    assert (forms, joins) == (2, 0)
    assert context == 3

    forms, joins, context = figure_richness(rich())
    assert forms == 4
    # One `links` entry plus one part drawn `in` another.
    assert joins == 2


def test_richness_of_a_non_diagram_is_zero():
    assert figure_richness(None) == (0, 0, 0)
    assert figure_richness({"kind": "flow"}) == (0, 0, 0)


# ---------------------------------------------------------------------------
# A figure the first pass got right does not pay for a second call
# ---------------------------------------------------------------------------


def test_a_good_figure_is_left_alone_without_a_call(monkeypatch):
    stub = _use(monkeypatch, [rich()])
    r = result_with(rich())
    assert asyncio.run(redraw_diagram(r, r["passage"])) is False
    assert stub.prompts == []


def test_a_figure_rich_in_shapes_but_bare_in_callouts_is_still_redrawn(
    monkeypatch,
):
    """The defect the student actually sees.

    Live set 2 of 2026-08-28 scored 5 distinct forms and 3 joins — a good
    drawing — and hung three bare blanks off it. A bar that looked only at the
    drawing would have skipped exactly the set that needed the pass most.
    """
    bare = rich()
    for i, n in enumerate((1, 2, 3)):
        bare["labels"][i]["text"] = f"__{n}__"
    assert already_good(bare) is False
    stub = _use(monkeypatch, [rich()])
    r = result_with(bare)
    assert asyncio.run(redraw_diagram(r, r["passage"])) is True
    assert len(stub.prompts) == 1


def _figure_scoring(forms: int, joins: int, bare_callouts: int) -> dict:
    """A figure built to hit a given (forms, joins, context) score."""
    shapes = ["tank", "disc", "panel", "platform", "stack", "coil", "valve"]
    parts = [
        {"id": f"p{i}", "form": shapes[i], "col": i, "row": 0}
        for i in range(forms)
    ]
    parts.append({"id": "floor", "form": "ground", "col": 0, "row": 2, "w": 4})
    links = [
        {"from": "p0", "to": f"p{i}", "style": "pipe"}
        for i in range(1, min(joins, forms) + 1)
    ]
    return {
        "kind": "diagram",
        "title": "t",
        "layout": "scene",
        "parts": parts,
        "links": links,
        "labels": [
            {"at": "p0", "text": f"__{n}__"} for n in range(1, bare_callouts + 1)
        ],
    }


@pytest.mark.parametrize(
    "forms,joins", [(1, 0), (5, 3), (4, 2), (2, 2), (3, 0)]
)
def test_the_bar_sits_above_every_live_figure_measured(forms, joins):
    """The five live sets of 2026-08-28. The redraw improved every one.

    A bar any of them cleared would have skipped a figure that needed the pass,
    so this pins the threshold to the evidence rather than to a round number.
    """
    assert already_good(_figure_scoring(forms, joins, 3)) is False


# ---------------------------------------------------------------------------
# The redraw is kept only when it is better
# ---------------------------------------------------------------------------


def test_a_richer_redraw_replaces_the_figure(monkeypatch):
    _use(monkeypatch, [rich()])
    r = result_with(thin())
    assert asyncio.run(redraw_diagram(r, r["passage"])) is True
    assert r["visual"]["parts"][0]["form"] == "stack"
    assert r["visual"]["links"]


def test_the_answers_are_handed_over_so_the_figure_can_avoid_them(monkeypatch):
    """Without them the model writes one gap's answer into another's callout."""
    stub = _use(monkeypatch, [rich()])
    r = result_with(thin())
    asyncio.run(redraw_diagram(r, r["passage"]))
    sent = stub.prompts[0]
    for answer in KEY.values():
        assert answer in sent
    assert "A vertical farm stacks its shelves" in sent


def test_a_blander_redraw_is_discarded(monkeypatch):
    """A legal figure is not automatically an improvement."""
    blander = rich()
    blander["links"] = []
    for part in blander["parts"]:
        part.pop("in", None)
        part["form"] = "box" if part["form"] != "ground" else "ground"
    _use(monkeypatch, [blander])
    r = result_with(thin())
    assert asyncio.run(redraw_diagram(r, r["passage"])) is False
    assert r["visual"] == thin()


def test_an_identical_redraw_is_discarded(monkeypatch):
    _use(monkeypatch, [thin()])
    r = result_with(thin())
    assert asyncio.run(redraw_diagram(r, r["passage"])) is False


def test_a_redraw_that_drops_a_gap_is_discarded(monkeypatch):
    """A dropped gap leaves a question pointing at nothing."""
    short = rich()
    short["labels"] = short["labels"][:2]
    _use(monkeypatch, [short])
    r = result_with(thin())
    assert asyncio.run(redraw_diagram(r, r["passage"])) is False
    assert r["visual"] == thin()


def test_a_redraw_that_invents_a_gap_is_discarded(monkeypatch):
    """Audit check #24: a blank no question asks about."""
    extra = rich()
    extra["labels"].append({"at": "lamp", "text": "Lamps run for __9__ hours"})
    _use(monkeypatch, [extra])
    r = result_with(thin())
    assert asyncio.run(redraw_diagram(r, r["passage"])) is False


# ---------------------------------------------------------------------------
# Rescuing a figure that would otherwise take the whole set down
# ---------------------------------------------------------------------------


def filler_boxes():
    """The commonest cause of a discarded set, measured over three live sweeps.

    The first pass draws a couple of real parts and then a row of plain boxes
    whose only content is a gap, so the student is asked to name blank
    rectangles. `diagram_error` refuses it — and refusing it discards the
    passage, the questions and the answer key with it.
    """
    return {
        "kind": "diagram",
        "title": "Cross-section of a vertical farm",
        "layout": "scene",
        "parts": [
            {"id": "tank", "form": "tank", "col": 0, "row": 0},
            {"id": "a", "form": "box", "name": "__1__", "col": 1, "row": 0},
            {"id": "b", "form": "box", "name": "__2__", "col": 2, "row": 0},
            {"id": "c", "form": "box", "name": "__3__", "col": 3, "row": 0},
        ],
        "labels": [],
    }


def test_a_figure_that_would_be_refused_is_rescued_by_any_valid_redraw(monkeypatch):
    """Validity is the whole bar when the original is already unusable.

    The redraw was reaching a legal figure and being thrown away for not also
    being *richer* than the broken one — so the set died anyway. A plainer
    figure that ships beats a richer one that does not exist.
    """
    r = result_with(filler_boxes())
    from app.agents._diagram import diagram_error

    assert diagram_error(r["visual"], r["questions"], r["answer_key"]) is not None

    # Deliberately no richer than what it replaces: same forms, no joins.
    plain = {
        "kind": "diagram",
        "title": "Cross-section of a vertical farm",
        "layout": "scene",
        "parts": [
            {"id": "tank", "form": "tank", "col": 0, "row": 1},
            {"id": "trays", "form": "platform", "col": 1, "row": 0},
            {"id": "floor", "form": "ground", "col": 0, "row": 2, "w": 3},
        ],
        "labels": [
            {"at": "trays", "text": "Seedlings are raised on the __1__"},
            {"at": "tank", "text": "Solution collects in the __2__"},
            {"at": "floor", "text": "The frame stands on the __3__"},
        ],
    }
    _use(monkeypatch, [plain])
    assert asyncio.run(redraw_diagram(r, r["passage"])) is True
    assert diagram_error(r["visual"], r["questions"], r["answer_key"]) is None


def test_a_broken_figure_is_never_skipped_as_good_enough(monkeypatch):
    """A figure can score well and still be refused.

    `already_good` reads shapes, joins and callouts. Filler boxes can pass all
    three, and skipping the call to save one request threw the set away.
    """
    rich_but_broken = rich()
    rich_but_broken["parts"].append(
        {"id": "x", "form": "box", "name": "__1__", "col": 3, "row": 0}
    )
    rich_but_broken["parts"].append(
        {"id": "y", "form": "box", "name": "__2__", "col": 4, "row": 0}
    )
    stub = _use(monkeypatch, [rich()])
    r = result_with(rich_but_broken)
    asyncio.run(redraw_diagram(r, r["passage"]))
    assert stub.prompts, "a refusable figure must not be skipped"


def test_a_redraw_that_hides_its_gaps_in_part_names_is_discarded(monkeypatch):
    """A better drawing carrying the same empty question.

    Live 2026-08-28: asked to redraw the turbine, the model satisfied every
    other rule by moving all three gaps into part names and writing no callouts
    at all. It scored better on shapes and joins, so a check on those alone
    accepted a figure with no passage context on it — the defect this pass
    exists to remove.
    """
    hidden = rich()
    hidden["labels"] = []
    for i, n in enumerate((1, 2, 3)):
        hidden["parts"][i]["name"] = f"__{n}__"
    _use(monkeypatch, [hidden])
    r = result_with(thin())
    assert asyncio.run(redraw_diagram(r, r["passage"])) is False
    assert r["visual"] == thin()


def test_a_strata_section_may_print_its_blanks_in_the_bands(monkeypatch):
    """`layers` is exempt: the exam really does print the blank in the band.

    Cambridge 2 Test 1's airport cross-section numbers the mud and the clay
    inside their own strata, where the position between the water and the sand
    is the context.
    """
    section = {
        "kind": "diagram",
        "title": "Cross-section of the airport site",
        "layout": "layers",
        "parts": [
            {"id": "runway", "form": "band", "name": "Granite runways"},
            {"id": "mud", "form": "soil", "name": "__1__"},
            {"id": "water", "form": "water", "name": "Water"},
            {"id": "clay", "form": "clay", "name": "__2__"},
            {"id": "sand", "form": "sand", "name": "__3__"},
        ],
        "labels": [],
    }
    _use(monkeypatch, [section])
    # From a figure with bare blanks, so the section is genuinely an
    # improvement. Started from `thin()`, whose callouts already carry a
    # clause each, the richness rule refuses it — correctly: trading three
    # contextual callouts for three band names is a downgrade.
    bare = thin()
    for i, n in enumerate((1, 2, 3)):
        bare["labels"][i]["text"] = f"__{n}__"
    r = result_with(bare)
    assert asyncio.run(redraw_diagram(r, r["passage"])) is True
    assert r["visual"]["layout"] == "layers"


def test_a_redraw_that_prints_an_answer_is_discarded(monkeypatch):
    leaky = rich()
    leaky["parts"][1]["name"] = "Reservoir"
    _use(monkeypatch, [leaky])
    r = result_with(thin())
    assert asyncio.run(redraw_diagram(r, r["passage"])) is False
    assert r["visual"] == thin()


def test_a_null_visual_is_taken_as_the_model_declining(monkeypatch):
    """`{"visual": null}` is a valid answer, not worth a retry."""
    stub = _use(monkeypatch, [None])
    r = result_with(thin())
    assert asyncio.run(redraw_diagram(r, r["passage"])) is False
    assert len(stub.prompts) == 1


def test_a_broken_call_leaves_the_figure_alone(monkeypatch):
    class Boom:
        is_finetune = False

        async def complete_json(self, *a, **k):
            raise RuntimeError("hosted endpoint said 410")

    monkeypatch.setattr(_figure_pass, "get_llm_client", lambda *a, **k: Boom())
    r = result_with(thin())
    assert asyncio.run(redraw_diagram(r, r["passage"])) is False
    assert r["visual"] == thin()


def test_a_set_with_no_diagram_is_skipped(monkeypatch):
    stub = _use(monkeypatch, [rich()])
    r = result_with({"kind": "flow", "steps": ["a", "b", "c"]})
    assert asyncio.run(redraw_diagram(r, r["passage"])) is False
    assert stub.prompts == []


def test_the_prompt_offers_only_forms_the_validator_knows(monkeypatch):
    """The drawing prompt's vocabulary is generated from the normaliser's.

    Written out by hand it drifted: `stack` and `panel` reached one list and
    not the other when the vocabulary was last widened, and a form the prompt
    offers but the normaliser does not know is silently replaced by `box` —
    which is the exact defect this whole pass exists to fix.
    """
    from app.agents._diagram import _APPARATUS_FORMS

    system = _figure_pass._system()
    for form in _APPARATUS_FORMS:
        assert f"`{form}`" in system
    assert "{apparatus_forms}" not in system


# ---------------------------------------------------------------------------
# A callout may not define its own answer
# ---------------------------------------------------------------------------


# Verbatim from the books, rendered with `tools/cambridge_figure_atlas.py`.
# The guard has to clear every one of these: they are what a real callout
# looks like, and refusing them would refuse the exam.
CAMBRIDGE_CALLOUTS = [
    "Hydraulic motors drive __22__",                                  # C11 T1
    "Air bubbles result from the __25__ behind blades",               # C9 T3
    "Sea life not in danger due to the fact that blades are "
    "comparatively __24__",                                           # C9 T3
    "Whole tower can be raised for __24__ and the extraction of "
    "seaweed from the blades",                                        # C9 T3
    "A pair of __20__ are lifted in order to shut out water from "
    "canal basin",                                                    # C11 T1
    "Float dropped into ocean and __23__ by satellite",               # C7 T2
    "a __12__ which beats each __13__",                               # C8 T1
    "Average distance travelled: __24__",                             # C7 T2
]

# What the redraw produced on 2026-08-28 when it was handed the question text.
DEFINITIONS = [
    "The vertical structure that supports the turbine is the __1__",
    "The component that converts mechanical rotation into electricity is __3__",
    "The source of artificial light that mimics sunlight for the plants "
    "is the __2__",
    "The conduit that carries excess water away from the system is the __3__",
    # The caption form the model moved to as soon as the copula was refused.
    "Draws liquid from the reservoir and delivers it to the grow trays - "
    "the __1__",
    "Provides a spectrum tailored to photosynthesis for the plants - the __2__",
    "Drains excess water back into the reservoir - the __3__",
]


def _labelled(text):
    return {"kind": "diagram", "labels": [{"at": "x", "text": text}]}


@pytest.mark.parametrize("text", CAMBRIDGE_CALLOUTS)
def test_a_real_cambridge_callout_is_not_taken_for_a_definition(text):
    assert _figure_pass._defines_its_answer(_labelled(text)) == []


@pytest.mark.parametrize("text", DEFINITIONS)
def test_a_callout_defining_its_own_answer_is_caught(text):
    assert _figure_pass._defines_its_answer(_labelled(text)) == [text]


def test_a_redraw_whose_callouts_define_their_answers_is_discarded(monkeypatch):
    """The student could fill these in without opening the passage."""
    defining = rich()
    for i, text in enumerate(DEFINITIONS[:3]):
        defining["labels"][i]["text"] = text.replace("__2__", "__2__")
    defining["labels"][0]["text"] = (
        "The structure that holds the seedlings is the __1__"
    )
    defining["labels"][1]["text"] = (
        "The device that moves the solution upward is the __2__"
    )
    defining["labels"][2]["text"] = (
        "The vessel that stores the nutrient mix is the __3__"
    )
    _use(monkeypatch, [defining])
    r = result_with(thin())
    assert asyncio.run(redraw_diagram(r, r["passage"])) is False
    assert r["visual"] == thin()


# ---------------------------------------------------------------------------
# Self-answering callouts are reworded, not deleted
# ---------------------------------------------------------------------------


LEAKY = "Solution is pumped from the __3__ by the circulation pump"


def leaky_result():
    v = rich()
    v["labels"][2]["text"] = LEAKY
    return result_with(v)


def test_a_callout_printing_another_gaps_answer_is_reworded(monkeypatch):
    """Deleting it would take the student's context with it.

    While a callout was a bare noun phrase, deletion was right: there was
    nothing in it to reword. A clause holding its OWN gap cannot be deleted at
    all without orphaning question 3.
    """
    _use(monkeypatch, ["Solution is pumped from the reservoir below"], key="callout")
    r = leaky_result()
    changed = asyncio.run(repair_self_answering_callouts(r))
    assert changed == [(LEAKY, "Solution is pumped from the __3__ below")]
    assert r["visual"]["labels"][2]["text"] == "Solution is pumped from the __3__ below"


def test_the_model_never_sees_the_gap(monkeypatch):
    """Shown a `__3__` it answers it instead of copying it through.

    `_flow._rewrite_step` documents the measurement: 4 tries out of 4 filled
    the blank in. The gap is filled with its own keyed answer before the call
    and blanked again after.
    """
    stub = _use(
        monkeypatch, ["Solution is pumped from the reservoir below"], key="callout"
    )
    asyncio.run(repair_self_answering_callouts(leaky_result()))
    assert "__3__" not in stub.prompts[0]
    assert "reservoir" in stub.prompts[0]
    assert "circulation pump" in stub.prompts[0]


def test_a_rewrite_that_loses_the_gap_is_rejected(monkeypatch):
    _use(monkeypatch, ["Solution is pumped up from below"], key="callout")
    r = leaky_result()
    assert asyncio.run(repair_self_answering_callouts(r)) == []
    assert r["visual"]["labels"][2]["text"] == LEAKY


def test_a_rewrite_still_printing_the_answer_is_rejected(monkeypatch):
    _use(
        monkeypatch,
        ["The circulation pump draws from the reservoir"],
        key="callout",
    )
    r = leaky_result()
    assert asyncio.run(repair_self_answering_callouts(r)) == []
    assert r["visual"]["labels"][2]["text"] == LEAKY


def test_a_clean_figure_makes_no_call(monkeypatch):
    stub = _use(monkeypatch, [], key="callout")
    assert asyncio.run(repair_self_answering_callouts(result_with(rich()))) == []
    assert stub.prompts == []

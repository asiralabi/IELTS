"""The figure conventions the engine retrieves while it draws.

The passage corpus grounded the PROSE a set is built from. Nothing grounded the
FIGURE, so every convention the exam follows was written into the system prompt
by hand — and one of them ("no exam diagram prints a sentence") was written
wrong and stood for weeks, which is what made every generated figure
contextless. These cover the retrieval end: the mapping from what a student
asked for to the figure family the books call it, and the guarantee that a
store with nothing in it leaves every caller exactly as it was.
"""

import pytest

from app.rag import figures as fig
from app.rag.figures import family_for, family_to_ground, figure_conventions


class _Store:
    """Stands in for the vector store and records what it was searched for."""

    def __init__(self, hits):
        self.hits = hits
        self.queries: list[tuple[str, int | None, str | None]] = []

    def search(self, query, top_k=None, source=None):
        self.queries.append((query, top_k, source))
        return self.hits


def _use(monkeypatch, hits):
    store = _Store(hits)
    monkeypatch.setattr("app.rag.store.get_vector_store", lambda: store)
    return store


# ---------------------------------------------------------------------------
# Which family a request is about
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "qtype,family",
    [
        ("diagram_label_completion", "diagram"),
        ("Diagram Label Completion", "diagram"),
        ("map_labelling", "plan"),
        ("flow_chart_completion", "flow_chart"),
        ("table_completion", "table"),
        ("form_completion", "form"),
        ("note_completion", "notes"),
        # Notes and summary are one block to the renderer and one family to the
        # exam; they differ only in typography.
        ("summary_completion", "notes"),
        ("picture_choice", "picture_choice"),
        ("chart_completion", "chart"),
    ],
)
def test_a_question_type_maps_to_the_family_the_books_use(qtype, family):
    assert family_for([qtype]) == family


def test_a_request_with_no_figure_type_asks_for_nothing():
    assert family_for(["multiple_choice", "true_false_not_given"]) is None
    assert family_for([]) is None
    assert family_for(None) is None


def test_the_first_figure_type_in_the_request_wins():
    """One figure per set, so one family to ground against."""
    assert family_for(["multiple_choice", "map_labelling", "table_completion"]) == "plan"


def test_a_diagram_is_not_grounded_in_the_one_pass_generator():
    """It is drawn again by `_figure_pass`, which gets the conventions itself.

    The reason is structural: the second pass exists BECAUSE the one-pass
    prompt is skimmed, so bolting 2.1k more characters onto a diagram block
    already ~9,000 long — in a prompt that must also write a passage, questions
    and an answer key — works against the thing that fixed it. The conventions
    still reach the drawing, in the focused call where they are the only thing
    being asked for.

    The live rounds are consistent with that and do not prove it (n=1 per
    configuration); the numbers are in `figures.DRAWN_BY_SECOND_PASS`.
    """
    assert family_to_ground(["diagram_label_completion"]) is None
    # Everything else has no second pass, so the one-pass prompt is the only
    # place its conventions can reach.
    assert family_to_ground(["table_completion"]) == "table"
    assert family_to_ground(["note_completion"]) == "notes"
    assert family_to_ground(["map_labelling"]) == "plan"


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


def test_conventions_are_fetched_from_the_figure_source_only(monkeypatch):
    """Filtered, or a passage about turbines outranks every convention."""
    store = _use(monkeypatch, [{
        "text": "FIGURE CONVENTION — diagram (reading paper)\nRULE: a callout is a clause",
        "source": fig.SOURCE, "score": 0.9,
    }])
    out = figure_conventions("diagram", module="reading", subject="a termite mound")
    query, top_k, source = store.queries[0]
    assert source == fig.SOURCE
    assert "diagram" in query and "reading" in query and "termite" in query
    assert top_k == 16  # over-fetched: most hits belong to another family
    assert "RULE: a callout is a clause" in out


def test_the_block_tells_the_model_not_to_reuse_the_subject(monkeypatch):
    """Grounding, never content — a student never sees a Cambridge page."""
    _use(monkeypatch, [{
        "text": "FIGURE CONVENTION — diagram (reading paper)\nSubject drawn: undersea turbine",
        "source": fig.SOURCE, "score": 0.9,
    }])
    out = figure_conventions("diagram")
    assert "do NOT reuse" in out.lower() or "do not reuse" in out.lower()
    assert "CONVENTIONS" in out


def test_an_empty_store_leaves_the_caller_as_it_was(monkeypatch):
    """Nothing ingested yet is the normal state of a fresh checkout."""
    _use(monkeypatch, [])
    assert figure_conventions("diagram", module="reading") == ""


def test_no_family_makes_no_query(monkeypatch):
    store = _use(monkeypatch, [{"text": "x", "source": fig.SOURCE, "score": 1}])
    assert figure_conventions("") == ""
    assert store.queries == []

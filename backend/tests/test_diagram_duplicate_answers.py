"""Two gaps on one diagram cannot share an answer.

Found live on 2026-08-23: a hive diagram keyed both "the area where the bees
store their food" and "the structure that regulates the hive's temperature" as
`Honeycomb`, the second of which is wrong. It is repaired rather than refused
because refusing costs a hosted passage of 14-25 minutes, and `ad0e767`
requires 3+ numbered parts so the question cannot be dropped either.

The rule is scoped to diagram labelling on measured grounds: a general
no-repeats rule is refuted by the exam itself, which repeats an answer in 19.6%
of Cambridge reading records and 31.0% of listening ones.
"""

import pytest

from app.agents.reading_trainer import (
    _duplicate_diagram_answers,
    _repair_duplicate_diagram_answers,
    validate_practice,
)

PASSAGE = (
    "The hive is built around a set of brood cells, where the queen lays her "
    "eggs and the young are raised. Above them the workers draw out the "
    "honeycomb, the wax lattice in which food is stored through the winter. "
    "Air moves through a ventilation shaft that the workers keep clear, and "
    "it is this shaft that regulates the temperature of the whole colony. "
    "A narrow entrance at the base is guarded day and night."
)


def _diagram_set(answers):
    """Three diagram gaps over the hive passage, keyed as the caller says."""
    return {
        "title": "The Evolution of the Honey Bee",
        "passage": PASSAGE,
        "questions": [
            {"number": 14, "type": "diagram_label_completion", "word_limit": 2,
             "question": "NO MORE THAN TWO WORDS. Label 14 on the diagram: "
                         "the structure where the queen bee lays her eggs."},
            {"number": 15, "type": "diagram_label_completion", "word_limit": 2,
             "question": "NO MORE THAN TWO WORDS. Label 15 on the diagram: "
                         "the area where the bees store their food."},
            {"number": 16, "type": "diagram_label_completion", "word_limit": 2,
             "question": "NO MORE THAN TWO WORDS. Label 16 on the diagram: "
                         "the structure that regulates the hive's temperature."},
        ],
        "answer_key": dict(zip(("14", "15", "16"), answers)),
        "visual": {"kind": "plan", "title": "Cross-section of a Hive",
                   "grid": [["", "__14__", ""], ["", "__15__", ""],
                            ["", "__16__", ""]]},
    }


class _Reply:
    """A generator client that answers the relabel call with a fixed string."""

    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    async def complete_json(self, system, messages, **kwargs):
        self.calls.append(messages[0]["content"])
        if isinstance(self.answer, Exception):
            raise self.answer
        return {"answer": self.answer}


@pytest.fixture
def relabel(monkeypatch):
    def install(answer):
        client = _Reply(answer)
        monkeypatch.setattr(
            "app.agents.reading_trainer.get_llm_client", lambda *a, **k: client
        )
        return client
    return install


def test_a_repeated_diagram_answer_is_detected():
    clashes = _duplicate_diagram_answers(
        _diagram_set(["Brood cells", "honeycomb", "Honeycomb"])
    )

    assert clashes == [("15", "16", "Honeycomb")]


def test_the_first_use_is_kept_and_the_later_one_is_the_fault():
    """Nothing can tell which gap is right, so position decides -- and it must
    decide the same way every time."""
    clashes = _duplicate_diagram_answers(
        _diagram_set(["Honeycomb", "Brood cells", "Honeycomb"])
    )

    assert clashes == [("14", "16", "Honeycomb")]


def test_distinct_answers_are_left_alone():
    assert _duplicate_diagram_answers(
        _diagram_set(["Brood cells", "honeycomb", "ventilation shaft"])
    ) == []


def test_only_the_diagram_is_judged():
    """The exam repeats answers freely elsewhere -- 19.6% of Cambridge reading
    records do. Nothing outside a diagram may be caught by this."""
    practice = _diagram_set(["Brood cells", "honeycomb", "ventilation shaft"])
    for q in practice["questions"]:
        q["type"] = "sentence_completion"
    practice["answer_key"]["16"] = "honeycomb"

    assert _duplicate_diagram_answers(practice) == []
    assert validate_practice(practice, judge_verbatim=False) is None


@pytest.mark.asyncio
async def test_the_repair_rekeys_the_repeating_gap(relabel):
    practice = _diagram_set(["Brood cells", "honeycomb", "Honeycomb"])
    client = relabel("ventilation shaft")

    repaired = await _repair_duplicate_diagram_answers(practice)

    assert repaired == [("16", "ventilation shaft")]
    assert practice["answer_key"]["16"] == "ventilation shaft"
    assert practice["answer_key"]["15"] == "honeycomb"
    assert _duplicate_diagram_answers(practice) == []


@pytest.mark.asyncio
async def test_the_repair_is_told_what_is_already_taken(relabel):
    """Without the used answers the model has no way to avoid them, and the
    second attempt repeats the first."""
    practice = _diagram_set(["Brood cells", "honeycomb", "Honeycomb"])
    client = relabel("ventilation shaft")

    await _repair_duplicate_diagram_answers(practice)

    prompt = client.calls[0]
    assert "Brood cells" in prompt
    assert "honeycomb" in prompt
    assert "regulates the hive's temperature" in prompt


@pytest.mark.asyncio
async def test_a_replacement_absent_from_the_passage_is_refused(relabel):
    """Trading an unanswerable gap for a different unanswerable gap is not a
    repair. The set must be left exactly as it was found."""
    practice = _diagram_set(["Brood cells", "honeycomb", "Honeycomb"])
    client = relabel("thermal regulator")

    repaired = await _repair_duplicate_diagram_answers(practice)

    assert len(client.calls) == 1, "the duplicate must have been noticed"
    assert repaired == []
    assert practice["answer_key"]["16"] == "Honeycomb"


@pytest.mark.asyncio
async def test_a_replacement_that_is_also_taken_is_refused(relabel):
    practice = _diagram_set(["Brood cells", "honeycomb", "Honeycomb"])
    client = relabel("brood cells")

    repaired = await _repair_duplicate_diagram_answers(practice)

    assert len(client.calls) == 1, "the duplicate must have been noticed"
    assert repaired == []
    assert practice["answer_key"]["16"] == "Honeycomb"


@pytest.mark.asyncio
async def test_a_failed_call_leaves_the_set_untouched(relabel):
    """One short call is worth trying; a set thrown away because the call
    errored is not. The gate downstream is what stops it reaching a student."""
    practice = _diagram_set(["Brood cells", "honeycomb", "Honeycomb"])
    before = dict(practice["answer_key"])
    client = relabel(RuntimeError("gateway said no"))

    repaired = await _repair_duplicate_diagram_answers(practice)

    assert len(client.calls) == 1, "the duplicate must have been noticed"
    assert repaired == []
    assert practice["answer_key"] == before


@pytest.mark.asyncio
async def test_a_clean_set_costs_no_call(relabel):
    practice = _diagram_set(["Brood cells", "honeycomb", "ventilation shaft"])
    client = relabel("should not be asked for")

    assert await _repair_duplicate_diagram_answers(practice) == []
    assert client.calls == []


def test_the_validator_refuses_a_duplicate_that_survived():
    practice = _diagram_set(["Brood cells", "honeycomb", "Honeycomb"])

    problem = validate_practice(practice)

    assert problem is not None
    assert "same diagram" in problem
    assert "Q16" in problem and "Q15" in problem


def test_the_validator_is_skipped_for_the_caller_that_repairs():
    """create_practice lets the set in and repairs afterwards, so a retry spent
    complaining about this buys nothing."""
    practice = _diagram_set(["Brood cells", "honeycomb", "Honeycomb"])

    assert validate_practice(practice, judge_diagram=False) is None


def test_the_validator_passes_a_repaired_set():
    practice = _diagram_set(["Brood cells", "honeycomb", "ventilation shaft"])

    assert validate_practice(practice) is None


@pytest.fixture
def expander(monkeypatch):
    """Stand in for the passage-expansion call the repair falls back to."""
    def install(expanded):
        calls = []

        async def fake(passage, title, must_name=None):
            calls.append((passage, title, list(must_name or [])))
            return expanded

        monkeypatch.setattr("app.agents.reading_trainer._expand_passage", fake)
        return calls
    return install


@pytest.mark.asyncio
async def test_a_right_label_the_passage_never_uses_is_written_into_it(
    relabel, expander
):
    """Measured live: the duplicate was the model's fallback for a gap whose
    part the passage never described. Throwing the label away leaves the gap
    unanswerable, so the passage is rewritten to name it -- the same cure
    `84c426c` applies to keyed answers."""
    practice = _diagram_set(["Brood cells", "honeycomb", "Honeycomb"])
    relabel("ventilation shaft")
    practice["passage"] = PASSAGE.replace(
        "Air moves through a ventilation shaft that the workers keep clear, "
        "and it is this shaft that regulates the temperature of the whole "
        "colony. ", "")
    calls = expander(PASSAGE)

    repaired = await _repair_duplicate_diagram_answers(practice)

    assert repaired == [("16", "ventilation shaft")]
    assert practice["answer_key"]["16"] == "ventilation shaft"
    assert practice["passage"] == PASSAGE
    assert calls[0][2] == ["ventilation shaft"], "the expander must be told the label"


@pytest.mark.asyncio
async def test_an_expansion_that_does_not_name_the_label_is_discarded(
    relabel, expander
):
    """The rewrite is only worth keeping if it actually took."""
    practice = _diagram_set(["Brood cells", "honeycomb", "Honeycomb"])
    before = practice["passage"]
    relabel("thermal regulator")
    expander(before + " The colony is kept cool by its own industry.")

    repaired = await _repair_duplicate_diagram_answers(practice)

    assert repaired == []
    assert practice["passage"] == before
    assert practice["answer_key"]["16"] == "Honeycomb"


@pytest.mark.asyncio
async def test_an_expansion_may_not_unfind_another_gaps_answer(relabel, expander):
    """The rest of the set is keyed against the old passage. A rewrite that
    drops the wording another gap depends on trades one defect for two."""
    practice = _diagram_set(["Brood cells", "honeycomb", "Honeycomb"])
    relabel("ventilation shaft")
    # The passage must NOT already contain the label, or the cheap path takes
    # it and no expansion is attempted at all.
    practice["passage"] = PASSAGE.replace(
        "Air moves through a ventilation shaft that the workers keep clear, "
        "and it is this shaft that regulates the temperature of the whole "
        "colony. ", "")
    # Names the new label but loses "brood cells", which Q14 is keyed to.
    expander("The workers draw out the honeycomb. A ventilation shaft "
             "regulates the temperature of the whole colony.")

    repaired = await _repair_duplicate_diagram_answers(practice)

    assert repaired == []
    assert practice["answer_key"]["16"] == "Honeycomb"


@pytest.mark.asyncio
async def test_a_verdict_is_not_a_label(relabel, expander):
    """Measured live, twice out of two: asked for a part it cannot find, the
    checkpoint falls back to the true/false vocabulary it was trained on. That
    must never be written into a passage as a diagram label."""
    practice = _diagram_set(["Brood cells", "honeycomb", "Honeycomb"])
    client = relabel("NOT GIVEN")
    calls = expander(PASSAGE + " NOT GIVEN is a part of the hive.")

    repaired = await _repair_duplicate_diagram_answers(practice)

    assert len(client.calls) == 1
    assert repaired == []
    assert calls == [], "a verdict must be refused before it reaches the passage"
    assert practice["answer_key"]["16"] == "Honeycomb"


@pytest.mark.asyncio
async def test_a_sentence_is_not_a_label(relabel, expander):
    practice = _diagram_set(["Brood cells", "honeycomb", "Honeycomb"])
    relabel("the shaft that regulates the temperature of the colony")
    calls = expander(PASSAGE)

    assert await _repair_duplicate_diagram_answers(practice) == []
    assert calls == []

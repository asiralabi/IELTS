"""The one short call that rewords a self-answering flow chart box.

The model is never shown the gap, and that is the whole design. Every attempt
to send it one came back with the blank filled in:

  * `__4__` -> "safety", 4 tries out of 4
  * a `PLACEHOLDERX4` token invented to look like a word rather than a blank,
    so it would read as something to preserve -> "safety", 3 tries out of 3

It is not disobeying an instruction. It is completing a sentence whose missing
word the context makes obvious, and no wording of the prompt stops that. So the
gap is filled in with its own keyed answer before the call and blanked again
afterwards: the model is handed an ordinary sentence, does the one job it is
good at, and the coupling to the questions is restored in code rather than
trusted to survive the trip.

Live proof (2026-08-25, `tools/_diag_flow_repair_live.py`), the chart that
prompted all this:

  was: "Despite its success, the Comet was not without its problems, with a
        series of accidents ... concerns about the aircraft's __4__."
  now: "The Comet was not without its problems, with a series of accidents ...
        which raised __4__ concerns."
"""

import asyncio

import pytest

from app.agents import _flow


class _Stub:
    """Stands in for the generator client and records what it was sent."""

    is_finetune = False

    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts: list[str] = []

    async def complete_json(self, system, messages, **kwargs):
        self.prompts.append(messages[0]["content"])
        if not self.replies:
            return {"step": ""}
        return {"step": self.replies.pop(0)}


def _use(monkeypatch, replies):
    stub = _Stub(replies)
    monkeypatch.setattr(_flow, "get_llm_client", lambda *a, **k: stub)
    return stub


STEP = (
    "Despite its success, the Comet was not without its problems, with a "
    "series of accidents occurring in the early 1950s, which led to concerns "
    "about the aircraft's __4__."
)
KEY = {"2": "success", "4": "safety"}


def test_the_model_is_sent_a_sentence_with_no_blank_in_it(monkeypatch):
    stub = _use(monkeypatch, ["The Comet had problems, raising safety concerns."])

    asyncio.run(_flow._rewrite_step(STEP, ["success"], "Comet", KEY))

    sent = stub.prompts[0]
    assert "__4__" not in sent
    assert "the aircraft's safety" in sent


def test_the_gap_is_put_back_where_its_answer_landed(monkeypatch):
    _use(monkeypatch, [
        "The Comet was not without its problems, with a series of accidents "
        "which raised safety concerns."
    ])

    out = asyncio.run(_flow._rewrite_step(STEP, ["success"], "Comet", KEY))

    assert out == (
        "The Comet was not without its problems, with a series of accidents "
        "which raised __4__ concerns."
    )


def test_the_gap_is_put_back_whatever_case_the_model_used(monkeypatch):
    _use(monkeypatch, ["Accidents raised Safety concerns for the Comet."])

    out = asyncio.run(_flow._rewrite_step(STEP, ["success"], "Comet", KEY))

    assert out == "Accidents raised __4__ concerns for the Comet."


@pytest.mark.parametrize(
    "reply, why",
    [
        ("The Comet had problems and accidents.", "the answer is gone"),
        ("Safety failings raised safety concerns.", "the answer appears twice"),
    ],
    ids=["answer missing", "answer ambiguous"],
)
def test_a_reply_the_gap_cannot_be_restored_into_is_refused(
    monkeypatch, reply, why
):
    """The blank has to land on exactly the words it came from. The caller's
    gap check would catch a rewrite that lost the gap, but not one where the
    blank landed on the wrong half of the sentence."""
    _use(monkeypatch, [reply])

    assert asyncio.run(_flow._rewrite_step(STEP, ["success"], "Comet", KEY)) is None


def test_an_empty_reply_is_refused(monkeypatch):
    _use(monkeypatch, [""])

    assert asyncio.run(_flow._rewrite_step(STEP, ["success"], "Comet", KEY)) is None


def test_a_gap_whose_own_answer_is_the_banned_word_is_left_as_a_marker(
    monkeypatch
):
    """Filling it would put two identical words in the sentence and the rewrite
    would take them both, leaving nothing to restore the blank onto. Sent as a
    marker instead and judged like any other reply."""
    step = "The safety record, or __3__, was questioned"
    stub = _use(monkeypatch, ["The record was questioned"])

    asyncio.run(_flow._rewrite_step(step, ["safety"], "t", {"3": "safety"}))

    assert "__3__" in stub.prompts[0]


def test_the_banned_words_are_named_in_the_prompt(monkeypatch):
    stub = _use(monkeypatch, ["x"])

    asyncio.run(_flow._rewrite_step(STEP, ["success"], "Comet", KEY))

    assert "success" in stub.prompts[0]
    assert "Comet" in stub.prompts[0]


def test_a_failed_call_is_not_an_exception(monkeypatch):
    """Every repair in this pipeline leaves the set no worse than it found it,
    so a dead call returns None rather than taking the generation down."""
    class Boom:
        is_finetune = False

        async def complete_json(self, *a, **k):
            raise RuntimeError("gateway said no")

    monkeypatch.setattr(_flow, "get_llm_client", lambda *a, **k: Boom())

    assert asyncio.run(_flow._rewrite_step(STEP, ["success"], "Comet", KEY)) is None

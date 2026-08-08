"""A fine-tuned generator must get the prompt shape it was trained on.

Every generator SFT record's user turn is topic/difficulty/types only — the
exporter rebuilds it via `_spec_user_message` rather than recording the
grounded runtime prompt. Appending a Cambridge exemplar therefore puts the
checkpoint off-distribution, and it answers by continuing the exemplar: a
reading set once came back with a passage on urban beekeeping and the
exemplar's own questions about ant taxonomy, which every structural validator
accepts. Nothing else would catch that.
"""

import asyncio

import pytest

from app.agents import listening_trainer, reading_trainer
from app.llm.client import LLMClient, get_llm_client, set_llm_client

GROUNDING_MARKER = "Real Cambridge IELTS"

READING_REPLY = {
    "title": "Urban Beekeeping",
    # Long enough that create_practice skips its expansion call.
    "passage": "Bees pollinate the city gardens of many temperate regions. " * 70,
    "questions": [
        {"number": 1, "type": "true_false_notgiven", "question": "Bees pollinate gardens."}
    ],
    "answer_key": {"1": "TRUE"},
}

LISTENING_REPLY = {
    "title": "Joining a Sports Centre",
    "audio_script": "AGENT: Good morning, how can I help you today? " * 130,
    "questions": [
        {"number": 1, "type": "form_completion", "question": "Membership starts on ..."}
    ],
    "answer_key": {"1": "Monday"},
}


class CapturingClient(LLMClient):
    """Records the user turn instead of generating."""

    def __init__(self, is_finetune: bool) -> None:
        self.is_finetune = is_finetune
        self.user_turns: list[str] = []

    async def complete(self, system, messages, **kw) -> str:
        raise AssertionError("generation must not fall back to free-text completion")

    async def complete_json(self, system, messages, **kw) -> dict:
        self.user_turns.append(messages[-1]["content"])
        if "Reading test writer" in system:
            return dict(READING_REPLY)
        return dict(LISTENING_REPLY)


@pytest.fixture()
def capture():
    previous = get_llm_client()

    def _install(is_finetune: bool) -> CapturingClient:
        client = CapturingClient(is_finetune)
        set_llm_client(client)
        return client

    yield _install
    set_llm_client(previous)


CALLS = {
    "reading_practice": lambda: reading_trainer.create_practice(topic="urban beekeeping"),
    "listening_practice": lambda: listening_trainer.create_practice(topic="a sports centre"),
    "listening_part": lambda: listening_trainer.create_part(1, topic="a sports centre"),
}


@pytest.mark.parametrize("name", list(CALLS), ids=list(CALLS))
def test_finetune_is_not_grounded(capture, name):
    client = capture(is_finetune=True)
    asyncio.run(CALLS[name]())

    turn = client.user_turns[0]
    assert GROUNDING_MARKER not in turn
    # conftest's vector store answers every query with this, so its absence
    # proves no retrieved text reached the prompt by another route.
    assert "band descriptor snippet" not in turn


@pytest.mark.parametrize("name", list(CALLS), ids=list(CALLS))
def test_general_model_keeps_its_grounding(capture, name):
    """Distillation pins the hosted teacher, which was never fine-tuned — it
    must keep the Cambridge exemplar that shaped the corpus."""
    client = capture(is_finetune=False)
    asyncio.run(CALLS[name]())

    assert GROUNDING_MARKER in client.user_turns[0]

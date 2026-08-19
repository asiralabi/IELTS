"""A true/false block with nothing to answer NOT GIVEN is repaired, not retried.

Every one of the 68 true/false blocks of four or more in the reading corpus
carries a NOT GIVEN, so the rule that demands one is exactly on-distribution.
The checkpoint still draws a block of wholly verifiable statements — a live
generation failed on it twice running, 553s spent — because the corrective
retry rewrites the whole passage rather than the one statement at fault.

So the set is accepted on the way in and one statement is rewritten by a second,
much narrower call. The tests below are about which statement is chosen and what
the key becomes, not about the wording of any reply.
"""

import asyncio
import json

import pytest

from app.agents import reading_trainer
from app.llm.client import LLMClient, get_llm_client, set_llm_client
from app.llm.prompts import NOTGIVEN_WRITER_SYSTEM

# Over _MIN_PASSAGE_WORDS, so nothing here depends on the expansion pass.
PASSAGE = "Beekeeping in cities has grown quickly over the past decade. " * 100

WRITTEN = "Urban hives produce more honey per colony than rural ones."


def _set(verdicts: list[str]) -> dict:
    """A set whose only questions are one true/false block."""
    return {
        "title": "Urban Beekeeping",
        "passage": PASSAGE,
        "questions": [
            {
                "number": i + 1,
                "type": "true_false_notgiven",
                "question": f"Statement number {i + 1} about city hives.",
            }
            for i in range(len(verdicts))
        ],
        "answer_key": {str(i + 1): v for i, v in enumerate(verdicts)},
    }


class NotGivenClient(LLMClient):
    """Answers the set call, then the one-statement call."""

    is_finetune = True

    def __init__(self, reply: dict, statement: str | None = WRITTEN) -> None:
        self.reply = reply
        self.statement = statement
        self.writer_turns: list[str] = []

    async def complete(self, system, messages, **kw) -> str:
        raise AssertionError("the passage must not need expanding in these tests")

    async def complete_json(self, system, messages, **kw) -> dict:
        if system is NOTGIVEN_WRITER_SYSTEM:
            self.writer_turns.append(messages[-1]["content"])
            if self.statement is None:
                raise ValueError("the writer had nothing to say")
            return {"statement": self.statement}
        reply = json.loads(json.dumps(self.reply))
        # The real complete_json runs the hook and retries once on a complaint.
        # This one has no second answer to give, so a complaint goes straight to
        # the caller — the state the retry would have reached anyway.
        problem = (kw.get("validate") or (lambda _: None))(reply)
        if problem:
            raise ValueError(problem)
        return reply


@pytest.fixture()
def practice():
    previous = get_llm_client()

    def _run(reply: dict, statement: str | None = WRITTEN):
        client = NotGivenClient(reply, statement)
        set_llm_client(client)
        return asyncio.run(reading_trainer.create_practice(topic="bees")), client

    yield _run
    set_llm_client(previous)


def test_a_block_with_no_not_given_gains_one(practice):
    """The live failure. The set is let in, then one statement is replaced."""
    result, client = practice(_set(["TRUE", "FALSE", "TRUE", "TRUE", "FALSE"]))

    keyed = list(result["answer_key"].values())
    assert keyed.count("NOT GIVEN") == 1
    rewritten = [
        q for q in result["questions"]
        if result["answer_key"][str(q["number"])] == "NOT GIVEN"
    ]
    assert rewritten[0]["question"] == WRITTEN
    assert len(client.writer_turns) == 1
    # The writer is shown the statements already used, so it cannot hand back a
    # negation of one — which would be FALSE, not NOT GIVEN.
    assert "Statement number 1 about city hives." in client.writer_turns[0]


def test_the_converted_statement_comes_from_the_majority_verdict(practice):
    """Converting the block's only FALSE would leave it all TRUE bar one.

    A real block mixes verdicts, and `validate_practice` says so separately;
    taking from the majority keeps a lone verdict alive without needing to.
    """
    result, _ = practice(_set(["TRUE", "TRUE", "TRUE", "TRUE", "FALSE"]))

    assert sorted(result["answer_key"].values()) == [
        "FALSE", "NOT GIVEN", "TRUE", "TRUE", "TRUE"
    ]


def test_a_block_that_already_has_one_is_left_alone(practice):
    """No call is spent on a set that does not need it."""
    original = _set(["TRUE", "FALSE", "NOT GIVEN", "TRUE"])
    result, client = practice(original)

    assert client.writer_turns == []
    assert result["answer_key"] == original["answer_key"]
    assert [q["question"] for q in result["questions"]] == [
        q["question"] for q in original["questions"]
    ]


def test_a_block_too_short_to_judge_is_left_alone(practice):
    """Under four, `validate_practice` does not ask for a NOT GIVEN either.

    Repairing anyway would spend a call satisfying a rule nothing enforces.
    """
    _, client = practice(_set(["TRUE", "FALSE", "TRUE"]))
    assert client.writer_turns == []


def test_a_set_the_writer_could_not_rescue_is_refused(practice):
    """The rule was waived on the way in on the promise it would be satisfied.

    If the narrow call fails there is nothing left to try, and a set with no
    NOT GIVEN must not reach a student under a question type whose whole point
    is that verdict.
    """
    with pytest.raises(ValueError, match="the repaired reading set is invalid"):
        practice(_set(["TRUE", "FALSE", "TRUE", "TRUE"]), statement=None)

"""complete_json: extraction, required-keys enforcement and corrective retry."""

import json

import pytest

from app.llm.client import LLMClient, _extract_json


class ScriptedClient(LLMClient):
    """Returns pre-scripted raw completions, recording every call."""

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls: list[list[dict]] = []

    async def complete(
        self,
        system: str,
        messages: list[dict],
        json_mode: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        self.calls.append(messages)
        return self.replies.pop(0)


class TestExtractJson:
    def test_plain_object(self):
        assert _extract_json('{"a": 1}') == {"a": 1}

    def test_strips_think_tags_and_fences(self):
        raw = '<think>reasoning...</think>```json\n{"band": 6.5}\n```'
        assert _extract_json(raw) == {"band": 6.5}

    def test_object_embedded_in_prose(self):
        assert _extract_json('Here you go: {"x": true} hope that helps') == {"x": True}

    def test_no_object_raises(self):
        with pytest.raises(ValueError):
            _extract_json("no json here")


async def test_complete_json_first_try():
    client = ScriptedClient(['{"band_score": 6.0}'])
    result = await client.complete_json("sys", [], required_keys=("band_score",))
    assert result == {"band_score": 6.0}
    assert len(client.calls) == 1


async def test_missing_required_key_triggers_corrective_retry():
    # First reply is valid JSON but the wrong shape (echoed input) — the exact
    # failure mode seen with small local models in Ollama JSON mode.
    echoed = json.dumps({"task_type": "task2", "essay": "..."})
    good = json.dumps({"band_score": 6.0, "feedback": "ok"})
    client = ScriptedClient([echoed, good])

    result = await client.complete_json(
        "sys",
        [{"role": "user", "content": "mark this"}],
        required_keys=("band_score", "feedback"),
    )
    assert result["band_score"] == 6.0
    assert len(client.calls) == 2
    correction = client.calls[1][-1]["content"]
    assert "band_score" in correction
    assert client.calls[1][-2]["content"] == echoed


async def test_null_valued_required_key_triggers_retry():
    # Keys present but null — the failure seen live: band_score set, criteria null.
    bad = json.dumps({"band_score": 6.0, "task_response": None})
    good = json.dumps({"band_score": 6.0, "task_response": 5.5})
    client = ScriptedClient([bad, good])

    result = await client.complete_json(
        "sys", [], required_keys=("band_score", "task_response")
    )
    assert result["task_response"] == 5.5
    assert len(client.calls) == 2
    assert "task_response" in client.calls[1][-1]["content"]


async def test_validator_rejection_triggers_retry_with_problem_message():
    bad = json.dumps({"band_score": "N/A"})
    good = json.dumps({"band_score": 7.0})
    client = ScriptedClient([bad, good])

    def validate(obj: dict) -> str | None:
        if not isinstance(obj["band_score"], (int, float)):
            return "band_score must be numeric"
        return None

    result = await client.complete_json(
        "sys", [], required_keys=("band_score",), validate=validate
    )
    assert result == {"band_score": 7.0}
    assert "band_score must be numeric" in client.calls[1][-1]["content"]


async def test_invalid_json_then_valid():
    client = ScriptedClient(["not json at all", '{"score": 1}'])
    result = await client.complete_json("sys", [], required_keys=("score",))
    assert result == {"score": 1}


async def test_two_bad_replies_raise_value_error():
    client = ScriptedClient(['{"wrong": 1}', "still wrong"])
    with pytest.raises(ValueError):
        await client.complete_json("sys", [], required_keys=("score",))


async def test_no_required_keys_accepts_any_object():
    client = ScriptedClient(['{"anything": "goes"}'])
    assert await client.complete_json("sys", []) == {"anything": "goes"}

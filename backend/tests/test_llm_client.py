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


async def test_oversized_reply_is_not_echoed_into_the_retry():
    """A truncated exam JSON plus the prompt it came from overruns the local
    checkpoints' 8192-token window, and Ollama trims the conversation silently
    rather than erroring — so the retry would be answered without its schema."""
    truncated = '{"title": "x", "audio_script": "' + "word " * 2000
    good = json.dumps({"title": "x", "audio_script": "y"})
    client = ScriptedClient([truncated, good])

    result = await client.complete_json(
        "sys",
        [{"role": "user", "content": "generate"}],
        required_keys=("title", "audio_script"),
    )
    assert result["audio_script"] == "y"
    retry = client.calls[1]
    assert [m["role"] for m in retry] == ["user", "user"]
    assert truncated not in retry[-1]["content"]


async def test_unechoed_validator_failure_asks_for_a_new_reply_not_an_edit():
    """No generated exam fits the echo budget — the shortest reply in either
    corpus is 5052 chars against a 2000 cap. So a validator message naming
    question numbers would otherwise tell the model to edit nothing."""
    bad = json.dumps({"passage": "word " * 2000, "questions": []})
    good = json.dumps({"passage": "p", "questions": [1]})
    client = ScriptedClient([bad, good])

    result = await client.complete_json(
        "sys",
        [{"role": "user", "content": "generate"}],
        required_keys=("passage", "questions"),
        validate=lambda o: "questions 3, 4 reuse heading i" if not o["questions"] else None,
    )
    assert result["questions"] == [1]
    correction = client.calls[1][-1]["content"]
    assert "questions 3, 4 reuse heading i" in correction
    assert "cannot be edited" in correction


async def test_an_echoed_reply_is_left_to_be_edited():
    """The complaint only disowns the previous reply when it is absent; a short
    one is right there in the conversation and pointing at it is the fix."""
    client = ScriptedClient([json.dumps({"score": None}), json.dumps({"score": 1})])
    await client.complete_json("sys", [], required_keys=("score",))
    assert "cannot be edited" not in client.calls[1][-1]["content"]


async def test_invalid_json_then_valid():
    client = ScriptedClient(["not json at all", '{"score": 1}'])
    result = await client.complete_json("sys", [], required_keys=("score",))
    assert result == {"score": 1}


async def test_cutoff_reply_is_told_to_be_shorter():
    """A reply cut off at num_predict is the local checkpoints' only JSON
    failure, and the decoder's column number is useless as feedback."""
    # Shaped like a real cut-off exam: earlier questions closed, the last one
    # severed mid-string, so _extract_json slices to that inner '}'.
    cutoff = (
        '{"title": "x", "questions": [{"number": 1, "type": "form_completion"}, '
        '{"number": 2, "question": "the caller says'
    )
    client = ScriptedClient([cutoff, '{"title": "x", "questions": []}'])

    await client.complete_json("sys", [], required_keys=("title",))
    correction = client.calls[1][-1]["content"]
    assert "shorter" in correction
    assert "delimiter" not in correction


async def test_two_bad_replies_raise_value_error():
    client = ScriptedClient(['{"wrong": 1}', "still wrong"])
    with pytest.raises(ValueError):
        await client.complete_json("sys", [], required_keys=("score",))


async def test_a_twice_rejected_set_reports_the_validator_not_a_json_error():
    """A live listening failure read 'LLM failed to return valid JSON' followed
    by 500 chars of audio script; the actual cause — two answers keyed 'not
    provided' — was only visible in the chained __cause__."""
    passage = json.dumps({"passage": "word " * 200})
    client = ScriptedClient([passage, passage])

    with pytest.raises(ValueError, match="rejected on retry: two answers say"):
        await client.complete_json(
            "sys", [], required_keys=("passage",),
            validate=lambda o: "two answers say the script does not answer it",
        )


async def test_no_required_keys_accepts_any_object():
    client = ScriptedClient(['{"anything": "goes"}'])
    assert await client.complete_json("sys", []) == {"anything": "goes"}

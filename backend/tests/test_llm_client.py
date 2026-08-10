"""complete_json: extraction, required-keys enforcement and corrective retry."""

import asyncio
import json

import pytest

from app.config import settings
from app.llm import client as client_module
from app.llm.client import (
    AnthropicClient,
    LLMClient,
    OllamaClient,
    OpenAIClient,
    _extract_json,
    gather_llm,
)


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


class CountingClient(LLMClient):
    """Records the highest number of calls ever in flight at once."""

    def __init__(self, serialised: bool) -> None:
        self.serialised = serialised
        self.active = 0
        self.peak = 0

    async def complete(self, system, messages, json_mode=False, temperature=None,
                       max_tokens=None) -> str:
        self.active += 1
        self.peak = max(self.peak, self.active)
        await asyncio.sleep(0)  # a real gather would interleave here
        self.active -= 1
        return messages[0]["content"]


class TestGatherLlm:
    """Gathering calls that all land on one ollama instance buys no wall time —
    they run one at a time regardless — and parks the rest in a queue that now
    counts against their own timeouts, turning a slow batch into a failing one.
    """

    @staticmethod
    def _calls(client: LLMClient) -> list:
        return [
            client.complete("sys", [{"role": "user", "content": str(i)}])
            for i in range(4)
        ]

    async def test_a_serialised_client_runs_one_call_at_a_time(self, monkeypatch):
        client = CountingClient(serialised=True)
        monkeypatch.setattr(client_module, "_override", client)
        assert await gather_llm(None, self._calls(client)) == ["0", "1", "2", "3"]
        assert client.peak == 1

    async def test_a_hosted_client_still_runs_them_together(self, monkeypatch):
        client = CountingClient(serialised=False)
        monkeypatch.setattr(client_module, "_override", client)
        assert await gather_llm(None, self._calls(client)) == ["0", "1", "2", "3"]
        assert client.peak == 4

    async def test_a_failure_partway_through_leaves_no_orphaned_calls(self, monkeypatch):
        """A set rejected twice raises, which is routine right now — the calls
        queued behind it must not resurface as "coroutine was never awaited" on
        top of the real error. A closed coroutine has dropped its frame.
        """
        client = CountingClient(serialised=True)
        monkeypatch.setattr(client_module, "_override", client)

        async def boom():
            raise ValueError("rejected on retry")

        ran = client.complete("sys", [{"role": "user", "content": "first"}])
        never_reached = client.complete("sys", [{"role": "user", "content": "last"}])
        with pytest.raises(ValueError, match="rejected on retry"):
            await gather_llm(None, [ran, boom(), never_reached])

        assert client.peak == 1
        assert never_reached.cr_frame is None

    def test_only_the_ollama_client_declares_itself_serialised(self):
        assert OllamaClient.serialised is True
        assert OpenAIClient.serialised is False
        assert AnthropicClient.serialised is False


async def test_the_ollama_budget_covers_time_spent_queued(monkeypatch):
    """Timing only the POST made the budget fiction: waiting for the semaphore
    was free, so a caller that asked for 3s could sit behind a 15-minute
    fine-tune call and come back having never 'exceeded' its cap.
    """

    class Response:
        def raise_for_status(self) -> None: ...

        def json(self) -> dict:
            return {"message": {"content": "done"}}

    class SlowOllama:
        async def post(self, *args, **kwargs):
            await asyncio.sleep(0.5)
            return Response()

    monkeypatch.setattr(client_module, "_ollama_semaphore", None)
    monkeypatch.setattr(client_module, "_get_http_client", SlowOllama)

    async def timed(client: OllamaClient):
        started = asyncio.get_running_loop().time()
        try:
            return await client.complete("sys", [{"role": "user", "content": "x"}]), 0.0
        except TimeoutError as exc:
            return exc, asyncio.get_running_loop().time() - started

    (held, _), (failure, elapsed) = await asyncio.gather(
        timed(OllamaClient("m", timeout=5.0)),
        timed(OllamaClient("m", timeout=0.1)),
    )
    assert held == "done"
    assert isinstance(failure, TimeoutError)
    # The point: it gives up on its own budget rather than at 0.5s, when the
    # call ahead of it finally let go of the semaphore.
    assert elapsed < 0.4
    assert "queued" in str(failure)


class TestHostedClientTimeouts:
    """Without an explicit timeout these inherit the SDK default of 600s, retried
    twice — half an hour before a stuck call gives up. The fine-tune route reaches
    them anyway: _expand_script and _expand_passage ask get_llm_client() for the
    general model, and swallow every exception, so the wait is also invisible.
    """

    @staticmethod
    def _recorder(recorded: dict):
        def factory(**kwargs):
            recorded.update(kwargs)
            return object()

        return factory

    def test_openai_client_passes_the_configured_timeout(self, monkeypatch):
        import openai

        recorded: dict = {}
        monkeypatch.setattr(openai, "AsyncOpenAI", self._recorder(recorded))
        OpenAIClient()
        assert recorded["timeout"] == settings.llm_timeout

    def test_anthropic_client_passes_the_configured_timeout(self, monkeypatch):
        import anthropic

        recorded: dict = {}
        monkeypatch.setattr(anthropic, "AsyncAnthropic", self._recorder(recorded))
        AnthropicClient()
        assert recorded["timeout"] == settings.llm_timeout

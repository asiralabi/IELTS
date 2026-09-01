"""complete_json: extraction, required-keys enforcement and corrective retry."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.config import settings
from app.llm import client as client_module
from app.llm.client import (
    AnthropicClient,
    LLMClient,
    OllamaClient,
    OpenAIClient,
    RunawayGeneration,
    _RUNAWAY_MIN_RATIO,
    _extract_json,
    _runaway_ratio,
    gather_llm,
    get_llm_client,
)


class FakeOllama:
    """httpx.AsyncClient stand-in that streams NDJSON chunks like /api/chat.

    `sent` counts the chunks actually pulled, which is how the tests tell an
    abandoned generation from one that was merely rejected after the fact.
    """

    def __init__(self, pieces: list[str], delay: float = 0.0,
                 finish: bool = True) -> None:
        self.pieces = list(pieces)
        self.delay = delay
        # ollama ends the stream with no done chunk when the reply can no longer
        # satisfy the JSON grammar. finish=False reproduces that.
        self.finish = finish
        self.sent = 0

    def stream(self, method, url, json=None, timeout=None):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def raise_for_status(self) -> None: ...

    async def aiter_lines(self):
        for piece in self.pieces:
            if self.delay:
                await asyncio.sleep(self.delay)
            self.sent += 1
            yield json.dumps({"message": {"content": piece}, "done": False})
        if self.finish:
            yield json.dumps({"message": {"content": ""}, "done": True})


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


async def test_a_rejected_reply_travels_out_WITH_the_complaint():
    """🔬 The verification sweep of 2026-09-01 saved the rejected set for six
    of its seven failures and had nothing for the seventh: `l_map_r2` died
    inside this retry, where the reply was dropped at the `raise`.

    A map fault — "A sits on 'Main trail'" — cannot be diagnosed from the
    sentence alone; you have to see the places and the letters. The reply rides
    out on `.result`, which is what `tools/figure_sweep.py` writes to disk.
    """
    reply = json.dumps({"passage": "word " * 200, "visual": {"kind": "plan"}})
    client = ScriptedClient([reply, reply])

    with pytest.raises(ValueError) as caught:
        await client.complete_json(
            "sys", [], required_keys=("passage",),
            validate=lambda o: "A sits on 'Main trail'",
        )
    assert caught.value.result["visual"] == {"kind": "plan"}


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

    monkeypatch.setattr(client_module, "_ollama_semaphore", None)
    monkeypatch.setattr(
        client_module, "_get_http_client", lambda: FakeOllama(["done"], delay=0.5)
    )

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


class TestRunawayDetection:
    """A run-on is the local checkpoints' one fatal failure: the model locks
    into a paragraph-length cycle and emits it until num_predict, ~880s of
    decode, so finetune_timeout kills it as a TimeoutError nothing catches.

    The hard part is that reading REQUIRES a large verbatim repetition — a
    matching-headings block repeats its whole options list on every question —
    so the detector has to tell the two apart, not just spot repetition.
    """

    # Shaped like the recorded run-on: prose inside one unterminated JSON
    # string, near-identical each time round, varying only a counter the model
    # increments forever ("In the 49th century... the 50th century...").
    @staticmethod
    def _looping_passage(cycles: int, start: int = 40) -> str:
        cycle = (
            "In the {n}th century, the production of paper in Europe will "
            "continue to decline, and this is due to a number of factors. One "
            "of the main factors is the decline of the paper industry in China. "
            "The decline of the paper industry in China leads to a decline in "
            "the quality of paper that is available in Europe. This decline in "
            "the quality of paper leads to a decline in the demand for paper, "
            "which in turn leads to a decline in the production of paper. "
        )
        return '{"title": "Paper", "passage": "' + "".join(
            cycle.format(n=start + i) for i in range(cycles)
        )

    # Shaped like a real headings set: the same options list on every question,
    # which is mandatory (the frontend renders no `headings` field).
    @staticmethod
    def _headings_questions(count: int) -> str:
        options = ", ".join(
            f'"{n}. The {w} of paper"'
            for n, w in zip("i ii iii iv v vi vii viii".split(),
                            "origin spread decline revival cost craft trade future".split())
        )
        return '{"questions": [' + ", ".join(
            f'{{"number": {i}, "type": "matching_headings", "question": '
            f'"Choose the correct heading for Paragraph {chr(64 + i)}.", '
            f'"options": [{options}]}}'
            for i in range(1, count + 1)
        ) + "]}"

    def test_a_repeating_cycle_is_caught(self):
        assert _runaway_ratio(self._looping_passage(12)) < _RUNAWAY_MIN_RATIO

    def test_a_whitespace_stall_is_caught(self):
        """The mode the previous detector was blind to by construction: it
        required a cycle of at least 200 characters, and this one has period 1.
        Measured live — a reply died at `known as "` and then emitted 3,539
        spaces, because an unescaped quote closes the string and the JSON
        grammar will accept nothing else the model wants to say.
        """
        assert _runaway_ratio('{"passage": "known as ' + '"' + " " * 4000) < _RUNAWAY_MIN_RATIO

    def test_the_mandatory_headings_repetition_is_not_a_loop(self):
        """The exact repetition reading depends on, and the reason the window is
        scored in 40-grams: at that length each repeat still carries enough of
        its own question text to read as distinct.
        """
        assert _runaway_ratio(self._headings_questions(8)) >= _RUNAWAY_MIN_RATIO

    def test_ordinary_prose_is_not_a_loop(self):
        passage = " ".join(
            f"Paragraph {i} discusses a different aspect of papermaking in "
            f"some detail, with its own facts, dates and named figures."
            for i in range(40)
        )
        assert _runaway_ratio(passage) >= _RUNAWAY_MIN_RATIO

    def test_a_short_reply_is_never_judged(self):
        """The ratio is meaningless on a tail too short to repeat in, and a
        legitimate reply is a fragment for its first few hundred characters.
        """
        assert _runaway_ratio('{"title": "Paper"') == 1.0

    async def test_a_run_on_is_abandoned_instead_of_decoded_to_the_cap(
        self, monkeypatch
    ):
        """The whole point: stop paying for it. Waiting for the reply means
        waiting out the full token budget, then failing with nothing to show.
        """
        text = self._looping_passage(40)
        pieces = [text[i:i + 60] for i in range(0, len(text), 60)]
        fake = FakeOllama(pieces)
        monkeypatch.setattr(client_module, "_ollama_semaphore", None)
        monkeypatch.setattr(client_module, "_get_http_client", lambda: fake)

        with pytest.raises(RunawayGeneration, match="anything new"):
            await OllamaClient("m", timeout=30.0).complete("sys", [])
        assert fake.sent < len(pieces)

    async def test_a_reply_longer_than_any_it_was_trained_on_is_abandoned(
        self, monkeypatch
    ):
        """The mode neither repeat-detector can see, measured live: the model
        kept writing NEW prose past 15,875 characters, scoring 0.325 — correctly
        above the repeat threshold, because nothing was repeating. Without a
        length bound the guard is a heuristic; with one it terminates.
        """
        novel = " ".join(
            f"Sentence {i} records a distinct fact about papermaking, naming "
            f"a different year, place and person from all the others."
            for i in range(400)
        )
        assert _runaway_ratio(novel) >= _RUNAWAY_MIN_RATIO, "must not be a repeat"
        assert len(novel) > client_module._RUNAWAY_MAX_CHARS
        pieces = [novel[i:i + 200] for i in range(0, len(novel), 200)]
        fake = FakeOllama(pieces)
        monkeypatch.setattr(client_module, "_ollama_semaphore", None)
        monkeypatch.setattr(client_module, "_get_http_client", lambda: fake)

        with pytest.raises(RunawayGeneration, match="trained on"):
            await OllamaClient("m", timeout=30.0).complete("sys", [])
        assert fake.sent < len(pieces)

    async def test_a_stream_that_never_completes_is_a_failure_not_a_reply(
        self, monkeypatch
    ):
        """Without this the fragment is returned as if it were the answer, and
        the retry is spent complaining about whatever the fragment failed to be.
        """
        fake = FakeOllama(['{"title": "Paper", "passage": "known as "'],
                          finish=False)
        monkeypatch.setattr(client_module, "_ollama_semaphore", None)
        monkeypatch.setattr(client_module, "_get_http_client", lambda: fake)

        with pytest.raises(RunawayGeneration, match="without a completion marker"):
            await OllamaClient("m", timeout=30.0).complete("sys", [])

    async def test_the_two_failure_modes_get_opposite_corrections(self):
        """A repeating reply must be told to write less; a stalled one is
        already too short, and telling it to write less cannot help.
        """
        class Breaks(LLMClient):
            def __init__(self, error: RunawayGeneration) -> None:
                self.error = error
                self.calls: list[list[dict]] = []

            async def complete(self, system, messages, json_mode=False,
                               temperature=None, max_tokens=None) -> str:
                self.calls.append(messages)
                if len(self.calls) == 1:
                    raise self.error
                return json.dumps({"passage": "p"})

        stalled = Breaks(RunawayGeneration(
            "ended without a completion marker", client_module._ADVICE_STALLED))
        await stalled.complete_json("sys", [{"role": "user", "content": "go"}],
                                    required_keys=("passage",))
        assert "quotation marks" in stalled.calls[1][-1]["content"]

        repeating = Breaks(RunawayGeneration(
            "stopped saying anything new", client_module._ADVICE_REPEATING))
        await repeating.complete_json("sys", [{"role": "user", "content": "go"}],
                                      required_keys=("passage",))
        assert "shorter" in repeating.calls[1][-1]["content"]

    async def test_a_run_on_earns_a_retry_rather_than_reaching_the_caller(self):
        """It used to surface as a TimeoutError raised outside complete_json's
        try block — the most expensive way for a generation to end, since it
        cost the full budget AND could not be retried.
        """
        class RunsAwayOnce(LLMClient):
            def __init__(self) -> None:
                self.calls: list[list[dict]] = []

            async def complete(self, system, messages, json_mode=False,
                               temperature=None, max_tokens=None) -> str:
                self.calls.append(messages)
                if len(self.calls) == 1:
                    raise RunawayGeneration("locked into a 769-character cycle",
                                            client_module._ADVICE_REPEATING)
                return json.dumps({"passage": "p"})

        client = RunsAwayOnce()
        result = await client.complete_json(
            "sys", [{"role": "user", "content": "generate"}],
            required_keys=("passage",),
        )
        assert result == {"passage": "p"}
        correction = client.calls[1][-1]["content"]
        assert "shorter" in correction
        # Nothing to echo — the reply was abandoned, not received.
        assert [m["role"] for m in client.calls[1]] == ["user", "user"]


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


class FakeOpenAIStream:
    """openai.AsyncOpenAI stand-in yielding chat.completions chunks.

    finish_reason=None reproduces a stream that just stops, which is what a
    dropped connection looks like from this side.
    """

    def __init__(self, pieces: list[str], finish_reason: str | None = "stop") -> None:
        self.pieces = list(pieces)
        self.finish_reason = finish_reason
        self.kwargs: dict = {}
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.kwargs = kwargs
        return self._events()

    async def _events(self):
        for piece in self.pieces:
            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content=piece), finish_reason=None
                    )
                ]
            )
        # Providers send a usage-only trailer with no choices at all; it must
        # not be read as the end of the reply.
        yield SimpleNamespace(choices=[])
        if self.finish_reason:
            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content=""),
                        finish_reason=self.finish_reason,
                    )
                ]
            )


class TestOpenAIStreaming:
    """A gateway in front of a hosted model abandons a request that stays
    silent: an unstreamed part-2 generation returned 504 after 302s, while the
    identical streamed request ran 564s and completed. So this client streams,
    which also puts it under the same runaway guard as the local one.
    """

    @staticmethod
    def _client(monkeypatch, fake):
        import openai

        monkeypatch.setattr(openai, "AsyncOpenAI", lambda **kwargs: fake)
        return OpenAIClient()

    def test_it_asks_for_a_stream_and_joins_the_deltas(self, monkeypatch):
        fake = FakeOpenAIStream(["{\"a\": ", "1}"])
        client = self._client(monkeypatch, fake)

        result = asyncio.run(client.complete("sys", [{"role": "user", "content": "x"}]))

        assert result == '{"a": 1}'
        assert fake.kwargs["stream"] is True

    def test_a_stream_that_just_stops_is_a_fragment_not_a_reply(self, monkeypatch):
        """Returning the fragment would surface as unterminated JSON and spend
        the retry complaining about syntax instead of the truncation."""
        fake = FakeOpenAIStream(["{\"a\": "], finish_reason=None)
        client = self._client(monkeypatch, fake)

        with pytest.raises(RunawayGeneration) as excinfo:
            asyncio.run(client.complete("sys", [{"role": "user", "content": "x"}]))

        assert "without a completion marker" in str(excinfo.value)

    def test_a_repeating_stream_is_cut_off(self, monkeypatch):
        """The guard was measured on the local model; the hosted one reaches it
        now only because this client streams."""
        fake = FakeOpenAIStream(["the same clause over and over. " * 40] * 30)
        client = self._client(monkeypatch, fake)

        with pytest.raises(RunawayGeneration) as excinfo:
            asyncio.run(client.complete("sys", [{"role": "user", "content": "x"}]))

        assert "distinct" in str(excinfo.value)
        # Abandoned mid-flight rather than judged at the end.
        assert fake.pieces


class TestReasoningBudget:
    """A reasoning model thinks out of the same allowance it writes from.

    Measured live 2026-08-30 on gpt-oss-120b at `reasoning_effort=medium`: the
    duplicate-gap relabel repair, which asks for one label at max_tokens=128,
    came back with EMPTY content every time -- the thinking spent the budget
    before the answer began. The whole reading set was then refused for the
    duplicate the repair exists to fix, and the diagram sweep read 28% refused
    against 11% before the model swap. Six hosted call sites ask for under
    1024, so the reserve belongs here rather than in each of them.
    """

    @staticmethod
    def _client(monkeypatch, fake):
        import openai

        monkeypatch.setattr(openai, "AsyncOpenAI", lambda **kwargs: fake)
        return OpenAIClient()

    def test_a_small_budget_is_topped_up_for_the_thinking(self, monkeypatch):
        monkeypatch.setattr(settings, "openai_reasoning_effort", "medium")
        fake = FakeOpenAIStream(["{}"])
        client = self._client(monkeypatch, fake)

        asyncio.run(
            client.complete("sys", [{"role": "user", "content": "x"}], max_tokens=128)
        )

        assert fake.kwargs["reasoning_effort"] == "medium"
        assert fake.kwargs["max_tokens"] == 128 + client_module._REASONING_RESERVE

    def test_a_model_that_does_not_reason_is_left_alone(self, monkeypatch):
        """Blank means the parameter is never sent -- a model that does not know
        it answers 400 -- and then there is no thinking to reserve for either."""
        monkeypatch.setattr(settings, "openai_reasoning_effort", "")
        fake = FakeOpenAIStream(["{}"])
        client = self._client(monkeypatch, fake)

        asyncio.run(
            client.complete("sys", [{"role": "user", "content": "x"}], max_tokens=128)
        )

        assert "reasoning_effort" not in fake.kwargs
        assert fake.kwargs["max_tokens"] == 128

    def test_the_configured_ceiling_still_wins(self, monkeypatch):
        """The reserve protects the small repair calls. A generation already
        asking for the whole allowance has room to think inside it, and asking
        the provider for more than .env permits is a different bug."""
        monkeypatch.setattr(settings, "openai_reasoning_effort", "medium")
        monkeypatch.setattr(settings, "llm_max_tokens", 16384)
        fake = FakeOpenAIStream(["{}"])
        client = self._client(monkeypatch, fake)

        asyncio.run(client.complete("sys", [{"role": "user", "content": "x"}]))

        assert fake.kwargs["max_tokens"] == 16384


class TestSkipFinetuneRouting:
    """A configured checkpoint serves "generator" — except for figure work.

    The generator's SFT corpus never mentions a figure, so the checkpoint
    answers a figure request with the shape it was trained on rather than the
    grid schema in the system prompt. skip_finetune is how a caller opts out.
    """

    @pytest.fixture(autouse=True)
    def routed(self, monkeypatch):
        import openai

        monkeypatch.setattr(client_module, "_override", None)
        monkeypatch.setattr(client_module, "_clients", {})
        monkeypatch.setattr(settings, "generator_model", "a-checkpoint")
        monkeypatch.setattr(settings, "llm_provider", "openai")
        monkeypatch.setattr(openai, "AsyncOpenAI", lambda **kwargs: object())

    def test_the_generator_serves_from_the_checkpoint_by_default(self):
        client = get_llm_client("generator")

        assert client.is_finetune
        assert client.model == "a-checkpoint"

    def test_skip_finetune_hands_the_call_to_the_general_model(self):
        client = get_llm_client("generator", skip_finetune=True)

        assert not client.is_finetune
        assert isinstance(client, OpenAIClient)

    def test_skipping_does_not_evict_the_checkpoint_for_later_callers(self):
        """The two clients are cached side by side — a figure part must not
        leave the non-figure parts talking to the hosted model."""
        get_llm_client("generator", skip_finetune=True)

        assert get_llm_client("generator").is_finetune


def test_a_rate_limited_model_is_not_reported_as_a_server_fault():
    """🔬 Live 2026-09-01: three figure sweeps drained the free tier, and the
    next `POST /writing/full-test/submit` raised `openai.RateLimitError` clean
    through the router — every handler catches `ValueError`, the reply a
    validator turned down, and none catches the provider declining to reply at
    all. The student was told "Internal Server Error", which is untrue and
    unactionable: nothing is broken and the fix is to wait.
    """
    import httpx as _httpx
    from fastapi import APIRouter
    from fastapi.testclient import TestClient
    from openai import RateLimitError

    from app.main import create_app

    app = create_app()
    hurt = APIRouter()

    @hurt.get("/_test/ratelimited")
    def _boom() -> dict:
        raise RateLimitError(
            "Too Many Requests",
            response=_httpx.Response(
                429, request=_httpx.Request("POST", "https://model.invalid/v1")),
            body=None,
        )

    app.include_router(hurt)
    # `raise_server_exceptions=False` so the handler is exercised rather than
    # the exception being re-raised into the test.
    r = TestClient(app, raise_server_exceptions=False).get("/_test/ratelimited")
    assert r.status_code == 503
    assert "busy" in r.json()["detail"]
    assert "Internal Server Error" not in r.text

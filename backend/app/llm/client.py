import asyncio
import json
import re
from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine, Iterable, Sequence
from typing import Any

import httpx

from app.config import settings

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)

# Echoing a failed reply back lets the model see what it got wrong, which is what
# fixes the "echoed the input" and "null-valued key" cases. But a generated exam
# is ~2-3k tokens on top of a ~3.2k-token prompt and a 4096-token generation
# budget, which overruns the 8192-token window of our local checkpoints — and
# Ollama silently drops part of the conversation to make it fit rather than
# failing. Past this size the correction message alone carries the feedback.
_MAX_ECHOED_REPLY_CHARS = 2000

# The local checkpoints fail to finish a reply in three measured ways, and each
# costs the full finetune_timeout as a TimeoutError that complete_json does not
# catch — 15 minutes spent, no retry earned. Watching the stream ends them early.
#
#   repeating  the model locks into a paragraph-length cycle and emits it until
#              it hits num_predict (recorded: a 769-char cycle incrementing a
#              counter, "In the 49th century... the 50th century...").
#   stalled    the model emits a RAW `"` inside a string value. Under
#              format="json" that closes the string, after which the grammar
#              admits only `,`/`}`/whitespace while the model still wants prose
#              — so it emits spaces and the stream dies with no `done` chunk.
#   unbounded  the model keeps writing NEW, non-repeating prose and never stops.
#              Measured live at 15,875 characters and still going, scoring 0.325
#              — correctly above the repeat threshold, because nothing repeats.
#              Only a hard length bound ends this one, which is also what makes
#              the guard a guarantee rather than a heuristic.
#
# An earlier probe-based detector (an exact 80-char probe repeated at three
# offsets) is deliberately gone. It caught both recorded run-ons but went 0/4
# live, including a full 900s timeout, because it needs a probe to land on
# digit-free text against a cycle that varies every repeat. The distinct-40-gram
# ratio below has no such luck in it, and catches whitespace stalls as well.
#
# Every threshold here is measured, and backend/tools/_diag_loop_detector.py
# re-measures them: run-ons score 0.171 and 0.051, every one of the 449
# legitimate replies floors at 0.303, and only one sits below 0.435.
_RUNAWAY_WINDOW = 6000
_RUNAWAY_GRAM = 40
_RUNAWAY_MIN_RATIO = 0.25
# Below this the tail is too short for the ratio to mean anything.
_RUNAWAY_MIN_CHARS = 2000
_RUNAWAY_CHECK_EVERY = 1000
# The longest reply in either committed corpus is 14,607 chars; the longest the
# checkpoint has been seen to produce and have accepted is 8,019. Past this the
# reply is longer than anything it was trained to write, so it is not going to
# become valid by continuing.
_RUNAWAY_MAX_CHARS = 16_000

_ADVICE_REPEATING = (
    "Your previous reply ran on and never closed the JSON object. "
    "Write a shorter one: keep every required key, but no repeated "
    "or padded text. Do not restate a sentence you have already "
    "written, and stop the passage once it is long enough rather "
    "than adding further paragraphs."
)
_ADVICE_STALLED = (
    "Your previous reply stopped in the middle of a JSON string and never "
    "closed the object. Write a completely new one, and do not use quotation "
    "marks anywhere inside the text of a JSON value — name things without "
    "quoting them."
)


class RunawayGeneration(ValueError):
    """The model never finished its reply, in any of the three ways above.

    Carries the correction to send back, because the modes need opposite advice:
    a repeating or unbounded reply must be told to write less, while a stalled
    one is already too short and needs to be told what tripped it.
    """

    def __init__(self, message: str, advice: str) -> None:
        super().__init__(message)
        self.advice = advice


def _strip_think(text: str) -> str:
    return _THINK_RE.sub("", text).strip()


def _runaway_ratio(text: str) -> float:
    """Share of the tail's 40-grams that are distinct. Low means self-repeating.

    Only the tail, so that a reply which rambles at the end is caught even
    though its opening was fine — and so the cost stays flat as the reply grows.

    Length 40 is what separates a lock-in from the repetition reading
    legitimately requires: a matching headings block repeats its whole options
    list on every question, but at 40 characters each repeat still carries
    enough of its own question text to read as distinct.
    """
    tail = text[-_RUNAWAY_WINDOW:]
    if len(tail) <= _RUNAWAY_GRAM:
        return 1.0
    grams = [tail[i:i + _RUNAWAY_GRAM] for i in range(len(tail) - _RUNAWAY_GRAM + 1)]
    return len(set(grams)) / len(grams)


class _RunawayWatch:
    """Accumulates a streamed reply, refusing one that stops making progress.

    Shared by both streaming clients so the measured thresholds above have a
    single home — a hosted reply runs on the same way a local one does, and a
    second copy of this logic would drift from the numbers the diagnostics
    re-measure.
    """

    def __init__(self, model: str) -> None:
        self.model = model
        self._pieces: list[str] = []
        self._next_check = _RUNAWAY_MIN_CHARS
        self.size = 0

    @property
    def text(self) -> str:
        return "".join(self._pieces)

    def add(self, piece: str) -> None:
        if not piece:
            return
        self._pieces.append(piece)
        self.size += len(piece)
        if self.size > _RUNAWAY_MAX_CHARS:
            raise RunawayGeneration(
                f"{self.model} wrote {self.size} characters without finishing, "
                "more than any reply it was trained on",
                _ADVICE_REPEATING,
            )
        if self.size >= self._next_check:
            self._next_check = self.size + _RUNAWAY_CHECK_EVERY
            ratio = _runaway_ratio(self.text)
            if ratio < _RUNAWAY_MIN_RATIO:
                # Raising drops the connection, which is how the server learns
                # to stop generating.
                raise RunawayGeneration(
                    f"{self.model} stopped saying anything new after "
                    f"{self.size} characters — only {ratio:.0%} of its recent "
                    "output was distinct",
                    _ADVICE_REPEATING,
                )

    def finish(self, completed: bool) -> str:
        if not completed:
            raise RunawayGeneration(
                f"{self.model} ended its reply after {self.size} characters "
                "without a completion marker, so the reply is a fragment",
                _ADVICE_STALLED,
            )
        return self.text


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = _strip_think(text)
    fence = _FENCE_RE.search(cleaned)
    if fence:
        cleaned = fence.group(1)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"No JSON object found in response: {text[:200]!r}")
    return json.loads(cleaned[start : end + 1])


class LLMClient(ABC):
    # True only for a client serving one of our own checkpoints. Callers use it
    # to send the prompt shape that checkpoint was trained on.
    is_finetune = False
    # True when every call funnels through one model instance, so concurrent
    # callers queue instead of overlapping. `gather_llm` reads it.
    serialised = False

    @abstractmethod
    async def complete(
        self,
        system: str,
        messages: list[dict],
        json_mode: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str: ...

    async def complete_json(
        self,
        system: str,
        messages: list[dict],
        required_keys: Sequence[str] = (),
        validate: Callable[[dict], str | None] | None = None,
        **kw: Any,
    ) -> dict:
        def parse(raw: str) -> dict:
            obj = _extract_json(raw)
            # Small models sometimes echo the input back as valid JSON, or fill
            # schema keys with nulls — enforce presence AND non-null values.
            missing = [k for k in required_keys if obj.get(k) is None]
            if missing:
                raise ValueError(
                    f"the following keys are missing or null: {', '.join(missing)}"
                )
            if validate is not None:
                problem = validate(obj)
                if problem:
                    raise ValueError(problem)
            return obj

        raw = ""
        try:
            # Inside the try so an abandoned run-on earns its retry. Left
            # outside, it reached the caller as a hard failure — the single
            # most expensive way for a generation to end.
            raw = await self.complete(system, messages, json_mode=True, **kw)
            return parse(raw)
        except (ValueError, json.JSONDecodeError) as first_error:
            echoed = bool(raw) and len(raw) <= _MAX_ECHOED_REPLY_CHARS
            if isinstance(first_error, RunawayGeneration):
                # Checked before ValueError generally: the stream watcher
                # already knows which way the reply broke, and the two ways need
                # opposite corrections.
                complaint = first_error.advice
            elif isinstance(first_error, json.JSONDecodeError):
                # A reply that got this far and still will not parse was cut off
                # at num_predict having rambled past any length it was trained
                # on. Quoting the decoder's column number gives the model nothing
                # to act on; asking for less prose does.
                complaint = _ADVICE_REPEATING
            else:
                complaint = f"Your previous reply was not acceptable ({first_error})."
                if not echoed:
                    # A validator names the offending question numbers, which
                    # only helps if the reply is there to edit. No generated
                    # exam ever fits the echo budget, so without this the model
                    # is told to "reassign question 4" against nothing.
                    complaint += (
                        " That reply is not shown above and cannot be edited —"
                        " write a completely new one that avoids the problem."
                    )
            correction = (
                complaint
                + " Return ONLY a single valid JSON object matching the schema "
                "in the system prompt"
            )
            if required_keys:
                correction += (
                    ", with non-null values for the keys: "
                    + ", ".join(required_keys)
                )
            retry_messages = list(messages)
            if echoed:
                retry_messages.append({"role": "assistant", "content": raw})
            retry_messages.append({"role": "user", "content": correction + "."})
            raw = await self.complete(system, retry_messages, json_mode=True, **kw)
            try:
                return parse(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"LLM failed to return valid JSON: {raw[:500]!r}") from exc
            except ValueError as exc:
                # Well-formed JSON a validator turned down. Quoting the reply
                # buries the reason under 500 chars of passage; the validator's
                # own complaint IS the reason, so lead with it.
                raise ValueError(f"LLM reply rejected on retry: {exc}") from exc


# Module-level singleton — creating a new httpx.AsyncClient per request
# throws away connection pooling and forces a full TCP+TLS handshake for
# every LLM call. Reuse a single client with bounded pool limits.
_http_client: httpx.AsyncClient | None = None
# Ollama runs a single model instance locally; concurrent requests just
# queue on the GPU/CPU anyway. Serialise them so we don't stampede one
# model and add a lower fail-fast timeout for warm-pool paths.
_ollama_semaphore: asyncio.Semaphore | None = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            timeout=settings.llm_timeout,
        )
    return _http_client


def _get_ollama_semaphore() -> asyncio.Semaphore:
    global _ollama_semaphore
    if _ollama_semaphore is None:
        _ollama_semaphore = asyncio.Semaphore(1)
    return _ollama_semaphore


async def shutdown_llm_http_client() -> None:
    """Close the module-level httpx client on FastAPI lifespan shutdown."""
    global _http_client
    if _http_client is not None:
        try:
            await _http_client.aclose()
        finally:
            _http_client = None


class OllamaClient(LLMClient):
    serialised = True

    def __init__(self, model: str | None = None, timeout: float | None = None,
                 is_finetune: bool = False) -> None:
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.model = model or settings.ollama_model
        self.timeout = timeout
        self.is_finetune = is_finetune

    async def complete(
        self,
        system: str,
        messages: list[dict],
        json_mode: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        # Hybrid thinking models (e.g. qwen3) ignore think=False and narrate
        # their reasoning inside `content` for free-text replies. With
        # think=True Ollama routes reasoning to a separate `thinking` field,
        # keeping `content` clean. JSON mode is already constrained by
        # format=json, so thinking stays off there to save tokens.
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}] + messages,
            # Streamed so a run-on can be cut off while it is happening. Waiting
            # for the whole reply means waiting out the full token budget.
            "stream": True,
            "think": not json_mode,
            "options": {
                "temperature": temperature if temperature is not None else settings.llm_temperature,
                "num_predict": max_tokens if max_tokens is not None else settings.llm_max_tokens,
            },
        }
        if json_mode:
            payload["format"] = "json"
        # Fail fast for warm-pool paths: cap at min(llm_timeout, 180s) so a
        # single stuck request can't hold the semaphore for the raw 600s. The
        # fine-tunes opt out via an explicit timeout — they legitimately run
        # for minutes, so the cap would abort every call.
        per_call_timeout = (
            self.timeout if self.timeout is not None else min(settings.llm_timeout, 180.0)
        )
        client = _get_http_client()
        semaphore = _get_ollama_semaphore()
        # The budget has to cover the queue as well as the generation. Timing
        # only the POST made it fiction: waiting for the semaphore was free, so
        # a caller that asked for 180s could sit behind two 900s fine-tune calls
        # and come back half an hour later, having never exceeded its "cap".
        loop = asyncio.get_running_loop()
        start = loop.time()
        acquired_at: float | None = None
        try:
            async with asyncio.timeout(per_call_timeout):
                async with semaphore:
                    acquired_at = loop.time()
                    content = await self._stream(client, payload, per_call_timeout)
        except TimeoutError as exc:
            elapsed = loop.time() - start
            queued = elapsed if acquired_at is None else acquired_at - start
            # Separating the two halves matters: "the model is slow" and "you
            # were behind three other callers" need completely different fixes.
            raise TimeoutError(
                f"{self.model} exceeded its {per_call_timeout:.0f}s budget after "
                f"{elapsed:.0f}s, {queued:.0f}s of it queued — ollama serves one "
                "model at a time, so concurrent callers wait their turn"
            ) from exc
        return _strip_think(content)

    async def _stream(
        self, client: httpx.AsyncClient, payload: dict[str, Any], timeout: float
    ) -> str:
        """Accumulate a streamed reply, abandoning it if it stops progressing."""
        watch = _RunawayWatch(self.model)
        finished = False
        async with client.stream(
            "POST", f"{self.base_url}/api/chat", json=payload, timeout=timeout
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                chunk = json.loads(line)
                # A streamed failure (model still loading, context overflow)
                # arrives as a JSON line under a 200, so it has to be read out
                # of the body rather than the status.
                if chunk.get("error"):
                    raise httpx.HTTPError(f"{self.model}: {chunk['error']}")
                watch.add((chunk.get("message") or {}).get("content") or "")
                if chunk.get("done"):
                    finished = True
                    break
        # ollama ends the stream without a done chunk when the reply can no
        # longer satisfy the JSON grammar — reliably, when the model writes an
        # unescaped quote inside a string. Returning the fragment would surface
        # as an unterminated-JSON error that spends the retry on the wrong
        # complaint, so it is named here where the cause is still known.
        return watch.finish(finished)


class AnthropicClient(LLMClient):
    def __init__(self) -> None:
        import anthropic

        self.client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key, timeout=settings.llm_timeout
        )
        self.model = settings.anthropic_model

    async def complete(
        self,
        system: str,
        messages: list[dict],
        json_mode: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        if json_mode:
            system = system + "\n\nReturn ONLY a single valid JSON object. No markdown, no prose."
        resp = await self.client.messages.create(
            model=self.model,
            system=system,
            messages=messages,
            temperature=temperature if temperature is not None else settings.llm_temperature,
            max_tokens=max_tokens if max_tokens is not None else settings.llm_max_tokens,
        )
        return "".join(block.text for block in resp.content if block.type == "text").strip()


class OpenAIClient(LLMClient):
    def __init__(self) -> None:
        import openai

        kwargs: dict[str, Any] = {
            "api_key": settings.openai_api_key,
            "timeout": settings.llm_timeout,
        }
        if settings.openai_base_url:
            kwargs["base_url"] = settings.openai_base_url
        self.client = openai.AsyncOpenAI(**kwargs)
        self.model = settings.openai_model

    async def complete(
        self,
        system: str,
        messages: list[dict],
        json_mode: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}] + messages,
            "temperature": temperature if temperature is not None else settings.llm_temperature,
            "max_tokens": max_tokens if max_tokens is not None else settings.llm_max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        # A reasoning model thinks before it writes, out of the SAME budget.
        # Left at its default, gpt-oss-120b spent every one of 2048 tokens
        # reasoning and returned empty content, which the app saw as "No JSON
        # object found in response". See `openai_reasoning_effort`.
        if settings.openai_reasoning_effort:
            kwargs["reasoning_effort"] = settings.openai_reasoning_effort
        # Streamed for the same reason ollama is, plus one the hosted side adds:
        # a gateway in front of the model will abandon a request that stays
        # silent too long. Measured against NVIDIA — an unstreamed part-2
        # generation returned 504 after 302s, while the identical streamed
        # request ran 564s and completed, because bytes kept arriving.
        kwargs["stream"] = True
        watch = _RunawayWatch(self.model)
        completed = False
        stream = await self.client.chat.completions.create(**kwargs)
        async for event in stream:
            if not event.choices:
                continue
            choice = event.choices[0]
            watch.add(choice.delta.content or "")
            if choice.finish_reason:
                completed = True
                break
        return watch.finish(completed).strip()


_override: LLMClient | None = None
_clients: dict[str | None, LLMClient] = {}

# Task name -> the Settings field naming its fine-tuned checkpoint.
_TASK_MODEL_SETTING = {
    "generator": "generator_model",
    "evaluator": "evaluator_model",
}


def _build_client(task: str | None) -> LLMClient:
    # A configured fine-tune is always served locally by ollama regardless of
    # the general provider — no hosted endpoint has our checkpoint.
    setting = _TASK_MODEL_SETTING.get(task or "")
    if setting and getattr(settings, setting):
        return OllamaClient(
            getattr(settings, setting),
            timeout=settings.finetune_timeout,
            is_finetune=True,
        )
    provider = settings.llm_provider
    if provider == "anthropic":
        return AnthropicClient()
    if provider == "openai":
        return OpenAIClient()
    return OllamaClient()


def get_llm_client(
    task: str | None = None, *, skip_finetune: bool = False
) -> LLMClient:
    """Return the client for a task ("generator", "evaluator") or the general
    model when task is None or has no fine-tuned checkpoint configured.

    skip_finetune routes a task past its checkpoint to the general model.
    Figure-bearing generation needs it: the generator's SFT corpus never
    mentions a figure, so the checkpoint answers with its trained shape instead
    of the schema the system prompt asks for.
    """
    if _override is not None:
        return _override
    if skip_finetune:
        task = None
    if task not in _clients:
        _clients[task] = _build_client(task)
    return _clients[task]


def set_llm_client(client: LLMClient | None) -> None:
    """Override every task's client (tests). Pass None to restore routing."""
    global _override
    _override = client
    _clients.clear()


async def gather_llm(
    task: str | None,
    coros: Iterable[Coroutine[Any, Any, Any]],
    *,
    skip_finetune: bool = False,
) -> list[Any]:
    """Run LLM calls concurrently only where the serving model actually is.

    Gathering N calls that all land on one ollama instance buys no wall time —
    they were going to run one at a time regardless — and it parks N-1 of them
    in a queue that counts against their own timeouts, turning a slow batch into
    a failing one. Hosted providers are genuinely concurrent and want the
    gather. Which of the two serves a task is a runtime setting, so no call site
    can hard-code either shape. skip_finetune asks the same question of the
    model a figure-bearing call is actually routed to, which is a different
    one from the task's checkpoint.
    """
    if not get_llm_client(task, skip_finetune=skip_finetune).serialised:
        return list(await asyncio.gather(*coros))
    queue = list(coros)
    results: list[Any] = []
    try:
        for coro in queue:
            results.append(await coro)
    finally:
        # A set rejected twice raises, and generation failures are routine — so
        # close the calls that never ran rather than let them surface later as
        # "coroutine was never awaited" on top of the real error.
        for skipped in queue[len(results) + 1 :]:
            skipped.close()
    return results

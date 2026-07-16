import asyncio
import json
import re
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from typing import Any

import httpx

from app.config import settings

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _strip_think(text: str) -> str:
    return _THINK_RE.sub("", text).strip()


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

        raw = await self.complete(system, messages, json_mode=True, **kw)
        try:
            return parse(raw)
        except (ValueError, json.JSONDecodeError) as first_error:
            correction = (
                f"Your previous reply was not acceptable ({first_error}). "
                "Return ONLY a single valid JSON object matching the schema "
                "in the system prompt"
            )
            if required_keys:
                correction += (
                    ", with non-null values for the keys: "
                    + ", ".join(required_keys)
                )
            retry_messages = messages + [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": correction + "."},
            ]
            raw = await self.complete(system, retry_messages, json_mode=True, **kw)
            try:
                return parse(raw)
            except (ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"LLM failed to return valid JSON: {raw[:500]!r}") from exc


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
    def __init__(self) -> None:
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.model = settings.ollama_model

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
            "stream": False,
            "think": not json_mode,
            "options": {
                "temperature": temperature if temperature is not None else settings.llm_temperature,
                "num_predict": max_tokens if max_tokens is not None else settings.llm_max_tokens,
            },
        }
        if json_mode:
            payload["format"] = "json"
        # Fail fast for warm-pool paths: cap at min(llm_timeout, 180s) so a
        # single stuck request can't hold the semaphore for the raw 600s.
        per_call_timeout = min(settings.llm_timeout, 180.0)
        client = _get_http_client()
        semaphore = _get_ollama_semaphore()
        async with semaphore:
            resp = await client.post(
                f"{self.base_url}/api/chat", json=payload, timeout=per_call_timeout
            )
            resp.raise_for_status()
            data = resp.json()
        return _strip_think(data["message"]["content"])


class AnthropicClient(LLMClient):
    def __init__(self) -> None:
        import anthropic

        self.client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
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

        kwargs: dict[str, Any] = {"api_key": settings.openai_api_key}
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
        resp = await self.client.chat.completions.create(**kwargs)
        return (resp.choices[0].message.content or "").strip()


_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    global _client
    if _client is None:
        provider = settings.llm_provider
        if provider == "anthropic":
            _client = AnthropicClient()
        elif provider == "openai":
            _client = OpenAIClient()
        else:
            _client = OllamaClient()
    return _client


def set_llm_client(client: LLMClient | None) -> None:
    global _client
    _client = client

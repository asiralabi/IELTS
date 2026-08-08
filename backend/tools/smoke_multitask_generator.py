"""Smoke test the combined multi-task generator on both sections.

The failure mode a multi-task adapter has here is schema bleed, not
hallucination, so each generation is checked with the section's own runtime
validator and with the foreign-key check. Topics are deliberately absent from
the SFT corpus, so this measures serving rather than recall.
"""

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.listening_trainer import validate_part  # noqa: E402
from app.agents.reading_trainer import validate_practice  # noqa: E402
from app.config import settings  # noqa: E402
from app.llm.client import OllamaClient  # noqa: E402
from app.llm.prompts import (  # noqa: E402
    LISTENING_TRAINER_SYSTEM,
    READING_TRAINER_SYSTEM,
)

MODEL = "ielts-multitask-generator"
DATASETS = Path(__file__).resolve().parents[1] / "data" / "datasets"

READING_USER = """Generate an IELTS Academic Reading practice set.
Difficulty: medium
Topic: The revival of urban beekeeping
Question Types: matching_headings, true_false_notgiven, sentence_completion
"""

LISTENING_USER = """Generate a Listening Test.
Section: Part 2
Difficulty: medium
Topic: A volunteer induction at a coastal wildlife reserve
Question Types: multiple_choice, sentence_completion, map_labelling
Target Duration: 7 minutes
"""

CASES = [
    ("reading", READING_TRAINER_SYSTEM, READING_USER, validate_practice,
     ("title", "passage", "questions", "answer_key"), "reading_generator_sft.jsonl"),
    ("listening", LISTENING_TRAINER_SYSTEM, LISTENING_USER, validate_part,
     ("title", "audio_script", "questions", "answer_key"), "listening_generator_sft.jsonl"),
]


def corpus_system(name: str) -> str:
    with (DATASETS / name).open(encoding="utf-8") as fh:
        return json.loads(fh.readline())["messages"][0]["content"]


async def main() -> None:
    client = OllamaClient(MODEL, timeout=settings.finetune_timeout)
    print(f"model={MODEL} timeout={settings.finetune_timeout}\n")

    for label, system, user, validator, required, jsonl in CASES:
        trained = corpus_system(jsonl)
        print(f"=== {label}")
        print(f"  system prompt matches the trained one: {system == trained}")

        t0 = time.time()
        try:
            result = await client.complete_json(
                system,
                [{"role": "user", "content": user}],
                required_keys=required,
                validate=validator,
                max_tokens=6144,
            )
        except Exception as exc:  # noqa: BLE001 - smoke test reports, never raises
            print(f"  FAILED after {time.time() - t0:.0f}s: {type(exc).__name__}: {exc}\n")
            continue

        elapsed = time.time() - t0
        questions = result.get("questions") or []
        body = str(result.get("passage") or result.get("audio_script") or "")
        foreign = [k for k in ("passage", "audio_script") if result.get(k)]
        print(f"  ok in {elapsed:.0f}s")
        print(f"  top-level keys: {sorted(result)}")
        print(f"  body keys present: {foreign} (expect exactly one, the section's own)")
        print(f"  body words: {len(body.split())}")
        print(f"  questions: {len(questions)} types={sorted({q.get('type') for q in questions})}")
        print(f"  answer_key: {len(result.get('answer_key') or {})}")
        print(f"  validator: {validator(result) or 'clean'}\n")

        out = Path(__file__).with_name(f"_smoke_multitask_{label}.json")
        out.write_text(json.dumps(result, indent=2), encoding="utf-8")


asyncio.run(main())

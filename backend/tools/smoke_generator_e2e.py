"""End-to-end: run the real create_part through app routing, timeout and post-processing."""
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.listening_trainer import create_part
from app.llm.client import get_llm_client


async def main() -> None:
    gen = get_llm_client("generator")
    print(f"generator client={type(gen).__name__} model={getattr(gen, 'model', None)} "
          f"timeout={getattr(gen, 'timeout', None)}")
    ev = get_llm_client("evaluator")
    print(f"evaluator client={type(ev).__name__} model={getattr(ev, 'model', None)} "
          f"timeout={getattr(ev, 'timeout', None)}")
    gp = get_llm_client()
    print(f"general   client={type(gp).__name__} model={getattr(gp, 'model', None)}")

    t0 = time.time()
    result = await create_part(2)
    print(f"create_part(2) ok in {time.time() - t0:.0f}s")
    qs = result.get("questions") or []
    print(f"part={result.get('part')} title={result.get('title')!r}")
    print(f"script_words={len(str(result.get('audio_script') or '').split())}")
    print(f"questions={len(qs)} numbers={[q.get('number') for q in qs]}")
    print(f"answer_key_keys={sorted((result.get('answer_key') or {}).keys())}")
    print(f"blueprint_keys={sorted(result.get('blueprint') or {})}")
    print(f"accepted_variants={len(result.get('accepted_variants') or {})} "
          f"answer_positions={len(result.get('answer_positions') or {})}")
    Path(__file__).with_name("_smoke_e2e_part2.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )


asyncio.run(main())

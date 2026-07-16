"""Probe the study-plan agent with a synthesized performance summary."""

import asyncio
import json
import sys
import time

from app.llm.client import get_llm_client
from app.llm.prompts import FEEDBACK_SYSTEM
from app.rag.retriever import retrieve_context

SUMMARY = """Target band: 7.5
Writing task2 (2026-07-01): band 6.5, 245 words, weaknesses: over-general supporting ideas, minor article errors, repetition of 'important'
Writing task2 (2026-06-28): band 6.5, 268 words, weaknesses: weak conclusion, run-on sentences, limited linking devices
Writing task1 (2026-06-25): band 6.0, 152 words, weaknesses: missing overview, mislabels trend, incorrect verb tense for data
Speaking part2 (2026-07-02): band 6.5, weaknesses: filler words (um/uh), limited vocabulary, short answers with few examples
Speaking part3 (2026-07-02): band 6.0, weaknesses: short answers, avoids abstract discussion, repeats speaker's phrasing
Reading practice (2026-07-01): 26/40 (band est. 6.0). Missed: Q11: TFNG paraphrase — confused 'reduced' with 'eliminated' | Q17: matching headings — chose surface keyword match | Q29: sentence completion — exceeded word limit
Reading practice (2026-06-27): 24/40 (band est. 5.5). Missed: Q4: TFNG — marked False when passage was silent | Q22: multiple choice — chose distractor from earlier paragraph
Listening practice (2026-06-30): 21/40 (band est. 5.5). Missed: Q6: form completion — spelled 'Katherine' as 'Catherine' | Q18: map labelling — reversed cardinal directions | Q34: multiple choice — missed negation ('not until')"""


async def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    t0 = time.perf_counter()
    context = retrieve_context(SUMMARY, top_k=8)
    print(f"Retrieved {len(context.splitlines())} lines of KB context in "
          f"{time.perf_counter()-t0:.1f}s")
    system = FEEDBACK_SYSTEM.format(
        context=context or "No reference material retrieved."
    )
    t1 = time.perf_counter()
    result = await get_llm_client().complete_json(
        system,
        [{"role": "user", "content": f"Student performance summary:\n{SUMMARY}"}],
        required_keys=("summary", "priorities", "study_plan"),
    )
    print(f"LLM elapsed: {time.perf_counter()-t1:.1f}s  (total: "
          f"{time.perf_counter()-t0:.1f}s)\n")
    payload = json.dumps(result, indent=2, ensure_ascii=False)
    with open("tools/study_plan_out.json", "w", encoding="utf-8") as f:
        f.write(payload)
    print(payload)


if __name__ == "__main__":
    asyncio.run(main())

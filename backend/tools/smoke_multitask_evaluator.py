"""End-to-end marking smoke test against the live fine-tuned evaluator.

Runs both sections through their real `check_answers`, so it exercises the
model routing, the deterministic pre-pass and the section's own band table.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents import listening_trainer, reading_trainer  # noqa: E402
from app.config import settings  # noqa: E402

READING = {
    "title": "The History of Tea",
    "passage": "Tea was first cultivated in China, where it was drunk as a medicine.",
    "questions": [
        {"number": 1, "type": "True/False/Not Given", "question": "Tea originated in China."},
        {"number": 2, "type": "True/False/Not Given", "question": "Tea was first exported to Portugal."},
        {"number": 3, "type": "short_answer", "question": "How was tea first drunk in China?"},
        {"number": 4, "type": "short_answer", "question": "Where was tea first cultivated?"},
    ],
    "answer_key": {"1": "TRUE", "2": "NOT GIVEN", "3": "as a medicine", "4": "China"},
    "accepted_variants": {"3": ["medicine", "as medicine"]},
}
READING_ANSWERS = {"1": "T", "2": "FALSE", "3": "medicine", "4": ""}

LISTENING = {
    "title": "Booking a City Tour",
    "audio_script": "AGENT: The tour starts at 6:00. STUDENT: And your surname? AGENT: Braithwaite.",
    "questions": [
        {"number": 1, "type": "form completion", "question": "Tour starts at ... (ONE WORD AND/OR A NUMBER)"},
        {"number": 2, "type": "form completion", "question": "Surname: ... (ONE WORD)"},
    ],
    "answer_key": {"1": "6:00", "2": "BRAITHWAITE"},
}
LISTENING_ANSWERS = {"1": "6:00", "2": "Braithwait"}


async def main() -> None:
    print(f"EVALUATOR_MODEL = {settings.evaluator_model!r}\n")
    for label, result in [
        ("reading", await reading_trainer.check_answers(READING, READING_ANSWERS)),
        ("listening", await listening_trainer.check_answers(LISTENING, LISTENING_ANSWERS)),
    ]:
        print(
            f"=== {label}: {result['score']}/{result['total']} "
            f"band {result['band_estimate']}"
        )
        for row in result["results"]:
            mark = "OK " if row["correct"] else "XX "
            print(
                f"  {mark} q{row['number']} {row['student_answer']!r} "
                f"vs {row['correct_answer']!r} :: {row['explanation'][:88]}"
            )
            if row.get("skill"):
                print(f"        skill: {row['skill']}")
        print()


asyncio.run(main())

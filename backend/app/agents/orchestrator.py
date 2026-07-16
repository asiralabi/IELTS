import asyncio
import json
from typing import Any

from sqlalchemy.orm import Session

from app.agents import (
    listening_trainer,
    question_generator,
    reading_trainer,
    speaking_examiner,
    writing_examiner,
)
from app.models import MockExam, User


def round_band(value: float) -> float:
    return min(9.0, max(0.0, round(value * 2) / 2))


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


async def build_mock_exam(user_target_band: float | None) -> dict:
    difficulty = f"Band {user_target_band}" if user_target_band else None
    # Real IELTS Speaking Part 1 runs 10-15 questions across ~3 topic frames.
    # We ask for a clustered payload (3 topics × 4 questions = 12) — the
    # prompt schema returns `question` as an array of {topic, questions[]}.
    listening, reading, task1, task2, part1, part2, part3 = await asyncio.gather(
        listening_trainer.create_practice(difficulty=difficulty),
        reading_trainer.create_practice(difficulty=difficulty),
        question_generator.generate("writing", "Task 1", difficulty),
        question_generator.generate("writing", "Task 2 essay", difficulty),
        question_generator.generate(
            "speaking", "Part 1 (12 questions across 3 topics)", difficulty
        ),
        question_generator.generate("speaking", "Part 2 cue card", difficulty),
        question_generator.generate("speaking", "Part 3 discussion questions", difficulty),
    )
    return {
        "listening": listening,
        "reading": reading,
        "writing": {"task1": task1, "task2": task2},
        "speaking": {"part1": part1, "part2": part2, "part3": [part3]},
    }


async def score_mock_exam(
    db: Session, user: User, exam: MockExam, submission: dict
) -> dict:
    exam_data = exam.exam or {}
    keys: list[tuple[str, str]] = []
    coros: list[Any] = []

    if exam_data.get("listening"):
        keys.append(("listening", "listening"))
        coros.append(
            listening_trainer.check_answers(
                exam_data["listening"], submission.get("listening_answers", {}) or {}
            )
        )
    if exam_data.get("reading"):
        keys.append(("reading", "reading"))
        coros.append(
            reading_trainer.check_answers(
                exam_data["reading"], submission.get("reading_answers", {}) or {}
            )
        )

    essays = submission.get("essays", {}) or {}
    writing_tasks = exam_data.get("writing", {}) or {}
    for task_name in ("task1", "task2"):
        essay = essays.get(task_name)
        if essay:
            task_payload = writing_tasks.get(task_name) or {}
            prompt_text = _as_text(task_payload.get("question", ""))
            visual = task_payload.get("visual") if isinstance(task_payload, dict) else None
            keys.append(("writing", task_name))
            coros.append(
                writing_examiner.evaluate(task_name, prompt_text, essay, visual)
            )

    transcripts = submission.get("speaking_transcripts", {}) or {}
    speaking_parts = exam_data.get("speaking", {}) or {}
    for part_name in ("part1", "part2", "part3"):
        transcript = transcripts.get(part_name)
        if transcript:
            question = _as_text(speaking_parts.get(part_name, ""))
            keys.append(("speaking", part_name))
            coros.append(speaking_examiner.evaluate(part_name, question, transcript))

    outcomes = await asyncio.gather(*coros)

    results: dict[str, Any] = {"listening": None, "reading": None, "writing": {}, "speaking": {}}
    for (section, sub_key), outcome in zip(keys, outcomes):
        if section in ("listening", "reading"):
            results[section] = outcome
        else:
            results[section][sub_key] = outcome

    section_bands: dict[str, float] = {}
    for section in ("listening", "reading"):
        outcome = results[section]
        if outcome and outcome.get("band_estimate") is not None:
            section_bands[section] = round_band(float(outcome["band_estimate"]))
    # Writing uses the official IELTS weighting: Task 2 is worth twice Task 1,
    # so the section band is (task1 + 2 * task2) / 3, rounded to the nearest
    # half band. If only one task was submitted, use that task's band alone.
    writing_results = results["writing"]
    t1 = writing_results.get("task1") if isinstance(writing_results, dict) else None
    t2 = writing_results.get("task2") if isinstance(writing_results, dict) else None
    t1_band = t1.get("band_score") if isinstance(t1, dict) else None
    t2_band = t2.get("band_score") if isinstance(t2, dict) else None
    if t1_band is not None and t2_band is not None:
        section_bands["writing"] = round_band((float(t1_band) + 2 * float(t2_band)) / 3)
    elif t2_band is not None:
        section_bands["writing"] = round_band(float(t2_band))
    elif t1_band is not None:
        section_bands["writing"] = round_band(float(t1_band))

    speaking_bands = [
        r["band_score"]
        for r in results["speaking"].values()
        if r and r.get("band_score") is not None
    ]
    if speaking_bands:
        section_bands["speaking"] = round_band(sum(speaking_bands) / len(speaking_bands))

    overall = (
        round_band(sum(section_bands.values()) / len(section_bands))
        if section_bands
        else None
    )

    results["section_bands"] = section_bands
    results["overall_band"] = overall

    exam.results = results
    exam.overall_band = overall
    exam.status = "scored"
    db.commit()
    return results

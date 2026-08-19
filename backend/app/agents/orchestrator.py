import asyncio
from typing import Any

from sqlalchemy.orm import Session

from app.agents import (
    listening_trainer,
    question_generator,
    reading_trainer,
    speaking_examiner,
    writing_examiner,
)
from app.agents._marking import round_band, speaking_band, writing_band
from app.agents.question_generator import as_text
from app.llm.client import gather_llm
from app.models import MockExam, User
from app.services import practice_pool


async def build_mock_exam(db: Session, user_target_band: float | None) -> dict:
    difficulty = f"Band {user_target_band}" if user_target_band else None

    # The real paper is 40 listening and 40 reading questions — four parts and
    # three passages, seven heavy local generations that no request can wait
    # out. The warm pool builds them in the background. When it is still cold
    # the exam falls back to one practice set per section: shorter than the
    # real thing, but `band_from_40` scales it, and a student who clicked
    # "mock exam" gets an exam rather than an error.
    listening = practice_pool.pop(db, "listening", practice_pool.FULL_TEST)
    reading = practice_pool.pop(db, "reading", practice_pool.FULL_TEST)

    # Real IELTS Speaking Part 1 runs 10-15 questions across ~3 topic frames.
    # We ask for a clustered payload (3 topics × 4 questions = 12) — the
    # prompt schema returns `question` as an array of {topic, questions[]}.
    # The two section generators share one fine-tune, so they are nested rather
    # than spread across the gather: run side by side they would only queue on
    # each other, and each retry deepens the queue the next call has to wait
    # out. The five question_generator calls go to the hosted provider and do
    # overlap, so they stay flat and cover the serial half.
    fallbacks = []
    if listening is None:
        fallbacks.append(listening_trainer.create_practice(difficulty=difficulty))
    if reading is None:
        fallbacks.append(reading_trainer.create_practice(difficulty=difficulty))

    sections, task1, task2, part1, part2, part3 = await asyncio.gather(
        gather_llm("generator", fallbacks),
        question_generator.generate("writing", "Task 1", difficulty),
        question_generator.generate("writing", "Task 2 essay", difficulty),
        question_generator.generate(
            "speaking", "Part 1 (12 questions across 3 topics)", difficulty
        ),
        question_generator.generate("speaking", "Part 2 cue card", difficulty),
        question_generator.generate("speaking", "Part 3 discussion questions", difficulty),
    )
    generated = list(sections)
    if listening is None:
        listening = generated.pop(0)
    if reading is None:
        reading = generated.pop(0)

    return {
        "listening": listening,
        "reading": reading,
        "writing": {"task1": task1, "task2": task2},
        "speaking": {"part1": part1, "part2": part2, "part3": [part3]},
    }


def _mark_section(trainer: Any, payload: dict, answers: dict) -> Any:
    """A full test holds its questions under parts/passages, not at the top.

    Handing one to `check_answers` finds no `questions` and hands the student a
    confident 0/0 rather than the paper they actually sat.
    """
    if payload.get("kind") in ("full_listening_test", "full_reading_test"):
        return trainer.check_full_test(payload, answers)
    return trainer.check_answers(payload, answers)


async def score_mock_exam(
    db: Session, user: User, exam: MockExam, submission: dict
) -> dict:
    exam_data = exam.exam or {}
    keys: list[tuple[str, str]] = []
    coros: list[Any] = []

    if exam_data.get("listening"):
        keys.append(("listening", "listening"))
        coros.append(
            _mark_section(
                listening_trainer,
                exam_data["listening"],
                submission.get("listening_answers", {}) or {},
            )
        )
    if exam_data.get("reading"):
        keys.append(("reading", "reading"))
        coros.append(
            _mark_section(
                reading_trainer,
                exam_data["reading"],
                submission.get("reading_answers", {}) or {},
            )
        )

    essays = submission.get("essays", {}) or {}
    writing_tasks = exam_data.get("writing", {}) or {}
    for task_name in ("task1", "task2"):
        essay = essays.get(task_name)
        if essay:
            task_payload = writing_tasks.get(task_name) or {}
            prompt_text = as_text(task_payload.get("question", ""))
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
            question = as_text(speaking_parts.get(part_name, ""))
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
    writing_results = results["writing"]

    def band_of(task: Any) -> float | None:
        score = task.get("band_score") if isinstance(task, dict) else None
        return None if score is None else float(score)

    writing = writing_band(
        band_of(writing_results.get("task1")), band_of(writing_results.get("task2"))
    )
    if writing is not None:
        section_bands["writing"] = writing

    speaking = speaking_band(
        [
            float(r["band_score"])
            for r in results["speaking"].values()
            if r and r.get("band_score") is not None
        ]
    )
    if speaking is not None:
        section_bands["speaking"] = speaking

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

"""Per-question answer marking shared by the Reading and Listening trainers.

Both sections' evaluator checkpoints were fine-tuned on the user turn built by
tools/build_dataset.py `_evaluator_records`. Building that turn in exactly one
place is what stops the runtime prompt and the training data from drifting
apart — a checkpoint fed an untrained shape degrades silently rather than
failing, so there is nothing to alert on.
"""

import asyncio
import logging
import re

from app.llm.client import get_llm_client

logger = logging.getLogger(__name__)

_PUNCT_RE = re.compile(r"[^\w\s]")


def norm(text: object) -> str:
    """Casefold, strip punctuation and collapse whitespace, so a clerical
    match ignores exactly what IELTS markers ignore."""
    return " ".join(_PUNCT_RE.sub(" ", str(text or "").casefold()).split())


def safe_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def band_from_40(correct: int, total: int, table: list[tuple[int, float]]) -> float:
    """Convert a raw score to an IELTS band using the section's own 40-question
    conversion table (scaling shorter/partial sets to /40)."""
    if total <= 0:
        return 0.0
    scaled = round(correct * 40 / total)
    for threshold, band in table:
        if scaled >= threshold:
            return band
    return 2.0 if scaled >= 2 else 0.0


def evaluator_user_turn(
    number: str, question: dict, official: str, variants: list[str], student: str
) -> str:
    """Must stay byte-identical to tools/build_dataset.py `_evaluator_records`."""
    qtext = str(question.get("question") or f"Question {number}").strip()
    return (
        f"Question: {qtext}\n"
        f"Official Answer: {official}\n"
        f"Accepted Variants: {', '.join(variants) if variants else 'none'}\n"
        f"Student Answer: {student if student else '(blank)'}"
    )


async def _evaluate_one(
    evaluator_system: str,
    number: str,
    question: dict,
    official: str,
    variants: list[str],
    student: str,
) -> dict:
    try:
        judged = await get_llm_client("evaluator").complete_json(
            evaluator_system,
            [
                {
                    "role": "user",
                    "content": evaluator_user_turn(
                        number, question, official, variants, student
                    ),
                }
            ],
            required_keys=("verdict", "reason"),
            # Marking must be reproducible, and the longest verdict in the
            # training set is 239 tokens — the 4096 default would let a
            # non-stopping generation run for 20+ minutes on CPU.
            temperature=0.0,
            max_tokens=320,
        )
    except Exception:
        # One unusable verdict must not void the other answers. The pre-pass
        # already found no clerical match, so incorrect is the honest fallback.
        logger.warning("evaluator failed on question %s; marking incorrect", number)
        return {
            "correct": False,
            "reason": f"Could not be marked automatically. The correct answer is '{official}'.",
        }
    return {
        "correct": str(judged.get("verdict") or "").strip().lower() == "correct",
        "reason": str(judged.get("reason") or "").strip(),
        "skill": str(judged.get("skill") or "").strip(),
    }


async def mark_answers(
    practice: dict,
    answers: dict,
    evaluator_system: str,
    band_table: list[tuple[int, float]],
) -> dict:
    """Mark one practice set answer-by-answer with the fine-tuned evaluator.

    Blank, exact and listed-variant answers are settled locally: on CPU each
    evaluator call costs seconds, so routing every answer through the model
    would make marking a test take longer than sitting it.
    """
    questions = {
        str(q.get("number")): q
        for q in (practice.get("questions") or [])
        if isinstance(q, dict)
    }
    variants_map = practice.get("accepted_variants")
    if not isinstance(variants_map, dict):
        variants_map = {}
    student_answers = {str(k): v for k, v in (answers or {}).items()}

    rows: dict[str, dict] = {}
    pending: list[tuple[str, str, list[str], str]] = []

    for raw_num, official_raw in (practice.get("answer_key") or {}).items():
        num = str(raw_num)
        official = str(official_raw or "").strip()
        student = str(student_answers.get(num) or "").strip()
        variants = [
            str(v).strip() for v in (variants_map.get(num) or []) if str(v).strip()
        ]
        row = {
            "number": safe_int(num),
            "student_answer": student,
            "correct_answer": official,
        }
        if not student:
            rows[num] = {
                **row,
                "correct": False,
                "explanation": f"No answer given. The correct answer is '{official}'.",
            }
        elif norm(student) == norm(official) or norm(student) in {
            norm(v) for v in variants
        }:
            rows[num] = {
                **row,
                "correct": True,
                "explanation": "Matches the official answer under IELTS marking.",
            }
        else:
            pending.append((num, official, variants, student))

    if pending:
        judged = await asyncio.gather(
            *(
                _evaluate_one(
                    evaluator_system,
                    num,
                    questions.get(num) or {},
                    official,
                    variants,
                    student,
                )
                for num, official, variants, student in pending
            )
        )
        for (num, official, _variants, student), verdict in zip(pending, judged):
            rows[num] = {
                "number": safe_int(num),
                "student_answer": student,
                "correct_answer": official,
                "correct": verdict["correct"],
                "explanation": verdict["reason"],
                **({"skill": verdict["skill"]} if verdict.get("skill") else {}),
            }

    results = [rows[k] for k in sorted(rows, key=safe_int)]
    score = sum(1 for r in results if r["correct"])
    return {
        "score": score,
        "total": len(results),
        "band_estimate": band_from_40(score, len(results), band_table),
        "results": results,
    }

"""Per-question answer marking shared by the Reading and Listening trainers.

Both sections' evaluator checkpoints were fine-tuned on the user turn built by
tools/build_dataset.py `_evaluator_records`. Building that turn in exactly one
place is what stops the runtime prompt and the training data from drifting
apart — a checkpoint fed an untrained shape degrades silently rather than
failing, so there is nothing to alert on.
"""

import logging
import re

from app.llm.client import gather_llm, get_llm_client

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


def round_band(value: float) -> float:
    """IELTS reports in half bands, and never outside 0-9."""
    return min(9.0, max(0.0, round(value * 2) / 2))


def writing_band(task1: float | None, task2: float | None) -> float | None:
    """The official IELTS weighting: Task 2 is worth twice Task 1.

    A candidate who wrote only one task is banded on that task alone rather
    than averaged against a blank they were never asked to fill.
    """
    if task1 is not None and task2 is not None:
        return round_band((task1 + 2 * task2) / 3)
    only = task2 if task2 is not None else task1
    return None if only is None else round_band(only)


def speaking_band(bands: list[float]) -> float | None:
    """Speaking is one continuous performance — the parts average into a band.

    Unweighted, unlike Writing: the examiner scores the candidate across the
    whole interview rather than scoring each part as a separate task.
    """
    return round_band(sum(bands) / len(bands)) if bands else None


def resolve_choice(question: dict, answer: str) -> str:
    """The option text an answer denotes, for a question that lists options.

    The frontend submits the option LETTER — question-list.tsx labels options
    A, B, C by position and sends that label. Generated answer keys mostly name
    the option TEXT instead: 829 of 845 listening multiple_choice questions do,
    against 175 of 231 reading ones keyed by letter. Comparing the two raw forms
    marks a correct choice wrong, and the evaluator cannot rescue it because the
    user turn it was trained on carries no options list — it sees only
    "Student Answer: B" against "Official Answer: University Restaurant".

    Resolving both sides settles either convention locally, and keeps the letter
    out of the reason string the student reads.
    """
    options = question.get("options")
    if not isinstance(options, list) or not options:
        return answer
    label = str(answer).strip().upper().rstrip(".)")
    if len(label) == 1 and "A" <= label < chr(ord("A") + len(options)):
        return str(options[ord(label) - ord("A")])
    return answer


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
        question = questions.get(num) or {}
        official = resolve_choice(question, str(official_raw or "").strip())
        student = resolve_choice(question, str(student_answers.get(num) or "").strip())
        variants = [
            str(v).strip() for v in (variants_map.get(num) or []) if str(v).strip()
        ]
        if isinstance(question.get("options"), list) and question["options"]:
            # A listed question has a closed answer space — the frontend renders
            # options as buttons, so nothing outside them can ever be submitted
            # and a variant is unreachable by construction. The teacher routinely
            # fills the array with the DISTRACTORS instead (9 corpus questions,
            # one listing all three), which would mark a wrong click correct.
            variants = []
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
        judged = await gather_llm(
            "evaluator",
            [
                _evaluate_one(
                    evaluator_system,
                    num,
                    questions.get(num) or {},
                    official,
                    variants,
                    student,
                )
                for num, official, variants, student in pending
            ],
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


async def mark_full_test(
    sections: list[dict],
    answers: dict,
    check_one,
    band_table: list[tuple[int, float]],
    index_key: str,
    summary_key: str,
) -> dict:
    """Mark a whole test section by section, then band the run as a whole.

    A full test is renumbered globally, so the student submits one flat dict of
    answers for the entire paper. Each section is handed only the numbers it
    owns — passing all of them to every section would have each section mark
    answers it has no question for and report a total nobody can add up.

    The band comes from the aggregate, never from the per-section scores:
    banding each section separately and averaging is not how IELTS converts,
    and would move a borderline candidate by half a band.
    """
    str_answers = {str(k): v for k, v in (answers or {}).items()}
    coros = []
    for section in sections:
        owned = {str(q.get("number")) for q in section.get("questions") or []}
        coros.append(
            check_one(section, {k: v for k, v in str_answers.items() if k in owned})
        )
    outcomes = await gather_llm("evaluator", coros)

    merged: list[dict] = []
    summaries: list[dict] = []
    total_correct = 0
    total_questions = 0
    for section, outcome in zip(sections, outcomes):
        rows = outcome.get("results") or []
        merged.extend(rows)
        score = safe_int(outcome.get("score"))
        section_total = safe_int(
            outcome.get("total"), len(section.get("questions") or [])
        )
        total_correct += score
        total_questions += section_total
        summaries.append(
            {
                index_key: section.get(index_key),
                "title": section.get("title"),
                "score": score,
                "total": section_total,
                "results": rows,
            }
        )

    merged.sort(key=lambda r: safe_int(r.get("number")))
    return {
        "score": total_correct,
        "total": total_questions,
        "band_estimate": band_from_40(total_correct, total_questions, band_table),
        summary_key: summaries,
        "results": merged,
    }

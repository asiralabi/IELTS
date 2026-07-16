import json
import logging

from app.llm.client import get_llm_client
from app.llm.prompts import (
    ANSWER_CHECKER_SYSTEM,
    PASSAGE_EXPANDER_SYSTEM,
    READING_TRAINER_SYSTEM,
)
from app.rag.retriever import retrieve_context

logger = logging.getLogger(__name__)

# Real IELTS passages are 650-900 words. qwen3:4b tends to short-generate;
# anything under this floor triggers an expansion pass so students still get
# exam-realistic length.
_MIN_PASSAGE_WORDS = 550

# Gap-fill question types that carry a word_limit rubric. If the LLM omits
# word_limit or produces an answer that exceeds it, we log — never fail.
_GAP_FILL_TYPES = {
    "sentence_completion",
    "summary_completion",
    "short_answer",
    "note_completion",
    "table_completion",
    "form_completion",
    "flow_chart_completion",
}


def _answer_word_count(answer: str) -> int:
    """Count words in an answer, treating pure numbers as 0 words (per the
    IELTS rubric: numbers do not count toward the word cap).
    """
    tokens = [t for t in str(answer).strip().split() if t]
    return sum(0 if t.replace(",", "").replace(".", "").isdigit() else 1 for t in tokens)


def _check_word_limits(result: dict) -> None:
    """Log a warning for any answer that exceeds its question's word_limit.
    Does not raise — the practice set is still usable if the cap is off by one.
    """
    answer_key = result.get("answer_key") or {}
    for q in result.get("questions") or []:
        if not isinstance(q, dict):
            continue
        qtype = str(q.get("type") or "").lower().replace("-", "_").replace(" ", "_")
        if qtype not in _GAP_FILL_TYPES:
            continue
        limit = q.get("word_limit")
        try:
            limit = int(limit) if limit is not None else None
        except (TypeError, ValueError):
            limit = None
        if limit is None:
            logger.warning(
                "reading_trainer: gap-fill question %s missing word_limit",
                q.get("number"),
            )
            continue
        answer = answer_key.get(str(q.get("number")))
        if answer is None:
            continue
        # Handle multi-answer strings (LLM sometimes returns "a; b")
        candidates = str(answer).split(";") if ";" in str(answer) else [str(answer)]
        for cand in candidates:
            if _answer_word_count(cand) > limit:
                logger.warning(
                    "reading_trainer: answer %r for Q%s exceeds word_limit=%d",
                    cand, q.get("number"), limit,
                )


async def create_practice(
    question_types: list[str] | None = None,
    difficulty: str | None = None,
    topic: str | None = None,
) -> dict:
    parts = ["Generate an IELTS Academic Reading practice set."]
    if question_types:
        parts.append("Question types: " + ", ".join(question_types) + ".")
    if difficulty:
        parts.append(f"Difficulty: {difficulty}.")
    if topic:
        parts.append(f"Topic: {topic}.")

    query = "IELTS Academic Reading passage " + (topic or "") + " " + (
        " ".join(question_types) if question_types else "True False Not Given matching headings"
    )
    # top_k=1 keeps the exemplar tight — extra chunks cost ~800 input tokens
    # each on a CPU-bound model without visibly improving output style.
    context = retrieve_context(query.strip(), top_k=1)
    if context:
        parts.append(
            "\nReal Cambridge IELTS Reading exemplar — match this style, tone, "
            "structure and question difficulty. Do NOT copy its phrasing, "
            "topic, or specific facts; use it as stylistic reference only.\n\n"
            + context
        )

    result = await get_llm_client().complete_json(
        READING_TRAINER_SYSTEM,
        [{"role": "user", "content": "\n".join(parts)}],
        required_keys=("title", "passage", "questions", "answer_key"),
    )

    passage = str(result.get("passage") or "")
    if len(passage.split()) < _MIN_PASSAGE_WORDS:
        expanded = await _expand_passage(passage, str(result.get("title") or ""))
        if expanded and len(expanded.split()) > len(passage.split()):
            result["passage"] = expanded

    _check_word_limits(result)
    return result


async def _expand_passage(passage: str, title: str) -> str | None:
    """Single-call expansion — asks the model to lengthen without changing meaning.

    Returns the raw expanded string or None if the call didn't produce
    something usably longer. Errors are swallowed so a failed expansion
    doesn't kill the whole practice generation.
    """
    if not passage.strip():
        return None
    prompt = (
        f"Title: {title}\n\nPassage to expand:\n{passage}\n\n"
        "Expand this passage to at least 700 words. Keep the same facts, "
        "claims, and paragraph labels; add supporting detail, examples, "
        "and elaboration. Return ONLY the expanded passage prose — no JSON, "
        "no title, no commentary."
    )
    try:
        expanded = await get_llm_client().complete(
            PASSAGE_EXPANDER_SYSTEM,
            [{"role": "user", "content": prompt}],
        )
    except Exception:
        return None
    expanded = expanded.strip()
    return expanded or None


async def check_answers(practice: dict, answers: dict) -> dict:
    payload = {
        "title": practice.get("title"),
        "questions": practice.get("questions", []),
        "answer_key": practice.get("answer_key", {}),
        "student_answers": {str(k): v for k, v in answers.items()},
    }
    if practice.get("passage"):
        payload["passage"] = practice["passage"]
    if practice.get("audio_script"):
        payload["audio_script"] = practice["audio_script"]
    if practice.get("accepted_variants"):
        payload["accepted_variants"] = practice["accepted_variants"]
    return await get_llm_client().complete_json(
        ANSWER_CHECKER_SYSTEM,
        [{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        required_keys=("score", "total", "results"),
    )

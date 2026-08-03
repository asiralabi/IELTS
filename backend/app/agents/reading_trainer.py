import json
import logging
import re

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


_TFNG_TYPES = {"true_false_notgiven", "yes_no_notgiven"}

# Types the teacher writes as a printed block ("complete the flow chart below").
# Nothing renders such a block, so the context has to live in the question text.
_STRUCTURE_TYPES = {
    "summary_completion",
    "note_completion",
    "flow_chart_completion",
    "table_completion",
}


def _qtype(q: dict) -> str:
    return str(q.get("type") or "").lower().replace("-", "_").replace(" ", "_")


def _visual_slots(visual: object) -> set[str]:
    """Question numbers the `visual` object supplies a fillable cell for."""
    if not visual:
        return set()
    return set(re.findall(r"__(\d+)__", json.dumps(visual, ensure_ascii=False)))


# A gap the student writes into: underscores, or the dotted leader a real exam
# paper prints. Three dots are an ellipsis, so a leader needs four.
_GAP_MARKER = re.compile(r"__+|\.{4,}")


def _is_self_contained(text: str) -> bool:
    """True if the item can be answered without the printed block it names.

    Either it shows its own gap, or it is a direct question ("What did the
    Greeks add to the alphabet?") — mistyped as a completion type, but the
    student can still answer it from the passage alone.
    """
    return bool(_GAP_MARKER.search(text)) or text.rstrip().endswith("?")


def validate_practice(result: dict) -> str | None:
    """Reject a practice set a student could not fairly sit.

    Returned as the `validate` hook on complete_json, so a broken set costs one
    corrective retry instead of reaching the student — or, during dataset
    export, becoming a training target that teaches the pathology.
    """
    questions = result.get("questions") or []
    answer_key = result.get("answer_key") or {}
    if not questions or not answer_key:
        return "questions and answer_key must both be non-empty"

    numbers = []
    for q in questions:
        if not isinstance(q, dict):
            return "every entry in questions must be an object"
        if not str(q.get("question") or "").strip():
            return f"question {q.get('number')} has empty question text"
        numbers.append(str(q.get("number")))
    if set(numbers) != set(map(str, answer_key)):
        return "question numbers and answer_key keys must match exactly"

    by_type: dict[str, list[dict]] = {}
    for q in questions:
        by_type.setdefault(_qtype(q), []).append(q)

    headings = by_type.get("matching_headings") or []
    if headings:
        answers = [str(answer_key.get(str(q.get("number")))) for q in headings]
        if len(set(answers)) != len(answers):
            return "each matching_headings answer must be a different heading"
        for q in headings:
            opts = q.get("options")
            if not isinstance(opts, list) or len(opts) < len(headings) + 2:
                return (
                    f"every matching_headings question needs an options list of at "
                    f"least {len(headings) + 2} headings ({len(headings)} paragraphs "
                    "+ 2 distractors)"
                )

    for name in ("multiple_choice", "matching_information", "matching_features",
                 "matching_sentence_endings"):
        block = by_type.get(name) or []
        for q in block:
            if not isinstance(q.get("options"), list) or not q["options"]:
                return f"{name} question {q.get('number')} is missing its options array"
        if len(block) >= 3:
            answers = {str(answer_key.get(str(q.get("number")))).strip().upper() for q in block}
            if len(answers) == 1:
                return (
                    f"all {len(block)} {name} answers are {answers.pop()!r}; spread the "
                    "correct choices across the options"
                )

    slots = _visual_slots(result.get("visual"))
    for q in questions:
        qtype = _qtype(q)
        if qtype not in _STRUCTURE_TYPES:
            continue
        text = str(q.get("question") or "")
        if _is_self_contained(text) or (q.get("options") or []):
            continue
        if str(q.get("number")) in slots:
            continue
        return (
            f"question {q.get('number')} ({qtype}) points at a summary/note/table/"
            "flow chart that the student never sees — nothing renders one. Rewrite "
            "it to carry its own context with the gap shown as ______, e.g. "
            "\"NO MORE THAN TWO WORDS. Ore is crushed, then ______, then washed.\""
            + (" Or emit a `visual` table with a matching __%s__ cell."
               % q.get("number") if qtype == "table_completion" else "")
        )

    tfng = [q for q in questions if _qtype(q) in _TFNG_TYPES]
    if len(tfng) >= 4:
        verdicts = {str(answer_key.get(str(q.get("number")))).strip().upper() for q in tfng}
        if len(verdicts) == 1:
            return (
                f"all {len(tfng)} true/false/not-given answers are "
                f"{verdicts.pop()!r}; a real block mixes the verdicts"
            )
        # The teacher reliably writes only verifiable statements unless pushed.
        # A block with no NOT GIVEN never trains the skill the type exists for.
        if not verdicts & {"NOT GIVEN", "NOTGIVEN", "NG"}:
            return (
                f"none of the {len(tfng)} true/false/not-given answers is NOT GIVEN; "
                "rewrite at least one statement so it makes a plausible claim the "
                "passage never actually states"
            )
    return None


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

    result = await get_llm_client("generator").complete_json(
        READING_TRAINER_SYSTEM,
        [{"role": "user", "content": "\n".join(parts)}],
        required_keys=("title", "passage", "questions", "answer_key"),
        validate=validate_practice,
        # A ~1200-word passage plus 8-13 questions carrying full options lists
        # is a 3.5-5k-token JSON object; LLM_MAX_TOKENS is 2048 locally. A
        # truncation is expensive twice over — the corrective retry replays the
        # truncated text as context, so it has even less room than the first
        # attempt. Buy the headroom.
        max_tokens=6144,
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

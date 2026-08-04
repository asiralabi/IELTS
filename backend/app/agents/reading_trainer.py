import json
import logging
import re

from app.agents.answerability import (
    canon,
    cross_section_error,
    dangling_structure_error,
    parse_word_limit,
    qtype,
)
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
_GAP_FILL_TYPES = {canon(t) for t in (
    "sentence_completion",
    "summary_completion",
    "short_answer",
    "note_completion",
    "table_completion",
    "form_completion",
    "flow_chart_completion",
)}


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
        if qtype(q) not in _GAP_FILL_TYPES:
            continue
        limit = parse_word_limit(q.get("word_limit"))
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


_TFNG_TYPES = {canon("true_false_notgiven"), canon("yes_no_notgiven")}

_ARTICLES = {"a", "an", "the"}


def _span_tokens(text: str) -> list[str]:
    """Words of `text` reduced to a comparable form: punctuation and casing
    dropped, "per cent"/"%" folded to one spelling, leading article stripped
    (the gap usually already supplies it).
    """
    lowered = str(text).lower().replace("per cent", "percent").replace("%", " percent ")
    words = re.sub(r"[^a-z0-9]+", " ", lowered).split()
    while words and words[0] in _ARTICLES:
        words = words[1:]
    return words


def _loose_stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > 4 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def _non_verbatim_answers(result: dict) -> list[str]:
    """Gap-fill answers that appear nowhere in the passage.

    Every completion type instructs the student to choose words FROM THE
    PASSAGE, so an answer that isn't a span of it cannot be produced or marked.
    The teacher's habitual failure is a paraphrase or a truncation — a passage
    reading "gaining attention" keyed as "more attention", or "functionality
    and community" keyed as "functionality community".
    """
    passage = _span_tokens(result.get("passage") or "")
    if not passage:
        return []
    haystack = f" {' '.join(passage)} "
    stemmed = f" {' '.join(_loose_stem(w) for w in passage)} "
    answer_key = result.get("answer_key") or {}
    missing = []
    for q in result.get("questions") or []:
        if not isinstance(q, dict) or qtype(q) not in _GAP_FILL_TYPES:
            continue
        # A question carrying its own word box is answered from the box.
        if isinstance(q.get("options"), list) and q["options"]:
            continue
        answer = answer_key.get(str(q.get("number")))
        if answer is None:
            continue
        for cand in (str(answer).split(";") if ";" in str(answer) else [str(answer)]):
            words = _span_tokens(cand)
            if not words:
                continue
            span = f" {' '.join(words)} "
            span_stemmed = f" {' '.join(_loose_stem(w) for w in words)} "
            if span not in haystack and span_stemmed not in stemmed:
                missing.append(f"Q{q.get('number')}={cand.strip()!r}")
    return missing


def validate_practice(result: dict) -> str | None:
    """Reject a practice set a student could not fairly sit.

    Returned as the `validate` hook on complete_json, so a broken set costs one
    corrective retry instead of reaching the student — or, during dataset
    export, becoming a training target that teaches the pathology.
    """
    cross_section = cross_section_error(result, "reading")
    if cross_section:
        return cross_section

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
        if not qtype(q):
            return (
                f"question {q.get('number')} has no `type`; every question must "
                "declare one of the allowed types so it renders and marks correctly"
            )
        numbers.append(str(q.get("number")))
    if set(numbers) != set(map(str, answer_key)):
        return "question numbers and answer_key keys must match exactly"

    by_type: dict[str, list[dict]] = {}
    for q in questions:
        by_type.setdefault(qtype(q), []).append(q)

    headings = by_type.get(canon("matching_headings")) or []
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
        block = by_type.get(canon(name)) or []
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

    dangling = dangling_structure_error(
        questions, result.get("visual"),
        "Ore is crushed, then ______, then washed.",
    )
    if dangling:
        return dangling

    # One stray paraphrase is teacher noise and costs a retry for little gain;
    # two in the same set is a habit that would train the model to invent
    # answers no student could find.
    unfindable = _non_verbatim_answers(result)
    if len(unfindable) >= 2:
        return (
            f"these gap-fill answers do not appear anywhere in the passage: "
            f"{', '.join(unfindable)}. Completion answers must be copied "
            "verbatim from the passage — the student is told to choose words "
            "FROM THE PASSAGE, so a paraphrase or a shortened phrase is "
            "unmarkable. Either reword the passage to contain the answer "
            "exactly, or key each gap to the exact words already written there."
        )

    tfng = [q for q in questions if qtype(q) in _TFNG_TYPES]
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

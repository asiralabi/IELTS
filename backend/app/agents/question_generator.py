import logging

from app.llm.client import get_llm_client
from app.llm.prompts import QUESTION_GENERATOR_SYSTEM
from app.rag.retriever import retrieve_context

logger = logging.getLogger(__name__)

_SECTION_QUERY_HINTS = {
    "writing": "IELTS Writing task prompt",
    "speaking": "IELTS Speaking part questions cue card",
    "reading": "IELTS Academic Reading passage question block",
    "listening": "IELTS Listening script question block",
}

# The four official IELTS Writing Task 2 essay types. Any task2_type value
# outside this set will be rejected in validation.
_TASK2_TYPES = {"opinion", "discuss_both_views", "problem_solution", "two_part_question"}


def _is_task1_academic(section: str, question_type: str | None) -> bool:
    """Task 1 Academic requires a chart visual. General Training Task 1 (letter)
    is text-only. Detection is heuristic: if the type string mentions "task 1"
    without explicitly saying "general", treat as Academic (the default in this app).
    """
    if section != "writing" or not question_type:
        return False
    qt = question_type.lower()
    if "task 1" not in qt and "task1" not in qt:
        return False
    if "general" in qt or "letter" in qt:
        return False
    return True


def _validate_cue_card(question) -> str | None:
    """Speaking Part 2 must be a dict with topic/bullets/closing, exactly 3
    bullets, closing beginning with "and explain". Returns None on success
    or an error message on failure.
    """
    if not isinstance(question, dict):
        return "Part 2 cue card `question` must be a JSON object with keys topic/bullets/closing"
    for key in ("topic", "bullets", "closing"):
        if key not in question or question[key] in (None, ""):
            return f"Part 2 cue card `question` is missing key: {key}"
    bullets = question.get("bullets")
    if not isinstance(bullets, list) or len(bullets) != 3:
        return "Part 2 cue card `bullets` must be a list of exactly 3 items"
    closing = str(question.get("closing") or "").strip().lower()
    if not closing.startswith("and explain"):
        return 'Part 2 cue card `closing` must start with "and explain"'
    return None


async def generate(
    section: str,
    question_type: str | None = None,
    difficulty: str | None = None,
    topic: str | None = None,
) -> dict:
    parts = [f"Generate an IELTS {section} question."]
    if question_type:
        parts.append(f"Question type: {question_type}.")
    if difficulty:
        parts.append(f"Difficulty: {difficulty}.")
    if topic:
        parts.append(f"Topic: {topic}.")

    hint = _SECTION_QUERY_HINTS.get(section, f"IELTS {section}")
    query = f"{hint} {question_type or ''} {topic or ''}".strip()
    context = retrieve_context(query, top_k=2)
    if context:
        parts.append(
            "\nReal Cambridge IELTS exemplars — match this style, register and "
            "structure. Do NOT copy their phrasing, topics, or answers; use them "
            "as stylistic reference only.\n\n"
            + context
        )

    user_message = "\n".join(parts)
    result = await get_llm_client().complete_json(
        QUESTION_GENERATOR_SYSTEM,
        [{"role": "user", "content": user_message}],
        required_keys=("section", "question_type", "question"),
    )

    qt = str(question_type or result.get("question_type") or "").lower()
    is_task1_academic = _is_task1_academic(section, question_type) or (
        section == "writing"
        and ("task 1" in qt or "task1" in qt)
        and "general" not in qt
        and "letter" not in qt
    )
    is_task2 = section == "writing" and ("task 2" in qt or "task2" in qt)
    is_part2 = section == "speaking" and ("part 2" in qt or "cue card" in qt)

    # ------------------------------------------------------------------
    # Post-generation validation (visual, cue-card structure, task2_type).
    # If any check fails, retry ONCE with a corrective user message. If it
    # still fails, raise ValueError so the endpoint returns a 502.
    # ------------------------------------------------------------------
    problems: list[str] = []
    if is_task1_academic and not result.get("visual"):
        problems.append(
            "This is Writing Task 1 Academic — the top-level `visual` field must be "
            "present and non-null, containing the chart schema described in the system prompt."
        )
    if is_task2:
        t2 = str(result.get("task2_type") or "").strip().lower()
        if t2 not in _TASK2_TYPES:
            problems.append(
                "For Writing Task 2, the top-level `task2_type` field MUST be exactly one of: "
                + ", ".join(sorted(_TASK2_TYPES))
                + "."
            )
    if is_part2:
        err = _validate_cue_card(result.get("question"))
        if err:
            problems.append(err)

    if problems:
        correction = (
            "Your previous reply did not meet the schema requirements: "
            + " ".join(problems)
            + " Regenerate the ENTIRE JSON object with these fixes applied."
        )
        retry_messages = [
            {"role": "user", "content": user_message},
            {
                "role": "assistant",
                "content": "(previous reply omitted for brevity)",
            },
            {"role": "user", "content": correction},
        ]
        result = await get_llm_client().complete_json(
            QUESTION_GENERATOR_SYSTEM,
            retry_messages,
            required_keys=("section", "question_type", "question"),
        )
        # Re-check after retry; raise cleanly if still bad.
        if is_task1_academic and not result.get("visual"):
            raise ValueError(
                "Writing Task 1 Academic requires a non-null `visual` chart payload"
            )
        if is_task2:
            t2 = str(result.get("task2_type") or "").strip().lower()
            if t2 not in _TASK2_TYPES:
                raise ValueError(
                    "Writing Task 2 must return task2_type as one of: "
                    + ", ".join(sorted(_TASK2_TYPES))
                )
            result["task2_type"] = t2
        if is_part2:
            err = _validate_cue_card(result.get("question"))
            if err:
                raise ValueError(err)
    else:
        # Normalise task2_type casing on the happy path.
        if is_task2 and isinstance(result.get("task2_type"), str):
            result["task2_type"] = result["task2_type"].strip().lower()

    return result

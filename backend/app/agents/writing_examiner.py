from typing import Any

from app.llm.client import get_llm_client
from app.llm.prompts import WRITING_EXAMINER_SYSTEM
from app.rag.retriever import retrieve_context

CRITERION_KEYS = (
    "task_response",
    "coherence_cohesion",
    "lexical_resource",
    "grammatical_range_accuracy",
)
SCORED_FIELDS = ("band_score",) + tuple(f"{k}_score" for k in CRITERION_KEYS)
BAND_FIELDS = SCORED_FIELDS + ("estimated_final_band",)


def clamp_band(value: Any) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return min(9.0, max(0.0, round(v * 2) / 2))


def require_numeric_bands(fields: tuple[str, ...]) -> Any:
    def _validate(result: dict) -> str | None:
        bad = [f for f in fields if clamp_band(result.get(f)) is None]
        if bad:
            return (
                "these keys must contain numeric band scores between 0 and 9: "
                + ", ".join(bad)
            )
        return None

    return _validate


def format_chart_data(visual: dict | None) -> str:
    """Render a chart payload as plain-text so the examiner sees the same numbers
    the student saw. Silently returns an empty string on anything unusable.
    """
    if not visual or not isinstance(visual, dict):
        return ""
    if visual.get("kind") != "chart":
        return ""
    chart_type = str(visual.get("chart_type") or "").lower()
    if chart_type not in {"bar", "line", "pie", "table"}:
        return ""
    series = visual.get("series")
    if not isinstance(series, list) or not series:
        return ""

    lines: list[str] = []
    title = str(visual.get("title") or "").strip()
    lines.append(f"Chart type: {chart_type}")
    if title:
        lines.append(f"Title: {title}")
    if visual.get("x_label"):
        lines.append(f"X-axis: {visual['x_label']}")
    if visual.get("y_label"):
        lines.append(f"Y-axis: {visual['y_label']}")

    for s in series:
        if not isinstance(s, dict):
            continue
        name = str(s.get("name") or "").strip() or "series"
        data = s.get("data")
        if not isinstance(data, list):
            continue
        pairs: list[str] = []
        for point in data:
            if isinstance(point, list) and len(point) == 2:
                pairs.append(f"{point[0]}={point[1]}")
            elif isinstance(point, (int, float)):
                pairs.append(str(point))
        if pairs:
            lines.append(f"- {name}: " + ", ".join(pairs))

    if len(lines) <= 4:  # only labels, no data rows
        return ""
    return "\n".join(lines)


async def evaluate(
    task_type: str,
    prompt_text: str,
    essay: str,
    visual: dict | None = None,
) -> dict:
    context = retrieve_context(f"IELTS writing {task_type} band descriptors")
    system = WRITING_EXAMINER_SYSTEM.format(
        context=context or "No reference material retrieved."
    )
    task_label = (
        "Writing Task 2 (essay, 250+ words expected)"
        if task_type == "task2"
        else "Writing Task 1 (report/letter, 150+ words expected)"
    )
    chart_block = format_chart_data(visual)
    parts = [f"Task type: {task_label}", "", f"Task prompt:\n{prompt_text}"]
    if chart_block:
        parts.append("")
        parts.append("CHART DATA (the exact figures shown to the student):")
        parts.append(chart_block)
    parts.append("")
    parts.append(f"Candidate response:\n{essay}")
    user_msg = "\n".join(parts)

    result = await get_llm_client().complete_json(
        system,
        [{"role": "user", "content": user_msg}],
        required_keys=SCORED_FIELDS + ("feedback",),
        validate=require_numeric_bands(SCORED_FIELDS),
    )
    for field in BAND_FIELDS:
        if field in result:
            result[field] = clamp_band(result[field])
    for key in CRITERION_KEYS:
        result[key] = result.pop(f"{key}_score", None)
    result["word_count"] = len(essay.split())
    return result

from typing import Any

from app.llm.client import get_llm_client
from app.llm.prompts import WRITING_EXAMINER_SYSTEM
from app.agents._plan import named_areas
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


def format_plan_data(plans: object) -> str:
    """Render a Task 1 map as plain text: the areas, and what changed.

    The examiner marks Task Achievement against what the student was shown, so
    it has to be shown the same thing. A grid of cells does not read as prose,
    and the drawing is not the point anyway — what matters is which areas each
    plan holds and which of them changed, because that is what the report is
    supposed to say. Silently returns "" on anything unusable, like its chart
    sibling above.
    """
    if not isinstance(plans, list) or len(plans) != 2:
        return ""
    if not all(isinstance(p, dict) and p.get("kind") == "plan" for p in plans):
        return ""

    lines: list[str] = []
    sets = []
    for plan in plans:
        areas = named_areas(plan)
        sets.append(set(areas))
        title = str(plan.get("title") or "").strip() or "plan"
        lines.append(f"{title}: " + (", ".join(areas) if areas else "(nothing named)"))

    before, after = sets
    kept = sorted(before & after)
    gone = sorted(before - after)
    added = sorted(after - before)
    lines.append("")
    lines.append(f"Present in both: {', '.join(kept) if kept else 'nothing'}")
    lines.append(f"Gone by the second plan: {', '.join(gone) if gone else 'nothing'}")
    lines.append(f"New in the second plan: {', '.join(added) if added else 'nothing'}")
    return "\n".join(lines)


async def evaluate(
    task_type: str,
    prompt_text: str,
    essay: str,
    visual: dict | None = None,
    visuals: list | None = None,
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
    plan_block = format_plan_data(visuals)
    parts = [f"Task type: {task_label}", "", f"Task prompt:\n{prompt_text}"]
    if chart_block:
        parts.append("")
        parts.append("CHART DATA (the exact figures shown to the student):")
        parts.append(chart_block)
    if plan_block:
        parts.append("")
        parts.append(
            "MAP DATA (the two plans shown to the student, and what changed "
            "between them):"
        )
        parts.append(plan_block)
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

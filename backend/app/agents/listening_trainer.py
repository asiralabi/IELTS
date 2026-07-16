import asyncio
import logging
import re

from app.agents.reading_trainer import (
    _check_word_limits as _check_word_limits,
)
from app.agents.reading_trainer import check_answers as check_answers  # noqa: F401
from app.llm.client import get_llm_client
from app.llm.prompts import LISTENING_TRAINER_SYSTEM, SCRIPT_EXPANDER_SYSTEM
from app.rag.retriever import retrieve_context

logger = logging.getLogger(__name__)

# Real IELTS Listening audio is 7-8 minutes ≈ 1200-1500 words at natural pace.
# We keep the floor slightly under the prompt target (1200) to allow for
# short-generation without triggering an expansion pass on borderline outputs.
_MIN_SCRIPT_WORDS = 1000

_BLANK_RE = re.compile(r"^__(\d+)__$")

# Each real IELTS Listening test has four parts of ten questions each, with a
# distinct register and typical figure per part.
_PART_SPECS: dict[int, dict[str, str]] = {
    1: {
        "format": (
            "Part 1: a two-speaker conversation in an everyday social or "
            "transactional context (booking a course, enquiring about a "
            "service, registering for membership). Label turns with character "
            "roles (e.g. 'AGENT:' / 'CALLER:')."
        ),
        "figure": (
            "Build the set around a form_completion or table_completion block "
            "so a TABLE figure is shown (include the `visual` table object). "
            "You may add 1-2 multiple_choice questions."
        ),
    },
    2: {
        "format": (
            "Part 2: a single-speaker monologue — a talk, a guided tour, or a "
            "radio segment about a place, facility, or event. Label turns "
            "'SPEAKER:'."
        ),
        "figure": (
            "Include a map_labelling block with 5-6 lettered locations A-F on a "
            "simple plan, so a MAP figure is shown (include the `visual` map "
            "object). Fill the remaining questions with multiple_choice or "
            "short completion. map_labelling answers are LETTERS, with no "
            "`options` array."
        ),
    },
    3: {
        "format": (
            "Part 3: an academic discussion between 2-3 speakers (students "
            "and/or a tutor) about an assignment, project, or study topic. "
            "Label each distinct speaker."
        ),
        "figure": (
            "Use multiple_choice and matching question types. No figure is "
            "needed — set `visual` to null."
        ),
    },
    4: {
        "format": (
            "Part 4: a single-speaker academic monologue or lecture on a "
            "research or general-interest topic. Label turns 'LECTURER:'."
        ),
        "figure": (
            "Use note_completion and sentence_completion (a set of lecture "
            "notes with numbered gaps). No figure is needed — set `visual` to "
            "null."
        ),
    },
}

# Standard Cambridge IELTS (Academic) Listening raw-score → band conversion,
# expressed as (minimum correct out of 40, band). Checked top-down.
_LISTENING_BAND_TABLE: list[tuple[int, float]] = [
    (39, 9.0),
    (37, 8.5),
    (35, 8.0),
    (32, 7.5),
    (30, 7.0),
    (26, 6.5),
    (23, 6.0),
    (18, 5.5),
    (16, 5.0),
    (13, 4.5),
    (10, 4.0),
    (8, 3.5),
    (6, 3.0),
    (4, 2.5),
]


async def create_practice(
    question_types: list[str] | None = None,
    difficulty: str | None = None,
    topic: str | None = None,
) -> dict:
    parts = ["Generate an IELTS Listening practice set."]
    if question_types:
        parts.append("Question types: " + ", ".join(question_types) + ".")
    if difficulty:
        parts.append(f"Difficulty: {difficulty}.")
    if topic:
        parts.append(f"Topic: {topic}.")

    query = "IELTS Listening script " + (topic or "") + " " + (
        " ".join(question_types) if question_types else "form completion note completion map labelling multiple choice"
    )
    # top_k=1: same reasoning as reading — extra chunks cost input eval time
    # on CPU without a matching quality gain.
    context = retrieve_context(query.strip(), top_k=1)
    if context:
        parts.append(
            "\nReal Cambridge IELTS Listening exemplar — match this style, "
            "conversational register, question type mix, and answer-key format. "
            "Do NOT copy its phrasing, scenarios, or specific answers; use it "
            "as stylistic reference only.\n\n"
            + context
        )

    result = await get_llm_client().complete_json(
        LISTENING_TRAINER_SYSTEM,
        [{"role": "user", "content": "\n".join(parts)}],
        required_keys=("title", "audio_script", "questions", "answer_key"),
    )

    script = str(result.get("audio_script") or "")
    if len(script.split()) < _MIN_SCRIPT_WORDS:
        expanded = await _expand_script(script, str(result.get("title") or ""))
        if expanded and len(expanded.split()) > len(script.split()):
            result["audio_script"] = expanded

    _normalize_map_visual(result)
    _check_word_limits(result)
    return result


async def _expand_script(script: str, title: str) -> str | None:
    if not script.strip():
        return None
    prompt = (
        f"Scenario title: {title}\n\nScript to expand:\n{script}\n\n"
        "Extend this listening script to at least 1200 words (real IELTS "
        "Listening audio is 7-8 minutes ≈ 1200-1500 words). Keep every "
        "existing turn, speaker label, testable detail, and correction. Add "
        "more turns of natural conversation OR additional monologue detail "
        "as appropriate for the scenario. Do NOT change any answers that "
        "have already been introduced in the script. Return ONLY the "
        "expanded script text with speaker labels — no JSON, no commentary."
    )
    try:
        expanded = await get_llm_client().complete(
            SCRIPT_EXPANDER_SYSTEM,
            [{"role": "user", "content": prompt}],
        )
    except Exception:
        return None
    expanded = expanded.strip()
    return expanded or None


# ---------------------------------------------------------------------------
# Full 4-part / 40-question test


def _renumber(result: dict, offset: int) -> dict:
    """Shift a single part's questions to global numbering.

    A part is generated with local numbers 1..10; for a full test Part 2 must
    become 11..20, Part 3 → 21..30, etc. Questions are renumbered positionally
    (robust to the model mislabelling), and the answer key and any table
    `__N__` blank placeholders are remapped through the same old→new mapping.
    """
    questions = result.get("questions") or []
    answer_key = result.get("answer_key") or {}
    mapping: dict[str, str] = {}
    new_questions = []
    for i, q in enumerate(questions):
        if not isinstance(q, dict):
            continue
        new_number = offset + i + 1
        mapping[str(q.get("number"))] = str(new_number)
        new_questions.append({**q, "number": new_number})
    new_answer_key = {
        mapping.get(str(k), str(k)): v for k, v in answer_key.items()
    }
    result["questions"] = new_questions
    result["answer_key"] = new_answer_key

    # Keep the answer-number-keyed metadata dicts aligned with the renumbering.
    for meta_key in ("accepted_variants", "answer_positions"):
        meta = result.get(meta_key)
        if isinstance(meta, dict):
            result[meta_key] = {
                mapping.get(str(k), str(k)): v for k, v in meta.items()
            }

    visual = result.get("visual")
    if isinstance(visual, dict) and visual.get("chart_type") == "table":
        for row in visual.get("series") or []:
            if not isinstance(row, dict):
                continue
            for cell in row.get("data") or []:
                if isinstance(cell, list) and len(cell) >= 2:
                    m = _BLANK_RE.match(str(cell[1]))
                    if m:
                        old_n = m.group(1)
                        cell[1] = f"__{mapping.get(old_n, old_n)}__"
    return result


def _num(value: object, default: float) -> float:
    try:
        f = float(str(value))
        return f if f == f else default  # reject NaN
    except (TypeError, ValueError):
        return default


def _clampi(value: float, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(round(value))))


def _normalize_map_visual(result: dict) -> None:
    """Clean a generated map visual in place so it always renders legibly.

    The model reliably produces a *consistent* map (letters match the answer
    key) but is unreliable about *geometry*: it sometimes drops two features on
    the same cell (labels then stack), places them off-grid, or reuses a
    letter. This clamps the grid, guarantees each feature sits on its own
    well-spaced cell, dedupes repeated letters, and prunes degenerate paths —
    none of which the LLM can be trusted to get right every time.
    """
    visual = result.get("visual")
    if not isinstance(visual, dict) or visual.get("kind") != "map":
        return

    gw = max(4, _clampi(_num(visual.get("width"), 10), 4, 24))
    gh = max(4, _clampi(_num(visual.get("height"), 8), 4, 24))
    visual["width"] = gw
    visual["height"] = gh

    raw = [f for f in (visual.get("features") or []) if isinstance(f, dict)]

    # Drop repeated single-letter labels (a duplicated "A" breaks labelling).
    seen_letters: set[str] = set()
    features: list[dict] = []
    for f in raw:
        label = str(f.get("label") or "").strip()
        if len(label) == 1 and label.isalpha():
            up = label.upper()
            if up in seen_letters:
                continue
            seen_letters.add(up)
            f["label"] = up
        features.append(f)

    occupied: set[tuple[int, int]] = set()

    def nearest_free(x: int, y: int) -> tuple[int, int]:
        """Nearest cell not already taken — minimal nudge, preserving layout.

        We only relocate features that genuinely collide, and move them the
        smallest distance possible, so the arrangement the recording describes
        (room B is left of the reception, etc.) stays intact.
        """
        x, y = _clampi(x, 0, gw), _clampi(y, 0, gh)
        if (x, y) not in occupied:
            return x, y
        for radius in range(1, gw + gh + 1):
            best: tuple[int, int] | None = None
            for dx in range(-radius, radius + 1):
                for dy in range(-radius, radius + 1):
                    if max(abs(dx), abs(dy)) != radius:
                        continue
                    nx, ny = _clampi(x + dx, 0, gw), _clampi(y + dy, 0, gh)
                    if (nx, ny) not in occupied:
                        best = (nx, ny)
                        break
                if best:
                    break
            if best:
                return best
        return x, y

    # Keep the model's positions (the script depends on them); only move a
    # feature when it would land on a cell another feature already holds.
    for f in features:
        x = _num(f.get("x"), gw / 2)
        y = _num(f.get("y"), gh / 2)
        if f.get("fixed") and "entrance" in str(f.get("label") or "").lower():
            y = 0
        nx, ny = nearest_free(_clampi(x, 0, gw), _clampi(y, 0, gh))
        occupied.add((nx, ny))
        f["x"], f["y"] = nx, ny

    visual["features"] = features

    clean_paths = []
    for path in visual.get("paths") or []:
        if not isinstance(path, dict):
            continue
        pts = [
            [_clampi(_num(p[0], 0), 0, gw), _clampi(_num(p[1], 0), 0, gh)]
            for p in (path.get("points") or [])
            if isinstance(p, (list, tuple)) and len(p) >= 2
        ]
        if len(pts) >= 2:
            path["points"] = pts
            clean_paths.append(path)
    visual["paths"] = clean_paths


async def create_part(
    part_number: int,
    difficulty: str | None = None,
    topic: str | None = None,
) -> dict:
    """Generate ONE part of a full test (10 questions), globally renumbered."""
    spec = _PART_SPECS[part_number]
    parts = [
        f"Generate ONE part of an IELTS Listening test. {spec['format']}",
        "Produce EXACTLY 10 questions, numbered 1 to 10.",
        spec["figure"],
    ]
    if difficulty:
        parts.append(f"Difficulty: {difficulty}.")
    if topic:
        parts.append(f"Topic: {topic}.")

    query = f"IELTS Listening Part {part_number} script " + (topic or "")
    context = retrieve_context(query.strip(), top_k=1)
    if context:
        parts.append(
            "\nReal Cambridge IELTS Listening exemplar — match this style, "
            "register, and answer-key format. Do NOT copy its phrasing, "
            "scenario, or answers; use it as stylistic reference only.\n\n"
            + context
        )

    result = await get_llm_client().complete_json(
        LISTENING_TRAINER_SYSTEM,
        [{"role": "user", "content": "\n".join(parts)}],
        required_keys=("title", "audio_script", "questions", "answer_key"),
    )

    script = str(result.get("audio_script") or "")
    if len(script.split()) < _MIN_SCRIPT_WORDS:
        expanded = await _expand_script(script, str(result.get("title") or ""))
        if expanded and len(expanded.split()) > len(script.split()):
            result["audio_script"] = expanded

    _renumber(result, (part_number - 1) * 10)
    _normalize_map_visual(result)
    result["part"] = part_number
    _check_word_limits(result)
    return result


async def create_full_test(difficulty: str | None = None) -> dict:
    """Assemble a complete 4-part / 40-question IELTS Listening test."""
    p1, p2, p3, p4 = await asyncio.gather(
        create_part(1, difficulty),
        create_part(2, difficulty),
        create_part(3, difficulty),
        create_part(4, difficulty),
    )
    return {
        "title": "IELTS Listening Practice Test",
        "kind": "full_listening_test",
        "parts": [p1, p2, p3, p4],
    }


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def _listening_band_from_40(correct: int, total: int = 40) -> float:
    """Convert a raw score to an IELTS Listening band using the standard
    40-question conversion table (scaling shorter/partial sets to /40)."""
    if total <= 0:
        return 0.0
    scaled = round(correct * 40 / total)
    for threshold, band in _LISTENING_BAND_TABLE:
        if scaled >= threshold:
            return band
    return 2.0 if scaled >= 2 else 0.0


async def check_full_test(test_payload: dict, answers: dict) -> dict:
    """Mark all 40 answers by checking each part in parallel, then aggregate."""
    parts = test_payload.get("parts") or []
    str_answers = {str(k): v for k, v in (answers or {}).items()}

    coros = []
    for part in parts:
        qnums = {str(q.get("number")) for q in part.get("questions") or []}
        part_answers = {k: v for k, v in str_answers.items() if k in qnums}
        coros.append(check_answers(part, part_answers))
    outcomes = await asyncio.gather(*coros)

    merged_results: list[dict] = []
    part_summaries: list[dict] = []
    total_correct = 0
    total_questions = 0
    for part, outcome in zip(parts, outcomes):
        rows = outcome.get("results") or []
        merged_results.extend(rows)
        score = _safe_int(outcome.get("score"))
        part_total = _safe_int(
            outcome.get("total"), len(part.get("questions") or [])
        )
        total_correct += score
        total_questions += part_total
        part_summaries.append(
            {
                "part": part.get("part"),
                "title": part.get("title"),
                "score": score,
                "total": part_total,
                "results": rows,
            }
        )

    merged_results.sort(key=lambda r: _safe_int(r.get("number")))
    return {
        "score": total_correct,
        "total": total_questions,
        "band_estimate": _listening_band_from_40(total_correct, total_questions),
        "parts": part_summaries,
        "results": merged_results,
    }

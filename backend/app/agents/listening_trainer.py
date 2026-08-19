import logging
import random
import re
from functools import partial

from app.agents._marking import band_from_40, mark_answers, safe_int
from app.agents.answerability import (
    canon,
    cross_section_error,
    dangling_completions,
    dangling_structure_error,
    missing_map_error,
    qtype,
    word_limit_error,
)
from app.llm.client import gather_llm, get_llm_client
from app.llm.prompts import (
    EVALUATOR_SYSTEM,
    FORM_WRITER_SYSTEM,
    LISTENING_TRAINER_SYSTEM,
    SCRIPT_EXPANDER_SYSTEM,
)
from app.rag.retriever import retrieve_context

logger = logging.getLogger(__name__)

# Real IELTS Listening audio is 7-8 minutes ≈ 1200-1500 words at natural pace.
# We keep the floor slightly under the prompt target (1200) to allow for
# short-generation without triggering an expansion pass on borderline outputs.
_MIN_SCRIPT_WORDS = 1000

# An answer key that says the script does not answer the question. The model is
# declining, not answering, so the student can never be marked correct — and
# these train it to decline again. Reading is not given this check: 'NOT GIVEN'
# is a real verdict there, and its corpus carries 1 of these against
# Listening's 14.
_REFUSAL_ANSWER = re.compile(
    r"^(not\s+(provided|given|specified|mentioned|stated|available|applicable"
    r"|determined|answerable|clear|known|found|present|included)"
    r"|n/?a|none|unknown|unspecified|no\s+answer"
    r"|cannot\s+be\s+determined|not\s+enough\s+information)\.?$",
    re.IGNORECASE,
)

_BLANK_RE = re.compile(r"^__(\d+)__$")

# The caption printed beside a gap on a form. 165 corpus labels run 1-4 words
# with a median of 1, so one word of slack over the longest is generous —
# beyond it the model has stopped naming a field and is writing the rubric
# again, which is the thing this repair exists to remove.
_MAX_LABEL_WORDS = 5
# "1. Name" / "2) Address". The model numbers the label it was asked for even
# though the number is what it was given.
_LABEL_PREFIX = re.compile(r"^\s*\d+\s*[.):]\s*")
_LABEL_TRAILING = re.compile(r"[\s:.…]+$")
# The gap the repaired question shows. Matches the corpus's inline route and
# GAP_MARKER, which is what makes the repaired question self-contained.
_GAP = "______"

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
            "Fill the rest with short_answer or sentence_completion. Use AT "
            "MOST 2 multiple_choice questions."
        ),
        "types": "form_completion, short_answer, multiple_choice",
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
            "object). Fill the remaining questions with sentence_completion or "
            "matching, plus AT MOST 2 multiple_choice. map_labelling answers "
            "are LETTERS, with no `options` array."
        ),
        "types": "map_labelling, multiple_choice, short_answer",
    },
    3: {
        "format": (
            "Part 3: an academic discussion between 2-3 speakers (students "
            "and/or a tutor) about an assignment, project, or study topic. "
            "Label each distinct speaker."
        ),
        "figure": (
            "Use a matching block, a flow_chart_completion block tracing the "
            "stages of the project the speakers discuss, and AT MOST 4 "
            "multiple_choice. No figure is needed — set `visual` to null."
        ),
        "types": "multiple_choice, matching",
    },
    4: {
        "format": (
            "Part 4: a single-speaker academic monologue or lecture on a "
            "research or general-interest topic. Label turns 'LECTURER:'."
        ),
        "figure": (
            "Use note_completion, summary_completion and sentence_completion "
            "(lecture notes with numbered gaps). Do NOT use multiple_choice. "
            "No figure is needed — set `visual` to null."
        ),
        "types": "note_completion, sentence_completion",
    },
}


def _finetune_user_message(
    section: int,
    difficulty: str | None,
    topic: str | None,
    question_types: list[str] | None = None,
) -> str:
    """The user turn shape every listening generator SFT record carries.

    Mirrors build_dataset._listening_user_message. Measured against the
    checkpoint: sent this shape it closed the JSON on 6 of 6 samples, peaking at
    2319 output tokens; sent the prose prompt below it looped on a ~78-token
    cycle 1 time in 4 and ran to the 4096-token cap with the object still open.
    The per-part `types` stand in for the `figure` instruction — the corpus
    encodes each part's figure through its question types, and never mentions a
    figure at all.
    """
    return "\n".join([
        "Generate a Listening Test.",
        f"Section: Part {section}",
        f"Difficulty: {difficulty or 'Medium'}",
        f"Topic: {topic or 'unspecified'}",
        "Question Types: "
        + (", ".join(question_types) if question_types else _PART_SPECS[section]["types"]),
        "Target Duration: 7 minutes",
    ])


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


def validate_part(result: dict, *, judge_structure: bool = True) -> str | None:
    """Reject a part a student could not actually sit.

    Passed as the `validate` hook on complete_json so a broken set costs one
    corrective retry instead of reaching the student. The teacher's usual
    failure is emitting a block's shared rubric on its first question and
    leaving the rest with `"question": ""`, which renders as a blank prompt.

    `judge_structure=False` is for the callers that repair a dangling
    completion item afterwards. Measured live, the corrective retry does not
    rescue one — both attempts of both e2e runs failed on it — so spending a
    ~4k-token regeneration on a complaint the repair answers for a few hundred
    tokens buys nothing. Export keeps the default: it has no repair pass, so a
    record that dangles must not become a training target.
    """
    cross_section = cross_section_error(result, "listening")
    if cross_section:
        return cross_section

    questions = result.get("questions") or []
    answer_key = result.get("answer_key") or {}
    if not questions or not answer_key:
        return "questions and answer_key must both be non-empty"

    numbers = []
    mc: list[dict] = []
    for q in questions:
        if not isinstance(q, dict):
            return "every entry in questions must be an object"
        if not str(q.get("question") or "").strip():
            return f"question {q.get('number')} has empty question text"
        numbers.append(str(q.get("number")))
        if qtype(q) == canon("multiple_choice"):
            mc.append(q)
    if set(numbers) != set(map(str, answer_key)):
        return "question numbers and answer_key keys must match exactly"

    # Checked before the structure rule below so a set whose real defect is a
    # missing answer is told that, rather than being sent to repair a question
    # whose gap has nothing to fill it. `_REFUSAL_ANSWER` does not match '', and
    # 0 of 3,965 corpus answers are blank, so this rejects nothing we train on.
    unanswered = sorted(num for num, ans in answer_key.items()
                        if not str(ans).strip())
    if unanswered:
        return (
            f"question(s) {', '.join(unanswered)} have no answer in answer_key — "
            "the student can never be marked correct. Key every question with "
            "the words the script actually says."
        )

    if judge_structure:
        dangling = dangling_structure_error(
            questions, result.get("visual"),
            "Membership form — Preferred start date: ______",
        )
        if dangling:
            return dangling

    mapless = missing_map_error(questions, result.get("visual"))
    if mapless:
        return mapless

    over_limit = word_limit_error(result)
    if over_limit:
        return over_limit

    refusals = [
        f"Q{num}={str(ans).strip()!r}"
        for num, ans in answer_key.items()
        if _REFUSAL_ANSWER.match(str(ans).strip())
    ]
    if refusals:
        return (
            f"these answers say the script does not answer the question: "
            f"{', '.join(sorted(refusals))}. Every question must be answerable "
            "from the audio script. Either add the missing detail to the script "
            "or replace the question with one the script already answers."
        )

    for q in mc:
        opts = q.get("options")
        if not isinstance(opts, list) or not opts:
            return f"multiple_choice question {q.get('number')} is missing its options array"
        answer = str(answer_key.get(str(q.get("number"))) or "").strip()
        letters = {chr(ord("A") + i).lower() for i in range(len(opts))}
        if canon(answer) not in {canon(o) for o in opts} | letters:
            return (
                f"the answer to multiple_choice question {q.get('number')} is "
                f"{answer!r}, which is not one of its options "
                f"({', '.join(repr(str(o)) for o in opts)}). Key it to the exact "
                "text of the correct option — a position number cannot be marked."
            )
    if len(mc) >= 3:
        answers = {str(answer_key.get(str(q.get("number")))).strip().upper() for q in mc}
        if len(answers) == 1:
            return (
                f"all {len(mc)} multiple_choice answers are {answers.pop()!r}; "
                "spread the correct choices across the options"
            )
    return None


async def create_practice(
    question_types: list[str] | None = None,
    difficulty: str | None = None,
    topic: str | None = None,
) -> dict:
    client = get_llm_client("generator")
    if client.is_finetune:
        # Every corpus record is one numbered part, so the fine-tune needs a
        # section. Spread across all four or the warm pool fills with Part 1
        # transactional conversations.
        parts = [
            _finetune_user_message(
                random.randint(1, 4), difficulty, topic, question_types
            )
        ]
    else:
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

    result = await client.complete_json(
        LISTENING_TRAINER_SYSTEM,
        [{"role": "user", "content": "\n".join(parts)}],
        required_keys=("title", "audio_script", "questions", "answer_key"),
        validate=partial(validate_part, judge_structure=False),
        # A full part is a ~1.7-3.1k-token JSON object, but LLM_MAX_TOKENS is
        # 2048 locally — that truncates mid-JSON on the longer half of the
        # range, and each retry costs another ~5 min. The ~2.9k prompt plus
        # this still fits the checkpoint's 8192 context.
        max_tokens=4096,
    )

    # Before the expansion, not after: a label names the field an answer fills
    # and the expander is forbidden to change an answer, so the longer script
    # would only cost input tokens on the repair call.
    await _repair_dangling_completions(result)
    # Skipped on the way in on the promise it would be repaired here.
    problem = validate_part(result)
    if problem:
        raise ValueError(f"the repaired listening set is invalid: {problem}")

    script = str(result.get("audio_script") or "")
    if len(script.split()) < _MIN_SCRIPT_WORDS:
        expanded = await _expand_script(script, str(result.get("title") or ""))
        if expanded and len(expanded.split()) > len(script.split()):
            result["audio_script"] = expanded

    _normalize_map_visual(result)
    return result


def _clean_label(value: object) -> str:
    return _LABEL_TRAILING.sub("", _LABEL_PREFIX.sub("", str(value).strip()))


async def _write_field_labels(
    script: str, gaps: list[tuple[str, str]]
) -> dict[str, str] | None:
    """Ask the model only to name each gap's field — the half it does not drop.

    Measured over 11 live artifacts: where the checkpoint emitted a `visual` at
    all it coupled every cell to its question correctly, 24 of 24. What it
    drops is the form itself, leaving the block's shared rubric behind as the
    question ("Complete the membership details below."). Naming the field one
    answer belongs to is a different task from writing the question and the
    form as one coupled object, and the gap is then placed here rather than
    asked for.

    The reply is a few hundred characters, so unlike a whole part it fits under
    the echo cap — a corrective retry can actually see what it wrote.
    """
    numbers = [number for number, _ in gaps]
    listed = "\n".join(f"{number}. {answer}" for number, answer in gaps)

    def check(reply: dict) -> str | None:
        labels = reply.get("labels")
        if not isinstance(labels, dict):
            return "`labels` must be an object with one gap number per key"
        blank = [n for n in numbers if not str(labels.get(n) or "").strip()]
        if blank:
            return (
                f"no label was written for gap {', '.join(blank)}; write one "
                "for every number you were given"
            )
        cleaned = [_clean_label(labels[n]) for n in numbers]
        overlong = [n for n, text in zip(numbers, cleaned)
                    if len(text.split()) > _MAX_LABEL_WORDS]
        if overlong:
            return (
                f"the label for gap {', '.join(overlong)} is too long to print "
                f"beside a gap; name the field in at most {_MAX_LABEL_WORDS} "
                "words"
            )
        # A form repeats a column heading down its rows and the row tells the
        # two apart, which is why 44.8% of corpus forms carry a duplicate. An
        # inline gap has no row, so here a repeat leaves two questions reading
        # identically and the student cannot tell which answer goes where.
        lowered = [text.lower() for text in cleaned]
        if len(set(lowered)) != len(lowered):
            return (
                "two gaps were given the same label; each label must name what "
                "makes its own gap different from the others"
            )
        return None

    try:
        reply = await get_llm_client("generator").complete_json(
            FORM_WRITER_SYSTEM,
            [{"role": "user", "content":
              f"Listening script:\n{script}\n\nName the form field each of "
              f"these {len(gaps)} answers fills.\n\n{listed}"}],
            required_keys=("labels",),
            validate=check,
            max_tokens=512,
        )
        # Read inside the try on purpose. `check` guarantees the shape only for
        # a client that honours the validate hook, and the caller's fallback
        # needs a None here rather than an exception thrown through it.
        return {n: _clean_label(reply["labels"][n]) for n in numbers}
    except Exception:
        return None


async def _repair_dangling_completions(result: dict) -> None:
    """Give every completion question that shows no gap one of its own.

    The set keeps whatever `visual` it already has: rebuilding the form would
    reproduce the two-artifact coupling that is what the checkpoint drops, and
    a set whose visual is a map has no room for a second object anyway. The
    corpus's other route is single-artifact — 8% of listening completion items
    and 93.4% of reading's, which is the section that does not have this bug —
    so the question is moved onto that one, where there is no second half left
    to lose.

    Left alone if the labels cannot be written. The caller re-validates, so a
    question still pointing at nothing fails loudly rather than reaching a
    student.
    """
    questions = result.get("questions") or []
    dangling = dangling_completions(questions, result.get("visual"))
    if not dangling:
        return

    answer_key = result.get("answer_key") or {}
    gaps = [
        (str(q.get("number")), str(answer_key[str(q.get("number"))]))
        for q in dangling
        if str(q.get("number")) in answer_key
    ]
    if not gaps:
        return

    labels = await _write_field_labels(str(result.get("audio_script") or ""), gaps)
    if not labels:
        return
    for q in dangling:
        label = labels.get(str(q.get("number")))
        if label:
            q["question"] = f"{label}: {_GAP}"


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


def _validate_full_test_part(result: dict, *, judge_structure: bool = True) -> str | None:
    """validate_part, plus the count a full test depends on.

    _renumber assigns global numbers positionally as `offset + i + 1`, so a part
    that comes back with nine questions leaves a hole at the seam and one with
    eleven overlaps the next part. The fine-tune is asked in its training shape,
    which states no count, and returned eight questions on 1 of 6 samples.

    The count is judged either way — the repair rewrites a question, it never
    adds one, so a short part still has to be regenerated.
    """
    problem = validate_part(result, judge_structure=judge_structure)
    if problem:
        return problem
    count = len(result.get("questions") or [])
    if count != 10:
        return f"a full-test part needs exactly 10 questions, not {count}"
    return None


async def create_part(
    part_number: int,
    difficulty: str | None = None,
    topic: str | None = None,
) -> dict:
    """Generate ONE part of a full test (10 questions), globally renumbered."""
    spec = _PART_SPECS[part_number]
    client = get_llm_client("generator")
    if client.is_finetune:
        parts = [_finetune_user_message(part_number, difficulty, topic)]
    else:
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

    result = await client.complete_json(
        LISTENING_TRAINER_SYSTEM,
        [{"role": "user", "content": "\n".join(parts)}],
        required_keys=("title", "audio_script", "questions", "answer_key"),
        validate=partial(_validate_full_test_part, judge_structure=False),
        # A full part is a ~1.7-3.1k-token JSON object, but LLM_MAX_TOKENS is
        # 2048 locally — that truncates mid-JSON on the longer half of the
        # range, and each retry costs another ~5 min. The ~2.9k prompt plus
        # this still fits the checkpoint's 8192 context.
        max_tokens=4096,
    )

    # Before _renumber, so the labels are keyed by the numbers the questions
    # still carry.
    await _repair_dangling_completions(result)
    problem = _validate_full_test_part(result)
    if problem:
        raise ValueError(f"the repaired listening part is invalid: {problem}")

    script = str(result.get("audio_script") or "")
    if len(script.split()) < _MIN_SCRIPT_WORDS:
        expanded = await _expand_script(script, str(result.get("title") or ""))
        if expanded and len(expanded.split()) > len(script.split()):
            result["audio_script"] = expanded

    _renumber(result, (part_number - 1) * 10)
    _normalize_map_visual(result)
    result["part"] = part_number
    return result


async def create_full_test(difficulty: str | None = None) -> dict:
    """Assemble a complete 4-part / 40-question IELTS Listening test."""
    parts = await gather_llm(
        "generator", [create_part(n, difficulty) for n in (1, 2, 3, 4)]
    )
    return {
        "title": "IELTS Listening Practice Test",
        "kind": "full_listening_test",
        "parts": parts,
    }


async def check_answers(practice: dict, answers: dict) -> dict:
    """Mark a Listening part answer-by-answer with the fine-tuned evaluator."""
    return await mark_answers(
        practice, answers, EVALUATOR_SYSTEM, _LISTENING_BAND_TABLE
    )


async def check_full_test(test_payload: dict, answers: dict) -> dict:
    """Mark all 40 answers part by part, then aggregate."""
    parts = test_payload.get("parts") or []
    str_answers = {str(k): v for k, v in (answers or {}).items()}

    coros = []
    for part in parts:
        qnums = {str(q.get("number")) for q in part.get("questions") or []}
        part_answers = {k: v for k, v in str_answers.items() if k in qnums}
        coros.append(check_answers(part, part_answers))
    outcomes = await gather_llm("evaluator", coros)

    merged_results: list[dict] = []
    part_summaries: list[dict] = []
    total_correct = 0
    total_questions = 0
    for part, outcome in zip(parts, outcomes):
        rows = outcome.get("results") or []
        merged_results.extend(rows)
        score = safe_int(outcome.get("score"))
        part_total = safe_int(
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

    merged_results.sort(key=lambda r: safe_int(r.get("number")))
    return {
        "score": total_correct,
        "total": total_questions,
        "band_estimate": band_from_40(
            total_correct, total_questions, _LISTENING_BAND_TABLE
        ),
        "parts": part_summaries,
        "results": merged_results,
    }

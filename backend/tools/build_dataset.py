"""Build structured-JSON fine-tuning datasets for the Listening/Reading engines.

Implements the "Dataset Construction" step of `AI IELTS Listening Exam Engine.md`:
we do NOT train on PDFs — every source is converted into structured JSON, and
from that JSON we emit chat-format SFT records for the two doc models:

  * the GENERATOR  (Qwen2.5 + LoRA): spec/blueprint -> full practice set
  * the EVALUATOR  (separate LoRA): question + answer + variants + student
                                    answer -> verdict / reason / skill

The two sections have genuinely different contracts — Listening is built around
a 4-part audio script with speakers, Reading around a single ~750-word passage —
so `SECTIONS` below holds one `SectionSpec` per section and the record builders
branch on it. Everything else (teacher enrichment, de-duplication, word-limit
reconciliation, evaluator synthesis) is shared.

Three files are produced under ``--out`` (default ``data/datasets``), named for
the ``--section`` being exported:

  cambridge_<section>.jsonl      one structured-JSON record per real Cambridge
                                 test (doc field schema). The passage/dialogue
                                 body is always null — these records document
                                 authentic answer keys and question mixes, and
                                 Cambridge prose must never reach a training
                                 target.
  <section>_generator_sft.jsonl  {messages:[system,user,assistant]} where the
                                 assistant is the section's generation contract
                                 exactly as its system prompt declares it.
                                 Sourced from teacher-generated (70B) payloads.
  <section>_evaluator_sft.jsonl  {messages:[system,user,assistant]} judging one
                                 student answer at a time, with correct /
                                 accepted-variant / incorrect cases synthesised
                                 per question.

Usage (run from the ``backend`` directory):

    python tools/build_dataset.py --section reading                # export DB rows
    python tools/build_dataset.py --section reading --generate 8   # live teacher
    python tools/build_dataset.py --section listening --complete-only

``--generate*`` calls the configured LLM (the NVIDIA-hosted 70B teacher) and
persists each result as a GeneratedQuestion row, so the corpus grows every run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents import listening_trainer, reading_trainer  # noqa: E402
from app.agents.answerability import parse_word_limit  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402
from app.llm.prompts import (  # noqa: E402
    EVALUATOR_SYSTEM,
    LISTENING_TRAINER_SYSTEM,
    READING_EVALUATOR_SYSTEM,
    READING_TRAINER_SYSTEM,
)
from app.models import CambridgeTest, GeneratedQuestion  # noqa: E402

OUT_DIR = Path("data/datasets")

_CLEAN_STATS = {
    "reconciled": 0,
    "cambridge_answers_dropped": 0,
    "cambridge_rows_skipped": 0,
    "below_min_questions": 0,
    "below_min_words": 0,
    "unanswerable": 0,
    "eval_no_question": 0,
}

# Gap-fill families share one sub-skill; keep in sync with the app's
# answerability.GAP_FILL_TYPES so training labels match runtime behaviour.
_GAP_FILL = {
    "form_completion",
    "note_completion",
    "table_completion",
    "flow_chart_completion",
    "sentence_completion",
    "short_answer",
    "summary_completion",
}


@dataclass(frozen=True)
class SectionSpec:
    """Everything that differs between the Listening and Reading pipelines."""

    name: str
    body_field: str  # the payload key holding the prose the questions are set on
    trainer_system: str
    evaluator_system: str
    gap_fill_skill: str
    default_skill: str
    skill_by_type: dict[str, str] = field(default_factory=dict)
    # Why a synthesised wrong answer is wrong. Section-specific because the
    # source of the error differs — a listener mishears the recording, a reader
    # miscopies the passage.
    distractor_reason: str = ""
    number_reason: str = ""
    misspelling_reason: str = ""
    # Only Reading's Cambridge answer keys need sanitising. Listening's parse
    # cleanly and legitimately carry examiner notes ('Prescott (must be correct
    # spelling...)'), which a length-based filter would throw away as debris.
    clean_cambridge_answers: bool = False
    # Generator targets with fewer questions than this are dropped. Reading's
    # system prompt demands 8-13 questions, so a stray 1-question row teaches
    # the model to ignore its own rubric. 0 disables the floor.
    min_questions: int = 0
    # Same idea for prose length. 550 matches reading_trainer._MIN_PASSAGE_WORDS
    # — anything the runtime would itself have sent for expansion is too short
    # to train on. 0 disables the floor.
    min_body_words: int = 0


SECTIONS: dict[str, SectionSpec] = {
    "listening": SectionSpec(
        name="listening",
        body_field="audio_script",
        trainer_system=LISTENING_TRAINER_SYSTEM,
        evaluator_system=EVALUATOR_SYSTEM,
        skill_by_type={
            "multiple_choice": "listening for gist and detail; resolving distractors",
            "map_labelling": "following directions and spatial language on a map/plan",
            "matching": "matching and classifying information across speakers",
        },
        gap_fill_skill="listening for specific detail (spelling, numbers, gap-fill)",
        default_skill="listening comprehension",
        distractor_reason="a distractor option the recording rules out",
        number_reason="a nearby number mentioned as a distractor before the correction",
        misspelling_reason="a mishearing/misspelling of the word heard",
    ),
    "reading": SectionSpec(
        name="reading",
        body_field="passage",
        trainer_system=READING_TRAINER_SYSTEM,
        evaluator_system=READING_EVALUATOR_SYSTEM,
        skill_by_type={
            "true_false_notgiven": "distinguishing stated facts from contradictions and absent information",
            "yes_no_notgiven": "identifying the writer's own views, claims and predictions",
            "matching_headings": "identifying the main idea of a paragraph",
            "matching_information": "locating specific information within paragraphs",
            "multiple_choice": "reading for detail; resolving distractors",
            "matching": "matching and classifying information across the passage",
        },
        gap_fill_skill="scanning for specific detail (exact wording from the passage)",
        default_skill="reading comprehension",
        distractor_reason="a distractor option the passage rules out",
        number_reason="a nearby number in the passage that the question does not ask for",
        misspelling_reason="a misspelling of a word that appears in the passage",
        clean_cambridge_answers=True,
        min_questions=6,
        min_body_words=550,
    ),
}

# Cues a speaker uses when they correct themselves — the doc's "corrections"
# signal and a core IELTS Listening distractor device.
_CORRECTION_CUES = re.compile(
    r"\b(sorry|actually|i mean|no,? wait|correction|scratch that|"
    r"let me correct|hang on|oh,? no)\b",
    re.IGNORECASE,
)
_LABEL_RE = re.compile(r"^\s*([A-Z][A-Za-z .'-]{0,24}?):", re.MULTILINE)
_CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

_NUM_WORDS = {
    0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
    6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven",
    12: "twelve", 13: "thirteen", 14: "fourteen", 15: "fifteen",
    16: "sixteen", 17: "seventeen", 18: "eighteen", 19: "nineteen",
    20: "twenty", 30: "thirty", 40: "forty", 50: "fifty", 60: "sixty",
    70: "seventy", 80: "eighty", 90: "ninety",
}

# Registers + default voices per Listening Part, used when a teacher row predates
# the `speakers`/`blueprint` fields so every SFT target is still well-formed.
_PART_META = {
    1: ("Part 1", "conversational", 150),
    2: ("Part 2", "informational monologue", 145),
    3: ("Part 3", "academic discussion", 160),
    4: ("Part 4", "lecture", 140),
}


def _norm_type(value: object) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _canon_type(value: object) -> str:
    """Punctuation-free key for matching a question type against the contract's
    allowed values. Rows written by the app store whatever label the caller
    sent ('True/False/Not Given'), while the system prompts declare snake_case
    ('true_false_notgiven'); collapsing both to 'truefalsenotgiven' lets one
    table serve either form."""
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


_GAP_FILL_CANON = {_canon_type(t) for t in _GAP_FILL}

# Canonical spelling of every question type each section's system prompt
# declares. The teacher freely mixes the contract's snake_case with display
# forms ("form completion", "map/plan labelling"), and a target carrying both
# teaches the model that either is acceptable — which pushes the cost onto
# every consumer, who must then canonicalise on read.
_CONTRACT_TYPES: dict[str, dict[str, str]] = {
    "reading": {
        _canon_type(t): t
        for t in (
            "true_false_notgiven", "yes_no_notgiven", "matching_headings",
            "matching_information", "matching_features",
            "matching_sentence_endings", "multiple_choice",
            "sentence_completion", "summary_completion", "note_completion",
            "table_completion", "flow_chart_completion", "short_answer",
        )
    },
    "listening": {
        _canon_type(t): t
        for t in (
            "form_completion", "note_completion", "table_completion",
            "flow_chart_completion", "summary_completion", "multiple_choice",
            "map_labelling", "sentence_completion", "short_answer", "matching",
        )
    },
}

# Display forms that survive punctuation-stripping as a distinct key, so the
# contract table alone cannot match them ("map/plan labelling" collapses to
# "mapplanlabelling", never "maplabelling").
_TYPE_ALIASES = {
    "mapplanlabelling": "map_labelling",
    "planlabelling": "map_labelling",
}


def _canonical_type(value: object, spec: SectionSpec) -> str:
    """The contract spelling of a question type, for this section."""
    table = _CONTRACT_TYPES.get(spec.name, {})
    key = _canon_type(value)
    if key in table:
        return table[key]
    aliased = _canon_type(_TYPE_ALIASES.get(key, ""))
    if aliased in table:
        return table[aliased]
    return _norm_type(value)


def _canonicalize_types(target: dict, spec: SectionSpec) -> None:
    """Rewrite every question's `type` to its section's contract spelling."""
    for q in target.get("questions") or []:
        if isinstance(q, dict) and q.get("type") is not None:
            q["type"] = _canonical_type(q.get("type"), spec)


def _skill_for(qtype: str, spec: SectionSpec) -> str:
    t = _canon_type(qtype)
    if t in _GAP_FILL_CANON:
        return spec.gap_fill_skill
    return _canon_keys(spec.skill_by_type).get(t, spec.default_skill)


def _canon_keys(mapping: dict[str, str]) -> dict[str, str]:
    return {_canon_type(k): v for k, v in mapping.items()}


def _num_word(text: str) -> str | None:
    """Word form of a small integer answer ('15' -> 'fifteen'), else None."""
    s = str(text).strip()
    if not s.isdigit():
        return None
    n = int(s)
    if n in _NUM_WORDS:
        return _NUM_WORDS[n]
    if 21 <= n <= 99:
        tens, ones = divmod(n, 10)
        return f"{_NUM_WORDS[tens * 10]}-{_NUM_WORDS[ones]}"
    return None


def _derive_variants(answer: object) -> list[str]:
    """Best-effort accepted variants for teacher rows that lack an explicit set.

    Only surface forms that IELTS genuinely accepts (digit/word for numbers,
    a couple of standard abbreviations); never anything that changes meaning.
    """
    ans = str(answer or "").strip()
    if not ans:
        return []
    out: list[str] = []
    word = _num_word(ans)
    if word:
        out.append(word)
    abbr = {"street": "St", "road": "Rd", "avenue": "Ave", "saint": "St"}
    low = ans.lower()
    for full, short in abbr.items():
        if low.endswith(full):
            out.append(re.sub(full, short, ans, flags=re.IGNORECASE).strip())
    # de-dupe, drop anything equal to the answer itself
    seen: list[str] = []
    for v in out:
        if v and v.lower() != ans.lower() and v not in seen:
            seen.append(v)
    return seen


def _script_labels(script: str) -> list[str]:
    """Distinct speaker labels in first-seen order from a labelled script."""
    seen: list[str] = []
    for m in _LABEL_RE.finditer(script or ""):
        label = m.group(1).strip()
        if label and label not in seen:
            seen.append(label)
    return seen


def _default_speakers(labels: list[str], wpm: int) -> list[dict]:
    genders = ("female", "male")
    return [
        {
            "label": lab,
            "gender": genders[i % 2],
            "accent": "British",
            "persona": "natural, clear",
            "wpm": wpm,
            "pause_ms": 300,
        }
        for i, lab in enumerate(labels)
    ]


def _question_types(questions: list) -> list[str]:
    types: list[str] = []
    for q in questions or []:
        if isinstance(q, dict):
            t = _norm_type(q.get("type"))
            if t and t not in types:
                types.append(t)
    return types


def _part_number(part: dict) -> int:
    n = part.get("part")
    try:
        n = int(n)
    except (TypeError, ValueError):
        n = 1
    return n if n in _PART_META else 1


def _paragraph_count(passage: str) -> int:
    return len([p for p in re.split(r"\n\s*\n", passage or "") if p.strip()])


# ---------------------------------------------------------------------------
# Doc structured-JSON record


def _structured_from_part(part: dict, difficulty: str, spec: SectionSpec) -> dict:
    """Convert a teacher-generated unit into the doc's structured JSON schema."""
    if spec.name == "reading":
        return _structured_from_reading_set(part, difficulty)
    return _structured_from_listening_part(part, difficulty)


def _structured_from_listening_part(part: dict, difficulty: str) -> dict:
    """{section, topic, dialogue, speakers, speaker_roles, difficulty,
    question_types, answers, accepted_variants, distractors, answer_positions,
    speech_rate, pauses, corrections, audio_duration, vocabulary_level,
    information_density}."""
    script = str(part.get("audio_script") or "")
    words = len(script.split())
    questions = part.get("questions") or []
    answer_key = part.get("answer_key") or {}
    blueprint = part.get("blueprint") if isinstance(part.get("blueprint"), dict) else {}
    pn = _part_number(part)
    _section, register, default_wpm = _PART_META[pn]

    speakers = part.get("speakers")
    if not isinstance(speakers, list) or not speakers:
        speakers = _default_speakers(_script_labels(script), default_wpm)
    wpms = [s.get("wpm") for s in speakers if isinstance(s, dict) and s.get("wpm")]
    pauses = [s.get("pause_ms") for s in speakers if isinstance(s, dict) and s.get("pause_ms") is not None]
    speech_rate = round(sum(wpms) / len(wpms)) if wpms else default_wpm

    distractors: dict[str, list] = {}
    for q in questions:
        if isinstance(q, dict) and q.get("options"):
            distractors[str(q.get("number"))] = list(q.get("options") or [])

    return {
        "section": blueprint.get("section") or f"Part {pn}",
        "topic": blueprint.get("topic") or part.get("title") or "",
        "dialogue": script,
        "speakers": speakers,
        "speaker_roles": [s.get("label") for s in speakers if isinstance(s, dict)],
        "difficulty": blueprint.get("difficulty") or difficulty or "Band 6-7",
        "question_types": blueprint.get("question_type_plan") or _question_types(questions),
        "answers": answer_key,
        "accepted_variants": part.get("accepted_variants") or {},
        "distractors": distractors,
        "answer_positions": part.get("answer_positions") or {},
        "speech_rate": speech_rate,
        "pauses": round(sum(pauses) / len(pauses)) if pauses else 300,
        "corrections": len(_CORRECTION_CUES.findall(script)),
        "audio_duration": round(words / (speech_rate / 60)) if speech_rate else 0,
        "vocabulary_level": blueprint.get("difficulty") or difficulty or "upper-intermediate",
        "information_density": round(len(answer_key) / max(1, words / 100), 2),
    }


def _structured_from_reading_set(part: dict, difficulty: str) -> dict:
    """Reading's analogue: no speakers or audio timing, but passage shape
    (length, paragraph count) is what drives question difficulty."""
    passage = str(part.get("passage") or "")
    words = len(passage.split())
    questions = part.get("questions") or []
    answer_key = part.get("answer_key") or {}

    distractors: dict[str, list] = {}
    for q in questions:
        if isinstance(q, dict) and q.get("options"):
            distractors[str(q.get("number"))] = list(q.get("options") or [])

    return {
        "section": "Academic Reading passage",
        "topic": part.get("topic") or part.get("title") or "",
        "passage": passage,
        "difficulty": difficulty or "Band 6-7",
        "question_types": _question_types(questions),
        "answers": answer_key,
        "accepted_variants": part.get("accepted_variants") or {},
        "distractors": distractors,
        "passage_length": words,
        "paragraph_count": _paragraph_count(passage),
        "vocabulary_level": difficulty or "upper-intermediate",
        "information_density": round(len(answer_key) / max(1, words / 100), 2),
    }


def _clean_cambridge_answer(value: object) -> str | None:
    """Drop answers the PDF parser mangled. Cambridge Reading keys in
    particular contain control-character runs and sentence fragments lifted
    from the surrounding explanation text; a real answer is a few words at
    most, so anything longer or unprintable is parse debris, not data."""
    s = str(value or "").strip()
    if not s or _CTRL_RE.search(s):
        return None
    if len(s.split()) > 5:
        return None
    if not re.search(r"[A-Za-z0-9]", s):
        return None
    return s


def _structured_from_cambridge(test: CambridgeTest, spec: SectionSpec) -> dict | None:
    """Structured JSON for a real Cambridge test. The prose body stays null
    (Cambridge text must never become a training target); the value is the
    authentic answer key + question mix."""
    data = getattr(test, spec.name) or {}
    raw_key = data.get("answer_key") or {}
    answer_key: dict[str, str] = {}
    for num, value in raw_key.items():
        if not spec.clean_cambridge_answers:
            answer_key[str(num)] = value
            continue
        cleaned = _clean_cambridge_answer(value)
        if cleaned is None:
            _CLEAN_STATS["cambridge_answers_dropped"] += 1
        else:
            answer_key[str(num)] = cleaned
    if not answer_key:
        _CLEAN_STATS["cambridge_rows_skipped"] += 1
        return None

    units = data.get("parts") if spec.name == "listening" else data.get("passages")
    qtypes: list[str] = []
    for unit in units or []:
        for block in unit.get("question_blocks") or []:
            t = _norm_type(block.get("type"))
            if t and t not in qtypes:
                qtypes.append(t)

    source = f"{test.book_id}-test{test.test_number}"
    if spec.name == "listening":
        return {
            "source": source,
            "section": "full_listening_test",
            "topic": None,
            "dialogue": None,
            "speakers": None,
            "speaker_roles": None,
            "difficulty": "Band 5-9 (official)",
            "question_types": qtypes,
            "answers": answer_key,
            "accepted_variants": {},
            "distractors": {},
            "answer_positions": {},
            "speech_rate": None,
            "pauses": None,
            "corrections": None,
            "audio_duration": None,
            "vocabulary_level": "official IELTS",
            "information_density": None,
        }
    passages = units or []
    return {
        "source": source,
        "section": "full_reading_test",
        "topic": None,
        "passage": None,
        "difficulty": "Band 5-9 (official)",
        "question_types": qtypes,
        "answers": answer_key,
        "accepted_variants": {},
        "distractors": {},
        "passage_titles": [str(p.get("title") or "") for p in passages],
        "passage_lengths": [len(str(p.get("text") or "").split()) for p in passages],
        "paragraph_count": None,
        "vocabulary_level": "official IELTS",
        "information_density": None,
    }


# ---------------------------------------------------------------------------
# Generator SFT (spec -> the section's declared contract)


def _spec_user_message(part: dict, difficulty: str, spec: SectionSpec) -> str:
    if spec.name == "reading":
        return _reading_user_message(part, difficulty)
    return _listening_user_message(part, difficulty)


def _listening_user_message(part: dict, difficulty: str) -> str:
    pn = _part_number(part)
    section, _register, _wpm = _PART_META[pn]
    qtypes = _question_types(part.get("questions") or [])
    blueprint = part.get("blueprint") if isinstance(part.get("blueprint"), dict) else {}
    topic = blueprint.get("topic") or part.get("title") or "unspecified"
    lines = [
        "Generate a Listening Test.",
        f"Section: {section}",
        f"Difficulty: {difficulty or blueprint.get('difficulty') or 'Medium'}",
        f"Topic: {topic}",
    ]
    if qtypes:
        lines.append("Question Types: " + ", ".join(qtypes))
    lines.append("Target Duration: 7 minutes")
    return "\n".join(lines)


def _reading_user_message(part: dict, difficulty: str) -> str:
    """Mirrors reading_trainer.create_practice's prompt construction so the
    fine-tune sees at training time the exact shape it is served at runtime.
    The RAG exemplar block is deliberately omitted — it is Cambridge prose and
    varies per call, so training on it would both leak source text and teach
    the model to expect an exemplar that may not be retrieved."""
    lines = ["Generate an IELTS Academic Reading practice set."]
    # Stored rows carry whatever label the caller sent; prompt with the
    # contract's own spelling so the input matches the allowed `type` values
    # the model must emit.
    qtypes: list[str] = []
    for t in _question_types(part.get("questions") or []):
        canon = _canonical_type(t, SECTIONS["reading"])
        if canon not in qtypes:
            qtypes.append(canon)
    if qtypes:
        lines.append("Question types: " + ", ".join(qtypes) + ".")
    # "unspecified" is the reading router's placeholder when the caller sent no
    # difficulty — it is not a value the model should be asked to honour.
    if difficulty and difficulty.lower() != "unspecified":
        lines.append(f"Difficulty: {difficulty}.")
    topic = part.get("topic") or part.get("title")
    if topic:
        lines.append(f"Topic: {topic}.")
    return "\n".join(lines)


def _answer_word_count(answer: object) -> int:
    """Words in an answer, treating pure numbers as 0 (IELTS rubric: numbers
    don't count toward the word cap). Mirrors reading_trainer._answer_word_count
    so the export matches the runtime warning logic exactly."""
    tokens = [t for t in str(answer).strip().split() if t]
    return sum(0 if t.replace(",", "").replace(".", "").isdigit() else 1 for t in tokens)


def _reconcile_word_limits(target: dict) -> None:
    """Bump each gap-fill question's word_limit up to fit its answer so the SFT
    target never contradicts itself. The teacher routinely states 'ONE WORD'
    then supplies a two- or three-word answer; training on that teaches the
    model to violate its own rubric. We trust the answer (the graded value) and
    raise the stated cap to match. Only genuine violations are touched."""
    answer_key = target.get("answer_key") or {}
    for q in target.get("questions") or []:
        if not isinstance(q, dict):
            continue
        if _canon_type(q.get("type")) not in _GAP_FILL_CANON:
            continue
        answer = answer_key.get(str(q.get("number")))
        if answer is None:
            continue
        needed = max(
            (_answer_word_count(c) for c in str(answer).split(";")), default=0
        )
        limit = parse_word_limit(q.get("word_limit"))
        if limit is None:
            # Gap-fill must carry a cap; the teacher sometimes omits it or
            # phrases it unparseably. Default to the answer's length (min 1).
            q["word_limit"] = max(1, needed)
            _CLEAN_STATS["reconciled"] += 1
        elif needed > limit:
            q["word_limit"] = needed
            _CLEAN_STATS["reconciled"] += 1
        elif not isinstance(q.get("word_limit"), int):
            # Both contracts declare word_limit an int and the shared runtime
            # check calls int() on it directly — a rubric sentence here raises
            # ValueError, which that check swallows, silently skipping the cap.
            q["word_limit"] = limit
            _CLEAN_STATS["reconciled"] += 1


def _generator_target(part: dict, difficulty: str, complete_only: bool,
                      spec: SectionSpec) -> dict | None:
    """The doc-ideal assistant completion: exactly the generator contract."""
    if spec.name == "reading":
        target = _reading_target(part)
    else:
        target = _listening_target(part, difficulty, complete_only)
    if target is None:
        return None
    if not _is_answerable(target, spec):
        _CLEAN_STATS["unanswerable"] += 1
        return None
    if spec.min_questions and len(target.get("questions") or []) < spec.min_questions:
        _CLEAN_STATS["below_min_questions"] += 1
        return None
    if spec.min_body_words:
        words = len(str(target.get(spec.body_field) or "").split())
        if words < spec.min_body_words:
            _CLEAN_STATS["below_min_words"] += 1
            return None
    _reconcile_word_limits(target)
    _canonicalize_types(target, spec)
    return target


def _is_answerable(target: dict, spec: SectionSpec) -> bool:
    """Reject whole units a student could not actually sit.

    Each section is held to the validator that already gates its generation, so
    a set the runtime would have sent back for a corrective retry never becomes
    a training target either. Rows predating those validators are exactly the
    ones this drops: blank question text under a block's shared rubric, answer
    keys that don't line up with the question numbers, every multiple-choice
    answer 'A', and completion items pointing at a table nothing renders.
    """
    if spec.name == "reading":
        return reading_trainer.validate_practice(target) is None
    return listening_trainer.validate_part(target) is None


def _reading_target(part: dict) -> dict | None:
    """READING_TRAINER_SYSTEM declares exactly {title, passage, visual,
    questions, answer_key} — nothing more. Adding a field the contract doesn't
    mention (source) would train the model to break its own stated schema, and
    omitting `visual` would teach it to skip the table a table_completion set
    needs."""
    passage = str(part.get("passage") or "")
    questions = part.get("questions") or []
    answer_key = part.get("answer_key") or {}
    if not passage or not questions or not answer_key:
        return None
    visual = part.get("visual")
    return {
        "title": part.get("title") or "",
        "passage": passage,
        "visual": visual if isinstance(visual, dict) else None,
        "questions": questions,
        "answer_key": answer_key,
    }


def _listening_target(part: dict, difficulty: str, complete_only: bool) -> dict | None:
    script = str(part.get("audio_script") or "")
    questions = part.get("questions") or []
    answer_key = part.get("answer_key") or {}
    if not script or not questions or not answer_key:
        return None

    has_full = bool(part.get("blueprint")) and bool(part.get("speakers")) and (
        "accepted_variants" in part
    )
    if complete_only and not has_full:
        return None

    pn = _part_number(part)
    section, register, default_wpm = _PART_META[pn]

    blueprint = part.get("blueprint")
    if not isinstance(blueprint, dict) or not blueprint:
        blueprint = {
            "section": section,
            "topic": part.get("title") or "",
            "difficulty": difficulty or "Band 6-7",
            "register": register,
            "question_type_plan": _question_types(questions),
            "distractor_strategy": "a speaker states a detail then corrects it",
            "answer_distribution": "answers spread evenly in script order",
        }

    speakers = part.get("speakers")
    if not isinstance(speakers, list) or not speakers:
        speakers = _default_speakers(_script_labels(script), default_wpm)

    accepted = part.get("accepted_variants")
    if not isinstance(accepted, dict):
        accepted = {k: _derive_variants(v) for k, v in answer_key.items()}

    target: dict[str, Any] = {
        "blueprint": blueprint,
        "title": part.get("title") or "",
        "audio_script": script,
        "speakers": speakers,
        "visual": part.get("visual"),
        "questions": questions,
        "answer_key": answer_key,
        "accepted_variants": accepted,
    }
    positions = part.get("answer_positions")
    if isinstance(positions, dict) and positions:
        target["answer_positions"] = positions
    return target


def _generator_records(part: dict, difficulty: str, complete_only: bool,
                       spec: SectionSpec) -> list[dict]:
    target = _generator_target(part, difficulty, complete_only, spec)
    if target is None:
        return []
    return [
        {
            "messages": [
                {"role": "system", "content": spec.trainer_system},
                {"role": "user", "content": _spec_user_message(part, difficulty, spec)},
                {
                    "role": "assistant",
                    "content": json.dumps(target, ensure_ascii=False),
                },
            ]
        }
    ]


# ---------------------------------------------------------------------------
# Evaluator SFT (one student answer at a time)


def _wrong_answer(answer: str, options: list | None, spec: SectionSpec) -> tuple[str, str] | None:
    """A plausible incorrect student answer + why it is wrong.

    Prefers a real distractor (another MC option, or a corrected-away value);
    falls back to a number perturbation, a dropped word, or a blank.
    """
    ans = str(answer or "").strip()
    if not ans:
        return None
    if options:
        for opt in options:
            label = str(opt).strip()
            if label and label.lower() != ans.lower():
                # MC keys are letters; map an option to its letter if needed
                letter = label[:1].upper() if label[:1].isalpha() else label
                cand = letter if len(ans) == 1 and ans.isalpha() else label
                if cand.lower() != ans.lower():
                    return cand, spec.distractor_reason
    if ans.isdigit():
        n = int(ans)
        return str(n + 1 if n < 9 else n - 1), spec.number_reason
    parts = ans.split()
    if len(parts) > 1:
        return " ".join(parts[:-1]), "an incomplete answer that drops a required word"
    if len(ans) > 3:
        return ans[:-1] + ("s" if not ans.endswith("s") else ""), spec.misspelling_reason
    return "", "a blank answer (nothing written)"


_TFNG = {"true", "false", "not given", "yes", "no", "notgiven", "not_given"}


def _wrong_for_section(answer: str, options: list | None, spec: SectionSpec) -> tuple[str, str] | None:
    """Reading's verdict types have a closed answer set, so the generic
    perturbations ('misspelling') produce nonsense like 'TRUEs'. Swap to
    another member of the same set instead."""
    ans = str(answer or "").strip()
    if spec.name == "reading" and ans.lower() in _TFNG:
        low = ans.lower()
        if low in {"true", "false"}:
            other = "FALSE" if low == "true" else "TRUE"
            return other, "the opposite verdict; the passage does state this"
        if low in {"yes", "no"}:
            other = "NO" if low == "yes" else "YES"
            return other, "the opposite verdict for the writer's view"
        return "TRUE", "a stated fact, when the passage never makes this claim"
    return _wrong_answer(ans, options, spec)


def _evaluator_records(part: dict, spec: SectionSpec) -> list[dict]:
    questions = {str(q.get("number")): q for q in (part.get("questions") or []) if isinstance(q, dict)}
    answer_key = part.get("answer_key") or {}
    variants_map = part.get("accepted_variants")
    if not isinstance(variants_map, dict):
        variants_map = {}
    records: list[dict] = []

    for num, answer in answer_key.items():
        ans = str(answer or "").strip()
        if not ans:
            continue
        q = questions.get(str(num), {})
        qtext = str(q.get("question") or "").strip()
        if not qtext:
            # At inference the evaluator always sees real question text. A
            # "Question 7" placeholder would train it to mark blind.
            _CLEAN_STATS["eval_no_question"] += 1
            continue
        options = q.get("options")
        skill = _skill_for(q.get("type"), spec)
        variants = variants_map.get(str(num))
        if not isinstance(variants, list) or not variants:
            variants = _derive_variants(ans)

        def _rec(student: str, verdict: str, reason: str) -> dict:
            user = (
                f"Question: {qtext}\n"
                f"Official Answer: {ans}\n"
                f"Accepted Variants: {', '.join(variants) if variants else 'none'}\n"
                f"Student Answer: {student if student else '(blank)'}"
            )
            assistant = {
                "verdict": verdict,
                "reason": reason,
                "correct_answer": ans,
                "skill": skill,
            }
            return {
                "messages": [
                    {"role": "system", "content": spec.evaluator_system},
                    {"role": "user", "content": user},
                    {"role": "assistant", "content": json.dumps(assistant, ensure_ascii=False)},
                ]
            }

        records.append(
            _rec(ans, "correct", "Matches the official answer exactly under IELTS marking.")
        )
        if variants:
            records.append(
                _rec(
                    variants[0],
                    "correct",
                    f"Accepted as an IELTS-recognised variant of '{ans}'.",
                )
            )
        wrong = _wrong_for_section(ans, options if isinstance(options, list) else None, spec)
        if wrong is not None:
            student, why = wrong
            records.append(
                _rec(student, "incorrect", f"The correct answer is '{ans}'; the student wrote {why}.")
            )
    return records


# ---------------------------------------------------------------------------
# DB harvest + live teacher enrichment


def _iter_units(payload: dict, spec: SectionSpec) -> list[dict]:
    """Every gradable unit in a stored payload (a Listening full test -> 4
    parts, otherwise the payload itself)."""
    if isinstance(payload.get("parts"), list):
        return [p for p in payload["parts"] if isinstance(p, dict)]
    if payload.get(spec.body_field) and payload.get("questions"):
        return [payload]
    return []


def _is_cambridge_row(row: GeneratedQuestion) -> bool:
    """Rows served from a real Cambridge test. Their payload carries genuine
    Cambridge prose, which the design doc forbids as a training target — and
    unlike Listening (whose Cambridge rows hold no script and so fall out
    naturally), Reading's carry a full passage and would silently be trained
    on."""
    if "cambridge" in str(row.question_type or "").lower():
        return True
    return isinstance(row.payload, dict) and bool(row.payload.get("source"))


async def _call_with_retries(fn, *args, attempts: int = 3, base_delay: float = 5.0):
    """Retry a teacher call on transient upstream failures (504 / timeout).

    The NVIDIA-hosted teacher intermittently returns gateway timeouts under
    load; these are transient, so a short backoff-and-retry recovers most of
    them instead of discarding the whole unit. Raises the last error only
    after all attempts fail (the caller still skips it so the batch continues).
    """
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await fn(*args)
        except Exception as e:  # noqa: BLE001 - any transient upstream error is retryable
            last = e
            if attempt < attempts:
                delay = base_delay * attempt
                print(f"    transient error (attempt {attempt}/{attempts}): {e} "
                      f"-> retrying in {delay:.0f}s", flush=True)
                await asyncio.sleep(delay)
    assert last is not None
    raise last


_LISTENING_TOPICS = [
    "library and study facilities", "a guided museum tour",
    "a student research project", "urban wildlife conservation",
    "booking accommodation", "a university sports centre",
    "a group presentation plan", "renewable energy in cities",
]

# Breadth matters more than depth here: a few hundred sets over ten topics
# teaches the student those ten articles, not the genre. Real Academic Reading
# ranges across science, history, technology, environment, society and
# psychology, so the list does too.
_READING_TOPICS = [
    "the domestication of the honeybee", "mapping the deep ocean floor",
    "the history of the urban public park", "sleep and memory consolidation",
    "the economics of household recycling", "trade along the ancient Silk Road",
    "regional dialects in birdsong", "the spread of the printing press",
    "desalination and freshwater supply", "the archaeology of early agriculture",
    "the physics of bridge design", "how coral reefs recover from bleaching",
    "the invention of standardised time zones", "vertical farming in cities",
    "volcanic ash and aviation",
    "the origins of paper money", "animal navigation and magnetoreception",
    "restoring degraded peatland", "the social history of tea",
    "lighthouses and coastal engineering", "the rise of the shipping container",
    "seed banks and crop diversity", "acoustics in concert hall design",
    "the ecology of urban foxes", "early cartography and the longitude problem",
    "recycling rare earth metals from electronics", "the psychology of queuing",
    "glacier retreat and water supply", "the domestication of the horse",
    "bioluminescence in the deep sea", "the economics of the museum sector",
    "traffic flow and road design", "the history of vaccination",
    "soundscapes and noise pollution", "the archaeology of shipwrecks",
    "artificial sweeteners and appetite", "the spread of invasive species",
    "wind turbine siting and bird strikes", "the origins of the alphabet",
    "termite mounds and passive cooling", "the market for second-hand clothing",
    "measuring happiness in economics", "forest fire management policy",
    "the chemistry of ancient pigments", "sports biomechanics and injury",
    "underground transport in growing cities", "the science of food preservation",
]

# Rotated so the corpus covers every allowed Reading type rather than
# over-fitting the two the teacher reaches for unprompted. 47 topics, 13 mixes
# and 3 difficulties are pairwise coprime, so a run walks distinct
# topic/type/difficulty triples instead of pairing the same topic with the same
# mix every cycle.
_READING_TYPE_MIXES = [
    ["true_false_notgiven", "matching_headings"],
    ["yes_no_notgiven", "multiple_choice"],
    ["matching_information", "sentence_completion"],
    ["summary_completion", "true_false_notgiven"],
    ["matching_headings", "short_answer"],
    ["multiple_choice", "matching_information"],
    ["true_false_notgiven", "sentence_completion", "matching_headings"],
    ["yes_no_notgiven", "summary_completion"],
    ["matching_features", "true_false_notgiven"],
    ["matching_sentence_endings", "multiple_choice"],
    ["note_completion", "matching_information"],
    ["table_completion", "true_false_notgiven"],
    ["flow_chart_completion", "short_answer", "yes_no_notgiven"],
]

_DIFFS = ["Easy", "Medium", "Hard"]


def _pin_teacher_client() -> None:
    """Force every task to the general/hosted model for the duration of a run.

    The trainers ask for `get_llm_client("generator")` so a finished fine-tune
    gets served, but distillation must come from the teacher — otherwise a
    configured GENERATOR_MODEL makes the student train on its own output.
    """
    from app.llm.client import get_llm_client, set_llm_client

    teacher = get_llm_client()
    set_llm_client(teacher)
    print(f"  [teacher] pinned to {type(teacher).__name__} "
          f"({getattr(teacher, 'model', '?')})", flush=True)


async def _generate(session, spec: SectionSpec, n_tests: int, n_units: int,
                    difficulty: str | None, concurrency: int = 1,
                    offset: int = 0) -> list[dict]:
    """Call the live teacher model, persist rows, and return their payloads."""
    _pin_teacher_client()
    if spec.name == "reading":
        if n_tests:
            raise SystemExit(
                "--generate-tests is Listening-only: reading_trainer has no "
                "create_full_test. Use --generate N to build practice sets."
            )
        return await _generate_reading(session, n_units, difficulty, concurrency,
                                       offset)
    return await _generate_listening(session, n_tests, n_units, difficulty, concurrency)


async def _generate_reading(session, n_sets: int, difficulty: str | None,
                            concurrency: int, offset: int = 0) -> list[dict]:
    sem = asyncio.Semaphore(max(1, concurrency))

    async def _one(i: int) -> dict | None:
        # `offset` continues the coprime walk where a previous run stopped, so
        # resuming a partial run doesn't replay the same topic/mix/difficulty
        # triples it already generated.
        j = i + offset
        diff = difficulty or _DIFFS[j % len(_DIFFS)]
        topic = _READING_TOPICS[j % len(_READING_TOPICS)]
        qtypes = _READING_TYPE_MIXES[j % len(_READING_TYPE_MIXES)]
        async with sem:
            print(f"  [teacher] reading set {i + 1}/{n_sets} "
                  f"({diff}, {topic}, {'+'.join(qtypes)}) ...", flush=True)
            try:
                result = await _call_with_retries(
                    reading_trainer.create_practice, qtypes, diff, topic
                )
            except Exception as e:  # noqa: BLE001
                print(f"    FAILED set {i + 1}: {e}", flush=True)
                return None
        # Persist the topic that was actually requested. Without it the SFT
        # prompt has to fall back to the generated title, which leaks part of
        # the target into the input.
        result["topic"] = topic
        row = GeneratedQuestion(
            user_id=None, section="reading", question_type="practice_set",
            difficulty=diff, payload=result,
        )
        session.add(row)
        session.commit()
        return result

    if not n_sets:
        return []
    results = await asyncio.gather(*[_one(i) for i in range(n_sets)])
    return [r for r in results if r is not None]


async def _generate_listening(session, n_tests: int, n_parts: int,
                              difficulty: str | None, concurrency: int) -> list[dict]:
    from app.agents import listening_trainer

    produced: list[dict] = []

    for i in range(n_tests):
        diff = difficulty or _DIFFS[i % len(_DIFFS)]
        print(f"  [teacher] full test {i + 1}/{n_tests} (difficulty={diff}) ...", flush=True)
        try:
            test = await _call_with_retries(listening_trainer.create_full_test, diff)
        except Exception as e:  # network / JSON failures shouldn't abort export
            print(f"    FAILED: {e}")
            continue
        row = GeneratedQuestion(
            user_id=None, section="listening", question_type="full_test",
            difficulty=diff, payload=test,
        )
        session.add(row)
        session.commit()
        produced.append(test)

    # Parts run concurrently up to `concurrency` in flight. Each part is a whole
    # generator SFT record on its own, so part-level fan-out (unlike full-test
    # fan-out) isolates failures — one bad part costs one part, not four.
    sem = asyncio.Semaphore(max(1, concurrency))

    async def _one_part(i: int) -> dict | None:
        pn = (i % 4) + 1
        diff = difficulty or _DIFFS[i % len(_DIFFS)]
        topic = _LISTENING_TOPICS[i % len(_LISTENING_TOPICS)]
        async with sem:
            print(f"  [teacher] part {i + 1}/{n_parts} (Part {pn}, {diff}, {topic}) ...", flush=True)
            try:
                part = await _call_with_retries(listening_trainer.create_part, pn, diff, topic)
            except Exception as e:
                print(f"    FAILED part {i + 1}: {e}", flush=True)
                return None
        # No await beyond this point: the shared Session is mutated atomically
        # w.r.t. other coroutines (asyncio is single-threaded), so per-part
        # commits stay durable — an interrupted concurrent run loses nothing.
        wrapper = {"title": part.get("title"), "kind": "single_part", "parts": [part]}
        row = GeneratedQuestion(
            user_id=None, section="listening", question_type="part",
            difficulty=diff, payload=wrapper,
        )
        session.add(row)
        session.commit()
        return wrapper

    if n_parts:
        results = await asyncio.gather(*[_one_part(i) for i in range(n_parts)])
        produced.extend([r for r in results if r is not None])

    return produced


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def run(args: argparse.Namespace) -> None:
    spec = SECTIONS[args.section]
    init_db()
    session = SessionLocal()
    out = Path(args.out)
    try:
        extra_payloads: list[dict] = []
        if args.generate_tests or args.generate:
            extra_payloads = asyncio.run(
                _generate(session, spec, args.generate_tests, args.generate,
                          args.difficulty, args.concurrency, args.generate_offset)
            )

        # --- Cambridge structured JSON ---
        cambridge_records: list[dict] = []
        for test in session.query(CambridgeTest).order_by(CambridgeTest.id):
            rec = _structured_from_cambridge(test, spec)
            if rec is not None:
                cambridge_records.append(rec)

        # --- teacher rows (DB) + freshly generated payloads ---
        rows = (
            session.query(GeneratedQuestion)
            .filter(GeneratedQuestion.section == spec.name)
            .order_by(GeneratedQuestion.id)
            .all()
        )
        excluded = sum(1 for r in rows if _is_cambridge_row(r))
        sources: list[tuple[dict, str]] = [
            (r.payload, r.difficulty) for r in rows
            if isinstance(r.payload, dict) and not _is_cambridge_row(r)
        ]
        sources += [(p, args.difficulty or "Medium") for p in extra_payloads]

        gen_records: list[dict] = []
        eval_records: list[dict] = []
        structured_teacher: list[dict] = []
        seen_bodies: set[str] = set()
        for payload, difficulty in sources:
            for unit in _iter_units(payload, spec):
                body = str(unit.get(spec.body_field) or "")
                key = body[:200]
                if key and key in seen_bodies:
                    continue  # de-dupe re-exported rows across runs
                seen_bodies.add(key)
                gen_records.extend(
                    _generator_records(unit, difficulty, args.complete_only, spec)
                )
                eval_records.extend(_evaluator_records(unit, spec))
                structured_teacher.append(_structured_from_part(unit, difficulty, spec))

        cambridge_name = f"cambridge_{spec.name}.jsonl"
        gen_name = f"{spec.name}_generator_sft.jsonl"
        eval_name = f"{spec.name}_evaluator_sft.jsonl"
        _write_jsonl(out / cambridge_name, cambridge_records + structured_teacher)
        _write_jsonl(out / gen_name, gen_records)
        _write_jsonl(out / eval_name, eval_records)

        session.commit()
        print(f"\n=== dataset build complete ({spec.name}) ===")
        print(f"  {cambridge_name:<32}: {len(cambridge_records)} Cambridge "
              f"+ {len(structured_teacher)} teacher = "
              f"{len(cambridge_records) + len(structured_teacher)} records")
        print(f"  {gen_name:<32}: {len(gen_records)} records "
              f"({_CLEAN_STATS['reconciled']} word_limit(s) reconciled)")
        print(f"  {eval_name:<32}: {len(eval_records)} records "
              f"({_CLEAN_STATS['eval_no_question']} skipped, no question text)")
        print(f"  Cambridge-sourced rows excluded from SFT : {excluded}")
        print(f"  units dropped as unanswerable            : "
              f"{_CLEAN_STATS['unanswerable']} (blank question text or "
              f"question/answer_key mismatch)")
        if spec.min_questions or spec.min_body_words:
            print(f"  units dropped as under-contract          : "
                  f"{_CLEAN_STATS['below_min_questions']} with <{spec.min_questions} "
                  f"questions, {_CLEAN_STATS['below_min_words']} under "
                  f"{spec.min_body_words} words")
        print(f"  Cambridge answers dropped as parse debris: "
              f"{_CLEAN_STATS['cambridge_answers_dropped']} "
              f"({_CLEAN_STATS['cambridge_rows_skipped']} tests left with none)")
        print(f"  output dir                : {out.resolve()}")
    finally:
        session.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--section", default="listening", choices=sorted(SECTIONS),
                    help="which IELTS section to export (default listening)")
    ap.add_argument("--out", default=str(OUT_DIR), help="output directory for .jsonl files")
    ap.add_argument("--generate", type=int, default=0,
                    help="generate N units via the live teacher model "
                         "(Listening: single Parts; Reading: practice sets)")
    ap.add_argument("--generate-tests", type=int, default=0,
                    help="generate N full 4-part Listening tests (Listening only)")
    ap.add_argument("--generate-offset", type=int, default=0,
                    help="skip the first N topic/type/difficulty triples "
                         "(Reading); use it to resume a partial run without "
                         "regenerating the same combinations")
    ap.add_argument("--concurrency", type=int, default=1,
                    help="units generated in parallel (default 1 = sequential); "
                         "e.g. 4 fires four teacher calls at once")
    ap.add_argument("--difficulty", default=None,
                    help="force a difficulty for generated material (else rotates)")
    ap.add_argument("--complete-only", action="store_true",
                    help="Listening only: emit generator records just for "
                         "full-contract payloads (blueprint + speakers + "
                         "accepted_variants)")
    args = ap.parse_args()
    run(args)


if __name__ == "__main__":
    main()

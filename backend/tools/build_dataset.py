"""Build structured-JSON fine-tuning datasets for the Listening Exam Engine.

Implements the "Dataset Construction" step of `AI IELTS Listening Exam Engine.md`:
we do NOT train on PDFs — every source is converted into structured JSON, and
from that JSON we emit chat-format SFT records for the two doc models:

  * the GENERATOR  (Qwen2.5-14B-Instruct + LoRA): spec/blueprint -> full test
  * the EVALUATOR  (separate LoRA): question + answer + variants + student
                                    answer -> verdict / reason / skill

Three files are produced under ``--out`` (default ``data/datasets``):

  cambridge_listening.jsonl  one structured-JSON record per Cambridge Listening
                             test (doc field schema). Dialogue/audio are null
                             because Cambridge scripts are not parsed — these
                             records document real answer keys / question mixes.
  generator_sft.jsonl        {messages:[system,user,assistant]} where the
                             assistant is the doc-ideal generation contract
                             (blueprint, dialogue, speakers, questions, answers,
                             accepted_variants, answer_positions). Sourced from
                             teacher-generated (70B) payloads in the DB.
  evaluator_sft.jsonl        {messages:[system,user,assistant]} judging one
                             student answer at a time, with correct / accepted-
                             variant / incorrect cases synthesised per question.

Usage (run from the ``backend`` directory):

    python tools/build_dataset.py                      # export existing DB rows
    python tools/build_dataset.py --generate-parts 8   # enrich via live teacher
    python tools/build_dataset.py --generate-tests 2   # 4 parts per full test
    python tools/build_dataset.py --complete-only      # only full-contract rows

``--generate-*`` calls the configured LLM (the NVIDIA-hosted 70B teacher) and
persists each result as a GeneratedQuestion row, so the corpus grows every run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal, init_db  # noqa: E402
from app.llm.prompts import EVALUATOR_SYSTEM, LISTENING_TRAINER_SYSTEM  # noqa: E402
from app.models import CambridgeTest, GeneratedQuestion  # noqa: E402

OUT_DIR = Path("data/datasets")

# How many gap-fill answers were bumped to fit their stated word_limit during
# the last export — surfaced in the run summary.
_CLEAN_STATS = {"reconciled": 0}

# Gap-fill families share one listening sub-skill; keep in sync with the app's
# reading_trainer._GAP_FILL_TYPES so training labels match runtime behaviour.
_GAP_FILL = {
    "form_completion",
    "note_completion",
    "table_completion",
    "flow_chart_completion",
    "sentence_completion",
    "short_answer",
    "summary_completion",
}

_SKILL_BY_TYPE = {
    "multiple_choice": "listening for gist and detail; resolving distractors",
    "map_labelling": "following directions and spatial language on a map/plan",
    "matching": "matching and classifying information across speakers",
}
_GAP_FILL_SKILL = "listening for specific detail (spelling, numbers, gap-fill)"

# Cues a speaker uses when they correct themselves — the doc's "corrections"
# signal and a core IELTS distractor device.
_CORRECTION_CUES = re.compile(
    r"\b(sorry|actually|i mean|no,? wait|correction|scratch that|"
    r"let me correct|hang on|oh,? no)\b",
    re.IGNORECASE,
)
_LABEL_RE = re.compile(r"^\s*([A-Z][A-Za-z .'-]{0,24}?):", re.MULTILINE)

_NUM_WORDS = {
    0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
    6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven",
    12: "twelve", 13: "thirteen", 14: "fourteen", 15: "fifteen",
    16: "sixteen", 17: "seventeen", 18: "eighteen", 19: "nineteen",
    20: "twenty", 30: "thirty", 40: "forty", 50: "fifty", 60: "sixty",
    70: "seventy", 80: "eighty", 90: "ninety",
}

# Registers + default voices per Part, used when a teacher row predates the
# `speakers`/`blueprint` fields so every SFT target is still well-formed.
_PART_META = {
    1: ("Part 1", "conversational", 150),
    2: ("Part 2", "informational monologue", 145),
    3: ("Part 3", "academic discussion", 160),
    4: ("Part 4", "lecture", 140),
}


def _norm_type(value: object) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _skill_for(qtype: str) -> str:
    t = _norm_type(qtype)
    if t in _GAP_FILL:
        return _GAP_FILL_SKILL
    return _SKILL_BY_TYPE.get(t, "listening comprehension")


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


# ---------------------------------------------------------------------------
# Doc structured-JSON record


def _structured_from_part(part: dict, difficulty: str) -> dict:
    """Convert a teacher-generated Part into the doc's structured JSON schema:
    {section, topic, dialogue, speakers, speaker_roles, difficulty,
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


def _structured_from_cambridge(test: CambridgeTest) -> dict | None:
    """Structured JSON for a real Cambridge test. Dialogue/audio stay null
    (scripts are not parsed); the value is the authentic answer key + mix."""
    listening = test.listening or {}
    answer_key = listening.get("answer_key") or {}
    if not answer_key:
        return None
    parts = listening.get("parts") or []
    qtypes: list[str] = []
    for p in parts:
        for block in p.get("question_blocks") or []:
            t = _norm_type(block.get("type"))
            if t and t not in qtypes:
                qtypes.append(t)
    return {
        "source": f"{test.book_id}-test{test.test_number}",
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


# ---------------------------------------------------------------------------
# Generator SFT (spec -> full doc contract)


def _spec_user_message(part: dict, difficulty: str) -> str:
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


_WORD_TO_INT = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


def _answer_word_count(answer: object) -> int:
    """Words in an answer, treating pure numbers as 0 (IELTS rubric: numbers
    don't count toward the word cap). Mirrors reading_trainer._answer_word_count
    so the export matches the runtime warning logic exactly."""
    tokens = [t for t in str(answer).strip().split() if t]
    return sum(0 if t.replace(",", "").replace(".", "").isdigit() else 1 for t in tokens)


def _parse_word_limit(value: object) -> int | None:
    """Integer word cap from a word_limit field. Handles ints, numeric strings,
    and IELTS phrasings ('ONE WORD', 'NO MORE THAN TWO WORDS AND/OR A NUMBER',
    '5 words'). The '/ A NUMBER' clause doesn't add to the count. None if no cap
    can be read."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().lower()
    if not text:
        return None
    m = re.search(r"\d+", text)
    if m:
        return int(m.group())
    for word, n in _WORD_TO_INT.items():
        if re.search(rf"\b{word}\b", text):
            return n
    return None


def _canonical_word_limit(n: int) -> str:
    word = {1: "ONE", 2: "TWO", 3: "THREE", 4: "FOUR", 5: "FIVE"}.get(n, str(n))
    unit = "WORD" if n == 1 else "WORDS"
    return f"NO MORE THAN {word} {unit} AND/OR A NUMBER"


def _reconcile_word_limits(target: dict) -> None:
    """Bump each gap-fill question's word_limit up to fit its answer so the SFT
    target never contradicts itself. The teacher routinely states 'ONE WORD'
    then supplies a two- or three-word answer; training on that teaches the
    model to violate its own rubric. We trust the answer (the graded value) and
    raise the stated cap to match, rendered in canonical IELTS phrasing. Only
    genuine violations are touched — consistent questions are left alone."""
    answer_key = target.get("answer_key") or {}
    for q in target.get("questions") or []:
        if not isinstance(q, dict):
            continue
        if _norm_type(q.get("type")) not in _GAP_FILL:
            continue
        answer = answer_key.get(str(q.get("number")))
        if answer is None:
            continue
        needed = max(
            (_answer_word_count(c) for c in str(answer).split(";")), default=0
        )
        limit = _parse_word_limit(q.get("word_limit"))
        if limit is None:
            # Gap-fill must carry a cap; the teacher sometimes omits it or
            # phrases it unparseably. Default to the answer's length (min 1).
            q["word_limit"] = _canonical_word_limit(max(1, needed))
            _CLEAN_STATS["reconciled"] += 1
        elif needed > limit:
            q["word_limit"] = _canonical_word_limit(needed)
            _CLEAN_STATS["reconciled"] += 1


def _generator_target(part: dict, difficulty: str, complete_only: bool) -> dict | None:
    """The doc-ideal assistant completion: exactly the generator contract."""
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
    _reconcile_word_limits(target)
    return target


def _generator_records(part: dict, difficulty: str, complete_only: bool) -> list[dict]:
    target = _generator_target(part, difficulty, complete_only)
    if target is None:
        return []
    return [
        {
            "messages": [
                {"role": "system", "content": LISTENING_TRAINER_SYSTEM},
                {"role": "user", "content": _spec_user_message(part, difficulty)},
                {
                    "role": "assistant",
                    "content": json.dumps(target, ensure_ascii=False),
                },
            ]
        }
    ]


# ---------------------------------------------------------------------------
# Evaluator SFT (one student answer at a time)


def _wrong_answer(answer: str, options: list | None) -> tuple[str, str] | None:
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
                    return cand, "a distractor option the recording rules out"
    if ans.isdigit():
        n = int(ans)
        return str(n + 1 if n < 9 else n - 1), "a nearby number mentioned as a distractor before the correction"
    parts = ans.split()
    if len(parts) > 1:
        return " ".join(parts[:-1]), "an incomplete answer that drops a required word"
    if len(ans) > 3:
        return ans[:-1] + ("s" if not ans.endswith("s") else ""), "a mishearing/misspelling of the word heard"
    return "", "a blank answer (nothing written)"


def _evaluator_records(part: dict) -> list[dict]:
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
        qtext = str(q.get("question") or f"Question {num}").strip()
        options = q.get("options")
        skill = _skill_for(q.get("type"))
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
                    {"role": "system", "content": EVALUATOR_SYSTEM},
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
        wrong = _wrong_answer(ans, options if isinstance(options, list) else None)
        if wrong is not None:
            student, why = wrong
            records.append(
                _rec(student, "incorrect", f"The correct answer is '{ans}'; the student wrote {why}.")
            )
    return records


# ---------------------------------------------------------------------------
# DB harvest + live teacher enrichment


def _iter_parts(payload: dict) -> list[dict]:
    """Every gradable Part in a stored payload (full test -> 4, else 1)."""
    if isinstance(payload.get("parts"), list):
        return [p for p in payload["parts"] if isinstance(p, dict)]
    if payload.get("audio_script") and payload.get("questions"):
        return [payload]
    return []


async def _call_with_retries(fn, *args, attempts: int = 3, base_delay: float = 5.0):
    """Retry a teacher call on transient upstream failures (504 / timeout).

    The NVIDIA-hosted teacher intermittently returns gateway timeouts under
    load; these are transient, so a short backoff-and-retry recovers most of
    them instead of discarding the whole part/test. Raises the last error only
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


async def _generate(session, n_tests: int, n_parts: int, difficulty: str | None,
                    concurrency: int = 1) -> list[dict]:
    """Call the live teacher model, persist rows, and return their payloads."""
    from app.agents import listening_trainer

    produced: list[dict] = []
    topics = [
        "library and study facilities", "a guided museum tour",
        "a student research project", "urban wildlife conservation",
        "booking accommodation", "a university sports centre",
        "a group presentation plan", "renewable energy in cities",
    ]
    diffs = ["Easy", "Medium", "Hard"]

    for i in range(n_tests):
        diff = difficulty or diffs[i % len(diffs)]
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
        diff = difficulty or diffs[i % len(diffs)]
        topic = topics[i % len(topics)]
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
    init_db()
    session = SessionLocal()
    out = Path(args.out)
    try:
        extra_payloads: list[dict] = []
        if args.generate_tests or args.generate_parts:
            extra_payloads = asyncio.run(
                _generate(session, args.generate_tests, args.generate_parts,
                          args.difficulty, args.concurrency)
            )

        # --- Cambridge structured JSON ---
        cambridge_records: list[dict] = []
        for test in session.query(CambridgeTest).order_by(CambridgeTest.id):
            rec = _structured_from_cambridge(test)
            if rec is not None:
                cambridge_records.append(rec)

        # --- teacher rows (DB) + freshly generated payloads ---
        rows = (
            session.query(GeneratedQuestion)
            .filter(GeneratedQuestion.section == "listening")
            .order_by(GeneratedQuestion.id)
            .all()
        )
        sources: list[tuple[dict, str]] = [
            (r.payload, r.difficulty) for r in rows if isinstance(r.payload, dict)
        ]
        sources += [(p, args.difficulty or "Medium") for p in extra_payloads]

        gen_records: list[dict] = []
        eval_records: list[dict] = []
        structured_teacher: list[dict] = []
        seen_scripts: set[str] = set()
        for payload, difficulty in sources:
            for part in _iter_parts(payload):
                script = str(part.get("audio_script") or "")
                key = script[:200]
                if key and key in seen_scripts:
                    continue  # de-dupe re-exported rows across runs
                seen_scripts.add(key)
                gen_records.extend(_generator_records(part, difficulty, args.complete_only))
                eval_records.extend(_evaluator_records(part))
                structured_teacher.append(_structured_from_part(part, difficulty))

        _write_jsonl(out / "cambridge_listening.jsonl", cambridge_records + structured_teacher)
        _write_jsonl(out / "generator_sft.jsonl", gen_records)
        _write_jsonl(out / "evaluator_sft.jsonl", eval_records)

        session.commit()
        print("\n=== dataset build complete ===")
        print(f"  cambridge_listening.jsonl : {len(cambridge_records)} Cambridge "
              f"+ {len(structured_teacher)} teacher = "
              f"{len(cambridge_records) + len(structured_teacher)} records")
        print(f"  generator_sft.jsonl       : {len(gen_records)} records "
              f"({_CLEAN_STATS['reconciled']} word_limit(s) reconciled)")
        print(f"  evaluator_sft.jsonl       : {len(eval_records)} records")
        print(f"  output dir                : {out.resolve()}")
    finally:
        session.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(OUT_DIR), help="output directory for .jsonl files")
    ap.add_argument("--generate-tests", type=int, default=0,
                    help="generate N full 4-part tests via the live teacher model")
    ap.add_argument("--generate-parts", type=int, default=0,
                    help="generate N single Parts via the live teacher model")
    ap.add_argument("--concurrency", type=int, default=1,
                    help="parts generated in parallel (default 1 = sequential); "
                         "e.g. 4 fires four teacher calls at once")
    ap.add_argument("--difficulty", default=None,
                    help="force a difficulty for generated material (else rotates)")
    ap.add_argument("--complete-only", action="store_true",
                    help="emit generator records only for full-contract payloads "
                         "(blueprint + speakers + accepted_variants)")
    args = ap.parse_args()
    run(args)


if __name__ == "__main__":
    main()

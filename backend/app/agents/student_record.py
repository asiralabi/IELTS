"""What the tutor knows about the student it is talking to.

Without this, "check my recent exam" got "please paste your answer": the chat
saw the conversation and the reference material, never the results the app
had already marked. A student asking "what mistakes did I make and how do I
fix them" needs the tutor to see the question, their answer, the right answer
and why, so the latest piece of each kind of work is shown in full and the
rest as one line each. It rides on every chat turn, so every field is capped.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import (
    GeneratedQuestion,
    MockExam,
    PracticeAttempt,
    SpeakingSubmission,
    User,
    WritingSubmission,
)

_WRONG_SHOWN = 10  # wrong answers explained per section
_TIMELINE = 8  # one-line entries in the activity list
_SPEAKING_SHOWN = 3  # a full speaking test is three parts

_MIN_WORDS = {"task1": 150, "task2": 250}
_WRITING = ("task_response", "coherence_cohesion", "lexical_resource", "grammatical_range_accuracy")
_SPEAKING = ("fluency_coherence", "lexical_resource", "grammatical_range_accuracy", "pronunciation")


def _cut(text: Any, limit: int) -> str:
    t = " ".join(str(text or "").split())
    return t if len(t) <= limit else t[: limit - 1].rstrip() + "…"


def _text(node: Any) -> str:
    """The words in a question, however deeply the paper nests them.

    A speaking part is sometimes one question and sometimes topics holding
    lists of questions; either way the tutor needs the questions, not JSON.
    """
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return " / ".join(t for t in (_text(n) for n in node) if t)
    if isinstance(node, dict):
        return " / ".join(t for t in (_text(v) for v in node.values()) if t)
    return ""


def _day(obj: Any) -> str:
    return obj.created_at.strftime("%d %b %Y") if obj.created_at else "unknown date"


def _questions(payload: Any) -> dict[str, dict]:
    """Every question in a paper, by number, wherever the paper nests it.

    Practice sets keep `questions` at the top, full tests under `passages` or
    `parts`, and a mock exam under each section, so walk the whole thing.
    """
    found: dict[str, dict] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "number" in node and "question" in node:
                found.setdefault(str(node["number"]), node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(payload)
    return found


def _scores(part: dict, criteria: tuple[str, ...]) -> str:
    return ", ".join(
        f"{c.replace('_', ' ')} {part[c]}" for c in criteria if part.get(c) is not None
    )


def _objective(label: str, result: Any, paper: Any) -> list[str]:
    """A marked reading or listening paper, with each wrong answer explained."""
    if not isinstance(result, dict):
        return []
    lines = [
        f"{label}: {result.get('score')}/{result.get('total')} correct, "
        f"band {result.get('band_estimate')}"
    ]
    questions = _questions(paper)
    wrong = [r for r in result.get("results") or [] if isinstance(r, dict) and not r.get("correct")]
    for r in wrong[:_WRONG_SHOWN]:
        q = questions.get(str(r.get("number")), {})
        kind = f" [{q['type']}]" if q.get("type") else ""
        lines.append(f"  Q{r.get('number')}{kind} {_cut(q.get('question'), 170)}")
        if q.get("options"):
            lines.append(f"    options: {_cut('; '.join(map(str, q['options'])), 500)}")
        lines.append(
            f"    student wrote: {_cut(r.get('student_answer'), 60) or '(blank)'} | "
            f"correct: {_cut(r.get('correct_answer'), 60)}"
        )
        if r.get("explanation"):
            lines.append(f"    why: {_cut(r['explanation'], 240)}")
    if len(wrong) > _WRONG_SHOWN:
        lines.append(f"  ...and {len(wrong) - _WRONG_SHOWN} more wrong answers")
    if not wrong and result.get("total"):
        lines.append("  All answers correct.")
    return lines


def _figure(visual: Any) -> str:
    """The Task 1 figure as numbers, so advice quotes real data.

    Without it the tutor wrote model answers around figures it made up
    ("78 mm in January") for a chart it had never seen.
    """
    if not isinstance(visual, dict):
        return ""
    if visual.get("kind") == "chart" and isinstance(visual.get("series"), list):
        series = "; ".join(
            f"{s.get('name')}: " + ", ".join(f"{x} {y}" for x, y in (s.get("data") or []))
            for s in visual["series"]
            if isinstance(s, dict)
        )
        head = f"{visual.get('chart_type', '')} chart \"{visual.get('title', '')}\""
        axes = f" (x: {visual.get('x_label')}, y: {visual.get('y_label')})" if visual.get("y_label") else ""
        return _cut(f"{head}{axes} — {series}", 900)
    # Tables, maps, processes and diagrams vary in shape; their JSON is compact
    # enough to read once the whitespace goes.
    return _cut(json.dumps(visual, ensure_ascii=False, separators=(",", ":")), 900)


def _writing(
    label: str, part: Any, prompt: str | None = None, visual: Any = None
) -> list[str]:
    if not isinstance(part, dict):
        return []
    scores = _scores(part, _WRITING)
    lines = [f"{label}: band {part.get('band_score')}" + (f" ({scores})" if scores else "")]
    if prompt:
        lines.append(f"  task: {_cut(prompt, 220)}")
    if figure := _figure(visual if visual is not None else part.get("visual")):
        lines.append(f"  figure data: {figure}")
    if part.get("word_count") is not None:
        minimum = _MIN_WORDS.get(label.split()[-1].lower())
        need = f" (minimum {minimum}: {'met' if part['word_count'] >= minimum else 'TOO SHORT'})" if minimum else ""
        lines.append(f"  words: {part['word_count']}{need}")
    for w in (part.get("weaknesses") or [])[:3]:
        lines.append(f"  weakness: {_cut(w, 200)}")
    for e in (part.get("errors") or [])[:5]:
        if isinstance(e, dict):
            lines.append(
                f"  error: \"{_cut(e.get('excerpt'), 90)}\" — {_cut(e.get('issue'), 110)} "
                f"→ \"{_cut(e.get('correction'), 90)}\""
            )
    if part.get("essay"):
        lines.append(f"  essay opening: \"{_cut(part['essay'], 300)}\"")
    for s in (part.get("improved_sentences") or [])[:2]:
        if isinstance(s, dict):
            lines.append(
                f"  rewrite: \"{_cut(s.get('original'), 120)}\" → \"{_cut(s.get('improved'), 160)}\""
            )
    return lines


def _speaking(
    label: str, part: Any, question: str | None = None, transcript: str | None = None
) -> list[str]:
    if not isinstance(part, dict):
        return []
    transcript = transcript or part.get("transcript")
    scores = _scores(part, _SPEAKING)
    lines = [f"{label}: band {part.get('band_score')}" + (f" ({scores})" if scores else "")]
    if question:
        lines.append(f"  question: {_cut(question, 200)}")
    if transcript:
        lines.append(f"  they said: \"{_cut(transcript, 350)}\"")
    for w in (part.get("weaknesses") or [])[:3]:
        lines.append(f"  weakness: {_cut(w, 200)}")
    for s in (part.get("strengths") or [])[:1]:
        lines.append(f"  strength: {_cut(s, 160)}")
    return lines


def _attempt_label(attempt: PracticeAttempt, paper: GeneratedQuestion | None) -> str:
    section = attempt.section.capitalize()
    kind = paper.question_type if paper is not None else ""
    if kind == "full_test":
        name = f"{section} full test"
    elif kind.startswith("cambridge"):
        source = (paper.payload or {}).get("source") if paper is not None else None
        name = f"{section}, real Cambridge paper" + (f" ({source})" if source else "")
    else:
        name = f"{section} practice set"
    title = (paper.payload or {}).get("title") if paper is not None else None
    return name + (f" \"{_cut(title, 60)}\"" if title else "")


def student_record(db: Session, user: User) -> str:
    uid = user.id
    exams = (
        db.query(MockExam)
        .filter(MockExam.user_id == uid, MockExam.status == "scored")
        .order_by(MockExam.created_at.desc(), MockExam.id.desc())
        .limit(_TIMELINE)
        .all()
    )
    attempts = (
        db.query(PracticeAttempt)
        .filter(PracticeAttempt.user_id == uid)
        .order_by(PracticeAttempt.created_at.desc(), PracticeAttempt.id.desc())
        .limit(_TIMELINE)
        .all()
    )
    writing = (
        db.query(WritingSubmission)
        .filter(WritingSubmission.user_id == uid)
        .order_by(WritingSubmission.created_at.desc(), WritingSubmission.id.desc())
        .limit(_TIMELINE)
        .all()
    )
    speaking = (
        db.query(SpeakingSubmission)
        .filter(SpeakingSubmission.user_id == uid)
        .order_by(SpeakingSubmission.created_at.desc(), SpeakingSubmission.id.desc())
        .limit(_TIMELINE)
        .all()
    )
    papers = {
        q.id: q
        for q in db.query(GeneratedQuestion).filter(
            GeneratedQuestion.id.in_([a.question_id for a in attempts if a.question_id])
        )
    }

    lines = [
        f"Today: {datetime.now(UTC).strftime('%d %b %Y')}",
        f"Target band: {user.target_band}",
    ]
    if not (exams or attempts or writing or speaking):
        lines.append("No marked work yet: the student has not finished a mock exam or any practice.")
        return "\n".join(lines)

    # 1. What they did, newest first, so "my recent exam" means the right thing.
    timeline: list[tuple[datetime, str]] = []
    for e in exams:
        timeline.append((e.created_at, f"{_day(e)}: full mock exam (all four sections), overall band {e.overall_band}"))
    for a in attempts:
        score = f"{a.score:g}/{a.total} correct" if a.score is not None else "not marked"
        timeline.append((a.created_at, f"{_day(a)}: {_attempt_label(a, papers.get(a.question_id))}, {score}"))
    for w in writing:
        timeline.append((w.created_at, f"{_day(w)}: writing {w.task_type}, band {w.band_score}"))
    for s in speaking:
        timeline.append((s.created_at, f"{_day(s)}: speaking {s.part}, band {s.band_score}"))
    # SQLite hands back naive datetimes and Postgres aware ones; compare as naive.
    timeline.sort(key=lambda t: (t[0] or datetime.min).replace(tzinfo=None), reverse=True)
    # Spelled out because the model kept reading "exam" as "mock exam" and
    # skipped a newer practice set two lines further down.
    lines.append(
        f'\nMOST RECENT (this is what "my recent exam / test" means, practice set or not): '
        f"{timeline[0][1]}"
    )
    # The model reads "exam" as "the mock exam" whenever one is in view, and
    # a general instruction did not move it (0 of 3), so say it right here.
    newest_exam = exams[0].created_at if exams else None
    if newest_exam is not None and timeline[0][0] != newest_exam:
        lines.append(
            f"  This was done AFTER the full mock exam of {_day(exams[0])}. If the student "
            "asks about their recent exam or test, go through THIS one first, then "
            "offer the mock exam in one line."
        )
    lines.append("RECENT ACTIVITY (newest first):")
    lines += [f"- {text}" for _, text in timeline[:_TIMELINE]]

    # 2. The latest of each kind in full, newest block first. The model leans
    # on whichever block comes first, so with the mock exam always on top it
    # answered "my recent exam" about the mock even after a newer practice set.
    blocks: list[tuple[datetime | None, list[str]]] = []

    if exams and isinstance(exams[0].results, dict):
        e, r = exams[0], exams[0].results
        paper = e.exam or {}
        block = [f"\nLATEST FULL MOCK EXAM ({_day(e)}), overall band {e.overall_band}:"]
        if isinstance(r.get("section_bands"), dict) and r["section_bands"]:
            official = ", ".join(f"{k} {v}" for k, v in r["section_bands"].items())
            block.append(f"Official section bands: {official}")
        block += _objective("Listening", r.get("listening"), paper.get("listening"))
        block += _objective("Reading", r.get("reading"), paper.get("reading"))
        tasks = (paper.get("writing") or {}) if isinstance(paper.get("writing"), dict) else {}
        for task, part in (r.get("writing") or {}).items():
            asked = tasks.get(task) if isinstance(tasks.get(task), dict) else {}
            block += _writing(f"Writing {task}", part, asked.get("question"), asked.get("visual"))
        asked = paper.get("speaking") if isinstance(paper.get("speaking"), dict) else {}
        for sp, part in (r.get("speaking") or {}).items():
            q = asked.get(sp)
            q = q[0] if isinstance(q, list) and q else q
            block += _speaking(f"Speaking {sp}", part, _text(q.get("question")) if isinstance(q, dict) else None)
        blocks.append((e.created_at, block))

    for section in ("reading", "listening"):
        latest = next((a for a in attempts if a.section == section and a.result), None)
        if latest is not None:
            paper = papers.get(latest.question_id)
            block = [f"\nLATEST {section.upper()} ({_day(latest)}):"]
            block += _objective(_attempt_label(latest, paper), latest.result, paper.payload if paper else None)
            blocks.append((latest.created_at, block))

    shown: set[str] = set()
    for w in writing:
        if w.task_type in shown:
            continue
        shown.add(w.task_type)
        block = [f"\nLATEST WRITING {w.task_type.upper()} ({_day(w)}):"]
        block += _writing(f"Writing {w.task_type}", w.result or {"band_score": w.band_score}, w.prompt)
        blocks.append((w.created_at, block))
    if speaking:
        block = ["\nLATEST SPEAKING ANSWERS:"]
        for s in speaking[:_SPEAKING_SHOWN]:
            block += _speaking(
                f"{_day(s)}, {s.part}", s.result or {"band_score": s.band_score}, s.question, s.transcript
            )
        blocks.append((speaking[0].created_at, block))

    blocks.sort(key=lambda b: (b[0] or datetime.min).replace(tzinfo=None), reverse=True)
    for _, block in blocks:
        lines += block

    return "\n".join(lines)

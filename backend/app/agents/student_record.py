"""What the tutor knows about the student it is talking to.

Without this, "check my recent exam" got "please paste your answer": the chat
saw the conversation and the reference material, never the results the app
had already marked. This is a short summary of those results, kept small
because it rides on every chat turn.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import MockExam, PracticeAttempt, SpeakingSubmission, User, WritingSubmission

# Enough to discuss a paper question by question without flooding the prompt.
_WRONG_PER_SECTION = 6
_RECENT = 3
# The marker's notes run to whole paragraphs; the gist is in the first line.
_NOTE_MAX = 160


def _day(obj: Any) -> str:
    return obj.created_at.strftime("%d %b %Y") if obj.created_at else "unknown date"


def _points(items: Any, n: int = 2) -> str:
    if not isinstance(items, list):
        return ""
    notes = [str(i) for i in items[:n]]
    return "; ".join(t if len(t) <= _NOTE_MAX else t[: _NOTE_MAX - 1].rstrip() + "…" for t in notes)


def _objective(name: str, part: Any) -> list[str]:
    if not isinstance(part, dict):
        return []
    lines = [f"- {name}: {part.get('score')}/{part.get('total')} correct, band {part.get('band_estimate')}"]
    wrong = [r for r in part.get("results") or [] if isinstance(r, dict) and not r.get("correct")]
    for r in wrong[:_WRONG_PER_SECTION]:
        lines.append(
            f"  Q{r.get('number')}: wrote {r.get('student_answer') or '(blank)'!r}, "
            f"answer {r.get('correct_answer')!r}"
        )
    if len(wrong) > _WRONG_PER_SECTION:
        lines.append(f"  ...and {len(wrong) - _WRONG_PER_SECTION} more wrong")
    return lines


def _marked(name: str, part: Any, criteria: tuple[str, ...]) -> list[str]:
    if not isinstance(part, dict):
        return []
    scores = ", ".join(
        f"{c.replace('_', ' ')} {part[c]}" for c in criteria if part.get(c) is not None
    )
    lines = [f"- {name}: band {part.get('band_score')}" + (f" ({scores})" if scores else "")]
    if weak := _points(part.get("weaknesses")):
        lines.append(f"  weaknesses: {weak}")
    return lines


_WRITING = ("task_response", "coherence_cohesion", "lexical_resource", "grammatical_range_accuracy")
_SPEAKING = ("fluency_coherence", "lexical_resource", "grammatical_range_accuracy", "pronunciation")


def student_record(db: Session, user: User) -> str:
    lines = [f"Target band: {user.target_band}"]

    exam = (
        db.query(MockExam)
        .filter(MockExam.user_id == user.id, MockExam.status == "scored")
        .order_by(MockExam.created_at.desc(), MockExam.id.desc())
        .first()
    )
    if exam is not None and isinstance(exam.results, dict):
        r = exam.results
        lines.append(f"\nMost recent full mock exam ({_day(exam)}): overall band {exam.overall_band}")
        lines += _objective("Listening", r.get("listening"))
        lines += _objective("Reading", r.get("reading"))
        for task, part in (r.get("writing") or {}).items():
            lines += _marked(f"Writing {task}", part, _WRITING)
        for sp, part in (r.get("speaking") or {}).items():
            lines += _marked(f"Speaking {sp}", part, _SPEAKING)

    writing = (
        db.query(WritingSubmission)
        .filter(WritingSubmission.user_id == user.id)
        .order_by(WritingSubmission.created_at.desc(), WritingSubmission.id.desc())
        .limit(_RECENT)
        .all()
    )
    if writing:
        lines.append("\nRecent writing practice:")
        for w in writing:
            lines += _marked(f"{_day(w)}, {w.task_type}, {w.word_count} words", w.result or {"band_score": w.band_score}, _WRITING)

    speaking = (
        db.query(SpeakingSubmission)
        .filter(SpeakingSubmission.user_id == user.id)
        .order_by(SpeakingSubmission.created_at.desc(), SpeakingSubmission.id.desc())
        .limit(_RECENT)
        .all()
    )
    if speaking:
        lines.append("\nRecent speaking practice:")
        for s in speaking:
            lines += _marked(f"{_day(s)}, {s.part}", s.result or {"band_score": s.band_score}, _SPEAKING)

    practice = (
        db.query(PracticeAttempt)
        .filter(PracticeAttempt.user_id == user.id)
        .order_by(PracticeAttempt.created_at.desc(), PracticeAttempt.id.desc())
        .limit(_RECENT * 2)
        .all()
    )
    if practice:
        lines.append("\nRecent reading/listening practice:")
        for p in practice:
            if p.score is None:
                lines.append(f"- {_day(p)}, {p.section}: not marked")
                continue
            line = f"- {_day(p)}, {p.section}: {p.score:g}/{p.total} correct"
            band = (p.result or {}).get("band_estimate")
            lines.append(line + (f", band {band}" if band is not None else ""))

    if len(lines) == 1:
        lines.append("No marked work yet: the student has not finished a mock exam or any practice.")
    return "\n".join(lines)

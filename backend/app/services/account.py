"""A student's own data: everything we hold about them, and how to erase it.

Bangladesh's Personal Data Protection Ordinance 2025 (and the GDPR, for anyone
who uses Oratio from the EU or UK) gives a person the right to see the data a
service holds about them and to have it deleted. These two functions are that
right, end to end, without anyone on the team having to touch the database.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    ChatMessage,
    ChatSession,
    Consent,
    Feedback,
    GeneratedQuestion,
    MockExam,
    PracticeAttempt,
    SpeakingSubmission,
    User,
    WeaknessProfile,
    WritingSubmission,
)

logger = logging.getLogger(__name__)


def _row(obj: Any, skip: tuple[str, ...] = ()) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for col in obj.__table__.columns:
        if col.name in skip:
            continue
        value = getattr(obj, col.name)
        out[col.name] = value.isoformat() if isinstance(value, datetime) else value
    return out


def export_user_data(db: Session, user: User) -> dict[str, Any]:
    uid = user.id
    sessions = db.scalars(select(ChatSession).where(ChatSession.user_id == uid)).all()
    session_ids = [s.id for s in sessions]
    messages = (
        db.scalars(select(ChatMessage).where(ChatMessage.session_id.in_(session_ids))).all()
        if session_ids
        else []
    )

    def rows(model: Any, col: Any) -> list[dict[str, Any]]:
        return [_row(r) for r in db.scalars(select(model).where(col == uid)).all()]

    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "account": _row(user, skip=("hashed_password",)),
        "chat_sessions": [_row(s) for s in sessions],
        "chat_messages": [_row(m) for m in messages],
        "writing_submissions": rows(WritingSubmission, WritingSubmission.user_id),
        "speaking_submissions": rows(SpeakingSubmission, SpeakingSubmission.user_id),
        "practice_attempts": rows(PracticeAttempt, PracticeAttempt.user_id),
        "mock_exams": rows(MockExam, MockExam.user_id),
        "weakness_profile": rows(WeaknessProfile, WeaknessProfile.user_id),
        "feedback": rows(Feedback, Feedback.user_id),
        "consents": rows(Consent, Consent.user_id),
    }


def delete_user_data(db: Session, user: User) -> None:
    """Erase the account and everything attached to it, in one transaction."""
    uid = user.id

    # Recorded speaking audio lives on disk, not in the database.
    for path in db.scalars(
        select(SpeakingSubmission.audio_path).where(SpeakingSubmission.user_id == uid)
    ).all():
        if path:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                logger.warning("could not remove audio file for deleted user %s", uid)

    session_ids = select(ChatSession.id).where(ChatSession.user_id == uid)
    db.execute(delete(ChatMessage).where(ChatMessage.session_id.in_(session_ids)))
    db.execute(delete(ChatSession).where(ChatSession.user_id == uid))
    db.execute(delete(PracticeAttempt).where(PracticeAttempt.user_id == uid))
    db.execute(delete(WritingSubmission).where(WritingSubmission.user_id == uid))
    db.execute(delete(SpeakingSubmission).where(SpeakingSubmission.user_id == uid))
    db.execute(delete(MockExam).where(MockExam.user_id == uid))
    db.execute(delete(WeaknessProfile).where(WeaknessProfile.user_id == uid))
    # Questions generated for this student alone. Pooled questions have no
    # owner and are shared, so they stay.
    db.execute(delete(GeneratedQuestion).where(GeneratedQuestion.user_id == uid))
    db.execute(delete(Feedback).where(Feedback.user_id == uid))
    db.execute(delete(Consent).where(Consent.user_id == uid))
    db.delete(user)
    db.commit()

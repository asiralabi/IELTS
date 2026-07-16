from sqlalchemy.orm import Session

from app.llm.client import get_llm_client
from app.llm.prompts import FEEDBACK_SYSTEM
from app.models import PracticeAttempt, SpeakingSubmission, User, WritingSubmission
from app.rag.retriever import retrieve_context


def summarize_performance(db: Session, user: User) -> str:
    lines: list[str] = []
    if user.target_band is not None:
        lines.append(f"Target band: {user.target_band}")

    writing = (
        db.query(WritingSubmission)
        .filter(WritingSubmission.user_id == user.id)
        .order_by(WritingSubmission.id.desc())
        .limit(10)
        .all()
    )
    for w in writing:
        result = w.result or {}
        weaknesses = ", ".join(result.get("weaknesses", [])[:3]) or "none recorded"
        lines.append(
            f"Writing {w.task_type} ({w.created_at:%Y-%m-%d}): band {w.band_score}, "
            f"{w.word_count} words, weaknesses: {weaknesses}"
        )

    speaking = (
        db.query(SpeakingSubmission)
        .filter(SpeakingSubmission.user_id == user.id)
        .order_by(SpeakingSubmission.id.desc())
        .limit(10)
        .all()
    )
    for s in speaking:
        result = s.result or {}
        weaknesses = ", ".join(result.get("weaknesses", [])[:3]) or "none recorded"
        lines.append(
            f"Speaking {s.part} ({s.created_at:%Y-%m-%d}): band {s.band_score}, "
            f"weaknesses: {weaknesses}"
        )

    attempts = (
        db.query(PracticeAttempt)
        .filter(PracticeAttempt.user_id == user.id)
        .order_by(PracticeAttempt.id.desc())
        .limit(10)
        .all()
    )
    for a in attempts:
        result = a.result or {}
        band = result.get("band_estimate")
        wrong = [
            f"Q{r.get('number')}: {r.get('explanation', '')[:120]}"
            for r in result.get("results", [])
            if not r.get("correct")
        ][:3]
        lines.append(
            f"{a.section.capitalize()} practice ({a.created_at:%Y-%m-%d}): "
            f"{a.score}/{a.total} (band est. {band}). "
            + ("Missed: " + " | ".join(wrong) if wrong else "All correct.")
        )

    if not lines:
        return "The student has no recorded practice data yet."
    return "\n".join(lines)


async def study_plan(db: Session, user: User) -> dict:
    summary = summarize_performance(db, user)
    context = retrieve_context(summary, top_k=8)
    system = FEEDBACK_SYSTEM.format(
        context=context or "No reference material retrieved."
    )
    return await get_llm_client().complete_json(
        system,
        [{"role": "user", "content": f"Student performance summary:\n{summary}"}],
        required_keys=("summary", "priorities", "study_plan"),
    )

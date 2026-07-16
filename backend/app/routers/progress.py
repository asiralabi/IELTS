from collections import OrderedDict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agents import feedback, weakness
from app.auth import get_current_user
from app.database import get_db
from app.models import (
    MockExam,
    PracticeAttempt,
    SpeakingSubmission,
    User,
    WritingSubmission,
)

router = APIRouter(prefix="/progress", tags=["progress"])


# NOTE: pagination cap for timeline queries. The timeline is trimmed to
# the top 10 items below, so pulling every historical row from the DB
# just to sort-and-slice is wasteful. 50 is a comfortable ceiling: it
# lets us merge across four sources (writing/speaking/reading/listening
# practice) and still hand the top 10 with variety.
_TIMELINE_SLICE = 10
_QUERY_LIMIT = 50

# Cache LLM-heavy weakness + study-plan responses per user, keyed on the
# id of the latest submission that could shift the answer. New submission
# ⇒ new key ⇒ recompute; old submissions keep serving from cache. Bounded
# LRU at 500 entries — plenty for a solo instructor deployment.
_CACHE_MAX = 500
_weakness_cache: OrderedDict[tuple[int, tuple[int, int, int]], dict] = OrderedDict()
_study_plan_cache: OrderedDict[tuple[int, tuple[int, int, int]], dict] = OrderedDict()


def _skill_stats(bands: list[float | None]) -> dict:
    values = [b for b in bands if b is not None]
    return {
        "latest_band": values[0] if values else None,
        "average_band": round(sum(values) / len(values), 2) if values else None,
    }


def _latest_submission_key(db: Session, user_id: int) -> tuple[int, int, int]:
    """Signature of the user's most recent submission across sources.

    Any new writing/speaking/practice row bumps at least one component,
    which is exactly the "cache invalidation by omission" semantics we
    want: a fresh submission gets a fresh LLM analysis.
    """
    # NOTE: three lightweight MAX(id) scalars — cheaper than one full sort.
    def _max_id(model: Any, user_col: Any) -> int:
        from sqlalchemy import func, select

        return int(
            db.execute(
                select(func.coalesce(func.max(model.id), 0)).where(user_col == user_id)
            ).scalar_one()
        )

    return (
        _max_id(WritingSubmission, WritingSubmission.user_id),
        _max_id(SpeakingSubmission, SpeakingSubmission.user_id),
        _max_id(PracticeAttempt, PracticeAttempt.user_id),
    )


def _cache_get(
    cache: OrderedDict, key: tuple[int, tuple[int, int, int]]
) -> dict | None:
    hit = cache.get(key)
    if hit is not None:
        cache.move_to_end(key)
    return hit


def _cache_set(
    cache: OrderedDict, key: tuple[int, tuple[int, int, int]], value: dict
) -> None:
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > _CACHE_MAX:
        cache.popitem(last=False)


@router.get("")
async def get_progress(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    # NOTE: cap each source at 50. Timeline is sliced to 10 downstream, and
    # counts/skills use the same limited set — trading a slightly stale
    # "average across all history" for an O(50) result set instead of O(N).
    writing = (
        db.query(WritingSubmission)
        .filter(WritingSubmission.user_id == user.id)
        .order_by(WritingSubmission.id.desc())
        .limit(_QUERY_LIMIT)
        .all()
    )
    speaking = (
        db.query(SpeakingSubmission)
        .filter(SpeakingSubmission.user_id == user.id)
        .order_by(SpeakingSubmission.id.desc())
        .limit(_QUERY_LIMIT)
        .all()
    )
    attempts = (
        db.query(PracticeAttempt)
        .filter(PracticeAttempt.user_id == user.id)
        .order_by(PracticeAttempt.id.desc())
        .limit(_QUERY_LIMIT)
        .all()
    )
    exams = (
        db.query(MockExam)
        .filter(MockExam.user_id == user.id)
        .order_by(MockExam.id.desc())
        .limit(_QUERY_LIMIT)
        .all()
    )

    def attempt_band(a: PracticeAttempt) -> float | None:
        return (a.result or {}).get("band_estimate")

    reading_attempts = [a for a in attempts if a.section == "reading"]
    listening_attempts = [a for a in attempts if a.section == "listening"]

    timeline_items: list[dict] = []
    for w in writing:
        timeline_items.append(
            {"type": "writing", "id": w.id, "band": w.band_score, "created_at": w.created_at}
        )
    for s in speaking:
        timeline_items.append(
            {"type": "speaking", "id": s.id, "band": s.band_score, "created_at": s.created_at}
        )
    for a in attempts:
        timeline_items.append(
            {
                "type": f"{a.section}_practice",
                "id": a.id,
                "score": a.score,
                "total": a.total,
                "band": attempt_band(a),
                "created_at": a.created_at,
            }
        )
    timeline_items.sort(key=lambda x: x["created_at"], reverse=True)

    return {
        "counts": {
            "writing_submissions": len(writing),
            "speaking_submissions": len(speaking),
            "reading_attempts": len(reading_attempts),
            "listening_attempts": len(listening_attempts),
            "mock_exams": len(exams),
        },
        "skills": {
            "writing": _skill_stats([w.band_score for w in writing]),
            "speaking": _skill_stats([s.band_score for s in speaking]),
            "reading": _skill_stats([attempt_band(a) for a in reading_attempts]),
            "listening": _skill_stats([attempt_band(a) for a in listening_attempts]),
            "mock_exam": _skill_stats([e.overall_band for e in exams]),
        },
        "target_band": user.target_band,
        "timeline": timeline_items[:_TIMELINE_SLICE],
    }


@router.get("/weaknesses")
async def get_weaknesses(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    key = (user.id, _latest_submission_key(db, user.id))
    cached = _cache_get(_weakness_cache, key)
    if cached is not None:
        return cached
    try:
        result = await weakness.analyze(db, user)
    except ValueError:
        raise HTTPException(status_code=502, detail="LLM returned invalid output")
    _cache_set(_weakness_cache, key, result)
    return result


@router.get("/study-plan")
async def get_study_plan(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    key = (user.id, _latest_submission_key(db, user.id))
    cached = _cache_get(_study_plan_cache, key)
    if cached is not None:
        return cached
    try:
        result = await feedback.study_plan(db, user)
    except ValueError:
        raise HTTPException(status_code=502, detail="LLM returned invalid output")
    _cache_set(_study_plan_cache, key, result)
    return result

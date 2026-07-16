from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agents import reading_trainer
from app.auth import get_current_user
from app.database import get_db
from app.models import GeneratedQuestion, PracticeAttempt, User
from app.services import practice_pool

router = APIRouter(prefix="/reading", tags=["reading"])


class PracticeRequest(BaseModel):
    question_types: list[str] | None = None
    difficulty: str | None = None
    topic: str | None = None


class CheckRequest(BaseModel):
    practice_id: int
    answers: dict[str, str]


@router.post("/practice")
async def create_practice(
    payload: PracticeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    # Default flow (no custom filters) → try the warm pool for an instant
    # response; only fall back to synchronous LLM generation when the pool
    # is empty.
    practice: dict | None = None
    if not payload.question_types and not payload.topic and not payload.difficulty:
        practice = practice_pool.pop(db, "reading", None)

    if practice is None:
        try:
            practice = await reading_trainer.create_practice(
                payload.question_types, payload.difficulty, payload.topic
            )
        except ValueError:
            raise HTTPException(status_code=502, detail="LLM returned invalid output")

    question = GeneratedQuestion(
        user_id=user.id,
        section="reading",
        question_type=", ".join(payload.question_types or []) or "mixed",
        difficulty=payload.difficulty or "unspecified",
        payload=practice,
    )
    db.add(question)
    db.commit()
    db.refresh(question)
    public = {k: v for k, v in practice.items() if k != "answer_key"}
    return {"practice_id": question.id, **public}


@router.post("/check")
async def check_answers(
    payload: CheckRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    question = db.get(GeneratedQuestion, payload.practice_id)
    if (
        question is None
        or question.section != "reading"
        or question.user_id not in (None, user.id)
    ):
        raise HTTPException(status_code=404, detail="Practice not found")

    try:
        result = await reading_trainer.check_answers(question.payload, payload.answers)
    except ValueError:
        raise HTTPException(status_code=502, detail="LLM returned invalid output")

    attempt = PracticeAttempt(
        user_id=user.id,
        section="reading",
        question_id=question.id,
        answers=payload.answers,
        score=result.get("score"),
        total=result.get("total"),
        result=result,
    )
    db.add(attempt)
    db.commit()
    return result

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agents import question_generator
from app.auth import get_current_user
from app.database import get_db
from app.models import GeneratedQuestion, User
from app.services import practice_pool

router = APIRouter(prefix="/questions", tags=["questions"])


class QuestionGenerateRequest(BaseModel):
    section: Literal["reading", "listening", "writing", "speaking"]
    question_type: str | None = None
    difficulty: str | None = None
    topic: str | None = None


@router.post("/generate")
async def generate_question(
    payload: QuestionGenerateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    result: dict | None = None
    if not payload.topic and not payload.difficulty:
        bucket_key = practice_pool.canonical_bucket(payload.section, payload.question_type)
        if bucket_key is not None:
            result = practice_pool.pop(db, payload.section, bucket_key)

    if result is None:
        try:
            result = await question_generator.generate(
                payload.section, payload.question_type, payload.difficulty, payload.topic
            )
        except ValueError:
            raise HTTPException(status_code=502, detail="LLM returned invalid output")

    question = GeneratedQuestion(
        user_id=user.id,
        section=payload.section,
        question_type=str(result.get("question_type") or payload.question_type or "general"),
        difficulty=str(result.get("difficulty") or payload.difficulty or "unspecified"),
        payload=result,
    )
    db.add(question)
    db.commit()
    db.refresh(question)
    return {"id": question.id, **result}

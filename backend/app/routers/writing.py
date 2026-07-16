from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents import writing_examiner
from app.auth import get_current_user
from app.database import get_db
from app.models import User, WritingSubmission

router = APIRouter(prefix="/writing", tags=["writing"])


class WritingSubmitRequest(BaseModel):
    task_type: Literal["task1", "task2"]
    prompt: str
    essay: str = Field(min_length=50)
    visual: dict[str, Any] | None = None


@router.post("/submit")
async def submit_essay(
    payload: WritingSubmitRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    try:
        result = await writing_examiner.evaluate(
            payload.task_type, payload.prompt, payload.essay, payload.visual
        )
    except ValueError:
        raise HTTPException(status_code=502, detail="LLM returned invalid output")

    if payload.visual is not None:
        # Persist alongside scores so the history/detail view can re-render the
        # exact chart that was graded — the model column is a JSON blob so no
        # schema migration is needed.
        result = {**result, "visual": payload.visual}

    submission = WritingSubmission(
        user_id=user.id,
        task_type=payload.task_type,
        prompt=payload.prompt,
        essay=payload.essay,
        word_count=result.get("word_count") or len(payload.essay.split()),
        result=result,
        band_score=result.get("band_score"),
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)
    return {"id": submission.id, "word_count": submission.word_count, **result}


@router.get("/history")
async def writing_history(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[dict]:
    rows = (
        db.query(WritingSubmission)
        .filter(WritingSubmission.user_id == user.id)
        .order_by(WritingSubmission.id.desc())
        .all()
    )
    return [
        {
            "id": r.id,
            "task_type": r.task_type,
            "band_score": r.band_score,
            "word_count": r.word_count,
            "created_at": r.created_at,
        }
        for r in rows
    ]

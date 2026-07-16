from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents import orchestrator
from app.auth import get_current_user
from app.database import get_db
from app.models import MockExam, User

router = APIRouter(prefix="/mock-exam", tags=["mock-exam"])

_HIDDEN_KEYS = {"answer_key", "answers", "explanation"}


def _strip_keys(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _strip_keys(v) for k, v in obj.items() if k not in _HIDDEN_KEYS}
    if isinstance(obj, list):
        return [_strip_keys(x) for x in obj]
    return obj


class MockExamSubmission(BaseModel):
    listening_answers: dict[str, str] = Field(default_factory=dict)
    reading_answers: dict[str, str] = Field(default_factory=dict)
    essays: dict[str, str] = Field(default_factory=dict)
    speaking_transcripts: dict[str, str] = Field(default_factory=dict)


def _get_owned_exam(exam_id: int, db: Session, user: User) -> MockExam:
    exam = db.get(MockExam, exam_id)
    if exam is None or exam.user_id != user.id:
        raise HTTPException(status_code=404, detail="Mock exam not found")
    return exam


@router.post("/generate")
async def generate_mock_exam(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    try:
        exam_payload = await orchestrator.build_mock_exam(user.target_band)
    except ValueError:
        raise HTTPException(status_code=502, detail="LLM returned invalid output")

    exam = MockExam(user_id=user.id, exam=exam_payload)
    db.add(exam)
    db.commit()
    db.refresh(exam)
    return {"id": exam.id, "exam": _strip_keys(exam_payload)}


@router.post("/{exam_id}/submit")
async def submit_mock_exam(
    exam_id: int,
    payload: MockExamSubmission,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    exam = _get_owned_exam(exam_id, db, user)
    if exam.status == "scored":
        raise HTTPException(status_code=409, detail="Mock exam already scored")
    try:
        return await orchestrator.score_mock_exam(db, user, exam, payload.model_dump())
    except ValueError:
        raise HTTPException(status_code=502, detail="LLM returned invalid output")


@router.get("/{exam_id}")
async def get_mock_exam(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    exam = _get_owned_exam(exam_id, db, user)
    exam_view = exam.exam if exam.status == "scored" else _strip_keys(exam.exam)
    return {
        "id": exam.id,
        "status": exam.status,
        "exam": exam_view,
        "results": exam.results,
        "overall_band": exam.overall_band,
        "created_at": exam.created_at,
    }

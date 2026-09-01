from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents import orchestrator
from app.auth import get_current_user
from app.database import get_db
from app.models import MockExam, User
from app.routers._payload import ANSWER_FIELDS
from app.services import tts

router = APIRouter(prefix="/mock-exam", tags=["mock-exam"])

def _strip_keys(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _strip_keys(v) for k, v in obj.items() if k not in ANSWER_FIELDS}
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
        exam_payload = await orchestrator.build_mock_exam(db, user.target_band)
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


@router.get("/{exam_id}/audio")
async def get_exam_audio(
    exam_id: int,
    part: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """Stream the recording for one Listening part of a mock exam.

    The mock exam printed its `audio_script` on screen, so a student sat the
    Listening paper by READING the transcript — which is a reading test with a
    different name on it. The single-practice route cannot serve this: it is
    keyed to a `GeneratedQuestion` id, and an exam's listening paper is a
    snapshot inside `MockExam.exam` with no id of its own.

    Synthesis is lazy and cached by the TTS service, so the first play of a
    part pays for it and every later play is free.
    """
    exam = _get_owned_exam(exam_id, db, user)
    parts = ((exam.exam or {}).get("listening") or {}).get("parts") or []
    for candidate in parts:
        if isinstance(candidate, dict) and candidate.get("part") == part:
            script = candidate.get("audio_script")
            speakers = candidate.get("speakers")
            break
    else:
        raise HTTPException(status_code=404, detail="No such part in this exam")

    if not script:
        raise HTTPException(status_code=404, detail="No recording for this part")

    try:
        audio = await tts.synthesize_script(script, speakers)
    except Exception:
        raise HTTPException(status_code=503, detail="Audio synthesis unavailable")

    return Response(
        content=audio,
        media_type="audio/mpeg",
        headers={"Cache-Control": "private, max-age=86400"},
    )


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

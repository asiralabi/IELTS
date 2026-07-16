from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agents import listening_trainer
from app.auth import get_current_user
from app.database import get_db
from app.models import GeneratedQuestion, PracticeAttempt, User
from app.services import practice_pool, tts

router = APIRouter(prefix="/listening", tags=["listening"])


class PracticeRequest(BaseModel):
    question_types: list[str] | None = None
    difficulty: str | None = None
    topic: str | None = None


class CheckRequest(BaseModel):
    practice_id: int
    answers: dict[str, str]


class FullTestRequest(BaseModel):
    difficulty: str | None = None


# Server-only fields that reveal answers or exam design — never sent to the
# client before grading (they stay in the stored payload for the checker).
_ANSWER_FIELDS = ("answer_key", "accepted_variants", "answer_positions", "blueprint")


def _public(practice: dict) -> dict:
    """Drop answer-bearing / design fields from a single practice payload."""
    return {k: v for k, v in practice.items() if k not in _ANSWER_FIELDS}


def _strip_answer_keys(test: dict) -> dict:
    """Return the full-test payload with every part's answer-bearing fields
    removed so the correct answers never reach the client before grading."""
    return {
        **{k: v for k, v in test.items() if k != "parts"},
        "parts": [_public(part) for part in test.get("parts", [])],
    }


@router.post("/practice")
async def create_practice(
    payload: PracticeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    practice: dict | None = None
    if not payload.question_types and not payload.topic and not payload.difficulty:
        practice = practice_pool.pop(db, "listening", None)

    if practice is None:
        try:
            practice = await listening_trainer.create_practice(
                payload.question_types, payload.difficulty, payload.topic
            )
        except ValueError:
            raise HTTPException(status_code=502, detail="LLM returned invalid output")

    question = GeneratedQuestion(
        user_id=user.id,
        section="listening",
        question_type=", ".join(payload.question_types or []) or "mixed",
        difficulty=payload.difficulty or "unspecified",
        payload=practice,
    )
    db.add(question)
    db.commit()
    db.refresh(question)
    return {"practice_id": question.id, **_public(practice)}


@router.post("/check")
async def check_answers(
    payload: CheckRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    question = db.get(GeneratedQuestion, payload.practice_id)
    if (
        question is None
        or question.section != "listening"
        or question.user_id not in (None, user.id)
    ):
        raise HTTPException(status_code=404, detail="Practice not found")

    try:
        result = await listening_trainer.check_answers(
            question.payload, payload.answers
        )
    except ValueError:
        raise HTTPException(status_code=502, detail="LLM returned invalid output")

    attempt = PracticeAttempt(
        user_id=user.id,
        section="listening",
        question_id=question.id,
        answers=payload.answers,
        score=result.get("score"),
        total=result.get("total"),
        result=result,
    )
    db.add(attempt)
    db.commit()
    return result


@router.get("/audio/{practice_id}")
async def get_audio(
    practice_id: int,
    part: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """Stream a multi-speaker neural recording of a listening script.

    Serves a full-test Part when ``?part=N`` is given, otherwise the single
    practice set's script. Synthesis is lazy + cached in the TTS service.
    """
    question = db.get(GeneratedQuestion, practice_id)
    if (
        question is None
        or question.section != "listening"
        or question.user_id not in (None, user.id)
    ):
        raise HTTPException(status_code=404, detail="Recording not found")

    payload = question.payload or {}
    script: str | None = None
    speakers: object = None
    if part is not None:
        for p in payload.get("parts", []):
            if p.get("part") == part:
                script = p.get("audio_script")
                speakers = p.get("speakers")
                break
    else:
        script = payload.get("audio_script")
        speakers = payload.get("speakers")

    if not script:
        raise HTTPException(status_code=404, detail="No recording for this material")

    try:
        audio = await tts.synthesize_script(script, speakers)
    except Exception:
        raise HTTPException(status_code=503, detail="Audio synthesis unavailable")

    return Response(
        content=audio,
        media_type="audio/mpeg",
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.post("/full-test")
async def create_full_test(
    payload: FullTestRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    try:
        test = await listening_trainer.create_full_test(payload.difficulty)
    except ValueError:
        raise HTTPException(status_code=502, detail="LLM returned invalid output")

    question = GeneratedQuestion(
        user_id=user.id,
        section="listening",
        question_type="full_test",
        difficulty=payload.difficulty or "unspecified",
        payload=test,
    )
    db.add(question)
    db.commit()
    db.refresh(question)
    return {"practice_id": question.id, **_strip_answer_keys(test)}


@router.post("/full-test/check")
async def check_full_test(
    payload: CheckRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    question = db.get(GeneratedQuestion, payload.practice_id)
    if (
        question is None
        or question.section != "listening"
        or question.question_type != "full_test"
        or question.user_id not in (None, user.id)
    ):
        raise HTTPException(status_code=404, detail="Test not found")

    try:
        result = await listening_trainer.check_full_test(
            question.payload, payload.answers
        )
    except ValueError:
        raise HTTPException(status_code=502, detail="LLM returned invalid output")

    attempt = PracticeAttempt(
        user_id=user.id,
        section="listening",
        question_id=question.id,
        answers=payload.answers,
        score=result.get("score"),
        total=result.get("total"),
        result=result,
    )
    db.add(attempt)
    db.commit()
    return result

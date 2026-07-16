from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.agents import speaking_examiner
from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models import SpeakingSubmission, User

router = APIRouter(prefix="/speaking", tags=["speaking"])


@router.post("/submit")
async def submit_speaking(
    part: str = Form(...),
    question: str = Form(...),
    transcript: str | None = Form(None),
    audio: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    audio_path: str | None = None
    text = (transcript or "").strip()
    if not text:
        if audio is None:
            raise HTTPException(
                status_code=400, detail="Provide a transcript or an audio file"
            )
        settings.ensure_data_dirs()
        suffix = Path(audio.filename or "").suffix or ".wav"
        audio_path = str(Path(settings.upload_dir) / f"{uuid4().hex}{suffix}")
        with open(audio_path, "wb") as f:
            f.write(await audio.read())
        text = speaking_examiner.transcribe(audio_path)
        if not text.strip():
            raise HTTPException(
                status_code=400, detail="Could not transcribe any speech from the audio"
            )

    try:
        result = await speaking_examiner.evaluate(part, question, text)
    except ValueError:
        raise HTTPException(status_code=502, detail="LLM returned invalid output")

    submission = SpeakingSubmission(
        user_id=user.id,
        part=part,
        question=question,
        transcript=text,
        audio_path=audio_path,
        result=result,
        band_score=result.get("band_score"),
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)
    return {"id": submission.id, "transcript": text, **result}


@router.get("/history")
async def speaking_history(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[dict]:
    rows = (
        db.query(SpeakingSubmission)
        .filter(SpeakingSubmission.user_id == user.id)
        .order_by(SpeakingSubmission.id.desc())
        .all()
    )
    return [
        {
            "id": r.id,
            "part": r.part,
            "band_score": r.band_score,
            "created_at": r.created_at,
        }
        for r in rows
    ]

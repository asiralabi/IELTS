import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents import question_generator, speaking_examiner
from app.agents._marking import speaking_band
from app.agents.question_generator import as_text
from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models import SpeakingSubmission, User
from app.services import practice_pool

router = APIRouter(prefix="/speaking", tags=["speaking"])

# One Speaking interview, in the order it is sat: the pool label to draw each
# part from, and the minutes the real exam allows it.
_INTERVIEW = (
    ("part1", "Part 1 questions", "Part 1: Introduction and interview", 5),
    ("part2", "Part 2 cue card", "Part 2: Long turn", 4),
    ("part3", "Part 3 discussion questions", "Part 3: Discussion", 5),
)


class SpeakingPartAnswer(BaseModel):
    # The generated question comes back as a string for Part 1, a cue-card
    # object for Part 2 and a list for Part 3, so it round-trips as-is.
    question: Any = None
    transcript: str = Field(min_length=1)


class SpeakingFullTestRequest(BaseModel):
    part1: SpeakingPartAnswer | None = None
    part2: SpeakingPartAnswer | None = None
    part3: SpeakingPartAnswer | None = None


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


@router.post("/full-test")
async def create_full_test(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """All three parts of one Speaking interview, served together.

    The parts come from the same warm pool the single-part page pops from, so
    asking for the whole interview costs no more waiting than asking for a
    third of it. Only a part the pool has run dry on is generated here.
    """
    parts = {key: practice_pool.pop(db, "speaking", label) for key, label, _, _ in _INTERVIEW}
    cold = [(key, label) for key, label, _, _ in _INTERVIEW if parts[key] is None]
    if cold:
        try:
            fresh = await asyncio.gather(
                *(question_generator.generate("speaking", label) for _, label in cold)
            )
        except ValueError:
            raise HTTPException(status_code=502, detail="LLM returned invalid output")
        for (key, _label), payload in zip(cold, fresh):
            parts[key] = payload

    return {
        "kind": "full_speaking_test",
        "title": "IELTS Speaking",
        "parts": [
            {"part": key, "label": label, "minutes": minutes, **parts[key]}
            for key, _bucket, label, minutes in _INTERVIEW
        ],
    }


@router.post("/full-test/submit")
async def submit_full_test(
    payload: SpeakingFullTestRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Mark all three parts and band the interview as one.

    Each part is also stored as an ordinary submission, so a full interview
    feeds the same history and progress views a single part does.
    """
    answered = [
        (key, answer)
        for key, *_ in _INTERVIEW
        if (answer := getattr(payload, key)) is not None
    ]
    if not answered:
        raise HTTPException(status_code=400, detail="Answer at least one part")

    questions = {key: as_text(answer.question) for key, answer in answered}
    try:
        outcomes = await asyncio.gather(
            *(
                speaking_examiner.evaluate(key, questions[key], answer.transcript)
                for key, answer in answered
            )
        )
    except ValueError:
        raise HTTPException(status_code=502, detail="LLM returned invalid output")

    results: dict[str, dict] = {}
    for (key, answer), result in zip(answered, outcomes):
        submission = SpeakingSubmission(
            user_id=user.id,
            part=key,
            question=questions[key],
            transcript=answer.transcript,
            result=result,
            band_score=result.get("band_score"),
        )
        db.add(submission)
        db.flush()
        results[key] = {"id": submission.id, **result}
    db.commit()

    return {
        "parts": results,
        "overall_band": speaking_band(
            [
                float(r["band_score"])
                for r in results.values()
                if r.get("band_score") is not None
            ]
        ),
    }


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

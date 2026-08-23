import asyncio
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents import question_generator, writing_examiner
from app.agents._marking import writing_band
from app.auth import get_current_user
from app.database import get_db
from app.models import User, WritingSubmission
from app.services import practice_pool

router = APIRouter(prefix="/writing", tags=["writing"])

# One Writing paper, in the order it is sat: the pool label to draw each task
# from, and the timing the real exam prints above it.
_PAPER = (
    ("task1", "Task 1", 20, 150),
    ("task2", "Task 2 essay", 40, 250),
)


class WritingSubmitRequest(BaseModel):
    task_type: Literal["task1", "task2"]
    prompt: str
    essay: str = Field(min_length=50)
    visual: dict[str, Any] | None = None
    # A Task 1 map is two plans of one place, so it arrives as a list rather
    # than in `visual`. Both are carried: a chart task still sends `visual`.
    visuals: list[dict[str, Any]] | None = None


class WritingTaskAnswer(BaseModel):
    prompt: str
    essay: str = Field(min_length=50)
    visual: dict[str, Any] | None = None
    visuals: list[dict[str, Any]] | None = None


class WritingFullTestRequest(BaseModel):
    task1: WritingTaskAnswer | None = None
    task2: WritingTaskAnswer | None = None


@router.post("/submit")
async def submit_essay(
    payload: WritingSubmitRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    try:
        result = await writing_examiner.evaluate(
            payload.task_type,
            payload.prompt,
            payload.essay,
            payload.visual,
            payload.visuals,
        )
    except ValueError:
        raise HTTPException(status_code=502, detail="LLM returned invalid output")

    if payload.visual is not None:
        # Persist alongside scores so the history/detail view can re-render the
        # exact chart that was graded — the model column is a JSON blob so no
        # schema migration is needed.
        result = {**result, "visual": payload.visual}
    if payload.visuals is not None:
        result = {**result, "visuals": payload.visuals}

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


@router.post("/full-test")
async def create_full_test(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Both tasks of one Writing paper, served together.

    The tasks come from the same warm pool the single-task page pops from, so a
    student who asked for the whole paper waits no longer than one who asked for
    half of it. Only a task the pool has run dry on is generated here.
    """
    tasks = {key: practice_pool.pop(db, "writing", label) for key, label, _, _ in _PAPER}
    cold = [(key, label) for key, label, _, _ in _PAPER if tasks[key] is None]
    if cold:
        try:
            fresh = await asyncio.gather(
                *(question_generator.generate("writing", label) for _, label in cold)
            )
        except ValueError:
            raise HTTPException(status_code=502, detail="LLM returned invalid output")
        for (key, _label), payload in zip(cold, fresh):
            tasks[key] = payload

    return {
        "kind": "full_writing_test",
        "title": "IELTS Academic Writing",
        "tasks": [
            {
                "task": key,
                "label": label.removesuffix(" essay"),
                "minutes": minutes,
                "min_words": min_words,
                **tasks[key],
            }
            for key, label, minutes, min_words in _PAPER
        ],
    }


@router.post("/full-test/submit")
async def submit_full_test(
    payload: WritingFullTestRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Mark both tasks and band the paper as one.

    Each task is also stored as an ordinary submission, so a full paper feeds
    the same history and progress views a single task does.
    """
    answered = [
        (key, answer)
        for key, *_ in _PAPER
        if (answer := getattr(payload, key)) is not None
    ]
    if not answered:
        raise HTTPException(status_code=400, detail="Write at least one task")

    try:
        outcomes = await asyncio.gather(
            *(
                writing_examiner.evaluate(
                    key, a.prompt, a.essay, a.visual, a.visuals
                )
                for key, a in answered
            )
        )
    except ValueError:
        raise HTTPException(status_code=502, detail="LLM returned invalid output")

    results: dict[str, dict] = {}
    for (key, answer), result in zip(answered, outcomes):
        if answer.visual is not None:
            result = {**result, "visual": answer.visual}
        if answer.visuals is not None:
            result = {**result, "visuals": answer.visuals}
        submission = WritingSubmission(
            user_id=user.id,
            task_type=key,
            prompt=answer.prompt,
            essay=answer.essay,
            word_count=result.get("word_count") or len(answer.essay.split()),
            result=result,
            band_score=result.get("band_score"),
        )
        db.add(submission)
        db.flush()
        results[key] = {
            "id": submission.id,
            "word_count": submission.word_count,
            **result,
        }
    db.commit()

    def band_of(key: str) -> float | None:
        score = results.get(key, {}).get("band_score")
        return None if score is None else float(score)

    return {
        "tasks": results,
        "overall_band": writing_band(band_of("task1"), band_of("task2")),
    }


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

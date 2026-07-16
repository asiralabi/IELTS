"""Cambridge IELTS loader — serves real Cambridge tests as PracticeSet-shaped
payloads so the reading/listening/writing pages can render them through the
same components as AI-generated content.

This is an opt-in flow — the student explicitly picks a book/test from the
Cambridge picker. The default practice endpoints still call the LLM.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import CambridgeTest, GeneratedQuestion, User

router = APIRouter(prefix="/cambridge", tags=["cambridge"])


# ---------------------------------------------------------------------------
# Helpers


def _blocks_to_questions(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Expand each Cambridge "Questions X-Y" block into per-question rows.

    Only the FIRST row in each block carries the block instructions + visual;
    the rest get a short placeholder so the answer input still renders per
    question while the block instructions stay visible once.
    """
    questions: list[dict[str, Any]] = []
    for block in blocks:
        start = block.get("start")
        end = block.get("end")
        if not isinstance(start, int) or not isinstance(end, int) or end < start:
            continue
        instruction = str(block.get("text") or "").strip() or f"Questions {start}-{end}."
        for n in range(start, end + 1):
            q: dict[str, Any] = {"number": n}
            if n == start:
                q["question"] = instruction
                if block.get("visual"):
                    q["visual"] = block["visual"]
                if block.get("visuals"):
                    q["visuals"] = block["visuals"]
            else:
                q["question"] = f"(Answer as directed for Questions {start}-{end}.)"
            questions.append(q)
    return questions


def _slice_answer_key(
    answer_key: dict[str, Any] | None, start: int, end: int
) -> dict[str, str]:
    if not answer_key:
        return {}
    return {
        str(n): str(answer_key[str(n)])
        for n in range(start, end + 1)
        if str(n) in answer_key
    }


def _question_range(blocks: list[dict[str, Any]]) -> tuple[int, int]:
    if not blocks:
        return (1, 0)
    starts = [b["start"] for b in blocks if isinstance(b.get("start"), int)]
    ends = [b["end"] for b in blocks if isinstance(b.get("end"), int)]
    if not starts or not ends:
        return (1, 0)
    return (min(starts), max(ends))


def _get_test(db: Session, book_id: str, test_number: int) -> CambridgeTest:
    test = (
        db.query(CambridgeTest)
        .filter_by(book_id=book_id, test_number=test_number)
        .first()
    )
    if test is None:
        raise HTTPException(status_code=404, detail="Cambridge test not found")
    return test


# ---------------------------------------------------------------------------
# Endpoints


@router.get("/index")
def cambridge_index(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """List every ingested book and its available tests."""
    rows = db.query(CambridgeTest).order_by(CambridgeTest.book_id, CambridgeTest.test_number).all()
    books: dict[str, dict[str, Any]] = {}
    for row in rows:
        book = books.setdefault(
            row.book_id,
            {"book_id": row.book_id, "book_title": row.book_title, "tests": []},
        )
        reading = row.reading or {}
        listening = row.listening or {}
        writing = row.writing or {}
        book["tests"].append(
            {
                "test_number": row.test_number,
                "reading_passages": len(reading.get("passages", []) or []),
                "listening_parts": len(listening.get("parts", []) or []),
                "writing_tasks": len(writing.get("tasks", []) or []),
                "warnings": row.warnings or [],
            }
        )
    ordered = sorted(books.values(), key=lambda b: _book_sort_key(b["book_id"]))
    return {"books": ordered}


def _book_sort_key(book_id: str) -> tuple[int, str]:
    # "cambridge-18" → (18, "cambridge-18") so C1 < C2 < ... < C18 rather than
    # lexicographic ordering that would put C10 next to C1.
    parts = book_id.rsplit("-", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return (int(parts[1]), book_id)
    return (10_000, book_id)


@router.get("/{book_id}/{test_number}")
def cambridge_test_summary(
    book_id: str,
    test_number: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Per-test summary — passage/part/task counts + has_visual flags."""
    test = _get_test(db, book_id, test_number)
    reading = test.reading or {}
    listening = test.listening or {}
    writing = test.writing or {}
    return {
        "book_id": test.book_id,
        "book_title": test.book_title,
        "test_number": test.test_number,
        "reading": {
            "passages": [
                {
                    "n": p.get("n"),
                    "title": p.get("title", ""),
                    "has_visual": bool(p.get("visual") or p.get("visuals")),
                }
                for p in reading.get("passages", []) or []
            ]
        },
        "listening": {
            "parts": [
                {
                    "n": p.get("n"),
                    "has_visual": bool(p.get("visual") or p.get("visuals")),
                }
                for p in listening.get("parts", []) or []
            ]
        },
        "writing": {
            "tasks": [
                {
                    "n": t.get("n"),
                    "has_visual": bool(t.get("visual") or t.get("visuals")),
                }
                for t in writing.get("tasks", []) or []
            ]
        },
        "warnings": test.warnings or [],
    }


@router.get("/{book_id}/{test_number}/reading")
def cambridge_reading(
    book_id: str,
    test_number: int,
    passage: int = Query(1, ge=1, le=3),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Serve a specific Cambridge reading passage as a PracticeSet.

    Persists a GeneratedQuestion row so `/reading/check` works unchanged.
    """
    test = _get_test(db, book_id, test_number)
    reading = test.reading or {}
    passages = reading.get("passages", []) or []
    match = next((p for p in passages if p.get("n") == passage), None)
    if match is None:
        raise HTTPException(status_code=404, detail=f"passage {passage} not found")

    blocks = match.get("question_blocks", []) or []
    questions = _blocks_to_questions(blocks)
    q_start, q_end = _question_range(blocks)
    answer_key = _slice_answer_key(reading.get("answer_key"), q_start, q_end)

    payload: dict[str, Any] = {
        "title": match.get("title") or f"Reading Passage {passage}",
        "passage": match.get("text", ""),
        "questions": questions,
        "answer_key": answer_key,
        "source": f"{book_id}-test-{test_number}-passage-{passage}",
    }
    if match.get("visual"):
        payload["visual"] = match["visual"]
    if match.get("visuals"):
        payload["visuals"] = match["visuals"]

    row = GeneratedQuestion(
        user_id=user.id,
        section="reading",
        question_type="cambridge",
        difficulty="reference",
        payload=payload,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    public = {k: v for k, v in payload.items() if k != "answer_key"}
    note = None
    if not answer_key:
        note = "Answer key not available for this passage."
    result = {"practice_id": row.id, **public}
    if note:
        result["note"] = note
    return result


@router.get("/{book_id}/{test_number}/listening")
def cambridge_listening(
    book_id: str,
    test_number: int,
    part: int = Query(1, ge=1, le=4),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Serve a Cambridge listening part. No audio — Cambridge PDFs don't ship
    the recordings, and TTS-reading the printed script would defeat the point.
    """
    test = _get_test(db, book_id, test_number)
    listening = test.listening or {}
    parts = listening.get("parts", []) or []
    match = next((p for p in parts if p.get("n") == part), None)
    if match is None:
        raise HTTPException(status_code=404, detail=f"listening part {part} not found")

    blocks = match.get("question_blocks", []) or []
    questions = _blocks_to_questions(blocks)
    q_start, q_end = _question_range(blocks)
    answer_key = _slice_answer_key(listening.get("answer_key"), q_start, q_end)

    payload: dict[str, Any] = {
        "title": f"Listening Part {part}",
        "questions": questions,
        "answer_key": answer_key,
        "source": f"{book_id}-test-{test_number}-listening-part-{part}",
    }
    if match.get("visual"):
        payload["visual"] = match["visual"]
    if match.get("visuals"):
        payload["visuals"] = match["visuals"]

    row = GeneratedQuestion(
        user_id=user.id,
        section="listening",
        question_type="cambridge",
        difficulty="reference",
        payload=payload,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    public = {k: v for k, v in payload.items() if k != "answer_key"}
    note = "Paper-based only — Cambridge audio recordings aren't included."
    if not answer_key:
        note += " Answer key not available for this part."
    return {"practice_id": row.id, "note": note, **public}


@router.get("/{book_id}/{test_number}/writing")
def cambridge_writing(
    book_id: str,
    test_number: int,
    task: int = Query(1, ge=1, le=2),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Serve a Cambridge writing task prompt (+ visual for Task 1).

    Does NOT persist — the writing submit flow builds its own record.
    """
    test = _get_test(db, book_id, test_number)
    writing = test.writing or {}
    tasks = writing.get("tasks", []) or []
    match = next((t for t in tasks if t.get("n") == task), None)
    if match is None:
        raise HTTPException(status_code=404, detail=f"writing task {task} not found")

    result: dict[str, Any] = {
        "task": task,
        "prompt": match.get("prompt", ""),
        "source": f"{book_id}-test-{test_number}-writing-task-{task}",
    }
    if match.get("visual"):
        result["visual"] = match["visual"]
    if match.get("visuals"):
        result["visuals"] = match["visuals"]
    return result

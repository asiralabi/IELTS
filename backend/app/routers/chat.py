from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agents import instructor
from app.auth import get_current_user
from app.database import get_db
from app.models import ChatMessage, ChatSession, User
from app.schemas import ChatMessageOut, ChatRequest, ChatResponse, ChatSessionOut

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    try:
        return await instructor.chat(db, user, payload.message, payload.session_id)
    except ValueError:
        raise HTTPException(status_code=502, detail="LLM returned invalid output")


@router.get("/sessions", response_model=list[ChatSessionOut])
async def list_sessions(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[ChatSession]:
    return (
        db.query(ChatSession)
        .filter(ChatSession.user_id == user.id)
        .order_by(ChatSession.id.desc())
        .all()
    )


@router.get("/sessions/{session_id}", response_model=list[ChatMessageOut])
async def get_session_messages(
    session_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ChatMessage]:
    session = db.get(ChatSession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.id.asc())
        .all()
    )

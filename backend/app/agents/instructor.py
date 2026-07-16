from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.llm.client import get_llm_client
from app.llm.prompts import INSTRUCTOR_SYSTEM
from app.models import ChatMessage, ChatSession, User
from app.rag.retriever import retrieve_context


async def chat(db: Session, user: User, message: str, session_id: int | None) -> dict:
    session: ChatSession | None = None
    if session_id is not None:
        session = db.get(ChatSession, session_id)
        if session is None or session.user_id != user.id:
            raise HTTPException(status_code=404, detail="Chat session not found")
    if session is None:
        session = ChatSession(user_id=user.id, title=message[:60])
        db.add(session)
        db.commit()
        db.refresh(session)

    history = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.id.desc())
        .limit(20)
        .all()
    )
    history.reverse()

    context = retrieve_context(message)
    system = INSTRUCTOR_SYSTEM.format(
        context=context or "No reference material retrieved."
    )
    messages = [{"role": m.role, "content": m.content} for m in history]
    messages.append({"role": "user", "content": message})

    reply = await get_llm_client().complete(system, messages)

    db.add(ChatMessage(session_id=session.id, role="user", content=message))
    db.add(ChatMessage(session_id=session.id, role="assistant", content=reply))
    db.commit()

    return {"session_id": session.id, "reply": reply}

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.llm.client import get_llm_client
from app.llm.prompts import INSTRUCTOR_SYSTEM
from app.models import ChatMessage, ChatSession, User
from app.rag.retriever import retrieve_context

# Below this, treat the turn as a follow-up rather than a new question. Real
# follow-ups are short ("more examples", "why?", "and for task 1?").
_ELLIPTICAL_WORDS = 8


def _retrieval_query(history: list[ChatMessage], message: str) -> str:
    """The text to embed when retrieving reference material for this turn.

    A follow-up carries no topic of its own, so embedding it alone retrieves
    arbitrary chunks — and the system prompt tells the model to lean on
    whatever comes back. Fold in the previous user turn so the query keeps the
    subject the student is actually asking about.
    """
    if len(message.split()) >= _ELLIPTICAL_WORDS:
        return message
    prior = [m.content for m in history if m.role == "user"]
    if not prior:
        return message
    return f"{prior[-1]}\n{message}"


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

    context = retrieve_context(_retrieval_query(history, message))
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

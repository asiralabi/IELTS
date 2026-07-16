from sqlalchemy.orm import Session

from app.agents.feedback import summarize_performance
from app.llm.client import get_llm_client
from app.llm.prompts import WEAKNESS_SYSTEM
from app.models import User, WeaknessProfile


async def analyze(db: Session, user: User) -> dict:
    summary = summarize_performance(db, user)
    profile = await get_llm_client().complete_json(
        WEAKNESS_SYSTEM,
        [{"role": "user", "content": f"Aggregated student results:\n{summary}"}],
        required_keys=("grammar", "vocabulary", "details"),
    )
    row = (
        db.query(WeaknessProfile).filter(WeaknessProfile.user_id == user.id).first()
    )
    if row is None:
        row = WeaknessProfile(user_id=user.id, profile=profile)
        db.add(row)
    else:
        row.profile = profile
    db.commit()
    return profile

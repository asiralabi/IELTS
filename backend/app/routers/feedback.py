"""Pilot feedback: what a tester says, and the address to answer them at.

The box lives on the landing page, so this route is deliberately public --
requiring a login to report "the register button did nothing" would lose
exactly the reports worth having.
"""

import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth import get_optional_user
from app.config import settings
from app.database import get_db
from app.models import Feedback, User
from app.schemas import FeedbackCreate, FeedbackOut

router = APIRouter(prefix="/feedback", tags=["feedback"])

# Long enough to identify a browser, short enough that a spoofed 8KB header
# cannot be used to fill the table. The column is 400 too.
_UA_MAX = 400
_LIST_MAX = 500


@router.post("", response_model=FeedbackOut, status_code=status.HTTP_201_CREATED)
async def submit_feedback(
    payload: FeedbackCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
) -> Feedback:
    """Record one note. No login required; a session is used when there is one."""
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="Feedback message is empty.")

    # A signed-in sender's account address wins over whatever the field holds:
    # the account one is verified by a password, the typed one is not, and a
    # tester typing a colleague's address would otherwise misattribute the note.
    email = user.email if user is not None else str(payload.email)

    entry = Feedback(
        user_id=user.id if user is not None else None,
        email=email,
        message=message,
        rating=payload.rating,
        page=payload.page,
        user_agent=(request.headers.get("user-agent") or "")[:_UA_MAX] or None,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.get("", response_model=list[FeedbackOut])
async def list_feedback(
    limit: int = 100,
    db: Session = Depends(get_db),
    x_admin_token: str = Header(default=""),
) -> list[Feedback]:
    """Read the pilot inbox, newest first. Guarded by a shared token.

    There is no admin role in this app, and inventing one to read a pilot's
    feedback would be more machinery than the feature is worth. An unset
    FEEDBACK_ADMIN_TOKEN closes the route rather than opening it: a
    deployment nobody configured must not hand a stranger every tester's
    email address.
    """
    expected = settings.feedback_admin_token
    if not expected:
        raise HTTPException(
            status_code=403,
            detail="Feedback listing is disabled: set FEEDBACK_ADMIN_TOKEN.",
        )
    # compare_digest, not ==: a plain comparison returns as soon as two bytes
    # differ, which leaks the token one character at a time to a patient caller.
    #
    # 🔬 Encoded to BYTES first, live 2026-09-06: compare_digest on `str` raises
    # TypeError the moment either side holds a non-ASCII character, and headers
    # reach us decoded as latin-1 — so `X-Admin-Token: café` came back 500
    # "Internal Server Error" instead of 403. A wrong guess must look like a
    # wrong guess, not like a way to make the server fall over.
    if not secrets.compare_digest(x_admin_token.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(status_code=403, detail="Invalid admin token.")

    return (
        db.query(Feedback)
        .order_by(Feedback.created_at.desc(), Feedback.id.desc())
        .limit(max(1, min(limit, _LIST_MAX)))
        .all()
    )

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.auth import (
    _DUMMY_HASH,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.database import get_db
from app.config import settings
from app.models import Consent, User
from app.schemas import DeleteAccountRequest, RefreshRequest, Token, UserCreate, UserOut
from app.services.account import delete_user_data, export_user_data

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(payload: UserCreate, db: Session = Depends(get_db)) -> User:
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=409, detail="Email already registered")
    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        target_band=payload.target_band,
    )
    db.add(user)
    db.flush()
    db.add(Consent(user_id=user.id, policy_version=settings.legal_policy_version))
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
async def login(
    form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)
) -> Token:
    user = db.query(User).filter(User.email == form.username).first()
    if user is None:
        verify_password(form.password, _DUMMY_HASH)
    if user is None or not verify_password(form.password, user.hashed_password):
        raise HTTPException(
            status_code=401,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=401, detail="User is inactive")
    return Token(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )


@router.post("/refresh", response_model=Token)
async def refresh(payload: RefreshRequest, db: Session = Depends(get_db)) -> Token:
    data = decode_token(payload.refresh_token)
    if data.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type")
    try:
        user = db.get(User, int(data["sub"]))
    except (KeyError, TypeError, ValueError):
        user = None
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return Token(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.get("/me/export")
async def export_me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Everything Oratio holds about the signed-in student, as JSON."""
    return export_user_data(db, user)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_me(
    payload: DeleteAccountRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Erase the account and all of its data. Asks for the password again, so
    a token left in an unlocked browser cannot erase someone's history."""
    if not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=403, detail="Password is incorrect")
    delete_user_data(db, user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

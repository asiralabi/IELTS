from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


# Checked against when the email is unknown, so a miss costs the same bcrypt
# time as a wrong password and response timing cannot reveal who has an account.
_DUMMY_HASH = bcrypt.hashpw(b"oratio-timing-equaliser", bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], hashed.encode("utf-8"))
    except ValueError:
        return False


_GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")
_google_keys = jwt.PyJWKClient("https://www.googleapis.com/oauth2/v3/certs")


def verify_google_credential(credential: str) -> dict:
    """The claims of a Google Sign-In ID token, or 401.

    The token is a JWT signed by Google. Checking the signature against
    Google's published keys, the audience against our client id, and the
    issuer is the whole of the verification; nothing is sent back to Google.
    """
    if not settings.google_client_id:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured")
    try:
        key = _google_keys.get_signing_key_from_jwt(credential)
        claims = jwt.decode(
            credential,
            key.key,
            algorithms=["RS256"],
            audience=settings.google_client_id,
            # A server clock a few seconds behind Google's would otherwise
            # reject a token Google issued a moment ago ("issued in the future").
            leeway=60,
        )
    except jwt.ExpiredSignatureError as exc:
        # Google's tokens live an hour; one held through a long consent step dies.
        raise HTTPException(status_code=401, detail="Your Google sign-in expired.") from exc
    except jwt.PyJWKClientConnectionError as exc:
        # Not the student's fault: we could not fetch Google's signing keys.
        raise HTTPException(
            status_code=503, detail="Couldn't reach Google just now. Please try again."
        ) from exc
    except (jwt.PyJWTError, jwt.PyJWKClientError) as exc:
        raise HTTPException(status_code=401, detail="Google sign-in failed") from exc
    if claims.get("iss") not in _GOOGLE_ISSUERS:
        raise HTTPException(status_code=401, detail="Google sign-in failed")
    return claims


def _create_token(user_id: int, token_type: str, expires_delta: timedelta) -> str:
    payload = {
        "sub": str(user_id),
        "type": token_type,
        "exp": datetime.now(timezone.utc) + expires_delta,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: int) -> str:
    return _create_token(
        user_id, "access", timedelta(minutes=settings.access_token_expire_minutes)
    )


def create_refresh_token(user_id: int) -> str:
    return _create_token(
        user_id, "refresh", timedelta(days=settings.refresh_token_expire_days)
    )


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    payload = decode_token(token)
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        user_id = None
    user = db.get(User, user_id) if user_id is not None else None
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


# Same bearer scheme, but `auto_error=False` so a missing header is None
# instead of a 401 raised before the route ever runs.
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


def get_optional_user(
    token: str | None = Depends(oauth2_scheme_optional),
    db: Session = Depends(get_db),
) -> User | None:
    """The signed-in user, or None — for routes a stranger may also reach.

    `get_current_user` answers 401 to anyone without a token, which is right
    for a student's own work and wrong for the public feedback box: a visitor
    who never registered still has something worth hearing.

    A token that is present but bad is treated as anonymous rather than as an
    error. The alternative punishes the wrong person: a tester whose session
    expired in a tab left open overnight would have their message rejected
    with "Token expired" and no way to understand it. Nothing here is
    protected by that token — the identity only decorates a note the caller is
    already allowed to leave.
    """
    if not token:
        return None
    try:
        payload = decode_token(token)
    except HTTPException:
        return None
    if payload.get("type") != "access":
        return None
    user = db.get(User, int(payload["sub"]))
    return user if user is not None and user.is_active else None

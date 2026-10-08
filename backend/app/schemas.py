from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class UserCreate(BaseModel):
    email: EmailStr
    # 72 is bcrypt's limit; anything past it was silently ignored before.
    password: str = Field(min_length=8, max_length=72)
    full_name: str | None = Field(default=None, max_length=120)
    # Explicit consent to the Terms and Privacy Policy, required by the
    # Personal Data Protection Ordinance 2025 before any data is processed.
    accept_terms: bool = Field(default=False, validate_default=True)

    @field_validator("accept_terms")
    @classmethod
    def _must_accept(cls, value: bool) -> bool:
        if not value:
            raise ValueError("You need to accept the Terms and Privacy Policy to create an account")
        return value
    target_band: float | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    full_name: str | None
    target_band: float | None
    is_active: bool
    created_at: datetime


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class DeleteAccountRequest(BaseModel):
    password: str = Field(min_length=1, max_length=72)


class RefreshRequest(BaseModel):
    refresh_token: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: int | None = None


class ChatResponse(BaseModel):
    session_id: int
    reply: str


class ChatSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    created_at: datetime


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str
    created_at: datetime


class FeedbackCreate(BaseModel):
    email: EmailStr
    message: str = Field(min_length=1, max_length=4000)
    # Optional on purpose: a tester with a bug to report should not have to
    # rate the product first, and a forced rating is a rating nobody means.
    rating: int | None = Field(default=None, ge=1, le=5)
    page: str | None = Field(default=None, max_length=200)


class FeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None
    email: EmailStr
    message: str
    rating: int | None
    page: str | None
    # Exposed on purpose: it is the field that turns "the timer sits on top of
    # the essay box" into a reproducible bug. Stored but unexposed, the column
    # was dead weight -- nobody reading the inbox could see it.
    user_agent: str | None
    created_at: datetime

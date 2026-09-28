from typing import Optional
from uuid import UUID
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, model_validator

MIN_PASSWORD_LENGTH = 8


class UserCreate(BaseModel):
    email: EmailStr
    username: str
    password: str = Field(min_length=MIN_PASSWORD_LENGTH)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class PublicUserOut(BaseModel):
    """What anyone may see about a user. Never add private fields here."""

    model_config = {"from_attributes": True}

    id: UUID
    username: str
    avatar_url: Optional[str] = None
    created_at: datetime


class UserOut(PublicUserOut):
    """The signed-in user's own account, as returned by auth routes."""

    email: EmailStr


class Token(BaseModel):
    token: str
    token_type: str = "bearer"
    user: UserOut


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH)


class MessageResponse(BaseModel):
    message: str

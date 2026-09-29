from typing import Optional
from uuid import UUID
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

MIN_PASSWORD_LENGTH = 8


class UserCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"email": "ada@example.com", "username": "ada", "password": "correct-horse"}]
        }
    )

    email: EmailStr
    username: str
    password: str = Field(min_length=MIN_PASSWORD_LENGTH)


class UserLogin(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"examples": [{"email": "ada@example.com", "password": "correct-horse"}]}
    )

    email: EmailStr
    password: str


_USER_OUT_EXAMPLE = {
        "id": "5f0c6a7e-1b2d-4c3e-9f80-a1b2c3d4e5f6",
        "username": "ada",
        "avatar_url": None,
        "created_at": "2026-09-01T12:00:00Z",
        "email": "ada@example.com",
        "is_librarian": False,
    }


class PublicUserOut(BaseModel):
    """What anyone may see about a user. Never add private fields here."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "5f0c6a7e-1b2d-4c3e-9f80-a1b2c3d4e5f6",
                    "username": "ada",
                    "avatar_url": None,
                    "created_at": "2026-09-01T12:00:00Z",
                }
            ]
        },
    )

    id: UUID
    username: str
    avatar_url: Optional[str] = None
    created_at: datetime


class UserOut(PublicUserOut):
    """The signed-in user's own account, as returned by auth routes."""

    model_config = ConfigDict(json_schema_extra={"examples": [_USER_OUT_EXAMPLE]})

    email: EmailStr
    # Decides what the frontend renders; the API enforces it (require_librarian).
    is_librarian: bool = False


class Token(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"token": "eyJhbGciOiJIUzI1NiJ9…", "token_type": "bearer", "user": _USER_OUT_EXAMPLE}]
        }
    )

    token: str
    token_type: str = "bearer"
    user: UserOut


class ForgotPasswordRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"email": "ada@example.com"}]})

    email: EmailStr


class ResetPasswordRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"examples": [{"token": "the-token-from-the-emailed-link", "new_password": "battery-staple"}]}
    )

    token: str
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH)


class MessageResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"message": "Password has been reset."}]})

    message: str

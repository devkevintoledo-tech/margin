import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class AuthProvider(str, enum.Enum):
    email = "email"
    google = "google"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    avatar_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    auth_provider: Mapped[AuthProvider] = mapped_column(
        Enum(AuthProvider, name="auth_provider_enum"), nullable=False
    )
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        server_default=text("now()"),
        nullable=False,
    )

    # Relationships
    shelves: Mapped[list["Shelf"]] = relationship("Shelf", back_populates="user", cascade="all, delete-orphan")  # noqa: F821
    threads: Mapped[list["Thread"]] = relationship("Thread", back_populates="user", cascade="all, delete-orphan")  # noqa: F821
    posts: Mapped[list["Post"]] = relationship("Post", back_populates="user", cascade="all, delete-orphan")  # noqa: F821
    votes: Mapped[list["Vote"]] = relationship("Vote", back_populates="user", cascade="all, delete-orphan")  # noqa: F821

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Thread(Base):
    __tablename__ = "threads"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    work_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("works.id", ondelete="CASCADE"), nullable=True, index=True
    )
    genre_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("genres.id", ondelete="CASCADE"), nullable=True, index=True
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        server_default=text("now()"),
        nullable=False,
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="threads")  # noqa: F821
    work: Mapped["Work | None"] = relationship("Work", back_populates="threads")  # noqa: F821
    genre: Mapped["Genre | None"] = relationship("Genre", back_populates="threads")  # noqa: F821
    posts: Mapped[list["Post"]] = relationship("Post", back_populates="thread", cascade="all, delete-orphan")  # noqa: F821
    votes: Mapped[list["Vote"]] = relationship("Vote", back_populates="thread", cascade="all, delete-orphan")  # noqa: F821

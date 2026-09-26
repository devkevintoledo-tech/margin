import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Thread(Base):
    __tablename__ = "threads"
    __table_args__ = (
        # A thread lives in a series room or a genre room, never both, never
        # neither. The migration adds these NOT VALID: ten legacy threads
        # orphaned by the works migration have no home at all.
        CheckConstraint(
            "(series_id IS NOT NULL) <> (genre_id IS NOT NULL)", name="ck_threads_one_home"
        ),
        # work_id is the optional book tag inside a series room.
        CheckConstraint(
            "work_id IS NULL OR series_id IS NOT NULL", name="ck_threads_tag_needs_series"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    series_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("series.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # The optional book tag: which book of the series this thread is about.
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
    series: Mapped["Series | None"] = relationship("Series", back_populates="threads")  # noqa: F821
    work: Mapped["Work | None"] = relationship("Work", back_populates="threads")  # noqa: F821
    genre: Mapped["Genre | None"] = relationship("Genre", back_populates="threads")  # noqa: F821
    posts: Mapped[list["Post"]] = relationship("Post", back_populates="thread", cascade="all, delete-orphan")  # noqa: F821
    votes: Mapped[list["Vote"]] = relationship("Vote", back_populates="thread", cascade="all, delete-orphan")  # noqa: F821

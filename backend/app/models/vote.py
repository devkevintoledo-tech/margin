import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Vote(Base):
    """One user's vote on one thread or one post.

    A cleared vote is a deleted row, never a stored 0 — that keeps `value` a
    two-valued check constraint and avoids introducing an enum type.
    """

    __tablename__ = "votes"
    __table_args__ = (
        CheckConstraint("value IN (-1, 1)", name="ck_vote_value"),
        CheckConstraint(
            "(thread_id IS NOT NULL) <> (post_id IS NOT NULL)",
            name="ck_vote_exactly_one_target",
        ),
        # Partial uniques make one-vote-per-user-per-item a database guarantee.
        Index(
            "uq_vote_user_thread",
            "user_id",
            "thread_id",
            unique=True,
            postgresql_where=text("thread_id IS NOT NULL"),
        ),
        Index(
            "uq_vote_user_post",
            "user_id",
            "post_id",
            unique=True,
            postgresql_where=text("post_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    thread_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("threads.id", ondelete="CASCADE"), nullable=True, index=True
    )
    post_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), nullable=True, index=True
    )
    value: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        server_default=text("now()"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        server_default=text("now()"),
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="votes")  # noqa: F821
    thread: Mapped["Thread | None"] = relationship("Thread", back_populates="votes")  # noqa: F821
    post: Mapped["Post | None"] = relationship("Post", back_populates="votes")  # noqa: F821

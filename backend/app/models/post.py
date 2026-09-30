import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    thread_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("threads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("posts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
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
    # Its own column, not `updated_at`: votes change `score` with a Core
    # update, which fires `updated_at`'s onupdate — every voted post would
    # look edited.
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # A deleted post is a tombstone: content erased, row and replies kept.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    thread: Mapped["Thread"] = relationship("Thread", back_populates="posts")  # noqa: F821
    user: Mapped["User"] = relationship("User", back_populates="posts")  # noqa: F821
    parent: Mapped["Post | None"] = relationship("Post", remote_side="Post.id", back_populates="replies")
    replies: Mapped[list["Post"]] = relationship("Post", back_populates="parent")
    votes: Mapped[list["Vote"]] = relationship("Vote", back_populates="post", cascade="all, delete-orphan")  # noqa: F821

import uuid
from datetime import datetime

from sqlalchemy import (
    DDL, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, PrimaryKeyConstraint, String, Text,
    UniqueConstraint, Uuid, column, event, table, text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

INFERENCE_SOURCES = ("open_library", "google", "catalog")


class Genre(Base):
    """A taxonomy entry. Exactly two levels: a parent (a discussion room) or a
    subgenre of one. Rows are written by ``scripts.sync_genres`` from
    ``app/data/genres.yaml``; an entry that leaves the file is retired, not deleted."""

    __tablename__ = "genres"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("genres.id"), nullable=True, index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    works: Mapped[list["Work"]] = relationship("Work", back_populates="genre")  # noqa: F821
    threads: Mapped[list["Thread"]] = relationship("Thread", back_populates="genre")  # noqa: F821


class GenreVote(Base):
    """One reader tagging one book with one genre. Withdrawing deletes the row."""

    __tablename__ = "genre_votes"
    __table_args__ = (UniqueConstraint("user_id", "work_id", "genre_id", name="uq_genre_votes_user_work_genre"),)

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    work_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("works.id", ondelete="CASCADE"), nullable=False, index=True
    )
    genre_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("genres.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class GenreInference(Base):
    """What one ingest source's mapping produced for a work. No roll-up at rest;
    ``source`` lets one path replace its own rows without erasing another's."""

    __tablename__ = "genre_inferences"
    __table_args__ = (
        PrimaryKeyConstraint("work_id", "genre_id", "source", name="pk_genre_inferences"),
        CheckConstraint(
            "source IN ('open_library', 'google', 'catalog')", name="ck_genre_inferences_source"
        ),
    )

    work_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("works.id", ondelete="CASCADE"), nullable=False)
    genre_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("genres.id"), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)


class WorkGenre(Base):
    """Derived summary. ``services/genres.recompute`` is the only writer."""

    __tablename__ = "work_genres"
    __table_args__ = (
        PrimaryKeyConstraint("work_id", "genre_id", name="pk_work_genres"),
        Index("ix_work_genres_genre_score", "genre_id", text("score DESC")),
    )

    work_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("works.id", ondelete="CASCADE"), nullable=False)
    genre_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("genres.id"), nullable=False)
    direct_votes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # readers who voted exactly this
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # distinct readers, subgenres rolled up
    inferred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # it, or a subgenre, is inferred
    vetoed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


# The effective-genre rule (spec §4.6), in one place. Readers' genres when any
# reader voted a live, unvetoed genre; otherwise the inferred ones. Vetoed and
# retired genres never appear. Executed verbatim by the migration and by the
# create_all listener below. No `%` characters: DDL() would format them.
EFFECTIVE_WORK_GENRES_VIEW = """
CREATE VIEW effective_work_genres AS
WITH voted AS (
    SELECT DISTINCT wg.work_id
    FROM work_genres wg JOIN genres g ON g.id = wg.genre_id
    WHERE wg.score > 0 AND NOT wg.vetoed AND g.retired_at IS NULL
)
SELECT wg.work_id, wg.genre_id, wg.score,
       CASE WHEN v.work_id IS NOT NULL THEN 'readers' ELSE 'inferred' END AS source
FROM work_genres wg
JOIN genres g ON g.id = wg.genre_id AND g.retired_at IS NULL
LEFT JOIN voted v ON v.work_id = wg.work_id
WHERE NOT wg.vetoed
  AND ((v.work_id IS NOT NULL AND wg.score > 0) OR (v.work_id IS NULL AND wg.inferred))
"""

event.listen(Base.metadata, "after_create", DDL(EFFECTIVE_WORK_GENRES_VIEW))
event.listen(Base.metadata, "before_drop", DDL("DROP VIEW IF EXISTS effective_work_genres"))

# For queries only: not a Table in Base.metadata, so create_all never makes it a table.
effective_work_genres = table(
    "effective_work_genres",
    column("work_id", Uuid),
    column("genre_id", Uuid),
    column("score", Integer),
    column("source", Text),
)

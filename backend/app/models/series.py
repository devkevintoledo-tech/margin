import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class SeriesSource(str, enum.Enum):
    """Where the grouping came from: an Open Library tag, or nothing (a singleton)."""

    openlibrary = "openlibrary"
    heuristic = "heuristic"


class SeriesKind(str, enum.Enum):
    series = "series"
    # A series of one. It exists so every book has exactly one room and one page
    # template; the page shows no series chrome for it.
    singleton = "singleton"


class Series(Base):
    """The discussion home: one room per saga, as r/redrising.

    Mirrors ``works`` on purpose — ``canonical_key`` for recognising the same
    series later, ``merged_into_id`` as a tombstone so a promoted singleton's
    URL keeps resolving.
    """

    __tablename__ = "series"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_series_source_external_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    source: Mapped[SeriesSource] = mapped_column(
        Enum(SeriesSource, name="series_source_enum"), nullable=False
    )
    # The normalized tag ("franchise:red rising") or "singleton:<work id>".
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    canonical_key: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    kind: Mapped[SeriesKind] = mapped_column(
        Enum(SeriesKind, name="series_kind_enum"), nullable=False
    )
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("series.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        onupdate=datetime.utcnow,
        nullable=False,
    )

    works: Mapped[list["Work"]] = relationship(  # noqa: F821
        "Work", back_populates="series", foreign_keys="Work.series_id"
    )
    threads: Mapped[list["Thread"]] = relationship("Thread", back_populates="series")  # noqa: F821

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.series import SeriesProvenance


class CatalogRelease(Base):
    """One loaded catalog release (spec §6.1). The highest version is the catalog's."""

    __tablename__ = "catalog_releases"

    version: Mapped[str] = mapped_column(String(32), primary_key=True)  # "2026.10.1"
    manifest: Mapped[dict] = mapped_column(JSONB, nullable=False)
    loaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class MembershipConfidence(str, enum.Enum):
    high = "high"
    medium = "medium"
    low = "low"


class SeriesMember(Base):
    """A work's place in a series: the order a room lists its books in.

    A work is a member of every series the catalog knows it in — *Mort* is in
    Discworld and in its Death sub-series — while ``works.series_id`` stays
    the one room its discussion lives in.
    """

    __tablename__ = "series_members"

    series_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("series.id", ondelete="CASCADE"), primary_key=True
    )
    work_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("works.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    # Numeric so a novella sits at 2.5; null for unnumbered members and collections.
    position: Mapped[float | None] = mapped_column(Numeric(asdecimal=False), nullable=True)
    provenance: Mapped[SeriesProvenance] = mapped_column(
        Enum(SeriesProvenance, name="series_provenance_enum"), nullable=False
    )
    confidence: Mapped[MembershipConfidence] = mapped_column(
        Enum(MembershipConfidence, name="membership_confidence_enum"), nullable=False
    )


class WorkAlias(Base):
    """An Open Library work id that now names another work: a merge loser or an OL redirect."""

    __tablename__ = "work_aliases"

    ol_work_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    work_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("works.id", ondelete="CASCADE"), nullable=False, index=True
    )

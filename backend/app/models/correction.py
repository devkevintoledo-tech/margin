import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CorrectionOp(str, enum.Enum):
    merge_works = "merge_works"
    split_work = "split_work"
    set_series = "set_series"
    set_position = "set_position"  # exports as set_series with a position
    remove_from_series = "remove_from_series"
    reject_series = "reject_series"
    rename_series = "rename_series"


def _now() -> datetime:
    # Python, not now(): Postgres' now() is constant within a transaction, and
    # "latest correction" has to order two fixes made in one.
    return datetime.now(timezone.utc)


class CatalogCorrection(Base):
    """One librarian fix: what it did, why, how it exports, and how to undo it."""

    __tablename__ = "catalog_corrections"
    __table_args__ = (
        CheckConstraint("(override IS NULL) = (runtime_only_reason IS NOT NULL)",
                        name="ck_catalog_corrections_export_state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    op: Mapped[CorrectionOp] = mapped_column(Enum(CorrectionOp, name="correction_op_enum"), nullable=False)
    # App ids the op acted on, as strings.
    payload: Mapped[dict] = mapped_column(JSONB(none_as_null=True), nullable=False)
    # The §5.4 entries this fix exports as, in order; null = runtime-only.
    override: Mapped[list | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    runtime_only_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    work_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("works.id", ondelete="SET NULL"), nullable=True, index=True
    )
    series_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("series.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=text("clock_timestamp()"), nullable=False
    )
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reverted_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)

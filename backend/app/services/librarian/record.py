"""Writing and reading the corrections log."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CatalogCorrection, CorrectionOp, MembershipConfidence, Series, SeriesMember, SeriesProvenance, User, Work,
)
from app.services.librarian.errors import Conflict, Invalid, NotFound

# Corrections whose subject is a series; every other op's subject is a work.
SERIES_SUBJECT_OPS = (CorrectionOp.rename_series, CorrectionOp.reject_series)


def clean_reason(reason: str | None) -> str:
    cleaned = (reason or "").strip()
    if not cleaned:
        raise Invalid("Say why: a reason is required.")
    return cleaned


def live_work(work: Work | None) -> Work:
    if work is None:
        raise NotFound("Unknown book.")
    if work.merged_into_id is not None:
        raise Conflict(f"{work.title} was merged into another book; reload the page.")
    return work


def live_series(series: Series | None) -> Series:
    if series is None:
        raise NotFound("Unknown series.")
    if series.merged_into_id is not None:
        raise Conflict(f"{series.name} was merged into another series; reload the page.")
    return series


def ids(items) -> list[str]:
    return [str(i) for i in items]


def uuids(strings) -> list[UUID]:
    return [UUID(s) for s in strings]


def member_state(m: SeriesMember) -> dict:
    return {"series_id": str(m.series_id), "work_id": str(m.work_id), "position": m.position,
            "provenance": m.provenance.value, "confidence": m.confidence.value}


def restore_member(state: dict) -> SeriesMember:
    return SeriesMember(series_id=UUID(state["series_id"]), work_id=UUID(state["work_id"]),
                        position=state["position"], provenance=SeriesProvenance(state["provenance"]),
                        confidence=MembershipConfidence(state["confidence"]))


async def record(db: AsyncSession, *, op: CorrectionOp, user: User, reason: str, payload: dict,
                 entries: list[dict] | None, runtime_only_reason: str | None, snapshot: dict | None = None,
                 work: Work | None = None, series: Series | None = None) -> CatalogCorrection:
    correction = CatalogCorrection(
        op=op, user_id=user.id, reason=reason, payload=payload, override=entries,
        runtime_only_reason=runtime_only_reason, snapshot=snapshot,
        work_id=work.id if work is not None else None, series_id=series.id if series is not None else None,
    )
    db.add(correction)
    await db.flush()
    return correction


async def latest_for_subject(db: AsyncSession, correction: CatalogCorrection) -> CatalogCorrection | None:
    """The newest unreverted fix on the same subject: its work, or its series for
    rename and dissolve."""
    query = select(CatalogCorrection).where(CatalogCorrection.reverted_at.is_(None))
    if correction.op in SERIES_SUBJECT_OPS:
        if correction.series_id is None:
            return None
        query = query.where(CatalogCorrection.series_id == correction.series_id,
                            CatalogCorrection.op.in_(SERIES_SUBJECT_OPS))
    else:
        if correction.work_id is None:
            return None
        query = query.where(CatalogCorrection.work_id == correction.work_id)
    query = query.order_by(CatalogCorrection.created_at.desc(), CatalogCorrection.id.desc()).limit(1)
    return (await db.execute(query)).scalar_one_or_none()

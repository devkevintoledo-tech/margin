"""Librarian genre fixes (spec 2026-09-29 §7.2). The corrections log's only writer
stays this package, so the merge path's veto re-pointing lives here too."""

from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CatalogCorrection, CorrectionOp, Genre, User, Work
from app.services import genres as genres_service
from app.services.librarian.errors import Conflict, Invalid
from app.services.librarian.record import clean_reason, live_work, locked, record


async def repoint_vetoes(db: AsyncSession, source_id: UUID, target_id: UUID) -> None:
    """A merged book's live vetoes keep holding on the survivor."""
    await db.execute(text("""
        UPDATE catalog_corrections
        SET work_id = CAST(:dst AS uuid),
            payload = jsonb_set(payload, '{work_id}', to_jsonb(CAST(CAST(:dst AS uuid) AS text)))
        WHERE op = 'veto_genre' AND reverted_at IS NULL AND work_id = :src"""),
        {"src": source_id, "dst": target_id})


RUNTIME_ONLY = "the pipeline has no genre overrides"


async def live_veto(db, work_id, genre_id) -> CatalogCorrection | None:
    return (await db.execute(select(CatalogCorrection).where(
        CatalogCorrection.op == CorrectionOp.veto_genre, CatalogCorrection.reverted_at.is_(None),
        CatalogCorrection.work_id == work_id,
        CatalogCorrection.payload["genre_id"].astext == str(genre_id)))).scalars().first()


async def veto_genre(db, user: User, work: Work, genre: Genre, *, reason: str) -> CatalogCorrection:
    """Hide a genre on a book from every reader. Votes are kept, so undo
    restores the book exactly; the veto only ever sets ``reverted_at``."""
    reason = clean_reason(reason)
    work = live_work(await locked(db, work))
    if genre.retired_at is not None:
        raise Invalid(f"{genre.name} is no longer in the genre list.")
    if await live_veto(db, work.id, genre.id) is not None:
        raise Conflict(f"{genre.name} is already vetoed on {work.title}.")
    correction = await record(
        db, op=CorrectionOp.veto_genre, user=user, reason=reason,
        payload={"work_id": str(work.id), "genre_id": str(genre.id)},
        entries=None, runtime_only_reason=RUNTIME_ONLY, work=work,
    )
    await genres_service.recompute(db, [work.id])
    return correction

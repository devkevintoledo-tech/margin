"""Librarian tools (spec §7). Thin: the services decide, these map errors."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Book, CatalogCorrection, Genre, Series, SeriesKind, User, Work
from app.schemas.librarian import (
    CorrectionOut, DissolveIn, EditionOut, MergeIn, MergePreviewOut, MoveIn, PositionIn, RemoveIn, RenameIn,
    SeriesHit, SplitIn, VetoIn,
)
from app.services import librarian
from app.services.auth import require_librarian
from app.services.librarian.errors import LibrarianError
from app.services.librarian.undo import undoable
from app.services.works import canonical_work

router = APIRouter(prefix="/librarian", tags=["librarian"])


async def _run(call):
    try:
        return await call
    except LibrarianError as exc:
        detail = exc.message if exc.consequences is None else {
            "message": exc.message, "consequences": exc.consequences}
        raise HTTPException(status_code=exc.status_code, detail=detail) from None


async def _work(db: AsyncSession, work_id: UUID) -> Work:
    work = await db.get(Work, work_id)
    if work is None:
        raise HTTPException(status_code=404, detail="Unknown book.")
    return work


async def _series(db: AsyncSession, series_id: UUID) -> Series:
    series = await db.get(Series, series_id)
    if series is None:
        raise HTTPException(status_code=404, detail="Unknown series.")
    return series


async def correction_out(db: AsyncSession, c: CatalogCorrection) -> CorrectionOut:
    user = await db.get(User, c.user_id)
    room_slug = subject = None
    if c.work_id is not None and (work := await db.get(Work, c.work_id)) is not None:
        work = await canonical_work(db, work)
        subject, room_slug = work.title, (await db.get(Series, work.series_id)).slug
    elif c.series_id is not None and (series := await db.get(Series, c.series_id)) is not None:
        subject, room_slug = series.name, series.slug
    return CorrectionOut(
        id=c.id, op=c.op, reason=c.reason, created_at=c.created_at, user=user.username,
        exportable=c.override is not None, runtime_only_reason=c.runtime_only_reason, undoable=await undoable(db, c),
        reverted_at=c.reverted_at, room_slug=room_slug, subject=subject,
    )


_CREATED = {"response_model": CorrectionOut, "status_code": status.HTTP_201_CREATED}


@router.post("/works/{work_id}/merge", **_CREATED)
async def merge_work(work_id: UUID, body: MergeIn, db: AsyncSession = Depends(get_db),
                     user: User = Depends(require_librarian)):
    source, target = await _work(db, work_id), await _work(db, body.into_work_id)
    c = await _run(librarian.merge(db, user, source, target, reason=body.reason, confirm=body.confirm))
    return await correction_out(db, c)


@router.get("/works/{work_id}/merge-preview", response_model=MergePreviewOut)
async def preview_merge(work_id: UUID, into: UUID = Query(...), db: AsyncSession = Depends(get_db),
                        user: User = Depends(require_librarian)):
    """Both books as their pages show them, and what merging ``work_id`` into
    ``into`` would move. Swapping the two ids swaps the survivor."""
    source, target = await _work(db, work_id), await _work(db, into)
    return await _run(librarian.merge_preview(db, source, target))


@router.post("/works/{work_id}/split", **_CREATED)
async def split_work(work_id: UUID, body: SplitIn, db: AsyncSession = Depends(get_db),
                     user: User = Depends(require_librarian)):
    work = await _work(db, work_id)
    c = await _run(librarian.split(db, user, work, body.edition_ids, reason=body.reason, confirm=body.confirm))
    return await correction_out(db, c)


@router.post("/works/{work_id}/move", **_CREATED)
async def move_work(work_id: UUID, body: MoveIn, db: AsyncSession = Depends(get_db),
                    user: User = Depends(require_librarian)):
    work = await _work(db, work_id)
    series = await _series(db, body.series_id) if body.series_id is not None else None
    c = await _run(librarian.set_series(db, user, work, series=series, new_series_name=body.new_series_name,
                                        position=body.position, reason=body.reason))
    return await correction_out(db, c)


@router.get("/works/{work_id}/editions", response_model=list[EditionOut])
async def work_editions(work_id: UUID, db: AsyncSession = Depends(get_db),
                        user: User = Depends(require_librarian)):
    work = await _work(db, work_id)
    rows = (await db.execute(select(Book).where(Book.work_id == work.id)
                             .order_by(Book.published_year.nulls_last(), Book.title))).scalars().all()
    return [EditionOut(id=b.id, title=b.title, publisher=b.publisher, published_year=b.published_year,
                       language=b.language, source=b.source) for b in rows]


@router.post("/series/{series_id}/position", **_CREATED)
async def position_in_series(series_id: UUID, body: PositionIn, db: AsyncSession = Depends(get_db),
                             user: User = Depends(require_librarian)):
    room, work = await _series(db, series_id), await _work(db, body.work_id)
    c = await _run(librarian.set_position(db, user, room, work, body.position, reason=body.reason))
    return await correction_out(db, c)


@router.post("/series/{series_id}/remove", **_CREATED)
async def remove_from_series(series_id: UUID, body: RemoveIn, db: AsyncSession = Depends(get_db),
                             user: User = Depends(require_librarian)):
    room, work = await _series(db, series_id), await _work(db, body.work_id)
    c = await _run(librarian.remove_from_series(db, user, room, work, reason=body.reason))
    return await correction_out(db, c)


@router.post("/series/{series_id}/rename", **_CREATED)
async def rename(series_id: UUID, body: RenameIn, db: AsyncSession = Depends(get_db),
                 user: User = Depends(require_librarian)):
    series = await _series(db, series_id)
    c = await _run(librarian.rename_series(db, user, series, body.name, reason=body.reason))
    return await correction_out(db, c)


@router.post("/series/{series_id}/dissolve", **_CREATED)
async def dissolve(series_id: UUID, body: DissolveIn, db: AsyncSession = Depends(get_db),
                   user: User = Depends(require_librarian)):
    series = await _series(db, series_id)
    c = await _run(librarian.reject_series(db, user, series, reason=body.reason))
    return await correction_out(db, c)


@router.get("/corrections", response_model=list[CorrectionOut])
async def list_corrections(
    runtime_only: bool | None = None, work_id: UUID | None = None, series_id: UUID | None = None,
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db), user: User = Depends(require_librarian),
):
    query = select(CatalogCorrection)
    if runtime_only is not None:
        query = query.where(CatalogCorrection.override.is_(None) if runtime_only
                            else CatalogCorrection.override.is_not(None))
    if work_id is not None:
        query = query.where(CatalogCorrection.work_id == work_id)
    if series_id is not None:
        query = query.where(CatalogCorrection.series_id == series_id)
    rows = (await db.execute(query.order_by(CatalogCorrection.created_at.desc(), CatalogCorrection.id.desc())
                             .limit(limit).offset(offset))).scalars().all()
    return [await correction_out(db, c) for c in rows]


@router.post("/corrections/{correction_id}/revert", response_model=CorrectionOut)
async def revert_correction(correction_id: UUID, db: AsyncSession = Depends(get_db),
                            user: User = Depends(require_librarian)):
    c = await db.get(CatalogCorrection, correction_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Unknown fix.")
    await _run(librarian.revert(db, user, c))
    return await correction_out(db, c)


@router.get("/series-search", response_model=list[SeriesHit])
async def series_search(q: str = Query(..., min_length=1), db: AsyncSession = Depends(get_db),
                        user: User = Depends(require_librarian)):
    """Move targets: real, live, top-level series. Singletons, dissolved series and
    sub-series are never offered (see set_series)."""
    escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    books = (select(func.count()).select_from(Work)
             .where(Work.series_id == Series.id, Work.merged_into_id.is_(None))
             .correlate(Series).scalar_subquery())
    rows = (await db.execute(
        select(Series, books.label("books")).where(
            Series.name.ilike(f"%{escaped}%", escape="\\"), Series.kind == SeriesKind.series,
            Series.dissolved_at.is_(None), Series.merged_into_id.is_(None), Series.parent_series_id.is_(None),
        ).order_by(Series.name).limit(10)
    )).all()
    return [SeriesHit(id=s.id, slug=s.slug, name=s.name, book_count=n) for s, n in rows]


@router.post("/works/{work_id}/genres/{slug}/veto", **_CREATED)
async def veto_work_genre(work_id: UUID, slug: str, body: VetoIn, db: AsyncSession = Depends(get_db),
                          user: User = Depends(require_librarian)):
    """Hide a genre on a book from readers, with a reason. Undo via the corrections log."""
    work = await _work(db, work_id)
    genre = (await db.execute(select(Genre).where(Genre.slug == slug))).scalar_one_or_none()
    if genre is None:
        raise HTTPException(status_code=404, detail="Unknown genre.")
    c = await _run(librarian.veto_genre(db, user, work, genre, reason=body.reason))
    return await correction_out(db, c)

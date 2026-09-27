from __future__ import annotations

from typing import NamedTuple
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Series, SeriesMember, Shelf, Thread, User, Work
from app.schemas.series import SeriesOut, SeriesThreadCreate, SeriesWorkOut
from app.schemas.thread import ThreadOut, ThreadSummary
from app.services.auth import get_current_user, get_current_user_optional
from app.services.enrichment import enrich_work
from app.services.series import get_series_by_slug
from app.services.threads import create_thread, thread_out, thread_summaries
from app.services.works import canonical_work, load_work_presentation

router = APIRouter(prefix="/series", tags=["series"])

# First view of a series pays for Google Books on its members, which used to
# happen on each work page. Capped so one huge series cannot stall a request.
_ENRICH_CAP = 10
_MAX_NESTING = 5


async def _series_or_404(db: AsyncSession, slug: str) -> Series:
    series = await get_series_by_slug(db, slug)
    if series is None:
        raise HTTPException(status_code=404, detail="Series not found")
    return series


class _Member(NamedTuple):
    work: Work
    position: float | None
    subseries: Series | None  # None: a member of the room itself


async def _members(db: AsyncSession, series: Series) -> list[_Member]:
    """The room's books in reading order: sub-series, then position, then publication.

    Each book is placed by its membership in the deepest series of the room's
    tree, so *Mistborn* lists under its own heading inside the Cosmere. Books
    in the room directly come first; sub-series follow in order of their
    earliest book. Runtime series have no memberships and keep publication
    order.
    """
    works = list((await db.execute(
        select(Work).where(Work.series_id == series.id, Work.merged_into_id.is_(None))
    )).scalars().all())
    tree, depth, frontier = {series.id: series}, {series.id: 0}, [series.id]
    for level in range(1, _MAX_NESTING + 1):
        children = (await db.execute(select(Series).where(
            Series.parent_series_id.in_(frontier), Series.merged_into_id.is_(None)))).scalars().all()
        frontier = [c.id for c in children if c.id not in tree]
        for child in children:
            tree.setdefault(child.id, child)
            depth.setdefault(child.id, level)
        if not frontier:
            break

    placed: dict[UUID, SeriesMember] = {}
    if works:
        rows = (await db.execute(select(SeriesMember).where(
            SeriesMember.work_id.in_([w.id for w in works]), SeriesMember.series_id.in_(list(tree))
        ))).scalars().all()
        for m in rows:
            best = placed.get(m.work_id)
            if best is None or (depth[m.series_id], tree[m.series_id].name) > (depth[best.series_id], tree[best.series_id].name):
                placed[m.work_id] = m

    members = []
    for w in works:
        m = placed.get(w.id)
        child = tree[m.series_id] if m is not None and m.series_id != series.id else None
        members.append(_Member(w, m.position if m is not None else None, child))

    def book_order(m: _Member):
        return (m.position is None, m.position or 0.0,
                m.work.first_publish_year is None, m.work.first_publish_year or 0, m.work.title)

    earliest: dict[UUID, tuple] = {}
    for m in members:
        if m.subseries is not None:
            year = m.work.first_publish_year or 9999
            earliest[m.subseries.id] = min(earliest.get(m.subseries.id, (9999, m.subseries.name)), (year, m.subseries.name))

    def group_order(m: _Member):
        return (0, ()) if m.subseries is None else (1, earliest[m.subseries.id])

    return sorted(members, key=lambda m: (group_order(m), book_order(m)))


@router.get("/{slug}", response_model=SeriesOut)
async def get_series(
    slug: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
) -> SeriesOut:
    """A tombstoned slug answers with the survivor; the client redirects on
    seeing a different ``slug`` than it asked for."""
    series = await _series_or_404(db, slug)
    members = await _members(db, series)
    works = [m.work for m in members]
    for work in [w for w in works if w.enriched_at is None][:_ENRICH_CAP]:
        await enrich_work(db, work)
        # Still unenriched means Google failed (enrich_work swallows it so the
        # next view retries). Stop: during an outage every member would fail
        # the same way, and the page would pay for each one on every view.
        if work.enriched_at is None:
            break

    presentation = await load_work_presentation(db, [w.id for w in works])
    shelves: dict[UUID, str] = {}
    if current_user is not None and works:
        rows = await db.execute(
            select(Shelf.work_id, Shelf.status).where(
                Shelf.user_id == current_user.id, Shelf.work_id.in_([w.id for w in works])
            )
        )
        shelves = {row.work_id: row.status for row in rows}

    first = presentation.get(works[0].id) if works else None
    return SeriesOut(
        slug=series.slug,
        name=series.name,
        kind=series.kind,
        description=first.description if first else None,
        works=[
            SeriesWorkOut(
                id=w.id,
                title=w.title,
                author=w.author,
                first_publish_year=w.first_publish_year,
                cover_url=presentation[w.id].cover_url if w.id in presentation else None,
                shelf_status=shelves.get(w.id),
                position=m.position,
                subseries=m.subseries.name if m.subseries is not None else None,
            )
            for m in members
            for w in [m.work]
        ],
    )


@router.get("/{slug}/threads", response_model=list[ThreadSummary])
async def get_series_threads(
    slug: str,
    work_id: UUID | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    series = await _series_or_404(db, slug)
    conditions = [Thread.series_id == series.id]
    if work_id is not None:
        conditions.append(Thread.work_id == work_id)
    return await thread_summaries(
        db, *conditions, current_user=current_user, limit=limit, offset=offset
    )


@router.post("/{slug}/threads", response_model=ThreadOut, status_code=status.HTTP_201_CREATED)
async def create_series_thread(
    slug: str,
    payload: SeriesThreadCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ThreadOut:
    series = await _series_or_404(db, slug)
    work_id = None
    if payload.work_id is not None:
        # Canonicalize first: a stale tab can hold a merged member's id.
        work = await db.get(Work, payload.work_id)
        work = await canonical_work(db, work) if work is not None else None
        if work is None or work.series_id != series.id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="That book is not part of this series.",
            )
        work_id = work.id
    thread = await create_thread(
        db, user=current_user, title=payload.title, body=payload.body,
        series_id=series.id, work_id=work_id,
    )
    return thread_out(thread, author=current_user.username)

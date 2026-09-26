from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Series, Shelf, Thread, User, Work
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


async def _series_or_404(db: AsyncSession, slug: str) -> Series:
    series = await get_series_by_slug(db, slug)
    if series is None:
        raise HTTPException(status_code=404, detail="Series not found")
    return series


async def _members(db: AsyncSession, series: Series) -> list[Work]:
    stmt = (
        select(Work)
        .where(Work.series_id == series.id, Work.merged_into_id.is_(None))
        .order_by(Work.first_publish_year.asc().nulls_last(), Work.title)
    )
    return list((await db.execute(stmt)).scalars().all())


@router.get("/{slug}", response_model=SeriesOut)
async def get_series(
    slug: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
) -> SeriesOut:
    """A tombstoned slug answers with the survivor; the client redirects on
    seeing a different ``slug`` than it asked for."""
    series = await _series_or_404(db, slug)
    works = await _members(db, series)
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
            )
            for w in works
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

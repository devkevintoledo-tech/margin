from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.book import GenreOut, WorkOut, work_out
from app.schemas.thread import ThreadSummary
from app.models.genre import Genre  # type: ignore[import]
from app.models.thread import Thread  # type: ignore[import]
from app.models.work import Work, WorkKind  # type: ignore[import]
from app.services.auth import get_current_user_optional
from app.services.threads import thread_summaries
from app.services.works import load_work_presentation

router = APIRouter(prefix="/genres", tags=["genres"])


async def _get_genre_or_404(slug: str, db: AsyncSession) -> Genre:
    stmt = select(Genre).where(Genre.slug == slug)
    genre = (await db.execute(stmt)).scalars().first()
    if genre is None:
        raise HTTPException(status_code=404, detail="Genre not found")
    return genre


@router.get("/", response_model=list[GenreOut])
async def list_genres(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Genre).order_by(Genre.name))
    return result.scalars().all()


@router.get("/{slug}", response_model=GenreOut)
async def get_genre(slug: str, db: AsyncSession = Depends(get_db)):
    return await _get_genre_or_404(slug, db)


@router.get("/{slug}/works", response_model=list[WorkOut])
async def get_genre_works(
    slug: str,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    genre = await _get_genre_or_404(slug, db)
    stmt = (
        select(Work)
        .where(
            Work.genre_id == genre.id,
            Work.kind == WorkKind.single,
            Work.merged_into_id.is_(None),  # tombstones are reachable, not listed
        )
        .order_by(Work.title)
        .limit(limit)
        .offset(offset)
    )
    works = (await db.execute(stmt)).scalars().all()
    presentation = await load_work_presentation(db, [w.id for w in works])
    return [work_out(w, presentation.get(w.id)) for w in works]


@router.get("/{slug}/threads", response_model=list[ThreadSummary])
async def get_genre_threads(
    slug: str,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user=Depends(get_current_user_optional),
):
    genre = await _get_genre_or_404(slug, db)
    return await thread_summaries(
        db, Thread.genre_id == genre.id, current_user=current_user, limit=limit, offset=offset
    )

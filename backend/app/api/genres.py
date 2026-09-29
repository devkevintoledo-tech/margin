from __future__ import annotations

from collections import defaultdict
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Genre, Thread, Work, WorkKind, effective_work_genres as ewg
from app.schemas.book import GenreWorkOut, work_out
from app.schemas.genre import GenreChild, GenreNode, GenreOut, GenreRef
from app.schemas.thread import ThreadSummary
from app.services.auth import get_current_user_optional
from app.services.threads import thread_summaries
from app.services.works import load_work_presentation

router = APIRouter(prefix="/genres", tags=["genres"])

_LISTED = (Work.kind == WorkKind.single, Work.merged_into_id.is_(None))  # tombstones are reachable, not listed


async def _get_genre_or_404(slug: str, db: AsyncSession) -> Genre:
    genre = (await db.execute(select(Genre).where(Genre.slug == slug))).scalars().first()
    if genre is None:
        raise HTTPException(status_code=404, detail="Genre not found")
    return genre


async def _room(db: AsyncSession, genre: Genre) -> Genre:
    """Subgenres have no rooms of their own (D9): their discussion is the parent's."""
    return await db.get(Genre, genre.parent_id) if genre.parent_id else genre


@router.get("/", response_model=list[GenreNode])
async def list_genres(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Genre).where(Genre.retired_at.is_(None))
                             .order_by(Genre.position, Genre.name))).scalars().all()
    children: dict[UUID, list[GenreRef]] = defaultdict(list)
    for g in rows:
        if g.parent_id is not None:
            children[g.parent_id].append(GenreRef(slug=g.slug, name=g.name))
    return [GenreNode(id=g.id, slug=g.slug, name=g.name, description=g.description, children=children[g.id])
            for g in rows if g.parent_id is None]


@router.get("/{slug}", response_model=GenreOut)
async def get_genre(slug: str, db: AsyncSession = Depends(get_db)):
    genre = await _get_genre_or_404(slug, db)
    room = await _room(db, genre)
    kids = [] if genre.parent_id else (await db.execute(
        select(Genre).where(Genre.parent_id == genre.id, Genre.retired_at.is_(None))
        .order_by(Genre.position, Genre.name))).scalars().all()
    counts = dict((await db.execute(
        select(ewg.c.genre_id, func.count()).join(Work, Work.id == ewg.c.work_id)
        .where(ewg.c.genre_id.in_([k.id for k in kids]), *_LISTED).group_by(ewg.c.genre_id))).all()) if kids else {}
    return GenreOut(
        id=genre.id, slug=genre.slug, name=genre.name, description=genre.description,
        parent=GenreRef(slug=room.slug, name=room.name) if room.id != genre.id else None,
        children=[GenreChild(slug=k.slug, name=k.name, book_count=counts.get(k.id, 0)) for k in kids],
        retired=genre.retired_at is not None, room_slug=room.slug,
    )


@router.get("/{slug}/works", response_model=list[GenreWorkOut])
async def get_genre_works(
    slug: str,
    db: AsyncSession = Depends(get_db),
    sort: Literal["top", "title"] = Query("top"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """Books whose effective genres include this one; a parent includes its
    subgenres' books through the roll-up. ``top`` puts voted books first."""
    genre = await _get_genre_or_404(slug, db)
    order = ((ewg.c.score.desc(), Work.readinglog_count.desc(), Work.title, Work.id) if sort == "top"
             else (Work.title, Work.id))
    rows = (await db.execute(
        select(Work, ewg.c.source).join(ewg, ewg.c.work_id == Work.id)
        .where(ewg.c.genre_id == genre.id, *_LISTED).order_by(*order).limit(limit).offset(offset))).all()
    presentation = await load_work_presentation(db, [w.id for w, _ in rows])
    return [GenreWorkOut(**work_out(w, presentation.get(w.id)).model_dump(), inferred=source == "inferred")
            for w, source in rows]


@router.get("/{slug}/threads", response_model=list[ThreadSummary])
async def get_genre_threads(
    slug: str,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user=Depends(get_current_user_optional),
):
    room = await _room(db, await _get_genre_or_404(slug, db))
    return await thread_summaries(
        db, Thread.genre_id == room.id, current_user=current_user, limit=limit, offset=offset
    )

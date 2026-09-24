from __future__ import annotations

from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
# Through the package, per CLAUDE.md: app.models.__init__ imports every model,
# so Base.metadata is complete without importing Base directly for its side
# effect.
from app.models import Book, Genre, Post, Shelf, Thread, User, Vote, Work, WorkKind
from app.schemas.book import ShelfIn, ShelfOut, WorkOut, work_out
from app.schemas.thread import ThreadSummary
from app.services import google_books
from app.services.auth import get_current_user, get_current_user_optional
from app.services.works import (
    canonical_work,
    load_work_presentation,
    resolve_editions,
)

router = APIRouter(prefix="/works", tags=["works"])

# Fields copied verbatim from the normalized Google Books dict onto an edition.
_EDITION_FIELDS = (
    "title", "subtitle", "author", "cover_url", "description", "publisher",
    "published_date", "published_year", "isbn_13", "page_count",
    "average_rating", "ratings_count", "language", "categories",
    "maturity_rating", "info_link", "preview_link",
)


async def _get_work_or_404(work_id: UUID, db: AsyncSession) -> Work:
    work = await db.get(Work, work_id)
    if work is None:
        raise HTTPException(status_code=404, detail="Work not found")
    return await canonical_work(db, work)


async def _upsert_editions(
    db: AsyncSession, results: list[dict]
) -> tuple[list[Book], dict[UUID, UUID]]:
    """Upsert every volume as an edition; return them in relevance order.

    The second return value maps ``Book.id`` to the genre its categories imply.
    Genre belongs to the work, so the hint is passed through rather than stored
    on the edition.
    """
    slugs = {r["genre_slug"] for r in results if r.get("genre_slug")}
    genre_ids: dict[str, UUID] = {}
    if slugs:
        rows = (await db.execute(select(Genre.slug, Genre.id).where(Genre.slug.in_(slugs)))).all()
        genre_ids = {slug: gid for slug, gid in rows}

    editions: list[Book] = []
    hints: dict[UUID, UUID] = {}
    for item in results:
        ext_id = item.get("external_id")
        if not ext_id:
            continue

        stmt = select(Book).where(Book.source == "google_books", Book.external_id == ext_id)
        existing = (await db.execute(stmt)).scalars().first()

        if existing:
            for field in _EDITION_FIELDS:
                value = item.get(field)
                if value:  # only overwrite when Google gave us something
                    setattr(existing, field, value)
            edition = existing
        else:
            edition = Book(
                source="google_books",
                external_id=ext_id,
                **{f: item.get(f) for f in _EDITION_FIELDS},
            )
            db.add(edition)

        await db.flush()  # get generated id
        editions.append(edition)
        if item.get("genre_slug") in genre_ids:
            hints[edition.id] = genre_ids[item["genre_slug"]]

    return editions, hints


async def _to_work_outs(
    db: AsyncSession, works: list[Work], shelf_by_work: dict[UUID, str] | None = None
) -> list[WorkOut]:
    presentation = await load_work_presentation(db, [w.id for w in works])
    shelf_by_work = shelf_by_work or {}
    return [
        work_out(w, presentation.get(w.id), shelf_by_work.get(w.id)) for w in works
    ]


@router.get("/search", response_model=list[WorkOut])
async def search_works(
    q: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
):
    """Search Google Books, group the volumes into works, return one per work."""
    try:
        results = await google_books.search_books(q)
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Book search is temporarily unavailable. Please try again shortly.",
        ) from exc

    editions, genre_hints = await _upsert_editions(db, results)
    by_edition = await resolve_editions(db, editions, genre_hints)

    # A work takes the position of its first-seen edition, so Google's relevance
    # ranking still drives the page.
    ordered: list[Work] = []
    seen: set[UUID] = set()
    for edition in editions:
        work = by_edition.get(edition.id)
        if work is None or work.id in seen:
            continue
        seen.add(work.id)
        if work.kind is WorkKind.single:
            ordered.append(work)

    return await _to_work_outs(db, ordered)


@router.get("/{work_id}", response_model=WorkOut)
async def get_work(
    work_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_optional),
):
    work = await _get_work_or_404(work_id, db)
    shelf_by_work: dict[UUID, str] = {}
    if current_user is not None:
        stmt = select(Shelf.status).where(
            Shelf.user_id == current_user.id, Shelf.work_id == work.id
        )
        found = (await db.execute(stmt)).scalar_one_or_none()
        if found is not None:
            shelf_by_work[work.id] = found
    return (await _to_work_outs(db, [work], shelf_by_work))[0]


@router.get("/{work_id}/threads", response_model=list[ThreadSummary])
async def get_work_threads(
    work_id: UUID,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user=Depends(get_current_user_optional),
):
    work = await _get_work_or_404(work_id, db)
    if current_user is None:
        my_vote = literal(0).label("my_vote")
    else:
        # A correlated scalar subquery, not a LEFT JOIN: this query already
        # GROUP BYs to produce post_count, and a join would have to be folded
        # into that grouping.
        my_vote = func.coalesce(
            select(Vote.value)
            .where(Vote.thread_id == Thread.id, Vote.user_id == current_user.id)
            .scalar_subquery(),
            0,
        ).label("my_vote")

    stmt = (
        select(
            Thread.id,
            Thread.title,
            Thread.score,
            my_vote,
            Thread.work_id,
            Thread.created_at,
            User.username.label("author"),
            Genre.slug.label("genre_slug"),
            func.count(Post.id).label("post_count"),
        )
        .join(User, Thread.user_id == User.id)
        .outerjoin(Genre, Thread.genre_id == Genre.id)
        .outerjoin(Post, Post.thread_id == Thread.id)
        .where(Thread.work_id == work.id)
        .group_by(Thread.id, User.username, Genre.slug)
        .order_by(Thread.score.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(stmt)).all()
    return [ThreadSummary.model_validate(row) for row in rows]


@router.post("/{work_id}/shelf", response_model=ShelfOut, status_code=status.HTTP_201_CREATED)
async def add_to_shelf(
    work_id: UUID,
    payload: ShelfIn,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    work = await _get_work_or_404(work_id, db)

    stmt = select(Shelf).where(Shelf.user_id == current_user.id, Shelf.work_id == work.id)
    existing = (await db.execute(stmt)).scalars().first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Book already on shelf. Use PUT to update.",
        )

    shelf = Shelf(user_id=current_user.id, work_id=work.id, status=payload.status)
    db.add(shelf)
    await db.flush()
    return shelf


@router.put("/{work_id}/shelf", response_model=ShelfOut)
async def update_shelf(
    work_id: UUID,
    payload: ShelfIn,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    work = await _get_work_or_404(work_id, db)
    stmt = select(Shelf).where(Shelf.user_id == current_user.id, Shelf.work_id == work.id)
    shelf = (await db.execute(stmt)).scalars().first()
    if shelf is None:
        raise HTTPException(status_code=404, detail="Shelf entry not found")

    shelf.status = payload.status
    await db.flush()
    return shelf


@router.delete("/{work_id}/shelf", status_code=status.HTTP_204_NO_CONTENT)
async def remove_from_shelf(
    work_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    work = await _get_work_or_404(work_id, db)
    stmt = select(Shelf).where(Shelf.user_id == current_user.id, Shelf.work_id == work.id)
    shelf = (await db.execute(stmt)).scalars().first()
    if shelf is None:
        raise HTTPException(status_code=404, detail="Shelf entry not found")

    await db.delete(shelf)

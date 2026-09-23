from __future__ import annotations

from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.base import Base  # noqa: F401 — ensure metadata loaded
from app.schemas.book import BookOut, ShelfIn, ShelfOut
from app.schemas.thread import ThreadSummary
from app.services import google_books
from app.services.auth import get_current_user, get_current_user_optional

# ---------------------------------------------------------------------------
# Lazy model imports — models live in app/models/ but we reference them by
# class name to avoid circular import issues at module load time.
# ---------------------------------------------------------------------------
from app.models.book import Book  # type: ignore[import]
from app.models.genre import Genre  # type: ignore[import]  # noqa: F401
from app.models.post import Post  # type: ignore[import]
from app.models.shelf import Shelf  # type: ignore[import]
from app.models.thread import Thread  # type: ignore[import]
from app.models.user import User  # type: ignore[import]
from app.models.vote import Vote  # type: ignore[import]

router = APIRouter(prefix="/books", tags=["books"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_book_or_404(book_id: UUID, db: AsyncSession) -> Book:
    result = await db.get(Book, book_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return result


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/search", response_model=list[BookOut])
async def search_books(
    q: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
):
    """Search Google Books and upsert results into the local DB."""
    try:
        results = await google_books.search_books(q)
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        # Upstream throttling (keyless 429), outages, or network failures —
        # surface a clean 503 rather than an opaque 500.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Book search is temporarily unavailable. Please try again shortly.",
        ) from exc

    # Resolve genre slugs → ids in one pass (avoid N queries).
    slugs = {r["genre_slug"] for r in results if r.get("genre_slug")}
    genre_ids: dict[str, UUID] = {}
    if slugs:
        rows = (await db.execute(select(Genre.slug, Genre.id).where(Genre.slug.in_(slugs)))).all()
        genre_ids = {slug: gid for slug, gid in rows}

    # Fields copied verbatim from the normalized Google Books dict onto the model.
    enrich = (
        "title", "subtitle", "author", "cover_url", "description", "publisher",
        "published_date", "published_year", "isbn_13", "page_count",
        "average_rating", "ratings_count", "language", "categories",
        "maturity_rating", "info_link", "preview_link",
    )

    books: list[Book] = []
    for item in results:
        ext_id = item.get("external_id")
        if not ext_id:
            continue

        stmt = select(Book).where(Book.source == "google_books", Book.external_id == ext_id)
        existing = (await db.execute(stmt)).scalars().first()

        if existing:
            for field in enrich:
                value = item.get(field)
                if value:  # only overwrite when Google gave us something
                    setattr(existing, field, value)
            book = existing
        else:
            book = Book(
                source="google_books",
                external_id=ext_id,
                **{f: item.get(f) for f in enrich},
            )
            db.add(book)

        if book.genre_id is None and item.get("genre_slug") in genre_ids:
            book.genre_id = genre_ids[item["genre_slug"]]

        await db.flush()  # get generated id
        books.append(book)

    return books


@router.get("/{book_id}", response_model=BookOut)
async def get_book(
    book_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_optional),
):
    book = await _get_book_or_404(book_id, db)
    out = BookOut.model_validate(book)
    if current_user is not None:
        stmt = select(Shelf.status).where(
            Shelf.user_id == current_user.id,
            Shelf.book_id == book_id,
        )
        out.shelf_status = (await db.execute(stmt)).scalar_one_or_none()
    return out


@router.get("/{book_id}/threads", response_model=list[ThreadSummary])
async def get_book_threads(
    book_id: UUID,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user=Depends(get_current_user_optional),
):
    await _get_book_or_404(book_id, db)
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
            Thread.book_id,
            Thread.created_at,
            User.username.label("author"),
            Genre.slug.label("genre_slug"),
            func.count(Post.id).label("post_count"),
        )
        .join(User, Thread.user_id == User.id)
        .outerjoin(Genre, Thread.genre_id == Genre.id)
        .outerjoin(Post, Post.thread_id == Thread.id)
        .where(Thread.book_id == book_id)
        .group_by(Thread.id, User.username, Genre.slug)
        .order_by(Thread.score.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(stmt)).all()
    return [ThreadSummary.model_validate(row) for row in rows]


@router.post("/{book_id}/shelf", response_model=ShelfOut, status_code=status.HTTP_201_CREATED)
async def add_to_shelf(
    book_id: UUID,
    payload: ShelfIn,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    await _get_book_or_404(book_id, db)

    # Prevent duplicate shelf entries
    stmt = select(Shelf).where(
        Shelf.user_id == current_user.id,
        Shelf.book_id == book_id,
    )
    existing = (await db.execute(stmt)).scalars().first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Book already on shelf. Use PUT to update.",
        )

    shelf = Shelf(user_id=current_user.id, book_id=book_id, status=payload.status)
    db.add(shelf)
    await db.flush()
    return shelf


@router.put("/{book_id}/shelf", response_model=ShelfOut)
async def update_shelf(
    book_id: UUID,
    payload: ShelfIn,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    stmt = select(Shelf).where(
        Shelf.user_id == current_user.id,
        Shelf.book_id == book_id,
    )
    shelf = (await db.execute(stmt)).scalars().first()
    if shelf is None:
        raise HTTPException(status_code=404, detail="Shelf entry not found")

    shelf.status = payload.status
    await db.flush()
    return shelf


@router.delete("/{book_id}/shelf", status_code=status.HTTP_204_NO_CONTENT)
async def remove_from_shelf(
    book_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    stmt = select(Shelf).where(
        Shelf.user_id == current_user.id,
        Shelf.book_id == book_id,
    )
    shelf = (await db.execute(stmt)).scalars().first()
    if shelf is None:
        raise HTTPException(status_code=404, detail="Shelf entry not found")

    await db.delete(shelf)

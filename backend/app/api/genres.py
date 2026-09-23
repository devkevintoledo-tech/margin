from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.book import BookOut, GenreOut
from app.schemas.thread import ThreadSummary
from app.models.book import Book  # type: ignore[import]
from app.models.genre import Genre  # type: ignore[import]
from app.models.post import Post  # type: ignore[import]
from app.models.thread import Thread  # type: ignore[import]
from app.models.user import User  # type: ignore[import]
from app.models.vote import Vote  # type: ignore[import]
from app.services.auth import get_current_user_optional

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


@router.get("/{slug}/books", response_model=list[BookOut])
async def get_genre_books(
    slug: str,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    genre = await _get_genre_or_404(slug, db)
    stmt = (
        select(Book)
        .where(Book.genre_id == genre.id)
        .order_by(Book.title)
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{slug}/threads", response_model=list[ThreadSummary])
async def get_genre_threads(
    slug: str,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user=Depends(get_current_user_optional),
):
    genre = await _get_genre_or_404(slug, db)
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
            User.username.label("author"),
            Genre.slug.label("genre_slug"),
            func.count(Post.id).label("post_count"),
        )
        .join(User, Thread.user_id == User.id)
        .outerjoin(Genre, Thread.genre_id == Genre.id)
        .outerjoin(Post, Post.thread_id == Thread.id)
        .where(Thread.genre_id == genre.id)
        .group_by(Thread.id, User.username, Genre.slug)
        .order_by(Thread.score.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(stmt)).all()
    return [ThreadSummary.model_validate(row) for row in rows]

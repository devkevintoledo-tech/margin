"""Thread listing and creation shared by the series and genre rooms.

One query builds every thread list so the series feed, its per-book filter and
the genre feed can never drift in shape or ordering.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Genre, Post, Thread, User, Vote
from app.schemas.thread import ThreadOut, ThreadSummary


async def thread_summaries(
    db: AsyncSession, *conditions, current_user: User | None, limit: int, offset: int
) -> list[ThreadSummary]:
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
        .where(*conditions)
        .group_by(Thread.id, User.username, Genre.slug)
        .order_by(Thread.score.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(stmt)).all()
    return [ThreadSummary.model_validate(row) for row in rows]


async def create_thread(
    db: AsyncSession,
    *,
    user: User,
    title: str,
    body: str | None = None,
    series_id: UUID | None = None,
    work_id: UUID | None = None,
    genre_id: UUID | None = None,
) -> Thread:
    thread = Thread(
        title=title, user_id=user.id, series_id=series_id, work_id=work_id, genre_id=genre_id
    )
    db.add(thread)
    await db.flush()
    # Optional opening post seeds the thread with its first message.
    if body:
        db.add(Post(thread_id=thread.id, user_id=user.id, content=body))
        await db.flush()
    await db.refresh(thread)
    return thread


def thread_out(
    thread: Thread, *, author: str | None, my_vote: int = 0, score: int | None = None
) -> ThreadOut:
    """Build from scalar columns — model_validate would lazy-load relationships."""
    return ThreadOut(
        id=thread.id,
        title=thread.title,
        user_id=thread.user_id,
        series_id=thread.series_id,
        work_id=thread.work_id,
        genre_id=thread.genre_id,
        score=thread.score if score is None else score,
        my_vote=my_vote,
        created_at=thread.created_at,
        author=author,
    )

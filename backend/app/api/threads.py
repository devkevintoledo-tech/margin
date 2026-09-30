from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.genre import Genre
from app.models.thread import Thread
from app.models.post import Post
from app.models.series import Series
from app.models.user import User
from app.models.vote import Vote
from app.models.work import Work
from app.schemas.series import SeriesRef
from app.services import threads as threads_service
from app.services.works import canonical_work
from app.schemas.thread import (
    PostOut,
    ThreadWorkRef,
    ThreadCreate,
    ThreadGenreRef,
    ThreadOut,
    VoteIn,
    post_out_from_orm,
)
from app.services.auth import get_current_user, get_current_user_optional
from app.services.votes import set_vote

router = APIRouter(prefix="/threads", tags=["threads"])


@router.post("/", response_model=ThreadOut, status_code=status.HTTP_201_CREATED)
async def create_thread(
    payload: ThreadCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ThreadOut:
    # ThreadCreate validator already enforces work XOR genre target.
    genre = None
    if payload.genre_slug and payload.genre_id is None:
        genre = (await db.execute(select(Genre).where(Genre.slug == payload.genre_slug))).scalars().first()
    elif payload.genre_id is not None:
        genre = await db.get(Genre, payload.genre_id)
    if (payload.genre_slug or payload.genre_id) and genre is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Genre not found")
    if genre is not None:
        # Rooms are parents only (spec D9); a subgenre's discussion is its parent's.
        if genre.parent_id is not None:
            parent = await db.get(Genre, genre.parent_id)
            raise HTTPException(status_code=422, detail=f"Discussion about {genre.name} happens in {parent.name}.")
        if genre.retired_at is not None:
            raise HTTPException(status_code=422, detail=f"{genre.name} is no longer in the genre list.")
    genre_id = genre.id if genre is not None else None

    # Resolve the work the same way every read path does. A stale client can
    # hold a merged work's id — tombstones exist precisely so those keep
    # working — and a thread stored against one would be invisible on both the
    # old and the new URL, because the listing canonicalizes before filtering.
    work_id = payload.work_id
    series_id: UUID | None = None
    if work_id is not None:
        work = await db.get(Work, work_id)
        if work is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Work not found"
            )
        work = await canonical_work(db, work)
        work_id, series_id = work.id, work.series_id

    thread = await threads_service.create_thread(
        db, user=current_user, title=payload.title, body=payload.body,
        series_id=series_id, work_id=work_id, genre_id=genre_id,
    )
    return threads_service.thread_out(thread, author=current_user.username)


class ThreadWithPosts(ThreadOut):
    # The work/genre a thread hangs off, so the client can render a link and a
    # path segment without a second round trip. These live here rather than on
    # ThreadOut because their names collide with the `Thread.work`/`.genre`
    # relationships, and ThreadOut is built by model_validate elsewhere.
    posts: list[PostOut] = []
    work: ThreadWorkRef | None = None
    genre: ThreadGenreRef | None = None
    series: SeriesRef | None = None


@router.get("/{id}", response_model=ThreadWithPosts)
async def get_thread(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
) -> ThreadWithPosts:
    result = await db.execute(select(Thread).where(Thread.id == id))
    thread = result.scalar_one_or_none()
    if thread is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")

    # One query for every post in the thread; assemble the reply tree in
    # Python so we never touch a lazy relationship.
    all_posts = (
        await db.execute(
            select(Post).where(Post.thread_id == id).order_by(Post.created_at)
        )
    ).scalars().all()

    # The caller's own votes: one scalar for the thread, one IN for every post,
    # so there is no per-post round trip and no lazy relationship is touched.
    my_vote = 0
    post_votes: dict[UUID, int] = {}
    if current_user is not None:
        my_vote = (
            await db.execute(
                select(Vote.value).where(
                    Vote.thread_id == id, Vote.user_id == current_user.id
                )
            )
        ).scalar_one_or_none() or 0
        post_ids = [p.id for p in all_posts]
        if post_ids:
            rows = (
                await db.execute(
                    select(Vote.post_id, Vote.value).where(
                        Vote.user_id == current_user.id, Vote.post_id.in_(post_ids)
                    )
                )
            ).all()
            post_votes = {row.post_id: row.value for row in rows}

    # Every username the page needs — the thread's author and each post's — in
    # one IN query. Reading `post.user.username` instead would lazy-load per
    # post, outside the greenlet.
    author_ids = {thread.user_id} | {p.user_id for p in all_posts}
    usernames = {
        row.id: row.username
        for row in (
            await db.execute(select(User.id, User.username).where(User.id.in_(author_ids)))
        ).all()
    }

    work_ref = None
    if thread.work_id is not None:
        work = (
            await db.execute(select(Work.id, Work.title).where(Work.id == thread.work_id))
        ).first()
        if work is not None:
            work_ref = ThreadWorkRef(id=work.id, title=work.title)

    genre_ref = None
    if thread.genre_id is not None:
        genre = (
            await db.execute(
                select(Genre.id, Genre.name, Genre.slug).where(Genre.id == thread.genre_id)
            )
        ).first()
        if genre is not None:
            genre_ref = ThreadGenreRef(id=genre.id, name=genre.name, slug=genre.slug)

    series_ref = None
    if thread.series_id is not None:
        row = (
            await db.execute(
                select(Series.slug, Series.name, Series.kind).where(Series.id == thread.series_id)
            )
        ).first()
        if row is not None:
            series_ref = SeriesRef(slug=row.slug, name=row.name, kind=row.kind)

    nodes = {
        post.id: post_out_from_orm(
            post,
            my_vote=post_votes.get(post.id, 0),
            author=usernames.get(post.user_id),
        )
        for post in all_posts
    }
    roots: list[PostOut] = []
    for post in all_posts:
        node = nodes[post.id]
        parent = nodes.get(post.parent_id) if post.parent_id else None
        if parent is not None:
            parent.replies.append(node)
        else:
            roots.append(node)

    # A tombstone is only worth showing while it holds live replies up. Replies
    # cannot nest further (2 levels), so pruning each root's replies first is
    # enough.
    for root in roots:
        root.replies = [r for r in root.replies if not r.deleted]
    roots = [r for r in roots if not r.deleted or r.replies]

    base = threads_service.thread_out(
        thread, author=usernames.get(thread.user_id), my_vote=my_vote
    )
    return ThreadWithPosts(
        **base.model_dump(),
        posts=roots,
        work=work_ref,
        genre=genre_ref,
        series=series_ref,
    )


@router.put("/{id}/vote", response_model=ThreadOut)
async def vote_thread(
    id: UUID,
    payload: VoteIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ThreadOut:
    thread = (
        await db.execute(select(Thread).where(Thread.id == id))
    ).scalar_one_or_none()
    if thread is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")

    score = await set_vote(
        db, user_id=current_user.id, thread_id=id, value=payload.value
    )
    await db.refresh(thread)
    return threads_service.thread_out(
        thread,
        author=(
            await db.execute(select(User.username).where(User.id == thread.user_id))
        ).scalar_one_or_none(),
        my_vote=payload.value,
        score=score,
    )

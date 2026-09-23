from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.genre import Genre
from app.models.thread import Thread
from app.models.post import Post
from app.models.user import User
from app.models.vote import Vote
from app.schemas.thread import PostOut, ThreadCreate, ThreadOut, VoteIn, post_out_from_orm
from app.services.auth import get_current_user, get_current_user_optional
from app.services.votes import set_vote

router = APIRouter(prefix="/threads", tags=["threads"])


@router.post("/", response_model=ThreadOut, status_code=status.HTTP_201_CREATED)
async def create_thread(
    payload: ThreadCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ThreadOut:
    # ThreadCreate validator already enforces book XOR genre target.
    genre_id = payload.genre_id
    if payload.genre_slug and genre_id is None:
        genre = (
            await db.execute(select(Genre).where(Genre.slug == payload.genre_slug))
        ).scalar_one_or_none()
        if genre is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Genre not found"
            )
        genre_id = genre.id

    thread = Thread(
        title=payload.title,
        user_id=current_user.id,
        book_id=payload.book_id,
        genre_id=genre_id,
    )
    db.add(thread)
    await db.flush()

    # Optional opening post seeds the thread with its first message.
    if payload.body:
        db.add(Post(thread_id=thread.id, user_id=current_user.id, content=payload.body))
        await db.flush()

    await db.refresh(thread)
    return ThreadOut.model_validate(thread)


class ThreadWithPosts(ThreadOut):
    posts: list[PostOut] = []


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

    nodes = {
        post.id: post_out_from_orm(post, my_vote=post_votes.get(post.id, 0))
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

    return ThreadWithPosts(
        id=thread.id,
        title=thread.title,
        user_id=thread.user_id,
        book_id=thread.book_id,
        genre_id=thread.genre_id,
        score=thread.score,
        my_vote=my_vote,
        created_at=thread.created_at,
        posts=roots,
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
    return ThreadOut(
        id=thread.id,
        title=thread.title,
        user_id=thread.user_id,
        book_id=thread.book_id,
        genre_id=thread.genre_id,
        score=score,
        my_vote=payload.value,
        created_at=thread.created_at,
    )

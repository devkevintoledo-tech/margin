from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.genre import Genre
from app.models.thread import Thread
from app.models.post import Post
from app.models.user import User
from app.schemas.thread import PostOut, ThreadCreate, ThreadOut, post_out_from_orm
from app.services.auth import get_current_user

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

    nodes = {post.id: post_out_from_orm(post) for post in all_posts}
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
        created_at=thread.created_at,
        posts=roots,
    )


@router.post("/{id}/upvote", response_model=ThreadOut)
async def upvote_thread(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ThreadOut:
    result = await db.execute(select(Thread).where(Thread.id == id))
    thread = result.scalar_one_or_none()
    if thread is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")
    thread.score += 1
    await db.flush()
    await db.refresh(thread)
    return ThreadOut.model_validate(thread)

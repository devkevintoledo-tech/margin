from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.post import Post
from app.models.user import User
from app.schemas.thread import PostCreate, PostOut, post_out_from_orm
from app.services.auth import get_current_user

router = APIRouter(prefix="/posts", tags=["posts"])


@router.post("/", response_model=PostOut, status_code=status.HTTP_201_CREATED)
async def create_post(
    payload: PostCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PostOut:
    if payload.parent_id is not None:
        # Verify parent exists and is a top-level post (parent_id must be None)
        parent_result = await db.execute(select(Post).where(Post.id == payload.parent_id))
        parent = parent_result.scalar_one_or_none()
        if parent is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parent post not found")
        if parent.parent_id is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Replies can only be made to top-level posts (2-level limit).",
            )

    post = Post(
        thread_id=payload.thread_id,
        user_id=current_user.id,
        parent_id=payload.parent_id,
        content=payload.content,
    )
    db.add(post)
    await db.flush()
    await db.refresh(post)
    return post_out_from_orm(post)


@router.post("/{id}/upvote", response_model=PostOut)
async def upvote_post(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PostOut:
    result = await db.execute(select(Post).where(Post.id == id))
    post = result.scalar_one_or_none()
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    post.score += 1
    await db.flush()
    await db.refresh(post)
    return post_out_from_orm(post)

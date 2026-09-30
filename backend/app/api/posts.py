from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.post import Post
from app.models.user import User
from app.models.vote import Vote
from app.schemas.thread import PostCreate, PostOut, PostUpdate, VoteIn, post_out_from_orm
from app.services import content as content_service
from app.services.auth import get_current_user
from app.services.votes import set_vote

router = APIRouter(prefix="/posts", tags=["posts"])


async def _post_or_404(db: AsyncSession, id: UUID) -> Post:
    post = (await db.execute(select(Post).where(Post.id == id))).scalar_one_or_none()
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    return post


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
    return post_out_from_orm(post, author=current_user.username)


@router.patch("/{id}", response_model=PostOut)
async def edit_post(
    id: UUID,
    payload: PostUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PostOut:
    post = await _post_or_404(db, id)
    try:
        post = await content_service.edit_post(db, post, current_user, payload.content)
    except content_service.NotAuthor:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only edit your own posts.")
    except content_service.AlreadyDeleted:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This post was deleted.")
    my_vote = (
        await db.execute(
            select(Vote.value).where(Vote.post_id == id, Vote.user_id == current_user.id)
        )
    ).scalar_one_or_none() or 0
    return post_out_from_orm(post, my_vote=my_vote, author=current_user.username)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_post(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    post = await _post_or_404(db, id)
    try:
        await content_service.delete_post(db, post, current_user)
    except content_service.NotAuthor:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only delete your own posts.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/{id}/vote", response_model=PostOut)
async def vote_post(
    id: UUID,
    payload: VoteIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PostOut:
    post = (await db.execute(select(Post).where(Post.id == id))).scalar_one_or_none()
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")

    await set_vote(db, user_id=current_user.id, post_id=id, value=payload.value)
    await db.refresh(post)
    # The voter is not necessarily the author, so resolve the author explicitly.
    author = (
        await db.execute(select(User.username).where(User.id == post.user_id))
    ).scalar_one_or_none()
    return post_out_from_orm(post, my_vote=payload.value, author=author)

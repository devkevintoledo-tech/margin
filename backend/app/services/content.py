"""Editing and deleting readers' own threads and posts.

Author-only, with no FastAPI types: routes map `NotAuthor` to 403 and
`AlreadyDeleted` to 409. A deletion is a tombstone — the text is erased and
`deleted_at` set, but the row (and its `user_id`, for later moderation) stays,
so replies keep their place in the tree.
"""

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Post, Thread, User


class NotAuthor(Exception):
    """The caller did not write this."""


class AlreadyDeleted(Exception):
    """The target is a tombstone and cannot change."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _tombstone(post: Post, when: datetime) -> None:
    post.content = ""
    post.deleted_at = when


async def edit_post(db: AsyncSession, post: Post, user: User, content: str) -> Post:
    if post.user_id != user.id:
        raise NotAuthor
    if post.deleted_at is not None:
        raise AlreadyDeleted
    # Conditional, not an ORM flush of the loaded row: a delete that commits
    # between our read and this write would otherwise get its erased text
    # written back into the tombstone. Row locking makes a concurrent delete
    # finish first; the WHERE then matches nothing.
    edited = (
        await db.execute(
            update(Post)
            .where(Post.id == post.id, Post.deleted_at.is_(None))
            .values(content=content, edited_at=_now())
            .returning(Post.id)
            .execution_options(synchronize_session=False)
        )
    ).scalar_one_or_none()
    if edited is None:
        raise AlreadyDeleted
    await db.refresh(post)
    return post


async def delete_post(db: AsyncSession, post: Post, user: User) -> None:
    # Ownership first: a stranger learns nothing from an already-deleted post.
    if post.user_id != user.id:
        raise NotAuthor
    if post.deleted_at is not None:
        return
    _tombstone(post, _now())
    await db.flush()


async def delete_thread(db: AsyncSession, thread: Thread, user: User) -> None:
    if thread.user_id != user.id:
        raise NotAuthor
    if thread.deleted_at is not None:
        return
    when = _now()
    thread.title = ""
    thread.deleted_at = when
    # The opener is the earliest top-level post. There is no opener flag, so
    # it only goes with the thread when the thread's author wrote it.
    opener = (
        await db.execute(
            select(Post)
            .where(Post.thread_id == thread.id, Post.parent_id.is_(None))
            .order_by(Post.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    if opener is not None and opener.user_id == user.id and opener.deleted_at is None:
        _tombstone(opener, when)
    await db.flush()

"""Setting a user's vote on a thread or a post.

The rule lives here so both routers apply it identically: one row per user per
target, `value` in (-1, 1), and a cleared vote is a deleted row. The target's
denormalized `score` moves by the delta in the same transaction.
"""

from uuid import UUID

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.post import Post
from app.models.thread import Thread
from app.models.vote import Vote


async def set_vote(
    db: AsyncSession,
    *,
    user_id: UUID,
    thread_id: UUID | None = None,
    post_id: UUID | None = None,
    value: int,
) -> int:
    """Set `user_id`'s vote on the target to `value` (-1, 0 or 1).

    `0` clears the vote. Idempotent: setting the value already stored writes
    nothing. Returns the target's new score.
    """
    if (thread_id is None) == (post_id is None):
        raise ValueError("Exactly one of thread_id or post_id must be provided.")

    target_model = Thread if thread_id is not None else Post
    target_id = thread_id if thread_id is not None else post_id
    target_col = Vote.thread_id if thread_id is not None else Vote.post_id

    # Two concurrent requests from the same user both read "no vote" and both
    # insert; the partial unique index rejects the loser. The insert runs in a
    # savepoint so that failure doesn't poison the request transaction, and one
    # retry is enough — afterwards the index guarantees a row exists to update.
    for attempt in (1, 2):
        existing = (
            await db.execute(
                select(Vote).where(Vote.user_id == user_id, target_col == target_id)
            )
        ).scalar_one_or_none()
        old = existing.value if existing else 0
        delta = value - old
        if delta == 0:
            break

        if existing is None:
            # A Core insert, not db.add(): a rolled-back savepoint would leave
            # an ORM-added object pending in the session for the retry to trip
            # over. Column defaults still apply.
            try:
                async with db.begin_nested():
                    await db.execute(
                        insert(Vote).values(
                            user_id=user_id,
                            thread_id=thread_id,
                            post_id=post_id,
                            value=value,
                        )
                    )
            except IntegrityError:
                if attempt == 2:
                    raise
                continue
        elif value == 0:
            await db.delete(existing)
            await db.flush()
        else:
            existing.value = value
            await db.flush()

        # SQL-expression update, never `obj.score += delta`, so concurrent
        # votes on the same target cannot lose each other.
        await db.execute(
            update(target_model)
            .where(target_model.id == target_id)
            .values(score=target_model.score + delta)
        )
        break

    return (
        await db.execute(
            select(target_model.score).where(target_model.id == target_id)
        )
    ).scalar_one()

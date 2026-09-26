"""Give every existing work a series and every work thread its room.

Run once between the two series migrations:

    alembic upgrade e7b3c9d2a1f4
    python -m scripts.backfill_series
    alembic upgrade head

Idempotent. Needs HTTP only to re-fetch the subjects of the few works whose
tags were stored space-joined, which is why this is a script rather than a
migration. Threads with neither a work nor a genre (orphaned by the works
migration) are reported and left alone; rehoming them is a product decision.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models import SeriesKind, Thread, Work, WorkSource
from app.services import open_library
from app.services.series import assign_series
from app.services.series_identity import SUBJECT_SEPARATOR, join_subjects
from app.services.works import canonical_work


def _needs_refetch(work: Work) -> bool:
    subjects = (work.subjects or "").lower()
    return (
        work.source is WorkSource.openlibrary
        and SUBJECT_SEPARATOR not in subjects
        and ("series:" in subjects or "franchise:" in subjects)
    )


async def backfill(session: AsyncSession, *, fetch: bool = True, commit: bool = True) -> dict[str, int]:
    stats = dict.fromkeys(("refetched", "series", "singletons", "tombstones", "threads", "orphans"), 0)
    works = (await session.execute(select(Work).order_by(Work.created_at))).scalars().all()
    live = [w for w in works if w.merged_into_id is None]

    if fetch:
        for work in live:
            if _needs_refetch(work):
                subjects = await open_library.fetch_work_subjects(work.external_id)
                if subjects:
                    work.subjects = join_subjects(subjects)
                    stats["refetched"] += 1
        await session.flush()

    for work in live:
        series = await assign_series(session, work)
        stats["series" if series.kind is SeriesKind.series else "singletons"] += 1

    for work in works:
        if work.merged_into_id is not None and work.series_id is None:
            work.series_id = (await canonical_work(session, work)).series_id
            stats["tombstones"] += 1
    await session.flush()

    result = await session.execute(
        update(Thread)
        .where(Thread.series_id.is_(None), Thread.work_id.is_not(None))
        .values(
            series_id=select(Work.series_id).where(Work.id == Thread.work_id).scalar_subquery()
        )
        .execution_options(synchronize_session=False)
    )
    stats["threads"] = result.rowcount or 0
    stats["orphans"] = await session.scalar(
        select(func.count()).select_from(Thread).where(
            Thread.series_id.is_(None), Thread.genre_id.is_(None)
        )
    ) or 0

    if commit:
        await session.commit()
    return stats


async def main() -> None:
    async with AsyncSessionLocal() as session:
        stats = await backfill(session)
    print(stats)


if __name__ == "__main__":
    asyncio.run(main())

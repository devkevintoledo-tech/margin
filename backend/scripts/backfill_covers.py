"""One-time repair for works ingested before local-first search.

Three idempotent passes:

1. Fill ``ol_cover_id`` and the popularity counts on every Open Library work,
   by looking each one up by title and author.
2. HEAD every stored ``books.cover_url`` and null Google's placeholders.
3. Re-pick each work's representative edition, so one with real art wins.

Heuristic works are skipped — they keep their existing upgrade path,
``python -m scripts.resolve_works --upgrade``.

Run with::

    python -m scripts.backfill_covers
    # or:
    docker compose exec backend python -m scripts.backfill_covers
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models import Book, Work, WorkSource
from app.services import covers, open_library
from app.services.series_identity import join_subjects
from app.services.works import _refresh_work


async def backfill(session: AsyncSession, commit: bool = True) -> dict[str, int]:
    """Repair covers and popularity in place. Returns a summary of counts."""
    works = (
        await session.execute(
            select(Work).where(
                Work.source == WorkSource.openlibrary,
                Work.merged_into_id.is_(None),
            )
        )
    ).scalars().all()

    works_updated = 0
    for work in works:
        found = await open_library.search_works(
            f"{work.title} {work.author}", limit=5
        )
        match = next((w for w in found if w.key == work.external_id), None)
        if match is None:
            continue
        work.ol_cover_id = match.cover_id or work.ol_cover_id
        work.ol_edition_count = match.edition_count
        work.readinglog_count = match.readinglog_count
        work.ratings_count = match.ratings_count
        work.subjects = join_subjects(match.subjects) or work.subjects
        works_updated += 1

    editions = (
        await session.execute(select(Book).where(Book.cover_url.is_not(None)))
    ).scalars().all()
    real = await covers.verify([e.cover_url for e in editions])

    covers_nulled = 0
    touched: set = set()
    for edition in editions:
        if edition.cover_url not in real:
            edition.cover_url = None
            covers_nulled += 1
            if edition.work_id:
                touched.add(edition.work_id)

    await session.flush()

    for work_id in touched:
        work = await session.get(Work, work_id)
        if work is not None:
            await _refresh_work(session, work)

    await session.flush()
    if commit:
        await session.commit()

    return {
        "works_scanned": len(works),
        "works_updated": works_updated,
        "covers_scanned": len(editions),
        "covers_nulled": covers_nulled,
        "representatives_repicked": len(touched),
    }


async def main() -> None:
    async with AsyncSessionLocal() as session:
        summary = await backfill(session)
    print(
        "Cover backfill complete: "
        f"{summary['works_scanned']} works scanned, "
        f"{summary['works_updated']} updated, "
        f"{summary['covers_scanned']} covers checked, "
        f"{summary['covers_nulled']} placeholders removed, "
        f"{summary['representatives_repicked']} representatives re-picked."
    )


if __name__ == "__main__":
    asyncio.run(main())

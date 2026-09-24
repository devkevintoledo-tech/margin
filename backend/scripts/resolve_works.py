"""Backfill: give every edition a work, then move threads and shelves onto it.

Alembic must not make HTTP calls, so identity resolution lives here, between
the two migrations. Run after migration 1 and before migration 2::

    docker compose exec backend python -m scripts.resolve_works

Idempotent: a second run resolves nothing. ``--upgrade`` re-attempts works that
fell back to the heuristic tier (because Open Library was unreachable or had no
record at the time) and merges each one into its Open Library work on success::

    docker compose exec backend python -m scripts.resolve_works --upgrade

Before running migration 2, confirm the gate is clean::

    SELECT count(*) FROM threads WHERE book_id IS NOT NULL AND work_id IS NULL;
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models import Book, Shelf, Thread, Work, WorkSource
from app.services import open_library
from app.services.works import merge_works, resolve_editions

# Google Books pages are 20 volumes; one Open Library call covers a batch.
_BATCH = 20


async def resolve_all(session: AsyncSession, *, upgrade: bool = False) -> dict[str, int]:
    """Resolve unresolved editions, link threads and shelves, optionally upgrade.

    Returns a summary dict with ``editions_resolved``, ``threads_linked``,
    ``shelves_linked`` and ``works_upgraded``.
    """
    editions = (
        await session.execute(select(Book).where(Book.work_id.is_(None)))
    ).scalars().all()

    for start in range(0, len(editions), _BATCH):
        await resolve_editions(session, editions[start : start + _BATCH])
    await session.flush()

    threads_linked = await _link_through_editions(session, Thread)
    shelves_linked = await _link_through_editions(session, Shelf)

    upgraded = await _upgrade_heuristic_works(session) if upgrade else 0

    await session.commit()
    return {
        "editions_resolved": len(editions),
        "threads_linked": threads_linked,
        "shelves_linked": shelves_linked,
        "works_upgraded": upgraded,
    }


async def _link_through_editions(session: AsyncSession, model) -> int:
    """Copy ``work_id`` onto rows that still only know their edition."""
    result = await session.execute(
        update(model)
        .where(model.work_id.is_(None), model.book_id.is_not(None))
        .values(
            work_id=select(Book.work_id).where(Book.id == model.book_id).scalar_subquery()
        )
    )
    return result.rowcount or 0


async def _upgrade_heuristic_works(session: AsyncSession) -> int:
    """Re-attempt Open Library for heuristic works; merge each success."""
    works = (
        await session.execute(
            select(Work).where(
                Work.source == WorkSource.heuristic, Work.merged_into_id.is_(None)
            )
        )
    ).scalars().all()

    upgraded = 0
    for work in works:
        editions = (
            await session.execute(select(Book).where(Book.work_id == work.id))
        ).scalars().all()

        isbns = [e.isbn_13 for e in editions if e.isbn_13]
        found = None
        if isbns:
            by_isbn = await open_library.resolve_by_isbns(isbns)
            found = next(iter(by_isbn.values()), None)
        if found is None:
            found = await open_library.resolve_by_title_author(work.title, work.author)
        if found is None:
            continue

        target = (
            await session.execute(
                select(Work).where(
                    Work.source == WorkSource.openlibrary, Work.external_id == found.key
                )
            )
        ).scalar_one_or_none()

        if target is None:
            # Promote in place: same row, real identity. Cheaper and safer than
            # creating a twin and merging into it.
            work.source = WorkSource.openlibrary
            work.external_id = found.key
            work.title = found.title
            work.author = found.author or work.author
            work.first_publish_year = found.first_publish_year or work.first_publish_year
            from app.models import WorkProvenance

            work.identity_provenance = (
                WorkProvenance.isbn if isbns else WorkProvenance.title_author
            )
        else:
            await merge_works(session, work, target)
        upgraded += 1

    await session.flush()
    return upgraded


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--upgrade",
        action="store_true",
        help="re-attempt Open Library for works that fell back to the heuristic tier",
    )
    args = parser.parse_args()

    async with AsyncSessionLocal() as session:
        summary = await resolve_all(session, upgrade=args.upgrade)

    print(
        "Work resolution complete: "
        f"{summary['editions_resolved']} editions resolved, "
        f"{summary['threads_linked']} threads linked, "
        f"{summary['shelves_linked']} shelves linked, "
        f"{summary['works_upgraded']} works upgraded."
    )


if __name__ == "__main__":
    asyncio.run(main())

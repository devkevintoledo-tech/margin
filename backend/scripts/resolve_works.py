"""Backfill: give every edition a work.

Alembic must not make HTTP calls, so identity resolution lives here, between
the two migrations. Run after migration 1 and before migration 2::

    docker compose exec backend python -m scripts.resolve_works

Migration 2 then moves threads and shelves onto those works in SQL and refuses
to run if any edition is still unresolved, so this script's only job is to fill
``books.work_id``.

Idempotent: a second run resolves nothing. ``--upgrade`` re-attempts works that
fell back to the heuristic tier (because Open Library was unreachable or had no
record at the time) and merges each one into its Open Library work on success::

    docker compose exec backend python -m scripts.resolve_works --upgrade
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models import Book, Work, WorkProvenance, WorkSource
from app.services import open_library
from app.services.works import _absorb_heuristic_twin, merge_works, resolve_editions

# Google Books pages are 20 volumes; one Open Library call covers a batch.
_BATCH = 20


async def resolve_all(session: AsyncSession, *, upgrade: bool = False) -> dict[str, int]:
    """Give every unresolved edition a work, optionally upgrading heuristic ones.

    Returns a summary dict with ``editions_resolved`` and ``works_upgraded``.
    """
    editions = (
        await session.execute(select(Book).where(Book.work_id.is_(None)))
    ).scalars().all()

    for start in range(0, len(editions), _BATCH):
        await resolve_editions(session, editions[start : start + _BATCH])
    await session.flush()

    upgraded = await _upgrade_heuristic_works(session) if upgrade else 0

    await session.commit()
    return {
        "editions_resolved": len(editions),
        "works_upgraded": upgraded,
    }


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
            # This rewrites the work's identity in place, so it must not guess.
            # If this work's own editions point at two different Open Library
            # works, the heuristic grouped two books together and no single
            # identity is right — leave it for a deliberate merge/split.
            candidates = {w.key: w for w in by_isbn.values()}
            if len(candidates) > 1:
                continue
            found = next(iter(candidates.values()), None)
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
            work.identity_provenance = (
                WorkProvenance.isbn if isbns else WorkProvenance.title_author
            )
            await session.flush()
            # It is an Open Library work now, so fold in any heuristic sibling
            # exactly as creating it fresh would have.
            await _absorb_heuristic_twin(session, work)
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
        f"{summary['works_upgraded']} works upgraded."
    )


if __name__ == "__main__":
    asyncio.run(main())

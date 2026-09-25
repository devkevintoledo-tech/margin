"""Repair works whose presentation predates the language-aware edition ladder.

Four idempotent passes over rows we already hold — no HTTP, so this is safe to
run at any time and as often as you like:

1. Detach editions whose identity does not match their work, by
   ``identity_keys`` — so a work whose stored key drifted from its own title
   still keeps its printings. Google answered a title+author query with
   everything the author wrote, and enrichment attached all of it: *Iron Gold*
   and five *Sons of Ares* graphic novels became editions of *Red Rising*.
   Detached rows are kept — a later search resolves them into their own works.
2. Clear a work description that came from an edition pass 1 detached, so the
   work stops describing a different book.
3. Null a ``representative_book_id`` pointing at an edition that belongs to
   another work, which duplicate works left behind.
4. Re-pick every work's representative under ``edition_rank``, so an English
   edition speaks for an English work.

Run with::

    python -m scripts.repair_presentation
    # or:
    docker compose exec backend python -m scripts.repair_presentation
"""

from __future__ import annotations

import asyncio
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models import Book, Work
from app.services.work_identity import canonical_key
from app.services.works import _refresh_work, identity_keys


async def repair(session: AsyncSession, commit: bool = True) -> dict[str, int]:
    """Repair edition attachment and representative choice. Returns counts."""
    works = {
        work.id: work
        for work in (await session.execute(select(Work))).scalars()
    }
    before: dict[UUID, UUID | None] = {
        work_id: work.representative_book_id for work_id, work in works.items()
    }

    editions = (
        await session.execute(select(Book).where(Book.work_id.is_not(None)))
    ).scalars().all()

    editions_detached = 0
    descriptions_cleared = 0
    for edition in editions:
        work = works.get(edition.work_id)
        if work is None:
            continue
        if canonical_key(edition.title, edition.author) in identity_keys(work):
            continue
        if work.description and work.description == edition.description:
            work.description = None
            descriptions_cleared += 1
        edition.work_id = None
        editions_detached += 1

    await session.flush()

    representatives_repointed = 0
    for work in works.values():
        if work.representative_book_id is None:
            continue
        representative = await session.get(Book, work.representative_book_id)
        if representative is None or representative.work_id != work.id:
            work.representative_book_id = None
            representatives_repointed += 1

    await session.flush()

    for work in works.values():
        await _refresh_work(session, work)

    await session.flush()

    representatives_changed = sum(
        1
        for work_id, work in works.items()
        if work.representative_book_id != before[work_id]
    )

    if commit:
        await session.commit()

    return {
        "editions_detached": editions_detached,
        "descriptions_cleared": descriptions_cleared,
        "representatives_repointed": representatives_repointed,
        "representatives_changed": representatives_changed,
    }


async def main() -> None:
    async with AsyncSessionLocal() as session:
        summary = await repair(session)
    print(
        "Presentation repair complete: "
        f"{summary['editions_detached']} editions detached, "
        f"{summary['descriptions_cleared']} descriptions cleared, "
        f"{summary['representatives_repointed']} stale representatives nulled, "
        f"{summary['representatives_changed']} representatives changed."
    )


if __name__ == "__main__":
    asyncio.run(main())

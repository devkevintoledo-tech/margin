"""Fills a work's editions from Google Books, once, on first view.

Open Library ingests works but carries no description or page count, and Google
Books has both. Calling Google here rather than during search keeps its latency
and its thin quota off the path every reader hits, and gives the cover
verification somewhere to live where an extra HEAD per edition costs nothing
anyone is waiting on.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Work
from app.services import covers, google_books
from app.services.work_identity import canonical_key
from app.services.works import _refresh_work, identity_keys


async def enrich_work(db: AsyncSession, work: Work) -> None:
    """Attach Google Books editions to a work that has never been enriched.

    A no-op once ``enriched_at`` is set. On upstream failure it leaves
    ``enriched_at`` null so the next view retries, rather than caching a
    failure forever.
    """
    if work.enriched_at is not None:
        return

    query = f'intitle:"{work.title}"'
    if work.author and work.author != "Unknown":
        query += f' inauthor:"{work.author}"'

    try:
        results = await google_books.search_books(query)
    except (httpx.HTTPStatusError, httpx.RequestError):
        return

    # Imported here: api/works.py owns edition upsert, and importing it at
    # module scope would close an import cycle through the router.
    from app.api.works import _upsert_editions

    editions, _ = await _upsert_editions(db, results)

    # Google answers `intitle:/inauthor:` with everything the author wrote
    # under that phrase — Iron Gold, the Sons of Ares graphic novels — so an
    # unattached edition is not evidence that it belongs here. It is attached
    # only when it resolves to this work's identity, by the same rule ingest
    # uses. A volume that fails keeps `work_id = None` and is free to be
    # resolved into its own work by a later search.
    mine: list = []
    for edition in editions:
        if edition.work_id is not None:
            if edition.work_id == work.id:
                mine.append(edition)
            continue
        if canonical_key(edition.title, edition.author) not in identity_keys(work):
            continue
        edition.work_id = work.id
        mine.append(edition)
    real = await covers.verify([e.cover_url for e in mine if e.cover_url])
    for edition in mine:
        if edition.cover_url and edition.cover_url not in real:
            edition.cover_url = None

    if not work.description:
        work.description = next((e.description for e in mine if e.description), None)

    await db.flush()
    # Re-pick the representative now that placeholder covers are gone, so the
    # edition with real art wins its tier of edition_rank.
    await _refresh_work(db, work)
    work.enriched_at = datetime.now(timezone.utc)
    await db.flush()

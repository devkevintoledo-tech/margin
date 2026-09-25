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
from app.services.works import _refresh_work


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
    for edition in editions:
        if edition.work_id is None:
            edition.work_id = work.id

    mine = [e for e in editions if e.work_id == work.id]
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

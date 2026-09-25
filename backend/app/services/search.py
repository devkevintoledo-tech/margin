"""Search orchestration: the database answers, Open Library fills it.

Every query is served from local ``works`` rows. Open Library is consulted at
most once per distinct query — see ``search`` — which is what makes its ~2s
response affordable: the cost is paid once, by one user, and amortized across
every later search for the same term.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SearchQuery, Work, WorkKind
from app.services import google_books, open_library
from app.services.google_books import normalize
from app.services.works import resolve_editions, upsert_work_from_ol

_DEFAULT_LIMIT = 20


async def search_local(
    db: AsyncSession, query: str, limit: int = _DEFAULT_LIMIT
) -> list[Work]:
    """Rank the local catalog against a query.

    ``ts_rank_cd`` scores the text match across the weighted document (title A,
    author B, subjects C); popularity multiplies it. Popularity is a multiplier
    rather than an addend so a famous but irrelevant book cannot outrank a
    relevant one — Dune does not surface for "red rising". The multiplier
    bottoms out at 1.0, so a work Open Library reports no readers for is still
    ranked by its text match rather than collapsed to zero.
    """
    if not query.strip():
        return []

    tsquery = func.plainto_tsquery("english", query)
    score = func.ts_rank_cd(Work.search_doc, tsquery) * (
        1 + func.ln(1 + Work.readinglog_count)
    )

    stmt = (
        select(Work)
        .where(
            Work.search_doc.op("@@")(tsquery),
            Work.kind == WorkKind.single,
            Work.merged_into_id.is_(None),
        )
        .order_by(
            score.desc(),
            Work.ol_edition_count.desc(),
            Work.first_publish_year.asc().nulls_last(),
        )
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


# How long a resolved query stays trusted. Long, because a book's identity does
# not change; the ceiling exists so a growing Open Library eventually reaches
# queries resolved when it was thinner.
_QUERY_TTL = timedelta(days=30)


async def _is_fresh(db: AsyncSession, normalized: str) -> bool:
    row = (
        await db.execute(
            select(SearchQuery).where(SearchQuery.normalized_query == normalized)
        )
    ).scalar_one_or_none()
    if row is None:
        return False
    return datetime.now(timezone.utc) - row.resolved_at < _QUERY_TTL


async def _record(db: AsyncSession, normalized: str, count: int) -> None:
    row = (
        await db.execute(
            select(SearchQuery).where(SearchQuery.normalized_query == normalized)
        )
    ).scalar_one_or_none()
    if row is None:
        db.add(
            SearchQuery(
                normalized_query=normalized,
                resolved_at=datetime.now(timezone.utc),
                result_count=count,
            )
        )
    else:
        row.resolved_at = datetime.now(timezone.utc)
        row.result_count = count
    await db.flush()


async def _ingest_from_google(db: AsyncSession, query: str) -> None:
    """Degraded path: Open Library is down, so fall back to the old pipeline.

    Deliberately does not record a search_queries row — the query must be
    retried upstream next time rather than be permanently stuck with whatever
    Google's weaker recall produced.
    """
    # Imported here to keep api/works.py's edition upsert as the single owner
    # of that logic.
    from app.api.works import _upsert_editions

    try:
        results = await google_books.search_books(query)
    except (httpx.HTTPStatusError, httpx.RequestError):
        return
    editions, hints = await _upsert_editions(db, results)
    await resolve_editions(db, editions, hints)


async def search(db: AsyncSession, query: str, limit: int = _DEFAULT_LIMIT) -> list[Work]:
    """Answer a search, filling the catalog from Open Library on a cold query."""
    normalized = normalize(query)
    if not normalized:
        return []

    if not await _is_fresh(db, normalized):
        ol_works = await open_library.search_works(query, limit=limit)
        if ol_works:
            for ol in ol_works:
                await upsert_work_from_ol(db, ol)
            await _record(db, normalized, len(ol_works))
        else:
            await _ingest_from_google(db, query)

    return await search_local(db, query, limit=limit)

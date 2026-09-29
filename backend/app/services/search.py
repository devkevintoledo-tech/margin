"""Search orchestration: the database answers, Open Library fills it.

Every query is served from local ``works`` rows. Open Library is consulted at
most once per distinct query — see ``search`` — which is what makes its ~2s
response affordable: the cost is paid once, by one user, and amortized across
every later search for the same term.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
from sqlalchemy import func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Genre, SearchQuery, Work, WorkKind, effective_work_genres as ewg
from app.services import google_books, open_library
from app.services.google_books import normalize
from app.services.works import resolve_editions, upsert_work_from_ol

_DEFAULT_LIMIT = 20


@dataclass(frozen=True)
class SearchFilters:
    """Filters narrow the local query only. Open Library is never asked to
    filter: its subjects are not our genres, and gating stays keyed on ``q``."""

    genres: tuple[str, ...] = ()
    author: str | None = None
    year_from: int | None = None
    year_to: int | None = None

    @property
    def active(self) -> bool:
        return bool(self.genres or self.author or self.year_from is not None or self.year_to is not None)


class InvalidFilter(ValueError):
    def __init__(self, param: str, message: str):
        super().__init__(message)
        self.param = param


async def _genre_ids(db: AsyncSession, filters: SearchFilters) -> list[UUID]:
    """Resolve and validate the filter up front, so a bad one never costs an upstream call."""
    if filters.year_from is not None and filters.year_to is not None and filters.year_from > filters.year_to:
        raise InvalidFilter("year_to", "year_to is before year_from.")
    if not filters.genres:
        return []
    found = dict((await db.execute(select(Genre.slug, Genre.id).where(
        Genre.slug.in_(filters.genres), Genre.retired_at.is_(None)))).all())
    for slug in filters.genres:
        if slug not in found:
            raise InvalidFilter("genre", f"Unknown genre: {slug}.")
    return [found[s] for s in filters.genres]


def _narrow(stmt, filters: SearchFilters, genre_ids: list[UUID]):
    for genre_id in genre_ids:  # every requested genre must be effective
        stmt = stmt.where(select(ewg.c.work_id).where(
            ewg.c.work_id == Work.id, ewg.c.genre_id == genre_id).exists())
    if filters.author:
        stmt = stmt.where(Work.author_doc.op("@@")(func.plainto_tsquery("simple", filters.author)))
    if filters.year_from is not None:
        stmt = stmt.where(Work.first_publish_year >= filters.year_from)  # NULL years drop out
    if filters.year_to is not None:
        stmt = stmt.where(Work.first_publish_year <= filters.year_to)
    return stmt


async def search_local(
    db: AsyncSession, query: str | None, limit: int = _DEFAULT_LIMIT, filters: SearchFilters | None = None
) -> list[Work]:
    """Rank the local catalog against a query, narrowed by filters.

    With a query: ``ts_rank_cd`` over the weighted document (title A, author B,
    subjects C), multiplied by popularity — a multiplier, so a famous but
    irrelevant book cannot outrank a relevant one; it bottoms out at 1.0. With
    filters alone: a browse, ordered by the summed score of the requested
    genres, then popularity.
    """
    filters = filters or SearchFilters()
    genre_ids = await _genre_ids(db, filters)
    stmt = select(Work).where(Work.kind == WorkKind.single, Work.merged_into_id.is_(None))
    if normalize(query or ""):
        tsquery = func.plainto_tsquery("english", query)
        score = func.ts_rank_cd(Work.search_doc, tsquery) * (1 + func.ln(1 + Work.readinglog_count))
        stmt = stmt.where(Work.search_doc.op("@@")(tsquery)).order_by(
            score.desc(), Work.ol_edition_count.desc(), Work.first_publish_year.asc().nulls_last())
    elif filters.active:
        genre_score = (select(func.coalesce(func.sum(ewg.c.score), 0))
                       .where(ewg.c.work_id == Work.id, ewg.c.genre_id.in_(genre_ids)).scalar_subquery()
                       if genre_ids else literal(0))
        stmt = stmt.order_by(genre_score.desc(), Work.readinglog_count.desc(), Work.title, Work.id)
    else:
        return []
    stmt = _narrow(stmt, filters, genre_ids).limit(limit)
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
    editions = await _upsert_editions(db, results)
    await resolve_editions(db, editions)


async def search(
    db: AsyncSession, query: str | None, filters: SearchFilters | None = None, limit: int = _DEFAULT_LIMIT
) -> list[Work]:
    """Answer a search, filling the catalog from Open Library on a cold ``q``.

    Filters never reach upstream: a cold ``q`` ingests once, whatever filters
    accompany it, and a filter-only search is a local browse with no HTTP call.
    """
    filters = filters or SearchFilters()
    await _genre_ids(db, filters)  # a bad filter fails before any upstream call
    normalized = normalize(query or "")
    if not normalized and not filters.active:
        return []
    if normalized and not await _is_fresh(db, normalized):
        ol_works = await open_library.search_works(query, limit=limit)
        if ol_works:
            for ol in ol_works:
                await upsert_work_from_ol(db, ol)
            await _record(db, normalized, len(ol_works))
        else:
            await _ingest_from_google(db, query)
    return await search_local(db, query, limit=limit, filters=filters)

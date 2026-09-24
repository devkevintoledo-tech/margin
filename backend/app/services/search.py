"""Search orchestration: the database answers, Open Library fills it.

Every query is served from local ``works`` rows. Open Library is consulted at
most once per distinct query — see ``search`` — which is what makes its ~2s
response affordable: the cost is paid once, by one user, and amortized across
every later search for the same term.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Work, WorkKind

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

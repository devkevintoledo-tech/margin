"""Genres on works (spec 2026-09-29 §4.5–7).

The only writer of ``work_genres``, ``genre_votes`` and ``genre_inferences``.
Every change to a source — a vote, an inference, a veto, a merge — ends in
``recompute`` in the caller's transaction, so the summary is never stale.
Readers never re-derive the effective-genre rule: they read the
``effective_work_genres`` view.
"""

from __future__ import annotations

from typing import Iterable, Mapping, Sequence
from uuid import UUID

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import INFERENCE_SOURCES, GenreInference, Work
from app.services.genre_inference import infer_genres, shipped_taxonomy

# One statement pair for one work, many, or all (:all). Votes and inferences
# on a vetoed genre count for that genre's own row (a librarian sees them) but
# never roll up into its parent.
_SCOPE = "(CAST(:all AS boolean) OR {col} = ANY(CAST(:ids AS uuid[])))"

_DELETE = text(f"DELETE FROM work_genres WHERE {_SCOPE.format(col='work_id')}")

_INSERT = text(f"""
WITH vetoes AS (
    SELECT DISTINCT c.work_id, CAST(c.payload ->> 'genre_id' AS uuid) AS genre_id
    FROM catalog_corrections c
    WHERE c.op = 'veto_genre' AND c.reverted_at IS NULL AND c.work_id IS NOT NULL
      AND {_SCOPE.format(col='c.work_id')}
),
credits AS (
    SELECT v.work_id, v.user_id, v.genre_id, true AS direct
    FROM genre_votes v WHERE {_SCOPE.format(col='v.work_id')}
    UNION ALL
    SELECT v.work_id, v.user_id, g.parent_id, false
    FROM genre_votes v JOIN genres g ON g.id = v.genre_id
    WHERE g.parent_id IS NOT NULL AND {_SCOPE.format(col='v.work_id')}
      AND NOT EXISTS (SELECT 1 FROM vetoes x WHERE x.work_id = v.work_id AND x.genre_id = v.genre_id)
),
scores AS (
    SELECT work_id, genre_id, count(DISTINCT user_id) AS score,
           count(*) FILTER (WHERE direct) AS direct_votes
    FROM credits GROUP BY work_id, genre_id
),
inferred AS (
    SELECT i.work_id, i.genre_id FROM genre_inferences i WHERE {_SCOPE.format(col='i.work_id')}
    UNION
    SELECT i.work_id, g.parent_id
    FROM genre_inferences i JOIN genres g ON g.id = i.genre_id
    WHERE g.parent_id IS NOT NULL AND {_SCOPE.format(col='i.work_id')}
      AND NOT EXISTS (SELECT 1 FROM vetoes x WHERE x.work_id = i.work_id AND x.genre_id = i.genre_id)
),
keys AS (
    SELECT work_id, genre_id FROM scores
    UNION SELECT work_id, genre_id FROM inferred
    UNION SELECT work_id, genre_id FROM vetoes
)
INSERT INTO work_genres (work_id, genre_id, direct_votes, score, inferred, vetoed)
SELECT k.work_id, k.genre_id, coalesce(s.direct_votes, 0), coalesce(s.score, 0),
       i.work_id IS NOT NULL, x.work_id IS NOT NULL
FROM keys k
JOIN works w ON w.id = k.work_id AND w.merged_into_id IS NULL
LEFT JOIN scores s ON s.work_id = k.work_id AND s.genre_id = k.genre_id
LEFT JOIN inferred i ON i.work_id = k.work_id AND i.genre_id = k.genre_id
LEFT JOIN vetoes x ON x.work_id = k.work_id AND x.genre_id = k.genre_id
""")


async def recompute(db: AsyncSession, work_ids: Iterable[UUID] | None) -> None:
    """Rewrite ``work_genres`` for these works (``None`` = every work)."""
    ids = [] if work_ids is None else list(dict.fromkeys(work_ids))
    if work_ids is not None and not ids:
        return
    params = {"all": work_ids is None, "ids": ids}
    await db.flush()
    await db.execute(_DELETE, params)
    await db.execute(_INSERT, params)


_INSERT_INFERENCES = text("""
INSERT INTO genre_inferences (work_id, genre_id, source)
SELECT r.work_id, g.id, :source
FROM unnest(CAST(:work_ids AS uuid[]), CAST(:slugs AS text[])) AS r(work_id, slug)
JOIN genres g ON g.slug = r.slug AND g.retired_at IS NULL
ON CONFLICT DO NOTHING
""")


async def set_inferences_bulk(
    db: AsyncSession, slugs_by_work: Mapping[UUID, Iterable[str]], source: str
) -> None:
    """Replace ``source``'s inferences for every work in the mapping, then recompute them."""
    if source not in INFERENCE_SOURCES:
        raise ValueError(f"unknown inference source {source!r}")
    if not slugs_by_work:
        return
    ids = list(slugs_by_work)
    await db.flush()
    await db.execute(delete(GenreInference).where(
        GenreInference.work_id.in_(ids), GenreInference.source == source))
    pairs = [(w, s) for w, slugs in slugs_by_work.items() for s in sorted(set(slugs))]
    if pairs:
        await db.execute(_INSERT_INFERENCES, {
            "source": source, "work_ids": [w for w, _ in pairs], "slugs": [s for _, s in pairs]})
    await recompute(db, ids)


async def set_inferences(db: AsyncSession, work: Work, slugs: Iterable[str], source: str) -> None:
    """Replace ``source``'s inferences for one work, then recompute it."""
    await set_inferences_bulk(db, {work.id: slugs}, source)


async def infer_from_subjects(db: AsyncSession, work: Work, subjects: Sequence[str], source: str) -> None:
    await set_inferences(db, work, infer_genres(subjects, shipped_taxonomy()), source)


async def infer_from_categories(db: AsyncSession, work: Work, categories: Sequence[str]) -> None:
    """Google's categories, only for a work Open Library's subjects said nothing about."""
    has_ol = await db.scalar(select(GenreInference.work_id).where(
        GenreInference.work_id == work.id, GenreInference.source.in_(("open_library", "catalog"))).limit(1))
    if has_ol is not None:
        return
    await set_inferences(db, work, infer_genres(categories, shipped_taxonomy()), "google")

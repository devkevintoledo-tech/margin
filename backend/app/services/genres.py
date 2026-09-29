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

from sqlalchemy import Text, and_, cast, delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import (
    INFERENCE_SOURCES,
    CatalogCorrection,
    CorrectionOp,
    Genre,
    GenreInference,
    GenreVote,
    User,
    Work,
    WorkGenre,
    WorkKind,
    effective_work_genres as ewg,
)
from app.schemas.genre import GenreRef, WorkGenreOut, WorkGenresOut
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


async def absorb(db: AsyncSession, source: Work, target: Work) -> None:
    """``merge_works``' genre half: votes (deduped per reader and genre),
    inferences (union) and vetoes follow the book; the tombstone keeps no summary."""
    # Imported here: the librarian package imports works.py, which imports this module.
    from app.services.librarian.genres import repoint_vetoes

    params = {"src": source.id, "dst": target.id}
    await db.flush()
    await db.execute(text("""
        DELETE FROM genre_votes s USING genre_votes t
        WHERE s.work_id = :src AND t.work_id = :dst AND t.user_id = s.user_id AND t.genre_id = s.genre_id"""), params)
    await db.execute(text("UPDATE genre_votes SET work_id = :dst WHERE work_id = :src"), params)
    await db.execute(text("""
        INSERT INTO genre_inferences (work_id, genre_id, source)
        SELECT :dst, genre_id, source FROM genre_inferences WHERE work_id = :src
        ON CONFLICT DO NOTHING"""), params)
    await db.execute(text("DELETE FROM genre_inferences WHERE work_id = :src"), params)
    await repoint_vetoes(db, source.id, target.id)
    await db.execute(text("DELETE FROM work_genres WHERE work_id = :src"), params)
    await recompute(db, [target.id])


MAX_GENRES_PER_READER = 5


class GenreRefused(Exception):
    """A vote the rules refuse. ``message`` is shown to the reader verbatim (422)."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


async def _live(db: AsyncSession, work: Work) -> Work:
    # One hop, like canonical_work (tombstone chains are flattened on merge).
    # Not imported from works.py: that module imports this one.
    if work.merged_into_id is None:
        return work
    return await db.get(Work, work.merged_into_id) or work


async def _vetoed(db: AsyncSession, work_id: UUID, genre_id: UUID) -> bool:
    return bool(await db.scalar(select(WorkGenre.vetoed).where(
        WorkGenre.work_id == work_id, WorkGenre.genre_id == genre_id)))


async def _my_live_votes(db: AsyncSession, user_id: UUID, work_id: UUID) -> set[UUID]:
    """The reader's votes that count: on live genres a librarian hasn't vetoed."""
    rows = await db.execute(
        select(GenreVote.genre_id)
        .join(Genre, Genre.id == GenreVote.genre_id)
        .join(WorkGenre, and_(WorkGenre.work_id == GenreVote.work_id, WorkGenre.genre_id == GenreVote.genre_id))
        .where(GenreVote.user_id == user_id, GenreVote.work_id == work_id,
               Genre.retired_at.is_(None), WorkGenre.vetoed.is_(False)))
    return set(rows.scalars())


async def vote(db: AsyncSession, user: User, work: Work, genre: Genre) -> Work:
    work = await _live(db, work)
    if work.kind is WorkKind.collection:
        raise GenreRefused("Box sets and omnibuses take their books' genres, not their own.")
    if genre.retired_at is not None:
        raise GenreRefused(f"{genre.name} is no longer in the genre list.")
    if await _vetoed(db, work.id, genre.id):
        raise GenreRefused("A librarian removed this genre from this book.")
    # Serialises one reader's concurrent votes on a book, so the cap holds.
    await db.execute(select(Work.id).where(Work.id == work.id).with_for_update())
    existing = await db.scalar(select(GenreVote.id).where(
        GenreVote.user_id == user.id, GenreVote.work_id == work.id, GenreVote.genre_id == genre.id))
    if existing is not None:
        return work
    if len(await _my_live_votes(db, user.id, work.id)) >= MAX_GENRES_PER_READER:
        raise GenreRefused(f"You've tagged this book with {MAX_GENRES_PER_READER} genres; remove one first.")
    db.add(GenreVote(user_id=user.id, work_id=work.id, genre_id=genre.id))
    await recompute(db, [work.id])
    return work


async def unvote(db: AsyncSession, user: User, work: Work, genre: Genre) -> Work:
    work = await _live(db, work)
    await db.execute(delete(GenreVote).where(
        GenreVote.user_id == user.id, GenreVote.work_id == work.id, GenreVote.genre_id == genre.id))
    await recompute(db, [work.id])
    return work


async def work_genres_payload(db: AsyncSession, work: Work, user: User | None) -> WorkGenresOut:
    parent = aliased(Genre)
    rows = (await db.execute(
        select(Genre.id, Genre.slug, Genre.name, parent.slug, ewg.c.score, WorkGenre.direct_votes, ewg.c.source)
        .select_from(ewg)
        .join(Genre, Genre.id == ewg.c.genre_id)
        .outerjoin(parent, parent.id == Genre.parent_id)
        .join(WorkGenre, and_(WorkGenre.work_id == ewg.c.work_id, WorkGenre.genre_id == ewg.c.genre_id))
        .where(ewg.c.work_id == work.id)
        .order_by(ewg.c.score.desc(), Genre.position, Genre.slug))).all()
    mine = await _my_live_votes(db, user.id, work.id) if user is not None else None
    genres = [
        WorkGenreOut(slug=slug, name=name, parent_slug=parent_slug, score=score, direct_votes=direct,
                     my_vote=None if mine is None else gid in mine)
        for gid, slug, name, parent_slug, score, direct, _ in rows
    ]
    if user is not None and user.is_librarian:
        genres += await _vetoed_rows(db, work.id)
    return WorkGenresOut(source=rows[0][6] if rows else "none", genres=genres,
                         my_vote_count=None if mine is None else len(mine))


async def _vetoed_rows(db: AsyncSession, work_id: UUID) -> list[WorkGenreOut]:
    parent = aliased(Genre)
    rows = (await db.execute(
        select(Genre.slug, Genre.name, parent.slug, WorkGenre.score, WorkGenre.direct_votes, CatalogCorrection.id)
        .select_from(WorkGenre)
        .join(Genre, Genre.id == WorkGenre.genre_id)
        .outerjoin(parent, parent.id == Genre.parent_id)
        .join(CatalogCorrection, and_(
            CatalogCorrection.work_id == WorkGenre.work_id,
            CatalogCorrection.op == CorrectionOp.veto_genre,
            CatalogCorrection.reverted_at.is_(None),
            CatalogCorrection.payload["genre_id"].astext == cast(WorkGenre.genre_id, Text)))
        .where(WorkGenre.work_id == work_id, WorkGenre.vetoed.is_(True))
        .order_by(Genre.position, Genre.slug))).all()
    return [WorkGenreOut(slug=s, name=n, parent_slug=p, score=sc, direct_votes=d, vetoed=True, veto_id=cid)
            for s, n, p, sc, d, cid in rows]


async def top_genres(db: AsyncSession, work_ids: Sequence[UUID], limit: int = 3) -> dict[UUID, list[GenreRef]]:
    """The top ``limit`` effective genres per work, in one query."""
    if not work_ids:
        return {}
    rank = func.row_number().over(
        partition_by=ewg.c.work_id, order_by=(ewg.c.score.desc(), Genre.position, Genre.slug)).label("rn")
    ranked = (select(ewg.c.work_id, Genre.slug, Genre.name, rank)
              .join(Genre, Genre.id == ewg.c.genre_id)
              .where(ewg.c.work_id.in_(list(work_ids))).subquery())
    rows = (await db.execute(select(ranked.c.work_id, ranked.c.slug, ranked.c.name)
                             .where(ranked.c.rn <= limit).order_by(ranked.c.work_id, ranked.c.rn))).all()
    out: dict[UUID, list[GenreRef]] = {}
    for work_id, slug, name in rows:
        out.setdefault(work_id, []).append(GenreRef(slug=slug, name=name))
    return out

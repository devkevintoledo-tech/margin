"""Work resolution: turning edition rows into a shared book identity.

The only module that writes ``works``. Resolution runs the ladder described in
the spec — batched ISBN, then title+author, then a local heuristic — and every
tier is allowed to fail: the heuristic always produces *some* grouping, so a
search never dies because Open Library did.
"""

from __future__ import annotations

from typing import Mapping, NamedTuple, Sequence
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.book import Book
from app.models.shelf import Shelf
from app.models.thread import Thread
from app.models.work import Work, WorkKind, WorkProvenance, WorkSource
from app.services import open_library
from app.services.open_library import OLWork
from app.services.work_identity import (
    canonical_key,
    classify_kind,
    display_title,
    heuristic_external_id,
)

# Tier 2 costs one HTTP call per volume, so it is capped. Anything past the cap
# falls to the heuristic tier and can be upgraded later by the script.
_TITLE_AUTHOR_CALL_CAP = 5


def completeness_score(edition: Book) -> int:
    """Higher = richer edition. Cover weighted highest — it carries the page.

    Moved here from ``google_books._completeness_score``: picking the richest
    edition is the only decision it was ever really making, and that decision
    now belongs to the work, not to a single search response.
    """
    score = 0
    if edition.cover_url:
        score += 4
    if edition.description:
        score += 1
    if edition.isbn_13:
        score += 1
    if edition.page_count:
        score += 1
    if edition.ratings_count:
        score += 1
    return score


async def canonical_work(db: AsyncSession, work: Work) -> Work:
    """Follow ``merged_into_id`` one hop. Merges repoint, so chains never grow."""
    if work.merged_into_id is None:
        return work
    target = await db.get(Work, work.merged_into_id)
    return target or work


async def resolve_editions(
    db: AsyncSession,
    editions: Sequence[Book],
    genre_hints: Mapping[UUID, UUID] | None = None,
) -> dict[UUID, Work]:
    """Attach every edition to a work, creating works as needed.

    Returns ``{book_id: work}`` with canonical (post-merge) works. Editions that
    already carry a ``work_id`` are returned as-is without any upstream call —
    an edition is resolved exactly once, ever.

    ``genre_hints`` maps ``Book.id`` to a ``Genre.id`` derived from the search
    payload's categories. Genre lives on the work, and ``books.genre_id`` is
    dropped, so this is the only path by which a work acquires one.
    """
    resolved: dict[UUID, Work] = {}
    pending: list[Book] = []

    for edition in editions:
        if edition.work_id is not None:
            work = await db.get(Work, edition.work_id)
            if work is not None:
                resolved[edition.id] = await canonical_work(db, work)
                continue
        pending.append(edition)

    if not pending:
        return resolved

    ol_by_edition = await _resolve_upstream(pending)

    touched: set[UUID] = set()
    for edition in pending:
        ol_work, provenance = ol_by_edition.get(
            edition.id, (None, WorkProvenance.heuristic)
        )
        work = await _upsert_work(db, edition, ol_work, provenance)
        edition.work_id = work.id
        resolved[edition.id] = work
        touched.add(work.id)

    await db.flush()
    for work_id in touched:
        work = await db.get(Work, work_id)
        if work is not None:
            await _refresh_work(db, work, genre_hints)
    await db.flush()

    return resolved


async def _resolve_upstream(
    editions: Sequence[Book],
) -> dict[UUID, tuple[OLWork | None, WorkProvenance]]:
    """Run tiers 1 and 2. Absent entries fall to the heuristic tier."""
    out: dict[UUID, tuple[OLWork | None, WorkProvenance]] = {}

    # Tier 1 — one batched ISBN call for the whole page of results.
    isbns = [e.isbn_13 for e in editions if e.isbn_13]
    by_isbn = await open_library.resolve_by_isbns(isbns) if isbns else {}
    for edition in editions:
        if edition.isbn_13 and edition.isbn_13 in by_isbn:
            out[edition.id] = (by_isbn[edition.isbn_13], WorkProvenance.isbn)

    # Tier 2 — title + author, capped.
    budget = _TITLE_AUTHOR_CALL_CAP
    for edition in editions:
        if edition.id in out or budget <= 0:
            continue
        if not edition.title or not edition.author:
            continue
        budget -= 1
        found = await open_library.resolve_by_title_author(edition.title, edition.author)
        if found is not None:
            out[edition.id] = (found, WorkProvenance.title_author)

    return out


async def _upsert_work(
    db: AsyncSession,
    edition: Book,
    ol_work: OLWork | None,
    provenance: WorkProvenance,
) -> Work:
    """Get-or-create the work an edition belongs to, merging on upgrade."""
    key = canonical_key(edition.title or "", edition.author)

    if ol_work is not None:
        source, external_id = WorkSource.openlibrary, ol_work.key
        title = ol_work.title
        author = ol_work.author or edition.author or "Unknown"
        year = ol_work.first_publish_year or edition.published_year
    else:
        source, external_id = WorkSource.heuristic, heuristic_external_id(key)
        # display_title, not clean_title: this string is shown on the work's
        # own page, and clean_title is a lookup key (lowercased, depunctuated).
        title = display_title(edition.title or "") or edition.title or "Untitled"
        author = edition.author or "Unknown"
        year = edition.published_year

    existing = (
        await db.execute(
            select(Work).where(Work.source == source, Work.external_id == external_id)
        )
    ).scalar_one_or_none()

    if existing is not None:
        return await canonical_work(db, existing)

    work = Work(
        source=source,
        external_id=external_id,
        canonical_key=key,
        title=title,
        subtitle=edition.subtitle,
        author=author,
        first_publish_year=year,
        kind=WorkKind(classify_kind(edition.title or "", edition.subtitle)),
        identity_provenance=provenance,
    )
    db.add(work)
    await db.flush()

    if source is WorkSource.openlibrary:
        await _absorb_heuristic_twin(db, work)
    return work


async def _absorb_heuristic_twin(db: AsyncSession, work: Work) -> None:
    """Merge any heuristic work that turns out to be this same book.

    Heuristic → Open Library only. Two distinct Open Library work ids are an
    authority's claim, and overriding one belongs in a deliberate merge, not in
    the middle of a search request.
    """
    twin = (
        await db.execute(
            select(Work).where(
                Work.source == WorkSource.heuristic,
                Work.canonical_key == work.canonical_key,
                Work.merged_into_id.is_(None),
            )
        )
    ).scalars().first()
    if twin is not None:
        await merge_works(db, twin, work)


async def _refresh_work(
    db: AsyncSession, work: Work, genre_hints: Mapping[UUID, UUID] | None = None
) -> None:
    """Recompute the derived fields that depend on the work's editions."""
    editions = (
        await db.execute(select(Book).where(Book.work_id == work.id))
    ).scalars().all()
    if not editions:
        return

    best = max(editions, key=completeness_score)
    work.representative_book_id = best.id

    if work.genre_id is None and genre_hints:
        work.genre_id = next(
            (genre_hints[e.id] for e in editions if e.id in genre_hints), None
        )


async def merge_works(db: AsyncSession, source: Work, target: Work) -> Work:
    """Fold ``source`` into ``target``, leaving a tombstone behind.

    Editions, threads and shelves move; the source row survives with
    ``merged_into_id`` set so its URLs keep resolving.
    """
    if source.id == target.id:
        return target

    # Shelves first: uq_shelf_user_work allows one row per (user, work), so a
    # user who shelved both works keeps their oldest entry.
    source_shelves = (
        await db.execute(select(Shelf).where(Shelf.work_id == source.id))
    ).scalars().all()
    target_owners = set(
        (
            await db.execute(select(Shelf.user_id).where(Shelf.work_id == target.id))
        ).scalars().all()
    )
    for shelf in source_shelves:
        if shelf.user_id in target_owners:
            await db.delete(shelf)
        else:
            shelf.work_id = target.id
            target_owners.add(shelf.user_id)
    await db.flush()

    await db.execute(
        update(Book).where(Book.work_id == source.id).values(work_id=target.id)
    )
    await db.execute(
        update(Thread).where(Thread.work_id == source.id).values(work_id=target.id)
    )

    source.merged_into_id = target.id
    await db.flush()
    await _refresh_work(db, target)
    await db.flush()
    return target


class WorkPresentation(NamedTuple):
    """The edition-derived bits a work needs to render."""

    cover_url: str | None
    description: str | None
    edition_count: int


async def load_work_presentation(
    db: AsyncSession, work_ids: Sequence[UUID]
) -> dict[UUID, WorkPresentation]:
    """Fetch cover, description and edition count for many works in one query.

    Kept out of the routes so both ``api/works.py`` and ``api/genres.py`` build
    the same shape, and out of the schema layer so nothing lazy-loads a
    relationship mid-serialization (MissingGreenlet).
    """
    if not work_ids:
        return {}

    representative = Book.__table__.alias("representative")
    counts = (
        select(Book.work_id, func.count(Book.id).label("n"))
        .where(Book.work_id.in_(work_ids))
        .group_by(Book.work_id)
        .subquery()
    )
    stmt = (
        select(
            Work.id,
            representative.c.cover_url,
            representative.c.description,
            func.coalesce(counts.c.n, 0),
        )
        .outerjoin(representative, Work.representative_book_id == representative.c.id)
        .outerjoin(counts, counts.c.work_id == Work.id)
        .where(Work.id.in_(work_ids))
    )
    rows = (await db.execute(stmt)).all()
    return {
        row[0]: WorkPresentation(cover_url=row[1], description=row[2], edition_count=row[3])
        for row in rows
    }

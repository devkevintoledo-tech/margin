"""Which book is which: merge and split (spec §5.2). Neither can be undone."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Book, CatalogCorrection, CorrectionOp, GenreVote, Series, SeriesKind, Shelf, Thread, User, Work, WorkProvenance,
    WorkSource,
)
from app.schemas.librarian import MergePreviewOut, MergeSide
from app.services.librarian.errors import Conflict, Invalid, NeedsConfirmation, NotFound
from app.services.librarian.keys import edition_key, exported, work_key
from app.services.librarian.placement import _override_member
from app.services.librarian.record import clean_reason, ids, live_work, locked, record
from app.services.work_identity import canonical_key, display_title, heuristic_external_id
from app.services.works import (
    WorkPresentation, _refresh_work, edition_rank, identity_keys, load_work_presentation, merge_works,
)


async def _count(db: AsyncSession, model, *conditions) -> int:
    return await db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0


def _distinct(source: Work | None, target: Work | None) -> None:
    if source is not None and target is not None and source.id == target.id:
        raise Invalid("A book cannot merge into itself.")


async def merge_consequences(db: AsyncSession, source: Work, target: Work) -> dict[str, int]:
    """What folding ``source`` into ``target`` moves. The confirmation and the
    preview both read it, so the two can never disagree."""
    room = await db.get(Series, source.series_id)
    moving_threads = await _count(db, Thread, Thread.work_id == source.id)
    if room.kind is SeriesKind.singleton and room.id != target.series_id:
        # absorb_series tags a singleton's untagged threads with the book and carries them.
        moving_threads += await _count(db, Thread, Thread.series_id == room.id, Thread.work_id.is_(None))
    return {
        "threads": moving_threads,
        "shelves": await _count(db, Shelf, Shelf.work_id == source.id),
        "editions": await _count(db, Book, Book.work_id == source.id),
        "genre_votes": await _count(db, GenreVote, GenreVote.work_id == source.id),
    }


async def _side(db: AsyncSession, work: Work, shown: WorkPresentation) -> MergeSide:
    room = await db.get(Series, work.series_id)
    threads = await _count(db, Thread, Thread.work_id == work.id)
    if room.kind is SeriesKind.singleton:
        threads += await _count(db, Thread, Thread.series_id == room.id, Thread.work_id.is_(None))
    return MergeSide(
        id=work.id, title=work.title, author=work.author, first_publish_year=work.first_publish_year,
        cover_url=shown.cover_url, description=shown.description, edition_count=shown.edition_count,
        thread_count=threads, shelf_count=await _count(db, Shelf, Shelf.work_id == work.id),
        series_slug=room.slug, series_name=room.name if room.kind is SeriesKind.series else None,
    )


async def merge_preview(db: AsyncSession, source: Work, target: Work) -> MergePreviewOut:
    """What merging ``source`` into ``target`` would do, without doing it: both
    books as their pages render them, and the counts the confirmation states.
    Refuses exactly what ``merge`` refuses. A read: no lock, no correction."""
    _distinct(source, target)
    source, target = live_work(source), live_work(target)
    shown = await load_work_presentation(db, [source.id, target.id])
    return MergePreviewOut(
        source=await _side(db, source, shown[source.id]),
        target=await _side(db, target, shown[target.id]),
        **await merge_consequences(db, source, target),
    )


async def merge(db: AsyncSession, user: User, source: Work, target: Work, *, reason: str,
                confirm: bool = False) -> CatalogCorrection:
    reason = clean_reason(reason)
    _distinct(source, target)
    for work in sorted((w for w in (source, target) if w is not None), key=lambda w: w.id):
        await locked(db, work)  # id order, so two opposite merges cannot deadlock
    source, target = live_work(source), live_work(target)
    consequences = await merge_consequences(db, source, target)
    if not confirm:
        raise NeedsConfirmation(f"Merging {source.title} into {target.title} cannot be undone.", consequences)
    entries, missing = exported(lambda: [{"merge_works": [work_key(target), work_key(source)]}])
    await merge_works(db, source, target)
    return await record(
        db, op=CorrectionOp.merge_works, user=user, reason=reason,
        payload={"source": str(source.id), "target": str(target.id), "consequences": consequences},
        entries=entries, runtime_only_reason=missing, work=target,
        series=await db.get(Series, target.series_id),
    )


async def split(db: AsyncSession, user: User, work: Work, edition_ids: list[UUID], *, reason: str,
                confirm: bool = False) -> CatalogCorrection:
    reason = clean_reason(reason)
    work = live_work(await locked(db, work))
    wanted = list(dict.fromkeys(edition_ids))
    if not wanted:
        raise Invalid("Pick at least one edition to split off.")
    editions = (await db.execute(select(Book).where(Book.id.in_(wanted)))).scalars().all()
    if len(editions) != len(wanted):
        raise NotFound("Unknown edition.")
    if any(e.work_id != work.id for e in editions):
        raise Invalid(f"That is not an edition of {work.title}.")
    total = await _count(db, Book, Book.work_id == work.id)
    if len(editions) == total:
        raise Invalid("Splitting off every edition leaves nothing behind; merge or move the book instead.")
    consequences = {"editions": len(editions), "remaining": total - len(editions)}
    if not confirm:
        raise NeedsConfirmation(f"Splitting {len(editions)} editions off {work.title} cannot be undone.",
                                consequences)

    title = display_title(max(editions, key=edition_rank).title) or work.title
    key = canonical_key(title, work.author)
    entries, missing = exported(lambda: [{"split_work": {
        "work": work_key(work), "editions": sorted(edition_key(e) for e in editions)}}])
    if entries is not None:
        # The pipeline's SplitWork.new_work, so the next release adopts this row.
        source, external_id = WorkSource.openlibrary, f"{work.external_id}~{min(edition_key(e) for e in editions)}"
        provenance = WorkProvenance.override
    else:
        if key in identity_keys(work):
            raise Invalid(f"The split-off editions are titled like {work.title} itself, so a runtime split "
                          "would be merged straight back; split Open Library editions instead.")
        source, external_id, provenance = WorkSource.heuristic, heuristic_external_id(key), WorkProvenance.heuristic
    if await _count(db, Work, Work.source == source, Work.external_id == external_id):
        raise Conflict("Those editions were already split off into their own book.")

    room = await db.get(Series, work.series_id)
    new = Work(
        source=source, external_id=external_id, canonical_key=key, title=title, author=work.author,
        kind=work.kind, identity_provenance=provenance,
        # A singleton is one book's page: the new book gets its own (flush listener).
        series_id=room.id if room.kind is SeriesKind.series else None,
    )
    db.add(new)
    await db.flush()
    if room.kind is SeriesKind.series:
        db.add(_override_member(room.id, new.id, None))
    for e in editions:
        e.work_id = new.id
    await db.flush()
    await _refresh_work(db, work)
    await _refresh_work(db, new)
    await db.flush()
    return await record(
        db, op=CorrectionOp.split_work, user=user, reason=reason,
        payload={"work": str(work.id), "new_work": str(new.id), "editions": ids(sorted(e.id for e in editions))},
        entries=entries, runtime_only_reason=missing, work=work, series=room,
    )

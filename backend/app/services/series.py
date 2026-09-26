"""Series writes: the only module that inserts or moves ``series`` rows.

A work's room is decided here. Detection rules live in ``series_identity``;
this module applies them against the database.
"""

from __future__ import annotations

import uuid

from sqlalchemy import event, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models import Series, SeriesKind, SeriesSource, Thread, Work
from app.services.series_identity import (
    choose_container,
    parse_tags,
    series_key,
    slugify,
    tag_external_id,
    tag_name,
)


def singleton_series_for(work: Work) -> Series:
    """A series of one for ``work``.

    The slug carries a short id so it needs no uniqueness query — three
    different books are titled plain "Dune" — which is what lets this run
    inside a flush.
    """
    if work.id is None:
        work.id = uuid.uuid4()
    series_id = uuid.uuid4()
    return Series(
        id=series_id,
        source=SeriesSource.heuristic,
        external_id=f"singleton:{work.id}",
        name=work.title,
        slug=f"{slugify(work.title, max_length=60)}-{series_id.hex[:6]}",
        canonical_key=series_key(work.title),
        kind=SeriesKind.singleton,
    )


@event.listens_for(Session, "before_flush")
def _every_work_has_a_series(session, flush_context, instances) -> None:
    """Give any new work that arrives without a room a singleton of its own.

    This is the column default for a required foreign key that has to create
    its target. Checking ``__dict__`` rather than ``work.series`` avoids
    triggering a relationship load in the middle of a flush.
    """
    for obj in list(session.new):
        if (
            isinstance(obj, Work)
            and obj.series_id is None
            and obj.__dict__.get("series") is None
        ):
            obj.series = singleton_series_for(obj)


_MAX_TOMBSTONE_HOPS = 10


async def canonical_series(db: AsyncSession, series: Series) -> Series:
    hops = 0
    while series.merged_into_id is not None and hops < _MAX_TOMBSTONE_HOPS:
        series = await db.get(Series, series.merged_into_id)
        hops += 1
    return series


async def get_series_by_slug(db: AsyncSession, slug: str) -> Series | None:
    found = (
        await db.execute(select(Series).where(Series.slug == slug))
    ).scalar_one_or_none()
    return await canonical_series(db, found) if found is not None else None


async def unique_slug(db: AsyncSession, name: str) -> str:
    base = slugify(name)
    taken = set(
        (
            await db.execute(
                select(Series.slug).where(
                    (Series.slug == base) | Series.slug.like(f"{base}-%")
                )
            )
        ).scalars()
    )
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


async def _tag_counts(db: AsyncSession, tags: tuple[str, ...]) -> dict[str, int]:
    """How many live works carry each tag, as its own subject line.

    Spaces in the pattern become LIKE's single-character wildcard so a tag
    stored as ``series:Red_Rising_Saga`` counts the same as the spaced form.
    """
    padded = func.concat("\n", func.coalesce(Work.subjects, ""), "\n")
    counts: dict[str, int] = {}
    for tag in tags:
        escaped = tag.replace("\\", "\\\\").replace("%", "\\%").replace(" ", "_")
        counts[tag] = await db.scalar(
            select(func.count())
            .select_from(Work)
            .where(
                Work.merged_into_id.is_(None),
                padded.ilike(f"%\n{escaped}\n%", escape="\\"),
            )
        ) or 0
    return counts


async def series_for_subjects(db: AsyncSession, subjects: str | None) -> Series | None:
    """The tag series these subjects put a work in, created on first sight."""
    tags = parse_tags(subjects)
    counts = (
        await _tag_counts(db, tags.series)
        if not tags.franchises and len(tags.series) > 1
        else {}
    )
    tag = choose_container(tags, counts)
    if tag is None:
        return None

    external_id = tag_external_id(tag)
    existing = (
        await db.execute(
            select(Series).where(
                Series.source == SeriesSource.openlibrary,
                Series.external_id == external_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return await canonical_series(db, existing)

    name = tag_name(tag)
    series = Series(
        source=SeriesSource.openlibrary,
        external_id=external_id,
        name=name,
        slug=await unique_slug(db, name),
        canonical_key=series_key(name),
        kind=SeriesKind.series,
    )
    db.add(series)
    await db.flush()
    return series


async def _promote(db: AsyncSession, work: Work, singleton: Series, target: Series) -> None:
    """Move a singleton's room, and everything in it, into a real series.

    Every thread in a singleton was about its one book, so untagged threads
    are tagged with it on the way in. Without the tag they would sink into
    the series-wide feed and vanish from that book's filter.
    """
    await db.execute(
        update(Thread)
        .where(Thread.series_id == singleton.id, Thread.work_id.is_(None))
        .values(work_id=work.id)
    )
    await db.execute(
        update(Thread).where(Thread.series_id == singleton.id).values(series_id=target.id)
    )
    # Tombstoned works that pointed at the singleton follow too.
    await db.execute(
        update(Work).where(Work.series_id == singleton.id).values(series_id=target.id)
    )
    work.series_id = target.id
    singleton.merged_into_id = target.id
    await db.flush()


async def assign_series(db: AsyncSession, work: Work) -> Series:
    """Put ``work`` in the room its subjects name, promoting a singleton.

    A work already in a real series is never moved to another automatically.
    That would be a merge decision, like OL → OL work merges.
    """
    target = await series_for_subjects(db, work.subjects)
    current = await db.get(Series, work.series_id) if work.series_id else None

    if target is None:
        if current is None:
            current = singleton_series_for(work)
            db.add(current)
            await db.flush()
            work.series_id = current.id
            await db.flush()
        return current
    if current is None:
        work.series_id = target.id
        await db.flush()
        return target
    if current.id == target.id or current.kind is SeriesKind.series:
        return current
    await _promote(db, work, current, target)
    return target


async def absorb_series(db: AsyncSession, source: Work, target: Work) -> None:
    """Carry ``source``'s discussion into ``target``'s room ahead of a work merge.

    Must run before ``merge_works`` rewrites ``Thread.work_id``, because that
    rewrite is how threads tagged to ``source`` are found.
    """
    if source.series_id == target.series_id:
        return
    src = await db.get(Series, source.series_id)
    if src.kind is SeriesKind.singleton:
        await db.execute(
            update(Thread)
            .where(Thread.series_id == src.id, Thread.work_id.is_(None))
            .values(work_id=source.id)
        )
    await db.execute(
        update(Thread).where(Thread.work_id == source.id).values(series_id=target.series_id)
    )
    if src.kind is SeriesKind.singleton:
        await db.execute(
            update(Work).where(Work.series_id == src.id).values(series_id=target.series_id)
        )
        src.merged_into_id = target.series_id
    source.series_id = target.series_id
    await db.flush()

"""Where a book lives: move, reorder, rename (spec §5.2). Remove and dissolve are in Task 5."""

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CatalogCorrection, CorrectionOp, MembershipConfidence, Series, SeriesKind, SeriesMember, SeriesProvenance,
    SeriesSource, Thread, User, Work,
)
from app.services.catalog_loader import retire_series
from app.services.librarian.errors import Conflict, Invalid
from app.services.librarian.keys import exported, release_series_key, series_key_of, work_key
from app.services.librarian.record import clean_reason, ids, live_series, live_work, member_state, record
from app.services.series import canonical_series, placed_memberships, tree_memberships, unique_slug
from app.services.series_identity import new_series_key, release_series_id, series_key


def _override_member(series_id, work_id, position) -> SeriesMember:
    return SeriesMember(series_id=series_id, work_id=work_id, position=position,
                        provenance=SeriesProvenance.override, confidence=MembershipConfidence.high)


async def _move_tagged_threads(db: AsyncSession, work_id, from_room, to_room) -> list[str]:
    """Threads tagged with the book follow it; untagged ones belong to the room."""
    moved = (await db.execute(select(Thread.id).where(
        Thread.work_id == work_id, Thread.series_id == from_room).order_by(Thread.id))).scalars().all()
    if moved:
        await db.execute(update(Thread).where(Thread.id.in_(moved)).values(series_id=to_room))
    return ids(moved)


async def _live_count(db: AsyncSession, room_id) -> int:
    return await db.scalar(select(func.count()).select_from(Work).where(
        Work.series_id == room_id, Work.merged_into_id.is_(None))) or 0


async def _target_for_name(db: AsyncSession, name: str | None) -> tuple[Series, bool]:
    """The series a librarian named: an existing one with that key, or a new one
    under the id the next release will give it."""
    name = (name or "").strip()
    if not name:
        raise Invalid("A new series needs a name.")
    key = new_series_key(name)
    found = await db.get(Series, release_series_id(key))
    if found is None:
        found = (await db.execute(select(Series).where(
            Series.external_id == key, Series.kind == SeriesKind.series))).scalars().first()
    if found is not None:
        return await canonical_series(db, found), False
    series = Series(
        id=release_series_id(key), source=SeriesSource.heuristic, external_id=key, name=name,
        slug=await unique_slug(db, name), canonical_key=series_key(name), kind=SeriesKind.series,
        provenance=SeriesProvenance.override,
    )
    db.add(series)
    await db.flush()
    return series, True


async def _ids_where(db: AsyncSession, column, *conditions) -> list[str]:
    return ids((await db.execute(select(column).where(*conditions).order_by(column))).scalars().all())


async def _retire_if_empty(db: AsyncSession, room: Series, target: Series, work: Work) -> dict | None:
    """A room the move emptied follows its book, as the catalog loader does."""
    if await _live_count(db, room.id):
        return None
    singleton = room.kind is SeriesKind.singleton
    state = {
        "room": str(room.id),
        "parent": str(room.parent_series_id) if room.parent_series_id else None,
        "threads": await _ids_where(db, Thread.id, Thread.series_id == room.id),
        "tagged": (await _ids_where(db, Thread.id, Thread.series_id == room.id, Thread.work_id.is_(None))
                   if singleton else []),
        "works": await _ids_where(db, Work.id, Work.series_id == room.id),
        "repointed": await _ids_where(db, Series.id, Series.merged_into_id == room.id),
    }
    await retire_series(db, room.id, target.id, work.id if singleton else None)
    await db.refresh(room)
    return state


async def set_series(db: AsyncSession, user: User, work: Work, *, reason: str, series: Series | None = None,
                     new_series_name: str | None = None, position: float | None = None) -> CatalogCorrection:
    reason = clean_reason(reason)
    work = live_work(work)
    if (series is None) == (new_series_name is None):
        raise Invalid("Pick a series, or name a new one, not both.")
    old_room = await db.get(Series, work.series_id)
    if series is not None:
        target, created = await canonical_series(db, live_series(series)), False
    else:
        target, created = await _target_for_name(db, new_series_name)
    if target.kind is SeriesKind.singleton:
        raise Invalid("A single book's page is not a series; pick a series or name a new one.")
    if target.parent_series_id is not None:
        raise Invalid(f"{target.name} is a sub-series; move the book to the series it belongs to.")
    if target.dissolved_at is not None:
        raise Conflict(f"{target.name} was dissolved.")
    if target.id == old_room.id:
        raise Invalid(f"{work.title} is already in {target.name}.")

    old_members = await tree_memberships(db, old_room, work.id)
    old_series = [await db.get(Series, m.series_id) for m in old_members]
    prior = await db.get(SeriesMember, (target.id, work.id))
    snapshot = {
        "old_room": str(old_room.id),
        "old_members": [member_state(m) for m in old_members],
        "prior_target_member": member_state(prior) if prior is not None else None,
        "created_series": str(target.id) if created else None,
    }
    for m in [*old_members, *([prior] if prior is not None else [])]:
        await db.delete(m)
    await db.flush()
    db.add(_override_member(target.id, work.id, position))
    snapshot["moved_threads"] = await _move_tagged_threads(db, work.id, old_room.id, target.id)
    work.series_id = target.id
    await db.flush()
    snapshot["retired"] = await _retire_if_empty(db, old_room, target, work)

    def build():
        wk = work_key(work)
        removes = [{"remove_from_series": {"work": wk, "series": release_series_key(s)}}
                   for s in sorted(old_series, key=lambda s: s.external_id) if s.catalog_release is not None]
        entry = {"work": wk, "series": series_key_of(target)}
        if position is not None:
            entry["position"] = position
        if target.catalog_release is None:
            entry["name"] = target.name  # lets the pipeline create it
        return [*removes, {"set_series": entry}]

    entries, missing = exported(build)
    return await record(
        db, op=CorrectionOp.set_series, user=user, reason=reason,
        payload={"work": str(work.id), "series": str(target.id), "position": position,
                 "new_series_name": new_series_name},
        entries=entries, runtime_only_reason=missing, snapshot=snapshot, work=work, series=target,
    )


async def set_position(db: AsyncSession, user: User, room: Series, work: Work, position: float | None, *,
                       reason: str) -> CatalogCorrection:
    reason = clean_reason(reason)
    room, work = live_series(room), live_work(work)
    if room.kind is SeriesKind.singleton:
        raise Invalid("A single book has no place in a series to set.")
    if work.series_id != room.id:
        raise Invalid(f"{work.title} is not in {room.name}.")
    placed, _ = await placed_memberships(db, room, [work.id])
    member = placed.get(work.id)
    prior = member_state(member) if member is not None else None
    if member is None:
        member = _override_member(room.id, work.id, position)
        db.add(member)
    else:
        member.position = position
        member.provenance, member.confidence = SeriesProvenance.override, MembershipConfidence.high
    await db.flush()
    member_series = await db.get(Series, member.series_id)

    def build():
        entry = {"work": work_key(work), "series": series_key_of(member_series), "position": position}
        if member_series.catalog_release is None:
            entry["name"] = member_series.name
        return [{"set_series": entry}]

    entries, missing = exported(build)
    return await record(
        db, op=CorrectionOp.set_position, user=user, reason=reason,
        payload={"work": str(work.id), "series": str(room.id), "member_series": str(member.series_id),
                 "position": position},
        entries=entries, runtime_only_reason=missing,
        snapshot={"member_series": str(member.series_id), "prior": prior}, work=work, series=room,
    )


async def rename_series(db: AsyncSession, user: User, series: Series, name: str, *,
                        reason: str) -> CatalogCorrection:
    reason = clean_reason(reason)
    series = live_series(series)
    if series.kind is SeriesKind.singleton:
        raise Invalid("A single book's page takes its book's title; it cannot be renamed.")
    if series.dissolved_at is not None:
        raise Conflict(f"{series.name} was dissolved.")
    name = (name or "").strip()
    if not name:
        raise Invalid("A series needs a name.")
    if name == series.name:
        raise Invalid(f"It is already called {name}.")
    # Built before the rename, so a runtime-only reason names the series as it was.
    entries, missing = exported(lambda: [{"rename_series": {"series": release_series_key(series), "name": name}}])
    old = series.name
    series.name = name  # the slug never changes: shared links keep working
    await db.flush()
    return await record(
        db, op=CorrectionOp.rename_series, user=user, reason=reason,
        payload={"series": str(series.id), "name": name}, entries=entries, runtime_only_reason=missing,
        snapshot={"old_name": old}, series=series,
    )

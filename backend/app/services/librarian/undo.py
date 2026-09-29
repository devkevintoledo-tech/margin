"""Undo (spec §6): only the latest unreverted fix on its subject, and only while
the catalog still looks the way that fix left it."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CatalogCorrection, CorrectionOp, Series, SeriesMember, Thread, User, Work
from app.services import genres as genres_service
from app.services.librarian.errors import Conflict, Invalid
from app.services.librarian.placement import _live_count
from app.services.librarian.record import SERIES_SUBJECT_OPS, latest_for_subject, locked, restore_member, uuids

UNDOABLE = frozenset({CorrectionOp.set_series, CorrectionOp.set_position, CorrectionOp.rename_series,
                      CorrectionOp.remove_from_series, CorrectionOp.reject_series,
                      CorrectionOp.veto_genre})
_STALE = "The book or series changed since this fix; it can no longer be undone."


async def _subject(db: AsyncSession, c: CatalogCorrection):
    if c.op in SERIES_SUBJECT_OPS:
        return await db.get(Series, c.series_id) if c.series_id else None
    return await db.get(Work, c.work_id) if c.work_id else None


async def undoable(db: AsyncSession, c: CatalogCorrection) -> bool:
    """What the log's undo button shows: the latest live fix on a subject that
    still exists. revert re-checks everything else."""
    if c.op not in UNDOABLE or c.reverted_at is not None:
        return False
    subject = await _subject(db, c)
    if subject is None or subject.merged_into_id is not None:
        return False
    latest = await latest_for_subject(db, c)
    return latest is not None and latest.id == c.id


async def revert(db: AsyncSession, user: User, correction: CatalogCorrection) -> CatalogCorrection:
    if correction.op not in UNDOABLE:
        raise Invalid("Merges and splits cannot be undone.")
    # Serialise with any fix to the same subject, and with a second undo click.
    await locked(db, await _subject(db, correction))
    await locked(db, correction)
    if correction.reverted_at is not None:
        raise Conflict("This fix was already undone.")
    latest = await latest_for_subject(db, correction)
    if latest is None or latest.id != correction.id:
        raise Conflict("A later fix to the same book or series came after this one; undo that first.")
    await _REVERT[correction.op](db, correction)
    correction.reverted_at = datetime.now(timezone.utc)
    correction.reverted_by_id = user.id
    await db.flush()
    if correction.op is CorrectionOp.veto_genre:
        await genres_service.recompute(db, [correction.work_id])
    return correction


async def _require_threads_in(db: AsyncSession, thread_ids: list[UUID], room_id: UUID) -> None:
    if not thread_ids:
        return
    rooms = (await db.execute(select(Thread.series_id).where(Thread.id.in_(thread_ids)))).scalars().all()
    if len(rooms) != len(thread_ids) or any(r != room_id for r in rooms):
        raise Conflict(_STALE)


async def _require_absent(db: AsyncSession, states: list[dict]) -> None:
    """A membership undo would re-create already exists (a release re-added it)."""
    for state in states:
        if await db.get(SeriesMember, (UUID(state["series_id"]), UUID(state["work_id"]))) is not None:
            raise Conflict(_STALE)


async def _move_threads(db: AsyncSession, thread_ids: list[UUID], **values) -> None:
    if thread_ids:
        await db.execute(update(Thread).where(Thread.id.in_(thread_ids)).values(**values))


async def _undo_set_series(db: AsyncSession, c: CatalogCorrection) -> None:
    s = c.snapshot
    work, target = await db.get(Work, c.work_id), await db.get(Series, c.series_id)
    if work is None or target is None or work.merged_into_id is not None or work.series_id != target.id:
        raise Conflict(_STALE)
    member = await db.get(SeriesMember, (target.id, work.id))
    if member is None:
        raise Conflict(_STALE)
    await _require_absent(db, [*s["old_members"], *([s["prior_target_member"]] if s["prior_target_member"] else [])])
    moved = uuids(s["moved_threads"])
    await _require_threads_in(db, moved, target.id)
    known = moved + (uuids(s["retired"]["threads"]) if s["retired"] else [])
    started_since = await db.scalar(select(func.count()).select_from(Thread).where(
        Thread.series_id == target.id, Thread.work_id == work.id, Thread.id.not_in(known)))
    if started_since:
        raise Conflict(f"New discussion about {work.title} started in {target.name} since; undoing would strand it.")
    old_room = await db.get(Series, UUID(s["old_room"]))
    if old_room is None:
        raise Conflict(_STALE)
    await db.refresh(old_room)
    retired = s["retired"]
    if retired is not None:
        if old_room.merged_into_id != target.id:
            raise Conflict(_STALE)
        await _require_threads_in(db, uuids(retired["threads"]), target.id)
        old_room.merged_into_id = None
        old_room.parent_series_id = UUID(retired["parent"]) if retired["parent"] else None
        await _move_threads(db, uuids(retired["threads"]), series_id=old_room.id)
        await _move_threads(db, uuids(retired["tagged"]), work_id=None)
        if retired["works"]:
            await db.execute(update(Work).where(Work.id.in_(uuids(retired["works"]))).values(series_id=old_room.id))
        if retired["repointed"]:
            await db.execute(update(Series).where(Series.id.in_(uuids(retired["repointed"])))
                             .values(merged_into_id=old_room.id))
    elif old_room.merged_into_id is not None or old_room.dissolved_at is not None:
        raise Conflict(_STALE)

    await _move_threads(db, moved, series_id=old_room.id)
    await db.delete(member)
    await db.flush()
    for state in [*s["old_members"], *([s["prior_target_member"]] if s["prior_target_member"] else [])]:
        db.add(restore_member(state))
    work.series_id = old_room.id
    await db.flush()
    if s["created_series"] and not await _live_count(db, target.id) and not await db.scalar(
        select(func.count()).select_from(Thread).where(Thread.series_id == target.id)
    ):
        target.merged_into_id = old_room.id  # a link shared in the meantime still resolves
        await db.flush()


async def _undo_set_position(db: AsyncSession, c: CatalogCorrection) -> None:
    s = c.snapshot
    work = await db.get(Work, c.work_id) if c.work_id else None
    if work is None or work.merged_into_id is not None or work.series_id != c.series_id:
        raise Conflict(_STALE)
    member = await db.get(SeriesMember, (UUID(s["member_series"]), c.work_id))
    if member is None or member.position != c.payload["position"]:
        raise Conflict(_STALE)
    prior = s["prior"]
    if prior is None:
        await db.delete(member)
    else:
        restored = restore_member(prior)
        member.position, member.provenance, member.confidence = (
            restored.position, restored.provenance, restored.confidence)
    await db.flush()


async def _undo_rename(db: AsyncSession, c: CatalogCorrection) -> None:
    series = await db.get(Series, c.series_id)
    if series is None or series.merged_into_id is not None or series.name != c.payload["name"]:
        raise Conflict(_STALE)
    series.name = c.snapshot["old_name"]
    await db.flush()


async def _check_reattach(db: AsyncSession, state: dict) -> tuple[Work, Series]:
    work = await db.get(Work, UUID(state["work"]))
    single = await db.get(Series, UUID(state["singleton"]))
    if (work is None or single is None or work.merged_into_id is not None
            or work.series_id != single.id or single.merged_into_id is not None):
        raise Conflict(_STALE)
    if await _live_count(db, single.id) != 1:
        raise Conflict(_STALE)
    now = set((await db.execute(select(Thread.id).where(Thread.series_id == single.id))).scalars().all())
    if now != set(uuids(state["threads"])):
        raise Conflict(f"New discussion started on {work.title}'s own page since; undoing would move it.")
    await _require_absent(db, state["members"])
    return work, single


async def _reattach(db: AsyncSession, room: Series, state: dict, work: Work, single: Series) -> None:
    await _move_threads(db, uuids(state["threads"]), series_id=room.id)
    for member in state["members"]:
        db.add(restore_member(member))
    work.series_id = room.id
    single.merged_into_id = room.id  # a link shared in the meantime still resolves
    await db.flush()


async def _undo_remove(db: AsyncSession, c: CatalogCorrection) -> None:
    room = await db.get(Series, c.series_id)
    if room is None or room.merged_into_id is not None or room.dissolved_at is not None:
        raise Conflict(_STALE)
    work, single = await _check_reattach(db, c.snapshot)
    await _reattach(db, room, c.snapshot, work, single)


async def _undo_reject(db: AsyncSession, c: CatalogCorrection) -> None:
    series = await db.get(Series, c.series_id)
    if series is None or series.merged_into_id is not None or series.dissolved_at is None:
        raise Conflict(_STALE)
    # Check every member before touching any, so a refusal leaves nothing half-undone.
    checked = [await _check_reattach(db, state) for state in c.snapshot["members"]]
    series.dissolved_at = None
    for state, (work, single) in zip(c.snapshot["members"], checked):
        await _reattach(db, series, state, work, single)


async def _undo_veto(db: AsyncSession, c: CatalogCorrection) -> None:
    work = await db.get(Work, c.work_id) if c.work_id else None
    if work is None or work.merged_into_id is not None:
        raise Conflict(_STALE)
    # Nothing to restore: the veto never touched a vote. revert() sets
    # reverted_at, then the summary is recomputed.


_REVERT = {
    CorrectionOp.set_series: _undo_set_series,
    CorrectionOp.set_position: _undo_set_position,
    CorrectionOp.rename_series: _undo_rename,
    CorrectionOp.remove_from_series: _undo_remove,
    CorrectionOp.reject_series: _undo_reject,
    CorrectionOp.veto_genre: _undo_veto,
}

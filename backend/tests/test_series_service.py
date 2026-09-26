"""Assigning works to rooms, and moving rooms when we learn more."""

import uuid

from sqlalchemy import select

from app.models import (
    AuthProvider,
    Series,
    SeriesKind,
    Thread,
    User,
    Work,
    WorkKind,
    WorkProvenance,
    WorkSource,
)
from app.services import series as series_service
from app.services.open_library import OLWork
from app.services.series_identity import join_subjects
from app.services.works import merge_works, upsert_work_from_ol


def _ol(key, title, subjects=(), year=None) -> OLWork:
    return OLWork(
        key=key, title=title, author="Pierce Brown", first_publish_year=year,
        edition_count=1, isbn_13s=frozenset(), subjects=tuple(subjects),
    )


RR_TAGS = ("franchise:Red Rising", "series:Red Rising Trilogy", "series:Red Rising Saga")


async def _user(db):
    u = User(email=f"u{uuid.uuid4().hex[:6]}@x.com", username=f"u{uuid.uuid4().hex[:6]}",
             password_hash="x", auth_provider=AuthProvider.email)
    db.add(u)
    await db.flush()
    return u


async def test_ingest_stores_subjects_one_per_line(db_session):
    work = await upsert_work_from_ol(db_session, _ol("OL1W", "Red Rising", ["Fiction", "series:X"]))
    assert work.subjects == "Fiction\nseries:X"


async def test_franchise_siblings_share_one_room(db_session):
    red = await upsert_work_from_ol(db_session, _ol("OL1W", "Red Rising", RR_TAGS, 2014))
    gold = await upsert_work_from_ol(db_session, _ol("OL2W", "Iron Gold", ["franchise:Red Rising"], 2018))
    assert red.series_id == gold.series_id
    series = await db_session.get(Series, red.series_id)
    assert series.kind is SeriesKind.series
    assert series.name == "Red Rising"
    assert series.slug == "red-rising"


async def test_untagged_ingest_is_a_singleton(db_session):
    work = await upsert_work_from_ol(db_session, _ol("OL3W", "The Hobbit", ["Fantasy"]))
    assert (await db_session.get(Series, work.series_id)).kind is SeriesKind.singleton


async def test_broadest_series_tag_wins(db_session):
    # Two works already carry the Saga tag, one the Trilogy tag.
    await upsert_work_from_ol(db_session, _ol("OL4W", "A", ["series:Saga"]))
    await upsert_work_from_ol(db_session, _ol("OL5W", "B", ["series:Saga"]))
    await upsert_work_from_ol(db_session, _ol("OL6W", "C", ["series:Trilogy"]))
    both = await upsert_work_from_ol(db_session, _ol("OL7W", "D", ["series:Trilogy", "series:Saga"]))
    assert (await db_session.get(Series, both.series_id)).name == "Saga"


async def test_unique_slug_suffixes_on_collision(db_session):
    first = await series_service.series_for_subjects(db_session, "series:Dune")
    second = await series_service.series_for_subjects(db_session, "franchise:Dune")
    assert first.slug == "dune"
    assert second.slug == "dune-2"


async def test_promotion_carries_threads_and_tags_untagged_ones(db_session):
    """A singleton later learns its series: the room moves, nothing is lost."""
    work = await upsert_work_from_ol(db_session, _ol("OL8W", "Golden Son"))
    singleton = await db_session.get(Series, work.series_id)
    user = await _user(db_session)
    thread = Thread(title="Is Mustang right?", user_id=user.id, series_id=singleton.id)
    db_session.add(thread)
    await db_session.flush()

    # Re-ingest with tags, as a later search would.
    await upsert_work_from_ol(db_session, _ol("OL8W", "Golden Son", ["franchise:Red Rising"]))

    await db_session.refresh(thread)
    await db_session.refresh(singleton)
    target = await db_session.get(Series, work.series_id)
    assert target.kind is SeriesKind.series
    assert thread.series_id == target.id
    assert thread.work_id == work.id  # tagged, so the book filter still finds it
    assert singleton.merged_into_id == target.id


async def test_a_book_is_never_moved_between_two_real_series(db_session):
    work = await upsert_work_from_ol(db_session, _ol("OL9W", "X", ["series:First"]))
    first = work.series_id
    await upsert_work_from_ol(db_session, _ol("OL9W", "X", ["franchise:Other"]))
    assert work.series_id == first


async def test_get_series_by_slug_follows_a_tombstone(db_session):
    work = await upsert_work_from_ol(db_session, _ol("OL10W", "Morning Star"))
    old_slug = (await db_session.get(Series, work.series_id)).slug
    await upsert_work_from_ol(db_session, _ol("OL10W", "Morning Star", ["franchise:Red Rising"]))
    found = await series_service.get_series_by_slug(db_session, old_slug)
    assert found.id == work.series_id
    assert found.slug == "red-rising"
    assert await series_service.get_series_by_slug(db_session, "nope") is None


async def test_merge_moves_a_singletons_threads_into_the_targets_room(db_session):
    source = Work(source=WorkSource.heuristic, external_id="h1", canonical_key="red rising\x1fpierce brown",
                  title="Red Rising", author="Pierce Brown", kind=WorkKind.single,
                  identity_provenance=WorkProvenance.heuristic)
    db_session.add(source)
    await db_session.flush()
    source_series = await db_session.get(Series, source.series_id)
    user = await _user(db_session)
    untagged = Thread(title="Untagged", user_id=user.id, series_id=source.series_id)
    db_session.add(untagged)
    await db_session.flush()

    target = await upsert_work_from_ol(db_session, _ol("OL11W", "Red Rising", ["franchise:Red Rising"]))
    # upsert_work_from_ol absorbs the heuristic twin, which calls merge_works.
    await db_session.refresh(untagged)
    await db_session.refresh(source)
    await db_session.refresh(source_series)
    assert untagged.series_id == target.series_id
    assert untagged.work_id == target.id
    assert source.series_id == target.series_id
    assert source_series.merged_into_id == target.series_id

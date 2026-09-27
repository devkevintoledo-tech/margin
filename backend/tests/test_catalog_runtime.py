"""Runtime code after a catalog load: search and series assignment respect the release."""

import uuid

from sqlalchemy import func, select

from app.models import (
    CatalogRelease, Series, SeriesKind, SeriesProvenance, SeriesSource, Work, WorkAlias, WorkKind,
    WorkProvenance, WorkSource,
)
from app.services.open_library import OLWork
from app.services.series import assign_series
from app.services.works import upsert_work_from_ol


async def _release_work(db, ol_id, title, kind=SeriesKind.singleton):
    db.add(CatalogRelease(version="2026.10.1", manifest={}))
    await db.flush()
    room = Series(source=SeriesSource.heuristic, external_id=f"single:{ol_id}", name=title,
                  slug=f"release-{ol_id.lower()}", canonical_key=title.lower(), kind=kind,
                  provenance=SeriesProvenance.single, catalog_release="2026.10.1")
    db.add(room)
    await db.flush()
    work = Work(source=WorkSource.openlibrary, external_id=ol_id, canonical_key=f"{title.lower()}\x1fpierce brown",
                title=title, author="Pierce Brown", kind=WorkKind.single, identity_provenance=WorkProvenance.isbn,
                series_id=room.id, catalog_release="2026.10.1")
    db.add(work)
    await db.flush()
    return work, room


async def test_a_release_singleton_is_never_promoted_by_runtime_tags(db_session):
    work, room = await _release_work(db_session, "OL33W", "Iron Gold")
    work.subjects = "franchise:Red Rising"
    assert (await assign_series(db_session, work)).id == room.id
    assert work.series_id == room.id
    assert (await db_session.get(Series, room.id)).merged_into_id is None


async def test_a_runtime_singleton_is_still_promoted(db_session):
    work = Work(source=WorkSource.openlibrary, external_id="OL1W", canonical_key="x\x1fy", title="Golden Son",
                author="Pierce Brown", kind=WorkKind.single, identity_provenance=WorkProvenance.isbn)
    db_session.add(work)
    await db_session.flush()
    work.subjects = "franchise:Red Rising"
    series = await assign_series(db_session, work)
    assert series.kind is SeriesKind.series


async def test_a_search_hit_for_a_merged_ol_id_lands_on_the_release_work(db_session):
    work, _ = await _release_work(db_session, "OL30W", "Red Rising")
    db_session.add(WorkAlias(ol_work_id="OL36W", work_id=work.id))
    await db_session.flush()
    found = await upsert_work_from_ol(db_session, OLWork(
        key="OL36W", title="Red Rising", author="Pierce Brown", first_publish_year=2014,
        edition_count=3, isbn_13s=frozenset(), subjects=("franchise:Red Rising",)))
    assert found.id == work.id
    assert await db_session.scalar(select(func.count()).select_from(Work)) == 1

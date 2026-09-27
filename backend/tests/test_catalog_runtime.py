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


async def test_a_search_hit_leaves_a_release_works_catalog_data_alone(db_session):
    # The release summed popularity across merged duplicates and chose the
    # subjects the ranker indexes; one runtime search doc must not undo that.
    work, _ = await _release_work(db_session, "OL30W", "Red Rising")
    work.readinglog_count, work.subjects, work.ol_cover_id = 900, "franchise:Red Rising", 7
    db_session.add(WorkAlias(ol_work_id="OL36W", work_id=work.id))
    await db_session.flush()
    await upsert_work_from_ol(db_session, OLWork(
        key="OL36W", title="Red Rising", author="Pierce Brown", first_publish_year=2014, edition_count=3,
        isbn_13s=frozenset(), subjects=("Mars",), readinglog_count=100, cover_id=99))
    assert (work.readinglog_count, work.subjects, work.ol_cover_id) == (900, "franchise:Red Rising", 7)


async def test_merging_a_tombstones_target_repoints_the_tombstone(db_session):
    from app.services.works import merge_works

    def w(ext, source=WorkSource.openlibrary):
        return Work(source=source, external_id=ext, canonical_key=f"{ext}\x1fx", title=ext, author="X",
                    kind=WorkKind.single, identity_provenance=WorkProvenance.isbn)

    first, middle, last = w("h1", WorkSource.heuristic), w("OL2W"), w("OL3W")
    db_session.add_all([first, middle, last])
    await db_session.flush()
    await merge_works(db_session, first, middle)
    await merge_works(db_session, middle, last)
    assert first.merged_into_id == last.id  # no two-hop chain


async def test_a_child_series_slug_resolves_to_its_room(db_session):
    from app.services.series import get_series_by_slug

    _, room = await _release_work(db_session, "OL1W", "Elantris", kind=SeriesKind.series)
    child = Series(source=SeriesSource.wikidata, external_id="wd:Q1", name="Mistborn", slug="mistborn",
                   canonical_key="mistborn", kind=SeriesKind.series, provenance=SeriesProvenance.wikidata,
                   catalog_release="2026.10.1", parent_series_id=room.id)
    db_session.add(child)
    await db_session.flush()
    assert (await get_series_by_slug(db_session, "mistborn")).id == room.id

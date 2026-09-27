"""The catalog tables: releases, series nesting and membership, work aliases."""

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import (
    CatalogRelease, MembershipConfidence, Series, SeriesKind, SeriesMember, SeriesProvenance, SeriesSource,
    Work, WorkAlias, WorkKind, WorkProvenance, WorkSource,
)


def _series(name, **kw):
    return Series(source=kw.pop("source", SeriesSource.wikidata), external_id=f"wd:{uuid.uuid4().hex[:6]}",
                  name=name, slug=f"{name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:4]}",
                  canonical_key=name.lower(), kind=SeriesKind.series,
                  provenance=kw.pop("provenance", SeriesProvenance.wikidata), **kw)


async def _work(db, series):
    w = Work(source=WorkSource.openlibrary, external_id=f"OL{uuid.uuid4().hex[:6]}W", canonical_key="k",
             title="Mistborn", author="Brandon Sanderson", kind=WorkKind.single,
             identity_provenance=WorkProvenance.isbn, series_id=series.id)
    db.add(w)
    await db.flush()
    return w


async def test_a_release_stamps_series_and_works(db_session):
    db_session.add(CatalogRelease(version="2026.10.1", manifest={"version": "2026.10.1"}))
    await db_session.flush()
    cosmere = _series("Cosmere", catalog_release="2026.10.1")
    db_session.add(cosmere)
    await db_session.flush()
    mistborn = _series("Mistborn", catalog_release="2026.10.1", parent_series_id=cosmere.id)
    db_session.add(mistborn)
    await db_session.flush()
    work = await _work(db_session, cosmere)
    work.catalog_release = "2026.10.1"
    db_session.add(SeriesMember(series_id=mistborn.id, work_id=work.id, position=2.5,
                                provenance=SeriesProvenance.wikidata, confidence=MembershipConfidence.high))
    db_session.add(WorkAlias(ol_work_id="OL1W", work_id=work.id))
    await db_session.flush()
    member = await db_session.get(SeriesMember, (mistborn.id, work.id))
    assert member.position == 2.5
    assert (await db_session.get(Series, mistborn.id)).parent_series_id == cosmere.id
    assert (await db_session.get(WorkAlias, "OL1W")).work_id == work.id


async def test_a_work_is_a_member_of_a_series_once(db_session):
    series = _series("Red Rising")
    db_session.add(series)
    await db_session.flush()
    work = await _work(db_session, series)
    for _ in range(2):
        db_session.add(SeriesMember(series_id=series.id, work_id=work.id, position=1,
                                    provenance=SeriesProvenance.ol_tag, confidence=MembershipConfidence.medium))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_a_stamp_must_name_a_loaded_release(db_session):
    db_session.add(_series("Dune", catalog_release="1999.01.1"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_runtime_series_record_their_provenance(db_session):
    work = Work(source=WorkSource.openlibrary, external_id="OL9W", canonical_key="k", title="Dune",
                author="Frank Herbert", kind=WorkKind.single, identity_provenance=WorkProvenance.isbn)
    db_session.add(work)
    await db_session.flush()
    assert (await db_session.get(Series, work.series_id)).provenance is SeriesProvenance.single

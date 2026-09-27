"""Loading a catalog release (spec §6.2): upserts, adoption, absent rows, idempotence."""

import json
import uuid

import pytest
from sqlalchemy import func, select

from app.models import (
    AuthProvider, Book, CatalogRelease, Genre, Series, SeriesKind, SeriesMember, SeriesProvenance,
    SeriesSource, Shelf, ShelfStatus, Thread, User, Work, WorkAlias, WorkKind, WorkProvenance, WorkSource,
)
from app.services.catalog_loader import CatalogLoadError, load_release, read_release
from app.services.series import get_series_by_slug

RR, ASOIAF = uuid.uuid4(), uuid.uuid4()
RED, GOLD, DARK, GAME = (uuid.uuid4() for _ in range(4))
ED_RED = uuid.uuid4()

SERIES = [
    {"id": RR, "name": "Red Rising", "slug": "red-rising", "key": "ol:red rising"},
    {"id": ASOIAF, "name": "A Song of Ice and Fire", "slug": "a-song-of-ice-and-fire", "key": "wd:Q45875",
     "source": "wikidata", "provenance": "wikidata"},
]
WORKS = [
    {"id": RED, "ol_work_id": "OL30W", "title": "Red Rising", "author": "Pierce Brown", "series_id": RR,
     "first_publish_year": 2014, "subjects": "franchise:Red Rising\nScience fiction", "representative_edition_id": ED_RED},
    {"id": GOLD, "ol_work_id": "OL31W", "title": "Golden Son", "author": "Pierce Brown", "series_id": RR},
    {"id": DARK, "ol_work_id": "OL34W", "title": "Dark Age", "author": "Pierce Brown", "series_id": RR,
     "first_publish_year": 2015},
    {"id": GAME, "ol_work_id": "OL10W", "title": "A Game of Thrones", "author": "George R. R. Martin",
     "series_id": ASOIAF},
]
MEMBERS = [
    {"series_id": RR, "work_id": RED, "position": 1.0},
    {"series_id": RR, "work_id": GOLD, "position": 2.0},
    {"series_id": RR, "work_id": DARK, "position": 5.0},
    {"series_id": ASOIAF, "work_id": GAME, "position": 1.0, "provenance": "wikidata", "confidence": "high"},
]
EDITIONS = [{"id": ED_RED, "ol_edition_id": "OL300M", "work_id": RED, "title": "Red Rising",
             "cover_url": "https://covers.openlibrary.org/b/id/1-L.jpg"}]
ALIASES = [{"ol_work_id": "OL36W", "work_id": RED}]


def v1(write_release, **changes):
    tables = {"series": SERIES, "works": WORKS, "series_members": MEMBERS, "editions": EDITIONS,
              "work_aliases": ALIASES, **changes}
    return read_release(write_release("2026.10.1", **tables))


async def count(db, model):
    return await db.scalar(select(func.count()).select_from(model))


async def user(db):
    u = User(email=f"{uuid.uuid4().hex[:8]}@x.test", username=uuid.uuid4().hex[:10],
             auth_provider=AuthProvider.email, password_hash="x")
    db.add(u)
    await db.flush()
    return u


async def runtime_work(db, external_id, title="Red Rising", source=WorkSource.openlibrary, key=None):
    w = Work(source=source, external_id=external_id, canonical_key=key or f"{title.lower()}\x1fpierce brown",
             title=title, author="Pierce Brown", kind=WorkKind.single, identity_provenance=WorkProvenance.isbn)
    db.add(w)
    await db.flush()
    return w


async def test_loads_every_table_and_stamps_the_release(db_session, write_release):
    db_session.add(Genre(name="Science Fiction", slug="science-fiction"))
    await db_session.flush()
    stats = await load_release(db_session, v1(write_release))
    assert stats.rows == {"works": 4, "editions": 1, "series": 2, "series_members": 4, "work_aliases": 1}
    red = await db_session.get(Work, RED)
    assert (red.catalog_release, red.series_id, red.external_id) == ("2026.10.1", RR, "OL30W")
    assert red.representative_book_id == ED_RED
    assert red.genre_id is not None
    asoiaf = await db_session.get(Series, ASOIAF)
    assert (asoiaf.source, asoiaf.provenance, asoiaf.external_id) == (
        SeriesSource.wikidata, SeriesProvenance.wikidata, "wd:Q45875")
    member = await db_session.get(SeriesMember, (RR, DARK))
    assert member.position == 5.0
    assert (await db_session.get(WorkAlias, "OL36W")).work_id == RED
    assert (await db_session.get(Book, ED_RED)).source == "openlibrary"
    assert (await db_session.get(CatalogRelease, "2026.10.1")) is not None


async def test_loading_the_same_release_twice_is_a_no_op(db_session, write_release):
    release = v1(write_release)
    await load_release(db_session, release)
    again = await load_release(db_session, release)
    assert again.noop
    assert await count(db_session, Work) == 4


async def test_an_older_release_is_refused(db_session, write_release, tmp_path):
    await load_release(db_session, v1(write_release))
    older = read_release(write_release("2026.09.1", series=SERIES, works=WORKS))
    with pytest.raises(CatalogLoadError, match="older"):
        await load_release(db_session, older)


def test_a_tampered_file_is_refused(write_release):
    folder = write_release("2026.10.1", series=SERIES, works=WORKS)
    (folder / "works.parquet").write_bytes(b"not parquet")
    with pytest.raises(CatalogLoadError, match="checksum"):
        read_release(folder)


def test_a_newer_schema_is_refused(write_release):
    folder = write_release("2026.10.1")
    manifest = json.loads((folder / "manifest.json").read_text())
    (folder / "manifest.json").write_text(json.dumps({**manifest, "schema_version": 2}))
    with pytest.raises(CatalogLoadError, match="schema"):
        read_release(folder)


async def test_a_runtime_work_is_adopted_with_its_threads_and_shelves(db_session, write_release):
    reader = await user(db_session)
    runtime = await runtime_work(db_session, "OL30W")  # gets a runtime singleton room
    room = runtime.series_id
    db_session.add_all([
        Thread(title="Is Darrow right?", user_id=reader.id, series_id=room),
        Shelf(user_id=reader.id, work_id=runtime.id, status=ShelfStatus.reading),
    ])
    await db_session.flush()

    stats = await load_release(db_session, v1(write_release))
    assert stats.adopted == 1
    await db_session.refresh(runtime)
    assert runtime.merged_into_id == RED
    thread = (await db_session.execute(select(Thread))).scalar_one()
    assert (thread.series_id, thread.work_id) == (RR, RED)  # a singleton's thread is about its book
    shelf = (await db_session.execute(select(Shelf))).scalar_one()
    assert shelf.work_id == RED
    assert (await db_session.get(Series, room)).merged_into_id == RR


async def test_a_runtime_work_is_adopted_through_an_alias(db_session, write_release):
    runtime = await runtime_work(db_session, "OL36W")
    await load_release(db_session, v1(write_release))
    await db_session.refresh(runtime)
    assert runtime.merged_into_id == RED


async def test_a_heuristic_work_is_adopted_by_title_and_author(db_session, write_release):
    runtime = await runtime_work(db_session, "abc123", title="Golden Son", source=WorkSource.heuristic)
    await load_release(db_session, v1(write_release))
    await db_session.refresh(runtime)
    assert runtime.merged_into_id == GOLD


async def test_a_runtime_tag_room_follows_its_books_and_frees_its_slug(db_session, write_release):
    reader = await user(db_session)
    tag_room = Series(source=SeriesSource.openlibrary, external_id="franchise:red rising", name="Red Rising",
                      slug="red-rising", canonical_key="red rising", kind=SeriesKind.series,
                      provenance=SeriesProvenance.ol_tag)
    db_session.add(tag_room)
    await db_session.flush()
    for ol in ("OL30W", "OL31W"):
        w = await runtime_work(db_session, ol)
        w.series_id = tag_room.id
    db_session.add(Thread(title="Best book?", user_id=reader.id, series_id=tag_room.id))
    await db_session.flush()

    stats = await load_release(db_session, v1(write_release))
    assert stats.reslugged == 1
    await db_session.refresh(tag_room)
    assert tag_room.slug == "red-rising-2"
    assert tag_room.merged_into_id == RR
    thread = (await db_session.execute(select(Thread))).scalar_one()
    assert (thread.series_id, thread.work_id) == (RR, None)  # untagged stays series-wide
    assert (await get_series_by_slug(db_session, "red-rising")).id == RR
    assert (await get_series_by_slug(db_session, "red-rising-2")).id == RR


async def test_a_second_release_moves_tagged_threads_and_settles_absent_rows(db_session, write_release):
    reader_id = (await user(db_session)).id  # the load expires every object the session holds
    await load_release(db_session, v1(write_release))
    db_session.add_all([
        Thread(title="Dark Age ending", user_id=reader_id, series_id=RR, work_id=DARK),
        Thread(title="Whole saga", user_id=reader_id, series_id=RR),
        Shelf(user_id=reader_id, work_id=GAME, status=ShelfStatus.read),
    ])
    await db_session.flush()

    new_room = uuid.uuid4()
    v2 = read_release(write_release(
        "2026.11.1",
        # Dark Age moves to its own sub-series room; Golden Son is now a merged alias of Red Rising;
        # A Game of Thrones is gone but shelved; A Song of Ice and Fire is gone and empty.
        series=[SERIES[0], {"id": new_room, "name": "Red God", "slug": "red-god", "key": "ol:red god"}],
        works=[{**WORKS[0], "title": "Red Rising (renamed)"}, {**WORKS[2], "series_id": new_room}],
        series_members=[MEMBERS[0], {"series_id": new_room, "work_id": DARK, "position": 1.0}],
        work_aliases=[*ALIASES, {"ol_work_id": "OL31W", "work_id": RED}],
    ))
    stats = await load_release(db_session, v2)

    db_session.expire_all()
    assert (await db_session.get(Work, RED)).title == "Red Rising (renamed)"
    tagged = (await db_session.execute(select(Thread).where(Thread.work_id == DARK))).scalar_one()
    untagged = (await db_session.execute(select(Thread).where(Thread.work_id.is_(None)))).scalar_one()
    assert tagged.series_id == new_room
    assert untagged.series_id == RR
    assert (await db_session.get(Work, GOLD)).merged_into_id == RED
    assert (await db_session.get(Work, GAME)) is not None and stats.kept_works == 1
    assert await db_session.get(SeriesMember, (RR, GOLD)) is None
    assert (await db_session.get(Series, ASOIAF)) is not None  # still the kept book's room


async def test_dropping_a_work_does_not_resurrect_the_runtime_work_it_adopted(db_session, write_release):
    runtime = await runtime_work(db_session, "OL34W", title="Dark Age")  # nobody discussed it
    await load_release(db_session, v1(write_release))
    runtime_id = runtime.id
    v2 = read_release(write_release("2026.11.1", series=SERIES, works=[w for w in WORKS if w["id"] != DARK],
                                    series_members=[m for m in MEMBERS if m["work_id"] != DARK]))
    await load_release(db_session, v2)
    db_session.expire_all()
    ghost = await db_session.get(Work, runtime_id)
    assert ghost is None or ghost.merged_into_id is not None
    live = await db_session.scalar(select(func.count()).select_from(Work).where(
        Work.external_id.like("merged:%"), Work.merged_into_id.is_(None)))
    assert live == 0


async def test_a_singleton_joining_a_series_keeps_its_threads_about_its_book(db_session, write_release):
    reader_id = (await user(db_session)).id
    iron, single = uuid.uuid4(), uuid.uuid4()
    lone = {"id": single, "name": "Iron Gold", "slug": "iron-gold", "key": "single:OL33W",
            "source": "heuristic", "provenance": "single", "kind": "singleton"}
    book = {"id": iron, "ol_work_id": "OL33W", "title": "Iron Gold", "author": "Pierce Brown"}
    await load_release(db_session, read_release(write_release(
        "2026.10.1", series=[*SERIES, lone], works=[*WORKS, {**book, "series_id": single}], editions=EDITIONS)))
    db_session.add(Thread(title="Lyria?", user_id=reader_id, series_id=single))
    await db_session.flush()
    await load_release(db_session, read_release(write_release(
        "2026.11.1", series=SERIES, works=[*WORKS, {**book, "series_id": RR}], editions=EDITIONS,
        series_members=[*MEMBERS, {"series_id": RR, "work_id": iron, "position": 4.0}])))
    db_session.expire_all()
    thread = (await db_session.execute(select(Thread))).scalar_one()
    assert (thread.series_id, thread.work_id) == (RR, iron)

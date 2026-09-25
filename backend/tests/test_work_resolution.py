import uuid

import respx
from httpx import Response
from sqlalchemy import select

from app.models import (
    AuthProvider,
    Book,
    Genre,
    Shelf,
    ShelfStatus,
    Thread,
    User,
    Work,
    WorkKind,
    WorkProvenance,
    WorkSource,
)
from app.services import works as works_service
from app.services.open_library import OLWork
from app.services.works import upsert_work_from_ol

SEARCH_URL = "https://openlibrary.org/search.json"

RED_RISING_DOC = {
    "key": "/works/OL17076473W",
    "title": "Red Rising",
    "author_name": ["Pierce Brown"],
    "first_publish_year": 2014,
    "edition_count": 26,
    "isbn": ["9780345539809", "9781444758986"],
}


def make_edition(**overrides) -> Book:
    defaults = dict(
        source="google_books",
        external_id=uuid.uuid4().hex[:12],
        title="Red Rising",
        author="Pierce Brown",
    )
    defaults.update(overrides)
    return Book(**defaults)


@respx.mock
async def test_editions_sharing_an_isbn_work_collapse_into_one_work(db_session):
    respx.get(SEARCH_URL).mock(return_value=Response(200, json={"docs": [RED_RISING_DOC]}))
    paperback = make_edition(isbn_13="9780345539809", cover_url="https://x/cover.jpg")
    deluxe = make_edition(title="Red Rising (Deluxe Slipcase Edition)", isbn_13="9781444758986")
    db_session.add_all([paperback, deluxe])
    await db_session.flush()

    resolved = await works_service.resolve_editions(db_session, [paperback, deluxe])

    assert resolved[paperback.id].id == resolved[deluxe.id].id
    work = resolved[paperback.id]
    assert work.source is WorkSource.openlibrary
    assert work.external_id == "OL17076473W"
    assert work.identity_provenance is WorkProvenance.isbn
    assert work.title == "Red Rising"  # OL's clean name, not the deluxe title


@respx.mock
async def test_representative_is_the_richest_edition(db_session):
    respx.get(SEARCH_URL).mock(return_value=Response(200, json={"docs": [RED_RISING_DOC]}))
    bare = make_edition(isbn_13="9780345539809")
    rich = make_edition(
        isbn_13="9781444758986",
        cover_url="https://x/cover.jpg",
        description="A boy from the mines.",
        page_count=400,
    )
    db_session.add_all([bare, rich])
    await db_session.flush()

    resolved = await works_service.resolve_editions(db_session, [bare, rich])
    assert resolved[bare.id].representative_book_id == rich.id


@respx.mock
async def test_falls_back_to_title_author_without_an_isbn(db_session):
    respx.get(SEARCH_URL).mock(return_value=Response(200, json={"docs": [RED_RISING_DOC]}))
    edition = make_edition(isbn_13=None)
    db_session.add(edition)
    await db_session.flush()

    work = (await works_service.resolve_editions(db_session, [edition]))[edition.id]
    assert work.source is WorkSource.openlibrary
    assert work.identity_provenance is WorkProvenance.title_author


@respx.mock
async def test_falls_back_to_heuristic_when_open_library_is_down(db_session):
    respx.get(SEARCH_URL).mock(return_value=Response(503, json={}))
    a = make_edition(title="Red Rising 01", isbn_13="9780345539809")
    b = make_edition(title="Red Rising (Deluxe Slipcase Edition)")
    db_session.add_all([a, b])
    await db_session.flush()

    resolved = await works_service.resolve_editions(db_session, [a, b])
    work = resolved[a.id]
    assert work.source is WorkSource.heuristic
    assert work.identity_provenance is WorkProvenance.heuristic
    # The heuristic still groups the two editions — it just can't name the work
    # with an authority's id.
    assert resolved[b.id].id == work.id


@respx.mock
async def test_collections_are_classified_not_dropped(db_session):
    respx.get(SEARCH_URL).mock(return_value=Response(503, json={}))
    bundle = make_edition(title="Red Rising 3-Book Bundle")
    db_session.add(bundle)
    await db_session.flush()

    work = (await works_service.resolve_editions(db_session, [bundle]))[bundle.id]
    assert work.kind is WorkKind.collection


@respx.mock
async def test_a_resolved_edition_is_never_re_resolved(db_session):
    route = respx.get(SEARCH_URL).mock(
        return_value=Response(200, json={"docs": [RED_RISING_DOC]})
    )
    edition = make_edition(isbn_13="9780345539809")
    db_session.add(edition)
    await db_session.flush()

    await works_service.resolve_editions(db_session, [edition])
    calls_after_first = route.call_count
    await works_service.resolve_editions(db_session, [edition])
    assert route.call_count == calls_after_first  # zero upstream cost on repeat


@respx.mock
async def test_a_heuristic_work_is_absorbed_when_open_library_answers_later(db_session):
    # First pass: OL is down, so the edition lands in a heuristic work.
    respx.get(SEARCH_URL).mock(return_value=Response(503, json={}))
    first = make_edition(title="Red Rising 01")
    db_session.add(first)
    await db_session.flush()
    heuristic_work = (await works_service.resolve_editions(db_session, [first]))[first.id]
    assert heuristic_work.source is WorkSource.heuristic

    # Second pass: OL answers for a sibling edition with the same canonical key.
    respx.get(SEARCH_URL).mock(return_value=Response(200, json={"docs": [RED_RISING_DOC]}))
    second = make_edition(isbn_13="9780345539809")
    db_session.add(second)
    await db_session.flush()
    ol_work = (await works_service.resolve_editions(db_session, [second]))[second.id]

    assert ol_work.source is WorkSource.openlibrary
    await db_session.refresh(heuristic_work)
    assert heuristic_work.merged_into_id == ol_work.id
    await db_session.refresh(first)
    assert first.work_id == ol_work.id


@respx.mock
async def test_genre_comes_from_the_hint_not_from_the_edition(db_session):
    from app.models import Genre

    respx.get(SEARCH_URL).mock(return_value=Response(200, json={"docs": [RED_RISING_DOC]}))
    genre = Genre(name="Science Fiction", slug="science-fiction")
    edition = make_edition(isbn_13="9780345539809")
    db_session.add_all([genre, edition])
    await db_session.flush()

    resolved = await works_service.resolve_editions(
        db_session, [edition], genre_hints={edition.id: genre.id}
    )
    assert resolved[edition.id].genre_id == genre.id


async def test_merge_moves_threads_and_shelves(db_session):
    source = Work(
        source=WorkSource.heuristic,
        external_id="abc",
        canonical_key="red rising\x1fpierce brown",
        title="Red Rising",
        author="Pierce Brown",
        kind=WorkKind.single,
        identity_provenance=WorkProvenance.heuristic,
    )
    target = Work(
        source=WorkSource.openlibrary,
        external_id="OL17076473W",
        canonical_key="red rising\x1fpierce brown",
        title="Red Rising",
        author="Pierce Brown",
        kind=WorkKind.single,
        identity_provenance=WorkProvenance.isbn,
    )
    user = User(
        email="m@example.com",
        username="merger",
        password_hash="x",
        auth_provider=AuthProvider.email,
    )
    db_session.add_all([source, target, user])
    await db_session.flush()

    thread = Thread(title="Is Darrow a hero?", user_id=user.id, work_id=source.id)
    shelf = Shelf(user_id=user.id, work_id=source.id, status=ShelfStatus.read)
    db_session.add_all([thread, shelf])
    await db_session.flush()

    await works_service.merge_works(db_session, source, target)

    await db_session.refresh(thread)
    await db_session.refresh(shelf)
    await db_session.refresh(source)
    assert thread.work_id == target.id
    assert shelf.work_id == target.id
    assert source.merged_into_id == target.id


async def test_merge_keeps_the_oldest_row_on_a_shelf_collision(db_session):
    source = Work(
        source=WorkSource.heuristic, external_id="abc",
        canonical_key="k", title="T", author="A",
        kind=WorkKind.single, identity_provenance=WorkProvenance.heuristic,
    )
    target = Work(
        source=WorkSource.openlibrary, external_id="OL1W",
        canonical_key="k", title="T", author="A",
        kind=WorkKind.single, identity_provenance=WorkProvenance.isbn,
    )
    user = User(
        email="c@example.com",
        username="collider",
        password_hash="x",
        auth_provider=AuthProvider.email,
    )
    db_session.add_all([source, target, user])
    await db_session.flush()

    db_session.add(Shelf(user_id=user.id, work_id=target.id, status=ShelfStatus.read))
    await db_session.flush()
    db_session.add(Shelf(user_id=user.id, work_id=source.id, status=ShelfStatus.want_to_read))
    await db_session.flush()

    await works_service.merge_works(db_session, source, target)

    rows = (
        await db_session.execute(select(Shelf).where(Shelf.user_id == user.id))
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].status is ShelfStatus.read  # the older row survived


async def test_canonical_work_follows_the_tombstone(db_session):
    target = Work(
        source=WorkSource.openlibrary, external_id="OL1W",
        canonical_key="k", title="T", author="A",
        kind=WorkKind.single, identity_provenance=WorkProvenance.isbn,
    )
    db_session.add(target)
    await db_session.flush()
    source = Work(
        source=WorkSource.heuristic, external_id="abc",
        canonical_key="k", title="T", author="A",
        kind=WorkKind.single, identity_provenance=WorkProvenance.heuristic,
        merged_into_id=target.id,
    )
    db_session.add(source)
    await db_session.flush()

    assert (await works_service.canonical_work(db_session, source)).id == target.id


@respx.mock
async def test_a_heuristic_work_keeps_a_readable_title(db_session):
    """The heuristic tier names the work from an edition — in title case.

    The canonical key is lowercased for matching; the title a reader sees
    must not be.
    """
    respx.get(SEARCH_URL).mock(return_value=Response(503, json={}))
    edition = make_edition(title="Red Rising (Deluxe Slipcase Edition)")
    db_session.add(edition)
    await db_session.flush()

    work = (await works_service.resolve_editions(db_session, [edition]))[edition.id]
    assert work.source is WorkSource.heuristic
    assert work.title == "Red Rising"
    assert work.canonical_key == "red rising\x1fpierce brown"


@respx.mock
async def test_an_edition_joins_an_existing_open_library_work_when_resolution_fails(db_session):
    """A later unresolved edition must not stand up a twin beside its own work.

    `_absorb_heuristic_twin` only fires when an Open Library work is *created*.
    Creation order is whatever the search returned, so the reverse case — the
    OL work already exists and the heuristic edition arrives second — has to be
    handled here or the duplicate is permanent.
    """
    respx.get(SEARCH_URL).mock(return_value=Response(200, json={"docs": [RED_RISING_DOC]}))
    resolved_first = make_edition(isbn_13="9780345539809")
    db_session.add(resolved_first)
    await db_session.flush()
    ol_work = (await works_service.resolve_editions(db_session, [resolved_first]))[
        resolved_first.id
    ]
    assert ol_work.source is WorkSource.openlibrary

    # Open Library goes down; a sibling edition of the same book arrives.
    respx.get(SEARCH_URL).mock(return_value=Response(503, json={}))
    later = make_edition(title="Red Rising (Deluxe Slipcase Edition)")
    db_session.add(later)
    await db_session.flush()
    got = (await works_service.resolve_editions(db_session, [later]))[later.id]

    assert got.id == ol_work.id
    others = (
        await db_session.execute(
            select(Work).where(
                Work.canonical_key == ol_work.canonical_key,
                Work.merged_into_id.is_(None),
            )
        )
    ).scalars().all()
    assert len(others) == 1


@respx.mock
async def test_a_merge_inside_one_batch_does_not_leave_a_stale_mapping(db_session):
    """A work tombstoned mid-batch must not still be returned for its editions.

    The first edition is recorded against a heuristic work; a later edition in
    the *same* batch resolves via Open Library, which absorbs that heuristic
    work. Without re-canonicalizing, the first edition still maps to the
    tombstone and search renders it as a second, empty card.
    """
    # Open Library knows the ISBN but its title+author search finds nothing, so
    # the first (ISBN-less) edition falls to the heuristic tier.
    def by_query(request):
        if "isbn" in request.url.params.get("q", ""):
            return Response(200, json={"docs": [RED_RISING_DOC]})
        return Response(200, json={"docs": []})

    respx.get(SEARCH_URL).mock(side_effect=by_query)

    heuristic_first = make_edition(title="Red Rising", isbn_13=None)
    resolves_second = make_edition(title="Red Rising", isbn_13="9780345539809")
    db_session.add_all([heuristic_first, resolves_second])
    await db_session.flush()

    resolved = await works_service.resolve_editions(
        db_session, [heuristic_first, resolves_second]
    )

    assert resolved[heuristic_first.id].merged_into_id is None
    assert resolved[heuristic_first.id].id == resolved[resolves_second.id].id


async def test_a_tombstone_keeps_no_presentation_of_its_own(db_session):
    """A merged work must not render with the cover of editions it lost."""
    from app.services.works import load_work_presentation

    target = Work(
        source=WorkSource.openlibrary, external_id="OL1W", canonical_key="k",
        title="T", author="A", kind=WorkKind.single,
        identity_provenance=WorkProvenance.isbn,
    )
    source = Work(
        source=WorkSource.heuristic, external_id="abc", canonical_key="k",
        title="T", author="A", kind=WorkKind.single,
        identity_provenance=WorkProvenance.heuristic,
    )
    db_session.add_all([target, source])
    await db_session.flush()

    edition = make_edition(cover_url="https://x/cover.jpg", work_id=source.id)
    db_session.add(edition)
    await db_session.flush()
    source.representative_book_id = edition.id
    await db_session.flush()

    await works_service.merge_works(db_session, source, target)

    presentation = await load_work_presentation(db_session, [source.id, target.id])
    assert presentation[source.id].cover_url is None
    assert presentation[source.id].edition_count == 0
    assert presentation[target.id].cover_url == "https://x/cover.jpg"
    assert presentation[target.id].edition_count == 1


def ol_work(**kw):
    base = dict(
        key="OL17076473W",
        title="Red Rising",
        author="Pierce Brown",
        first_publish_year=2014,
        edition_count=26,
        isbn_13s=frozenset({"9780345539809"}),
        cover_id=7316188,
        readinglog_count=1036,
        ratings_count=102,
        subjects=("franchise:Red Rising", "genre:science fiction"),
    )
    base.update(kw)
    return OLWork(**base)


async def test_upsert_creates_a_work_with_cover_popularity_and_subjects(db_session):
    work = await upsert_work_from_ol(db_session, ol_work())
    assert work.source is WorkSource.openlibrary
    assert work.external_id == "OL17076473W"
    assert work.title == "Red Rising"
    assert work.ol_cover_id == 7316188
    assert work.readinglog_count == 1036
    assert work.ratings_count == 102
    assert work.ol_edition_count == 26
    assert "franchise:Red Rising" in work.subjects
    assert work.identity_provenance is WorkProvenance.isbn


async def test_upsert_is_idempotent_on_the_open_library_key(db_session):
    first = await upsert_work_from_ol(db_session, ol_work())
    second = await upsert_work_from_ol(db_session, ol_work())
    assert first.id == second.id
    rows = (await db_session.execute(select(Work))).scalars().all()
    assert len(rows) == 1


async def test_upsert_refreshes_popularity_on_an_existing_work(db_session):
    await upsert_work_from_ol(db_session, ol_work(readinglog_count=10))
    work = await upsert_work_from_ol(db_session, ol_work(readinglog_count=1036))
    assert work.readinglog_count == 1036


async def test_upsert_assigns_a_genre_from_the_open_library_subject_tag(db_session):
    genre = Genre(name="Science Fiction", slug="science-fiction")
    db_session.add(genre)
    await db_session.flush()
    work = await upsert_work_from_ol(db_session, ol_work())
    assert work.genre_id == genre.id


async def test_upsert_absorbs_a_matching_heuristic_work(db_session):
    from app.services.work_identity import canonical_key, heuristic_external_id

    key = canonical_key("Red Rising", "Pierce Brown")
    twin = Work(
        source=WorkSource.heuristic,
        external_id=heuristic_external_id(key),
        canonical_key=key,
        title="Red Rising",
        author="Pierce Brown",
        kind=WorkKind.single,
        identity_provenance=WorkProvenance.heuristic,
    )
    db_session.add(twin)
    await db_session.flush()

    work = await upsert_work_from_ol(db_session, ol_work())
    await db_session.refresh(twin)
    assert twin.merged_into_id == work.id


async def test_upsert_marks_a_box_set_as_a_collection(db_session):
    work = await upsert_work_from_ol(
        db_session, ol_work(key="OL99W", title="Red Rising Series 5 Books Collection Set")
    )
    assert work.kind is WorkKind.collection


async def test_representative_prefers_english_over_a_richer_translation(db_session):
    """The live Red Rising bug: Heyne (de) outscored Del Rey (en) on richness."""
    import uuid

    from app.models import Book, Work, WorkKind, WorkProvenance, WorkSource
    from app.services.works import _refresh_work

    work = Work(
        source=WorkSource.openlibrary,
        external_id=f"OL{uuid.uuid4().hex[:8]}W",
        canonical_key="red rising\x1fpierce brown",
        title="Red Rising",
        author="Pierce Brown",
        kind=WorkKind.single,
        identity_provenance=WorkProvenance.isbn,
    )
    db_session.add(work)
    await db_session.flush()

    heyne = Book(
        source="google_books",
        external_id="de1",
        title="Red Rising",
        author="Pierce Brown",
        language="de",
        publisher="Heyne Verlag",
        cover_url="https://x/de.jpg",
        description="Der fulminante Auftakt ...",
        isbn_13="9783453316355",
        page_count=560,
        ratings_count=900,
        work_id=work.id,
    )
    del_rey = Book(
        source="google_books",
        external_id="en1",
        title="Red Rising",
        author="Pierce Brown",
        language="en",
        publisher="Del Rey",
        cover_url="https://x/en.jpg",
        work_id=work.id,
    )
    db_session.add_all([heyne, del_rey])
    await db_session.flush()

    await _refresh_work(db_session, work)

    representative = await db_session.get(Book, work.representative_book_id)
    assert representative.external_id == "en1"

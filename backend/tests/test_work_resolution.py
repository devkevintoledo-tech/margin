import uuid

import respx
from httpx import Response
from sqlalchemy import select

from app.models import (
    AuthProvider,
    Book,
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

import uuid

import respx
from httpx import Response
from app.models import AuthProvider, Book, Thread, User, Work, WorkSource
from scripts.resolve_works import resolve_all

OL_URL = "https://openlibrary.org/search.json"

OL_RED_RISING = {
    "key": "/works/OL17076473W",
    "title": "Red Rising",
    "author_name": ["Pierce Brown"],
    "first_publish_year": 2014,
    "edition_count": 26,
    "isbn": ["9780345539809"],
}


async def seed_unresolved_edition(db_session):
    edition = Book(
        source="google_books",
        external_id=uuid.uuid4().hex[:12],
        title="Red Rising (Deluxe Slipcase Edition)",
        author="Pierce Brown",
        isbn_13="9780345539809",
    )
    db_session.add(edition)
    await db_session.flush()
    return edition


@respx.mock
async def test_backfill_resolves_unlinked_editions(db_session):
    respx.get(OL_URL).mock(return_value=Response(200, json={"docs": [OL_RED_RISING]}))
    edition = Book(
        source="google_books",
        external_id=uuid.uuid4().hex[:12],
        title="Red Rising (Deluxe Slipcase Edition)",
        author="Pierce Brown",
        isbn_13="9780345539809",
    )
    db_session.add(edition)
    await db_session.flush()

    summary = await resolve_all(db_session)

    await db_session.refresh(edition)
    assert edition.work_id is not None
    assert summary["editions_resolved"] == 1


@respx.mock
async def test_backfill_is_idempotent(db_session):
    respx.get(OL_URL).mock(return_value=Response(200, json={"docs": [OL_RED_RISING]}))
    await seed_unresolved_edition(db_session)

    await resolve_all(db_session)
    second = await resolve_all(db_session)

    assert second["editions_resolved"] == 0


@respx.mock
async def test_upgrade_promotes_a_heuristic_work_and_merges_it(db_session):
    # First pass with Open Library down produces a heuristic work.
    respx.get(OL_URL).mock(return_value=Response(503, json={}))
    edition = await seed_unresolved_edition(db_session)
    await resolve_all(db_session)

    await db_session.refresh(edition)
    heuristic = await db_session.get(Work, edition.work_id)
    assert heuristic.source is WorkSource.heuristic

    # Second pass with Open Library answering upgrades and merges.
    respx.get(OL_URL).mock(return_value=Response(200, json={"docs": [OL_RED_RISING]}))
    summary = await resolve_all(db_session, upgrade=True)

    assert summary["works_upgraded"] == 1
    await db_session.refresh(edition)
    upgraded = await db_session.get(Work, edition.work_id)
    assert upgraded.source is WorkSource.openlibrary
    assert upgraded.external_id == "OL17076473W"
    # No Open Library twin existed, so the row was promoted in place rather
    # than merged — same id, no tombstone, and nothing for callers to follow.
    assert upgraded.id == heuristic.id
    assert upgraded.merged_into_id is None


@respx.mock
async def test_upgrade_merges_into_an_existing_open_library_work(db_session):
    """When the Open Library work already exists, the heuristic row is folded in.

    The heuristic edition is titled so it cleans to a *different* canonical key
    than its sibling, which is what stops `_absorb_heuristic_twin` from having
    already merged it during the sibling's resolution. Only the ISBN retry in
    `--upgrade` can see they are the same book.
    """
    respx.get(OL_URL).mock(return_value=Response(503, json={}))
    edition = Book(
        source="google_books",
        external_id=uuid.uuid4().hex[:12],
        title="The Red Rising Saga",
        author="Pierce Brown",
        isbn_13="9780345539809",
    )
    user = User(
        email="m@example.com",
        username="merger",
        password_hash="x",
        auth_provider=AuthProvider.email,
    )
    db_session.add_all([edition, user])
    await db_session.flush()

    await resolve_all(db_session)
    await db_session.refresh(edition)
    heuristic = await db_session.get(Work, edition.work_id)
    assert heuristic.source is WorkSource.heuristic

    # A thread on the heuristic work: the merge has to carry it across.
    thread = Thread(title="Legacy thread", user_id=user.id, work_id=heuristic.id)
    db_session.add(thread)
    await db_session.flush()

    # A sibling edition resolves to the real Open Library work. Its canonical
    # key differs, so the heuristic work is left standing.
    respx.get(OL_URL).mock(return_value=Response(200, json={"docs": [OL_RED_RISING]}))
    sibling = Book(
        source="google_books",
        external_id=uuid.uuid4().hex[:12],
        title="Red Rising",
        author="Pierce Brown",
        isbn_13="9780345539809",
    )
    db_session.add(sibling)
    await db_session.flush()
    await resolve_all(db_session)
    await db_session.refresh(sibling)
    await db_session.refresh(heuristic)
    target_id = sibling.work_id
    assert target_id != heuristic.id
    assert heuristic.merged_into_id is None

    summary = await resolve_all(db_session, upgrade=True)

    assert summary["works_upgraded"] == 1
    await db_session.refresh(heuristic)
    await db_session.refresh(thread)
    assert heuristic.merged_into_id == target_id
    assert thread.work_id == target_id


@respx.mock
async def test_upgrade_refuses_a_work_whose_editions_disagree(db_session):
    """--upgrade rewrites identity in place, so it must not guess.

    If a heuristic work's own editions resolve to two different Open Library
    works, the grouping itself is wrong and no single identity is correct.
    Promoting to whichever answered first would silently pick one.
    """
    respx.get(OL_URL).mock(return_value=Response(503, json={}))
    a = Book(
        source="google_books", external_id=uuid.uuid4().hex[:12],
        title="Red Rising", author="Pierce Brown", isbn_13="9780345539809",
    )
    b = Book(
        source="google_books", external_id=uuid.uuid4().hex[:12],
        title="Red Rising", author="Pierce Brown", isbn_13="9781473646506",
    )
    db_session.add_all([a, b])
    await db_session.flush()
    await resolve_all(db_session)
    await db_session.refresh(a)
    work = await db_session.get(Work, a.work_id)
    assert work.source is WorkSource.heuristic

    # The two ISBNs belong to two different Open Library works.
    respx.get(OL_URL).mock(
        return_value=Response(200, json={"docs": [OL_RED_RISING, {
            "key": "/works/OL19340986W",
            "title": "Golden Son",
            "author_name": ["Pierce Brown"],
            "first_publish_year": 2015,
            "edition_count": 21,
            "isbn": ["9781473646506"],
        }]})
    )
    summary = await resolve_all(db_session, upgrade=True)

    assert summary["works_upgraded"] == 0
    await db_session.refresh(work)
    assert work.source is WorkSource.heuristic

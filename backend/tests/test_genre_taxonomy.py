import pytest
from sqlalchemy import select

from app.models import Genre, Thread
from app.services.genre_inference import TaxonomyError, parse_taxonomy, shipped_taxonomy
from app.services.genre_taxonomy import sync_genres
from tests.librarian_factories import make_user

TWO = parse_taxonomy([
    {"slug": "fantasy", "name": "Fantasy", "children": [{"slug": "grimdark", "name": "Grimdark"}]},
    {"slug": "mystery", "name": "Mystery"},
])


async def rows(db):
    return {g.slug: g for g in (await db.execute(select(Genre))).scalars()}


async def test_sync_creates_the_tree(db_session):
    changes = await sync_genres(db_session, TWO)
    got = await rows(db_session)
    assert got["grimdark"].parent_id == got["fantasy"].id
    assert (got["fantasy"].position, got["mystery"].position) == (0, 1)
    assert any("grimdark" in c for c in changes)


async def test_sync_is_idempotent(db_session):
    await sync_genres(db_session, TWO)
    assert await sync_genres(db_session, TWO) == []


async def test_existing_rows_keep_their_ids(db_session):
    old = Genre(name="Fantasy", slug="fantasy")
    db_session.add(old)
    await db_session.flush()
    await sync_genres(db_session, TWO)
    assert (await rows(db_session))["fantasy"].id == old.id


async def test_an_entry_missing_from_the_file_is_retired_then_unretired(db_session):
    await sync_genres(db_session, TWO)
    one = parse_taxonomy([{"slug": "fantasy", "name": "Fantasy", "children": [{"slug": "grimdark", "name": "Grimdark"}]}])
    changes = await sync_genres(db_session, one)
    assert (await rows(db_session))["mystery"].retired_at is not None
    assert any("retired mystery" in c for c in changes)
    await sync_genres(db_session, TWO)
    assert (await rows(db_session))["mystery"].retired_at is None


async def test_rename_changes_the_name_only(db_session):
    await sync_genres(db_session, TWO)
    before = (await rows(db_session))["mystery"].id
    renamed = parse_taxonomy([
        {"slug": "fantasy", "name": "Fantasy", "children": [{"slug": "grimdark", "name": "Grimdark"}]},
        {"slug": "mystery", "name": "Mystery & Crime"},
    ])
    await sync_genres(db_session, renamed)
    after = (await rows(db_session))["mystery"]
    assert (after.id, after.name) == (before, "Mystery & Crime")


async def test_a_genre_with_threads_cannot_become_a_subgenre(db_session):
    # Review Focus 3: rooms are parents only (D9).
    await sync_genres(db_session, TWO)
    user = await make_user(db_session)
    db_session.add(Thread(title="t", user_id=user.id, genre_id=(await rows(db_session))["mystery"].id))
    await db_session.flush()
    demoted = parse_taxonomy([{"slug": "fantasy", "name": "Fantasy", "children": [
        {"slug": "grimdark", "name": "Grimdark"}, {"slug": "mystery", "name": "Mystery"}]}])
    with pytest.raises(TaxonomyError, match="mystery has discussion threads"):
        await sync_genres(db_session, demoted)
    assert (await rows(db_session))["mystery"].parent_id is None  # nothing written


async def test_a_parent_with_subgenres_in_the_db_cannot_become_a_child(db_session):
    await sync_genres(db_session, TWO)
    flipped = parse_taxonomy([{"slug": "mystery", "name": "Mystery", "children": [
        {"slug": "fantasy", "name": "Fantasy"}]}, {"slug": "grimdark", "name": "Grimdark"}])
    # grimdark moves to top level in the same file, so this one is legal:
    await sync_genres(db_session, flipped)
    got = await rows(db_session)
    assert got["fantasy"].parent_id == got["mystery"].id and got["grimdark"].parent_id is None


async def test_the_shipped_taxonomy_syncs(db_session):
    await sync_genres(db_session, shipped_taxonomy())
    got = await rows(db_session)
    assert got["epic-fantasy"].parent_id == got["fantasy"].id
    assert all(g.parent_id is None or got_by_id(got, g.parent_id).parent_id is None for g in got.values())


def got_by_id(got, gid):
    return next(g for g in got.values() if g.id == gid)

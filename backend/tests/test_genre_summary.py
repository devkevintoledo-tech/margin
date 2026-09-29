from sqlalchemy import select, text

from app.models import CorrectionOp, Genre, GenreInference, WorkGenre, effective_work_genres
from app.services import genres as genres_service
from tests.genre_factories import add_veto, add_vote, effective, make_genre, summary
from tests.librarian_factories import make_user, make_work


async def test_the_view_exists_under_create_all_and_reads_empty(db_session):
    rows = (await db_session.execute(select(effective_work_genres))).all()
    assert rows == []


async def test_genre_hierarchy_columns(db_session):
    parent = Genre(name="Fantasy", slug="fantasy")
    db_session.add(parent)
    await db_session.flush()
    child = Genre(name="Grimdark", slug="grimdark", parent_id=parent.id, position=1)
    db_session.add(child)
    await db_session.flush()
    assert (child.parent_id, child.position, child.retired_at) == (parent.id, 1, None)


async def test_inference_source_is_checked(db_session):
    import pytest
    from sqlalchemy.exc import IntegrityError

    g = Genre(name="Fantasy", slug="fantasy")
    db_session.add(g)
    w = await make_work(db_session, "The Hobbit")
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(GenreInference(work_id=w.id, genre_id=g.id, source="guess"))
            await db_session.flush()


async def test_author_doc_is_generated(db_session):
    w = await make_work(db_session, "Red Rising", author="Pierce Brown")
    hit = await db_session.scalar(text(
        "SELECT count(*) FROM works WHERE id = :id AND author_doc @@ plainto_tsquery('simple', 'brown')"),
        {"id": w.id})
    assert hit == 1


def test_veto_genre_is_a_correction_op():
    assert CorrectionOp.veto_genre.value == "veto_genre"



async def tree(db):
    fantasy = await make_genre(db, "fantasy")
    epic = await make_genre(db, "epic-fantasy", parent=fantasy)
    grim = await make_genre(db, "grimdark", parent=fantasy, position=1)
    mystery = await make_genre(db, "mystery", position=1)
    return fantasy, epic, grim, mystery


async def test_inferred_genres_show_when_nobody_voted(db_session):
    fantasy, epic, grim, mystery = await tree(db_session)
    w = await make_work(db_session, "The Hobbit")
    await genres_service.set_inferences(db_session, w, {"epic-fantasy"}, "open_library")
    assert await effective(db_session, w) == {"epic-fantasy": (0, "inferred"), "fantasy": (0, "inferred")}


async def test_votes_beat_inference(db_session):
    fantasy, epic, grim, mystery = await tree(db_session)
    w = await make_work(db_session, "The Hobbit")
    reader = await make_user(db_session)
    await genres_service.set_inferences(db_session, w, {"mystery"}, "open_library")
    await add_vote(db_session, reader, w, grim)
    await genres_service.recompute(db_session, [w.id])
    assert await effective(db_session, w) == {"grimdark": (1, "readers"), "fantasy": (1, "readers")}


async def test_roll_up_counts_one_reader_once(db_session):
    fantasy, epic, grim, _ = await tree(db_session)
    w = await make_work(db_session, "The Hobbit")
    a, b = await make_user(db_session), await make_user(db_session)
    for genre in (fantasy, epic, grim):
        await add_vote(db_session, a, w, genre)
    await add_vote(db_session, b, w, epic)
    await genres_service.recompute(db_session, [w.id])
    got = await effective(db_session, w)
    assert got["fantasy"] == (2, "readers")
    assert got["epic-fantasy"] == (2, "readers")
    row = next(r for r in await summary(db_session) if r[1] == fantasy.id)
    assert row[2] == 1  # direct_votes: only `a` voted fantasy itself


async def test_a_veto_hides_a_genre_from_both_branches(db_session):
    fantasy, epic, grim, mystery = await tree(db_session)
    lib = await make_user(db_session, librarian=True)
    inferred_only = await make_work(db_session, "Inferred")
    await genres_service.set_inferences(db_session, inferred_only, {"mystery", "grimdark"}, "open_library")
    await add_veto(db_session, lib, inferred_only, mystery)
    await genres_service.recompute(db_session, [inferred_only.id])
    assert "mystery" not in await effective(db_session, inferred_only)

    voted = await make_work(db_session, "Voted")
    await add_vote(db_session, await make_user(db_session), voted, mystery)
    await add_vote(db_session, await make_user(db_session), voted, grim)
    await add_veto(db_session, lib, voted, mystery)
    await genres_service.recompute(db_session, [voted.id])
    assert set(await effective(db_session, voted)) == {"grimdark", "fantasy"}


async def test_a_vetoed_subgenre_does_not_roll_up(db_session):
    fantasy, epic, grim, _ = await tree(db_session)
    lib = await make_user(db_session, librarian=True)
    w = await make_work(db_session, "Cookbook")
    await add_vote(db_session, await make_user(db_session), w, grim)
    await add_veto(db_session, lib, w, grim)
    await genres_service.recompute(db_session, [w.id])
    assert await effective(db_session, w) == {}


async def test_only_votes_on_vetoed_genres_fall_back_to_inference(db_session):
    fantasy, epic, grim, mystery = await tree(db_session)
    lib = await make_user(db_session, librarian=True)
    w = await make_work(db_session, "Troll target")
    await genres_service.set_inferences(db_session, w, {"mystery"}, "open_library")
    await add_vote(db_session, await make_user(db_session), w, grim)
    await add_veto(db_session, lib, w, grim)
    await genres_service.recompute(db_session, [w.id])
    assert await effective(db_session, w) == {"mystery": (0, "inferred")}


async def test_a_reverted_veto_does_not_hold(db_session):
    fantasy, *_ = await tree(db_session)
    lib = await make_user(db_session, librarian=True)
    w = await make_work(db_session, "Back again")
    await genres_service.set_inferences(db_session, w, {"fantasy"}, "open_library")
    await add_veto(db_session, lib, w, fantasy, reverted=True)
    await genres_service.recompute(db_session, [w.id])
    assert "fantasy" in await effective(db_session, w)


async def test_retired_genres_drop_out(db_session):
    fantasy, epic, grim, mystery = await tree(db_session)
    old = await make_genre(db_session, "weird-west", retired=True)
    w = await make_work(db_session, "Weird")
    await add_vote(db_session, await make_user(db_session), w, old)
    await genres_service.set_inferences(db_session, w, {"mystery"}, "open_library")
    assert await effective(db_session, w) == {"mystery": (0, "inferred")}


async def test_set_inferences_ignores_retired_and_unknown_slugs(db_session):
    await make_genre(db_session, "weird-west", retired=True)
    w = await make_work(db_session, "Weird")
    await genres_service.set_inferences(db_session, w, {"weird-west", "no-such"}, "open_library")
    assert await summary(db_session) == set()


async def test_one_source_replaces_only_its_own_rows(db_session):
    fantasy, epic, grim, mystery = await tree(db_session)
    w = await make_work(db_session, "Two sources")
    await genres_service.set_inferences(db_session, w, {"mystery"}, "google")
    await genres_service.set_inferences(db_session, w, {"grimdark"}, "open_library")
    await genres_service.set_inferences(db_session, w, set(), "open_library")
    assert await effective(db_session, w) == {"mystery": (0, "inferred")}


async def test_recompute_everything_matches_per_work_recompute(db_session):
    fantasy, epic, grim, mystery = await tree(db_session)
    works = [await make_work(db_session, title) for title in ("Alpha", "Beta", "Gamma")]
    reader = await make_user(db_session)
    await add_vote(db_session, reader, works[0], epic)
    await genres_service.set_inferences(db_session, works[1], {"mystery"}, "catalog")
    await genres_service.recompute(db_session, [w.id for w in works])
    incremental = await summary(db_session)
    await genres_service.recompute(db_session, None)
    assert await summary(db_session) == incremental

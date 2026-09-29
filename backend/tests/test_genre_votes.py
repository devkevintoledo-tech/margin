import asyncio
import random

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models import Genre, User, Work, WorkKind
from app.services import genres as genres_service
from app.services.genres import GenreRefused, MAX_GENRES_PER_READER, unvote, vote
from app.services.librarian import revert, veto_genre
from app.services.librarian.errors import Conflict
from tests.conftest import TEST_DB_URL
from tests.genre_factories import add_veto, effective, make_genre, summary
from tests.librarian_factories import make_user, make_work


async def test_vote_and_unvote(db_session, taxonomy):
    reader, w = await make_user(db_session), await make_work(db_session, "Dune")
    await vote(db_session, reader, w, taxonomy["space-opera"])
    assert await effective(db_session, w) == {"space-opera": (1, "readers"), "science-fiction": (1, "readers")}
    await vote(db_session, reader, w, taxonomy["space-opera"])  # no-op
    assert (await effective(db_session, w))["space-opera"] == (1, "readers")
    await unvote(db_session, reader, w, taxonomy["space-opera"])
    assert await effective(db_session, w) == {}


async def test_the_sixth_genre_is_refused(db_session, taxonomy):
    reader, w = await make_user(db_session), await make_work(db_session, "Dune")
    slugs = ["space-opera", "hard-sf", "cyberpunk", "dystopian", "science-fiction", "fantasy"]
    for slug in slugs[:MAX_GENRES_PER_READER]:
        await vote(db_session, reader, w, taxonomy[slug])
    with pytest.raises(GenreRefused, match="You've tagged this book with 5 genres"):
        await vote(db_session, reader, w, taxonomy["fantasy"])


async def test_votes_on_vetoed_or_retired_genres_do_not_use_cap_slots(db_session, taxonomy):
    # Review Focus 4.
    lib, reader, w = await make_user(db_session, librarian=True), await make_user(db_session), await make_work(db_session, "Dune")
    for slug in ["space-opera", "hard-sf", "cyberpunk", "dystopian", "time-travel"]:
        await vote(db_session, reader, w, taxonomy[slug])
    await add_veto(db_session, lib, w, taxonomy["time-travel"])
    await genres_service.recompute(db_session, [w.id])
    await vote(db_session, reader, w, taxonomy["science-fiction"])  # a slot freed by the veto


async def test_refusals(db_session, taxonomy):
    lib, reader = await make_user(db_session, librarian=True), await make_user(db_session)
    w = await make_work(db_session, "Dune")
    await add_veto(db_session, lib, w, taxonomy["horror"])
    await genres_service.recompute(db_session, [w.id])
    with pytest.raises(GenreRefused, match="A librarian removed this genre from this book."):
        await vote(db_session, reader, w, taxonomy["horror"])
    old = await make_genre(db_session, "weird-west", retired=True)
    with pytest.raises(GenreRefused, match="no longer in the genre list"):
        await vote(db_session, reader, w, old)
    box = await make_work(db_session, "Dune Box Set")
    box.kind = WorkKind.collection
    with pytest.raises(GenreRefused, match="Box sets and omnibuses"):
        await vote(db_session, reader, box, taxonomy["fantasy"])


async def test_a_tombstone_resolves_to_its_survivor(db_session, taxonomy):
    reader = await make_user(db_session)
    keeper, gone = await make_work(db_session, "Dune"), await make_work(db_session, "Dune (1965)", ol_id="OL2W")
    gone.merged_into_id = keeper.id
    await db_session.flush()
    live = await vote(db_session, reader, gone, taxonomy["space-opera"])
    assert live.id == keeper.id and "space-opera" in await effective(db_session, keeper)


async def test_two_concurrent_sixth_votes_cannot_both_land(db_session, taxonomy):
    reader, w = await make_user(db_session), await make_work(db_session, "Dune")
    for slug in ["space-opera", "hard-sf", "cyberpunk", "dystopian"]:
        await vote(db_session, reader, w, taxonomy[slug])
    await db_session.commit()

    engine = create_async_engine(TEST_DB_URL, poolclass=NullPool)
    make = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with make() as a, make() as b:
            ua, wa = await a.get(User, reader.id), await a.get(Work, w.id)
            ub, wb = await b.get(User, reader.id), await b.get(Work, w.id)
            await vote(a, ua, wa, await a.get(Genre, taxonomy["time-travel"].id))  # 5th, holds the row lock
            second = asyncio.create_task(vote(b, ub, wb, await b.get(Genre, taxonomy["first-contact"].id)))
            await asyncio.sleep(0.3)
            assert not second.done()  # blocked on FOR UPDATE
            await a.commit()
            with pytest.raises(GenreRefused):
                await second
            await b.rollback()
    finally:
        await engine.dispose()


async def test_drift_guard_incremental_equals_rebuild(db_session, taxonomy):
    rng = random.Random(20260929)
    readers = [await make_user(db_session) for _ in range(3)]
    works = [await make_work(db_session, title) for title in ("Alpha", "Beta", "Gamma")]
    pool = [taxonomy[s] for s in ("fantasy", "epic-fantasy", "grimdark", "mystery", "noir", "horror")]
    lib, vetoes = await make_user(db_session, librarian=True), []
    for _ in range(60):
        r, w, g = rng.choice(readers), rng.choice(works), rng.choice(pool)
        roll = rng.random()
        if roll < 0.5:
            try:
                await vote(db_session, r, w, g)
            except GenreRefused:
                pass
        elif roll < 0.8:
            await unvote(db_session, r, w, g)
        elif roll < 0.9:
            await genres_service.set_inferences(
                db_session, w, {x.slug for x in rng.sample(pool, 2)}, rng.choice(["open_library", "google"]))
        elif vetoes and rng.random() < 0.5:
            await revert(db_session, lib, vetoes.pop(rng.randrange(len(vetoes))))
        else:
            try:
                vetoes.append(await veto_genre(db_session, lib, w, g, reason="r"))
            except Conflict:
                pass
    incremental = await summary(db_session)
    await genres_service.recompute(db_session, None)
    assert await summary(db_session) == incremental

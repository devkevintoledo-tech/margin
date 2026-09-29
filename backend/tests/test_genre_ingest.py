import uuid

import respx
from httpx import Response
from sqlalchemy import select

from app.models import Book, GenreInference, GenreVote, Work, WorkGenre
from app.services import genres as genres_service
from app.services.catalog_loader import load_release
from app.services.librarian.identity import split
from app.services.works import merge_works, resolve_editions, upsert_work_from_ol
from tests.genre_factories import add_veto, add_vote, effective
from tests.librarian_factories import make_edition, make_user, make_work
from tests.test_work_resolution import ol_work  # the OLWork builder used by the upsert tests


async def sources(db, work):
    rows = (await db.execute(select(GenreInference).where(GenreInference.work_id == work.id))).scalars()
    return {(r.source) for r in rows}


async def test_open_library_ingest_infers_from_subjects(db_session, taxonomy):
    work = await upsert_work_from_ol(db_session, ol_work(subjects=("genre:science fiction", "Space opera")))
    assert set(await effective(db_session, work)) == {"science-fiction"}
    assert await sources(db_session, work) == {"open_library"}


async def test_a_release_work_is_not_reinferred_by_search(db_session, taxonomy):
    from app.models import CatalogRelease

    work = await upsert_work_from_ol(db_session, ol_work(subjects=("Fantasy",)))
    db_session.add(CatalogRelease(version="2026.10.1", manifest={}))
    await db_session.flush()
    work.catalog_release = "2026.10.1"
    await genres_service.set_inferences(db_session, work, {"mystery"}, "catalog")
    await upsert_work_from_ol(db_session, ol_work(subjects=("Horror",)))
    assert "horror" not in await effective(db_session, work)


async def test_google_categories_infer_only_without_an_open_library_inference(db_session, taxonomy):
    bare = await make_work(db_session, "Bare")
    await genres_service.infer_from_categories(db_session, bare, ["Fiction / Fantasy / Epic"])
    assert set(await effective(db_session, bare)) == {"fantasy", "epic-fantasy"}

    known = await make_work(db_session, "Known")
    await genres_service.set_inferences(db_session, known, {"mystery"}, "open_library")
    await genres_service.infer_from_categories(db_session, known, ["Fiction / Fantasy"])
    assert set(await effective(db_session, known)) == {"mystery"}


async def test_refresh_work_infers_from_edition_categories(db_session, taxonomy):
    work = await make_work(db_session, "Heuristic")
    edition = await make_edition(db_session, work)
    edition.categories = ["Fiction / Horror"]
    from app.services.works import _refresh_work
    await _refresh_work(db_session, work)
    assert set(await effective(db_session, work)) == {"horror"}


async def test_merge_combines_votes_carries_inferences_and_vetoes(db_session, taxonomy):
    lib = await make_user(db_session, librarian=True)
    a, b = await make_user(db_session), await make_user(db_session)
    source, target = await make_work(db_session, "Dup A", ol_id="OL1W"), await make_work(db_session, "Dup B", ol_id="OL2W")
    await add_vote(db_session, a, source, taxonomy["grimdark"])
    await add_vote(db_session, a, target, taxonomy["grimdark"])  # same reader, same genre: deduped
    await add_vote(db_session, b, source, taxonomy["epic-fantasy"])
    await genres_service.set_inferences(db_session, source, {"horror"}, "open_library")
    veto = await add_veto(db_session, lib, source, taxonomy["mystery"])
    await genres_service.recompute(db_session, [source.id, target.id])

    await merge_works(db_session, source, target)

    votes = (await db_session.execute(select(GenreVote.user_id, GenreVote.genre_id).where(
        GenreVote.work_id == target.id))).all()
    assert sorted(votes) == sorted([(a.id, taxonomy["grimdark"].id), (b.id, taxonomy["epic-fantasy"].id)])
    assert await sources(db_session, target) == {"open_library"}
    await db_session.refresh(veto)
    assert veto.work_id == target.id and veto.payload["work_id"] == str(target.id)
    assert (await db_session.execute(select(WorkGenre).where(WorkGenre.work_id == source.id))).first() is None
    assert await effective(db_session, target) == {
        "grimdark": (1, "readers"), "epic-fantasy": (1, "readers"), "fantasy": (2, "readers")}


async def test_split_off_book_starts_with_no_votes(db_session, taxonomy):
    lib = await make_user(db_session, librarian=True)
    work = await make_work(db_session, "Omnibus")
    keep, move = await make_edition(db_session, work, title="Omnibus"), await make_edition(db_session, work, title="Sequel")
    move.categories = ["Fiction / Horror"]
    await add_vote(db_session, await make_user(db_session), work, taxonomy["fantasy"])
    await genres_service.recompute(db_session, [work.id])
    c = await split(db_session, lib, work, [move.id], reason="sequel", confirm=True)
    new = await db_session.get(Work, uuid.UUID(c.payload["new_work"]))
    assert (await db_session.execute(select(GenreVote).where(GenreVote.work_id == new.id))).first() is None
    assert set(await effective(db_session, new)) == {"horror"}
    assert "fantasy" in await effective(db_session, work)


async def test_a_reingest_without_subjects_keeps_the_inference(db_session, taxonomy):
    # No subjects is no evidence: a doc without tags must not erase a genre
    # the work already has (for older works, the one works.genre_id became).
    work = await upsert_work_from_ol(db_session, ol_work(subjects=("genre:science fiction",)))
    await upsert_work_from_ol(db_session, ol_work(subjects=()))
    assert set(await effective(db_session, work)) == {"science-fiction"}

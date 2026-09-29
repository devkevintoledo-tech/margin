import pytest

from app.models import CatalogCorrection, CorrectionOp
from app.services import genres as genres_service
from app.services.librarian import revert, set_series, veto_genre
from app.services.librarian.errors import Conflict, Invalid
from tests.genre_factories import effective
from tests.librarian_factories import headers_for, make_series, make_user, make_work


async def test_veto_hides_and_undo_restores_exactly(db_session, taxonomy):
    lib, reader = await make_user(db_session, librarian=True), await make_user(db_session)
    w = await make_work(db_session, "Dune")
    await genres_service.vote(db_session, reader, w, taxonomy["space-opera"])
    before = await effective(db_session, w)
    c = await veto_genre(db_session, lib, w, taxonomy["space-opera"], reason="troll tagging")
    assert (c.op, c.override, c.runtime_only_reason) == (
        CorrectionOp.veto_genre, None, "the pipeline has no genre overrides")
    assert await effective(db_session, w) == {}
    await revert(db_session, lib, c)
    assert await effective(db_session, w) == before


async def test_vetoing_twice_is_a_conflict_and_a_reason_is_required(db_session, taxonomy):
    lib, w = await make_user(db_session, librarian=True), await make_work(db_session, "Dune")
    with pytest.raises(Invalid):
        await veto_genre(db_session, lib, w, taxonomy["horror"], reason="  ")
    await veto_genre(db_session, lib, w, taxonomy["horror"], reason="wrong genre")
    with pytest.raises(Conflict):
        await veto_genre(db_session, lib, w, taxonomy["horror"], reason="wrong genre")


async def test_vetoing_a_parent_leaves_its_subgenres(db_session, taxonomy):
    lib, reader, w = await make_user(db_session, librarian=True), await make_user(db_session), await make_work(db_session, "Dune")
    await genres_service.vote(db_session, reader, w, taxonomy["space-opera"])
    await veto_genre(db_session, lib, w, taxonomy["science-fiction"], reason="too broad for this book")
    assert set(await effective(db_session, w)) == {"space-opera"}


async def test_a_veto_and_a_move_on_one_book_undo_independently(db_session, taxonomy):
    # Review Focus 2: vetoes are their own (work, genre) queue.
    lib = await make_user(db_session, librarian=True)
    saga = await make_series(db_session, "Dune Saga")
    w = await make_work(db_session, "Dune")
    veto = await veto_genre(db_session, lib, w, taxonomy["horror"], reason="wrong genre")
    move = await set_series(db_session, lib, w, series=saga, reason="belongs to this series")
    await revert(db_session, lib, veto)   # not blocked by the later move
    await revert(db_session, lib, move)   # not blocked by a veto
    second = await veto_genre(db_session, lib, w, taxonomy["mystery"], reason="wrong genre")
    await veto_genre(db_session, lib, w, taxonomy["noir"], reason="wrong genre")
    await revert(db_session, lib, second)  # different genre: its own queue


async def test_api_status_codes(client, db_session, taxonomy):
    lib, reader, w = await make_user(db_session, librarian=True), await make_user(db_session), await make_work(db_session, "Dune")
    await db_session.commit()
    url = f"/api/librarian/works/{w.id}/genres/horror/veto"
    assert (await client.post(url, json={"reason": "r"})).status_code in (401, 403)  # FastAPI-version dependent
    assert (await client.post(url, json={"reason": "r"}, headers=headers_for(reader))).status_code == 403
    assert (await client.post(f"/api/librarian/works/{w.id}/genres/nope/veto", json={"reason": "r"},
                              headers=headers_for(lib))).status_code == 404
    made = await client.post(url, json={"reason": "wrong genre"}, headers=headers_for(lib))
    assert made.status_code == 201 and made.json()["op"] == "veto_genre" and made.json()["undoable"] is True
    assert (await client.post(url, json={"reason": "again"}, headers=headers_for(lib))).status_code == 409
    vote = await client.put(f"/api/works/{w.id}/genres/horror", headers=headers_for(reader))
    assert (vote.status_code, vote.json()["detail"]) == (422, "A librarian removed this genre from this book.")


async def test_librarians_see_vetoed_genres_with_the_fix_to_undo(client, db_session, taxonomy):
    lib, reader, w = await make_user(db_session, librarian=True), await make_user(db_session), await make_work(db_session, "Dune")
    await genres_service.vote(db_session, reader, w, taxonomy["horror"])
    c = await veto_genre(db_session, lib, w, taxonomy["horror"], reason="wrong genre")
    await db_session.commit()
    as_lib = (await client.get(f"/api/works/{w.id}/genres", headers=headers_for(lib))).json()
    vetoed = [g for g in as_lib["genres"] if g["vetoed"]]
    assert [(g["slug"], g["veto_id"]) for g in vetoed] == [("horror", str(c.id))]
    as_reader = (await client.get(f"/api/works/{w.id}/genres", headers=headers_for(reader))).json()
    assert not any(g["vetoed"] for g in as_reader["genres"]) and as_reader["source"] == "none"


async def test_merge_preview_counts_genre_votes(client, db_session, taxonomy):
    lib, reader = await make_user(db_session, librarian=True), await make_user(db_session)
    a, b = await make_work(db_session, "Dune", ol_id="OL1W"), await make_work(db_session, "Dune (1965)", ol_id="OL2W")
    await genres_service.vote(db_session, reader, a, taxonomy["space-opera"])
    await db_session.commit()
    body = (await client.get(f"/api/librarian/works/{a.id}/merge-preview", params={"into": b.id},
                             headers=headers_for(lib))).json()
    assert body["genre_votes"] == 1

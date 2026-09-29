from tests.genre_factories import add_veto
from tests.librarian_factories import headers_for, make_user, make_work
from app.services import genres as genres_service


async def test_get_is_public_and_reports_inferred(client, db_session, taxonomy):
    w = await make_work(db_session, "Dune")
    await genres_service.set_inferences(db_session, w, {"space-opera"}, "open_library")
    await db_session.commit()
    body = (await client.get(f"/api/works/{w.id}/genres")).json()
    assert body["source"] == "inferred"
    assert {g["slug"] for g in body["genres"]} == {"science-fiction", "space-opera"}
    assert body["my_vote_count"] is None and body["genres"][0]["my_vote"] is None


async def test_none_when_nothing_is_known(client, db_session, taxonomy):
    w = await make_work(db_session, "Mystery Box")
    await db_session.commit()
    assert (await client.get(f"/api/works/{w.id}/genres")).json() == {
        "source": "none", "genres": [], "my_vote_count": None}


async def test_put_and_delete_return_the_payload(client, db_session, taxonomy):
    reader, w = await make_user(db_session), await make_work(db_session, "Dune")
    await db_session.commit()
    h = headers_for(reader)
    body = (await client.put(f"/api/works/{w.id}/genres/space-opera", headers=h)).json()
    assert body["source"] == "readers" and body["my_vote_count"] == 1
    opera = next(g for g in body["genres"] if g["slug"] == "space-opera")
    assert (opera["score"], opera["direct_votes"], opera["my_vote"], opera["parent_slug"]) == (1, 1, True, "science-fiction")
    parent = next(g for g in body["genres"] if g["slug"] == "science-fiction")
    assert (parent["score"], parent["direct_votes"], parent["my_vote"]) == (1, 0, False)
    body = (await client.delete(f"/api/works/{w.id}/genres/space-opera", headers=h)).json()
    assert body["source"] == "none" and body["my_vote_count"] == 0


async def test_status_codes(client, db_session, taxonomy):
    lib, reader, w = await make_user(db_session, librarian=True), await make_user(db_session), await make_work(db_session, "Dune")
    await add_veto(db_session, lib, w, taxonomy["horror"])
    await genres_service.recompute(db_session, [w.id])
    await db_session.commit()
    h = headers_for(reader)
    # HTTPBearer answers a missing header with 401 or 403 depending on the FastAPI
    # version; the librarian permission tests accept both for the same reason.
    assert (await client.put(f"/api/works/{w.id}/genres/space-opera")).status_code in (401, 403)
    assert (await client.put(f"/api/works/{w.id}/genres/no-such", headers=h)).status_code == 404
    assert (await client.put("/api/works/00000000-0000-0000-0000-000000000000/genres/fantasy",
                             headers=h)).status_code == 404
    refused = await client.put(f"/api/works/{w.id}/genres/horror", headers=h)
    assert refused.status_code == 422
    assert refused.json()["detail"] == "A librarian removed this genre from this book."


async def test_search_results_carry_top_genres(client, db_session, taxonomy):
    reader, w = await make_user(db_session), await make_work(db_session, "Dune")
    await db_session.commit()
    await client.put(f"/api/works/{w.id}/genres/space-opera", headers=headers_for(reader))
    body = (await client.get(f"/api/works/{w.id}")).json()
    assert {g["slug"] for g in body["top_genres"]} == {"space-opera", "science-fiction"}
    assert set(body["top_genres"][0]) == {"slug", "name"}

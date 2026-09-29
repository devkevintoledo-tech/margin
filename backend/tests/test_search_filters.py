import respx
from httpx import Response

from app.services import genres as genres_service
from tests.librarian_factories import headers_for, make_user
from tests.test_search import DOCS, OL_URL
from tests.test_search_local import make_work


async def seed(db, taxonomy):
    dune = make_work("Dune", "Frank Herbert", first_publish_year=1965, readinglog_count=4402)
    hyperion = make_work("Hyperion", "Dan Simmons", first_publish_year=1989, readinglog_count=900)
    thorns = make_work("Prince of Thorns", "Mark Lawrence", first_publish_year=2011, readinglog_count=300)
    undated = make_work("Undated Opera", "Anon", readinglog_count=10)
    db.add_all([dune, hyperion, thorns, undated])
    await db.flush()
    await genres_service.set_inferences(db, dune, {"space-opera"}, "open_library")
    await genres_service.set_inferences(db, hyperion, {"space-opera", "time-travel"}, "open_library")
    await genres_service.set_inferences(db, thorns, {"grimdark"}, "open_library")
    await genres_service.set_inferences(db, undated, {"space-opera"}, "open_library")
    await db.commit()
    return dune, hyperion, thorns, undated


def titles(resp):
    assert resp.status_code == 200, resp.text
    return [w["title"] for w in resp.json()]


@respx.mock
async def test_a_genre_filter_alone_browses_locally_with_zero_http(client, db_session, taxonomy):
    await seed(db_session, taxonomy)
    got = titles(await client.get("/api/works/search", params={"genre": "space-opera"}))
    assert got == ["Dune", "Hyperion", "Undated Opera"]  # score ties → readinglog_count
    assert respx.calls.call_count == 0


@respx.mock
async def test_a_parent_slug_matches_subgenre_books(client, db_session, taxonomy):
    await seed(db_session, taxonomy)
    assert titles(await client.get("/api/works/search", params={"genre": "fantasy"})) == ["Prince of Thorns"]


@respx.mock
async def test_every_genre_must_match(client, db_session, taxonomy):
    await seed(db_session, taxonomy)
    got = titles(await client.get("/api/works/search", params=[("genre", "space-opera"), ("genre", "time-travel")]))
    assert got == ["Hyperion"]


@respx.mock
async def test_browse_orders_by_the_requested_genres_score(client, db_session, taxonomy):
    dune, hyperion, *_ = await seed(db_session, taxonomy)
    await client.put(f"/api/works/{hyperion.id}/genres/space-opera", headers=headers_for(await make_user(db_session)))
    assert titles(await client.get("/api/works/search", params={"genre": "space-opera"}))[0] == "Hyperion"


@respx.mock
async def test_author_and_year_filters(client, db_session, taxonomy):
    await seed(db_session, taxonomy)
    assert titles(await client.get("/api/works/search", params={"author": "simmons"})) == ["Hyperion"]
    got = titles(await client.get("/api/works/search", params={"genre": "space-opera", "year_from": 1965, "year_to": 1989}))
    assert got == ["Dune", "Hyperion"]  # inclusive, and the undated book is out
    assert titles(await client.get("/api/works/search", params={"year_to": 1970})) == ["Dune"]


@respx.mock
async def test_bad_filters_are_422_naming_the_parameter(client, db_session, taxonomy):
    await seed(db_session, taxonomy)
    for params, param in [({"genre": "no-such"}, "genre"), ({"year_from": 2000, "year_to": 1990}, "year_to"),
                          ({}, "q"), ({"year_from": "soon"}, "year_from")]:
        resp = await client.get("/api/works/search", params=params)
        assert resp.status_code == 422, params
        assert resp.json()["detail"][0]["loc"][-1] == param


@respx.mock
async def test_a_retired_genre_is_refused(client, db_session, taxonomy):
    from datetime import datetime, timezone
    taxonomy["noir"].retired_at = datetime.now(timezone.utc)
    await db_session.commit()
    assert (await client.get("/api/works/search", params={"genre": "noir"})).status_code == 422


@respx.mock
async def test_a_cold_query_with_filters_ingests_once_then_filters_locally(client, db_session, taxonomy):
    route = respx.get(OL_URL).mock(return_value=Response(200, json={"docs": DOCS}))
    await db_session.commit()
    first = titles(await client.get("/api/works/search", params={"q": "red rising", "genre": "science-fiction"}))
    assert first == ["Red Rising"]  # Iron Gold has no genre: subject
    both = titles(await client.get("/api/works/search", params={"q": "red rising"}))
    assert set(both) == {"Red Rising", "Iron Gold"}
    assert route.call_count == 1


@respx.mock
async def test_odd_input(client, db_session, taxonomy):
    # Review Focus 5.
    route = respx.get(OL_URL).mock(return_value=Response(200, json={"docs": DOCS}))
    await seed(db_session, taxonomy)
    bad = await client.get("/api/works/search", params={"q": "never searched", "genre": "no-such"})
    assert bad.status_code == 422 and route.call_count == 0  # validated before any upstream call
    assert titles(await client.get("/api/works/search", params={"q": "!!!", "genre": "grimdark"})) == ["Prince of Thorns"]
    assert route.call_count == 0  # punctuation-only q is a browse
    dup = await client.get("/api/works/search", params=[("genre", "grimdark"), ("genre", "grimdark")])
    assert titles(dup) == ["Prince of Thorns"]

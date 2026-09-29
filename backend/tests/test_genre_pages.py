from datetime import datetime, timezone

from app.models import Thread
from app.services import genres as genres_service
from tests.librarian_factories import headers_for, make_user, make_work


async def test_tree_lists_live_parents_with_children_in_order(client, db_session, taxonomy):
    taxonomy["noir"].retired_at = datetime.now(timezone.utc)
    await db_session.commit()
    tree = (await client.get("/api/genres/")).json()
    assert tree[0]["slug"] == "literary-fiction"
    fantasy = next(g for g in tree if g["slug"] == "fantasy")
    assert [c["slug"] for c in fantasy["children"]][:2] == ["epic-fantasy", "grimdark"]
    mystery = next(g for g in tree if g["slug"] == "mystery")
    assert "noir" not in [c["slug"] for c in mystery["children"]]
    assert all("children" not in c for c in fantasy["children"])


async def test_a_subgenre_names_its_parent_and_room(client, db_session, taxonomy):
    await db_session.commit()
    body = (await client.get("/api/genres/grimdark")).json()
    assert body["parent"] == {"slug": "fantasy", "name": "Fantasy"}
    assert (body["room_slug"], body["children"], body["retired"]) == ("fantasy", [], False)


async def test_a_parent_counts_books_per_subgenre(client, db_session, taxonomy):
    w = await make_work(db_session, "Prince of Thorns")
    await genres_service.set_inferences(db_session, w, {"grimdark"}, "open_library")
    await db_session.commit()
    body = (await client.get("/api/genres/fantasy")).json()
    grim = next(c for c in body["children"] if c["slug"] == "grimdark")
    assert grim["book_count"] == 1 and body["room_slug"] == "fantasy"


async def test_a_retired_slug_still_answers(client, db_session, taxonomy):
    taxonomy["noir"].retired_at = datetime.now(timezone.utc)
    await db_session.commit()
    resp = await client.get("/api/genres/noir")
    assert resp.status_code == 200 and resp.json()["retired"] is True


async def test_parent_page_rolls_up_and_sorts_voted_books_first(client, db_session, taxonomy):
    voted, inferred = await make_work(db_session, "Zzz Voted"), await make_work(db_session, "Aaa Inferred")
    await genres_service.set_inferences(db_session, inferred, {"epic-fantasy"}, "open_library")
    await db_session.commit()
    await client.put(f"/api/works/{voted.id}/genres/grimdark", headers=headers_for(await make_user(db_session)))

    top = (await client.get("/api/genres/fantasy/works")).json()
    assert [(w["title"], w["inferred"]) for w in top] == [("Zzz Voted", False), ("Aaa Inferred", True)]
    by_title = (await client.get("/api/genres/fantasy/works", params={"sort": "title"})).json()
    assert [w["title"] for w in by_title] == ["Aaa Inferred", "Zzz Voted"]
    assert (await client.get("/api/genres/fantasy/works", params={"sort": "new"})).status_code == 422


async def test_a_subgenre_shows_its_parents_threads(client, db_session, taxonomy):
    user = await make_user(db_session)
    db_session.add(Thread(title="Is grimdark over?", user_id=user.id, genre_id=taxonomy["fantasy"].id))
    await db_session.commit()
    titles = [t["title"] for t in (await client.get("/api/genres/grimdark/threads")).json()]
    assert titles == ["Is grimdark over?"]


async def test_a_subgenre_cannot_be_a_thread_room(client, db_session, taxonomy):
    user = await make_user(db_session)
    await db_session.commit()
    resp = await client.post("/api/threads/", headers=headers_for(user),
                             json={"title": "t", "genre_slug": "grimdark", "content": "c"})
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Discussion about Grimdark happens in Fantasy."

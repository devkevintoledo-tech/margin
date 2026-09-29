import uuid

import pytest

from app.models import Series
from tests.librarian_factories import (
    headers_for, make_edition, make_member, make_series, make_thread, make_user, make_work,
)

R = "2026.10.1"
ANY = "00000000-0000-0000-0000-000000000000"
WRITES = [
    (f"/api/librarian/works/{ANY}/merge", {"into_work_id": ANY, "reason": "r"}),
    (f"/api/librarian/works/{ANY}/split", {"edition_ids": [], "reason": "r"}),
    (f"/api/librarian/works/{ANY}/move", {"new_series_name": "x", "reason": "r"}),
    (f"/api/librarian/series/{ANY}/position", {"work_id": ANY, "position": 1, "reason": "r"}),
    (f"/api/librarian/series/{ANY}/remove", {"work_id": ANY, "reason": "r"}),
    (f"/api/librarian/series/{ANY}/rename", {"name": "x", "reason": "r"}),
    (f"/api/librarian/series/{ANY}/dissolve", {"reason": "r"}),
    (f"/api/librarian/corrections/{ANY}/revert", {}),
]
READS = ["/api/librarian/corrections", "/api/librarian/series-search?q=a", f"/api/librarian/works/{ANY}/editions",
         f"/api/librarian/works/{ANY}/merge-preview?into={ANY}"]


async def test_every_route_refuses_readers_and_anonymous(client, db_session):
    reader = headers_for(await make_user(db_session))
    for path, body in WRITES:
        assert (await client.post(path, json=body, headers=reader)).status_code == 403, path
        assert (await client.post(path, json=body)).status_code in (401, 403), path
    for path in READS:
        assert (await client.get(path, headers=reader)).status_code == 403, path


async def test_unknown_ids_are_404(client, db_session):
    lib = headers_for(await make_user(db_session, librarian=True))
    for path, body in WRITES:
        resp = await client.post(path, json=body, headers=lib)
        assert resp.status_code == 404, (path, resp.text)  # the route looks the row up first


async def test_move_lands_on_the_new_room_and_undo_restores(client, db_session):
    librarian = await make_user(db_session, librarian=True)
    lib = headers_for(librarian)
    book = await make_work(db_session, "The Fifth Season", ol_id="OL50W")

    resp = await client.post(f"/api/librarian/works/{book.id}/move",
                             json={"new_series_name": "The Broken Earth", "position": 1, "reason": "trilogy"},
                             headers=lib)
    assert resp.status_code == 201, resp.text
    out = resp.json()
    assert out["op"] == "set_series" and out["exportable"] is True and out["undoable"] is True
    assert out["user"] == librarian.username and out["subject"] == "The Fifth Season"
    page = (await client.get(f"/api/series/{out['room_slug']}")).json()
    assert [w["title"] for w in page["works"]] == ["The Fifth Season"]

    undone = await client.post(f"/api/librarian/corrections/{out['id']}/revert", headers=lib)
    assert undone.status_code == 200, undone.text
    assert undone.json()["reverted_at"] is not None and undone.json()["undoable"] is False


async def test_blank_reason_is_422(client, db_session):
    lib = headers_for(await make_user(db_session, librarian=True))
    book = await make_work(db_session, "Book", ol_id="OL1W")
    resp = await client.post(f"/api/librarian/works/{book.id}/move",
                             json={"new_series_name": "S", "reason": "   "}, headers=lib)
    assert resp.status_code == 422 and "reason" in resp.json()["detail"]


async def test_merge_asks_for_confirmation_then_refuses_a_second_merge(client, db_session):
    lib = headers_for(await make_user(db_session, librarian=True))
    source = await make_work(db_session, "Dune", ol_id="OL2W", author="Brian Herbert")
    target = await make_work(db_session, "Dune", ol_id="OL1W", author="Frank Herbert")
    await make_edition(db_session, source, ol_id="OL5M")
    path, body = f"/api/librarian/works/{source.id}/merge", {"into_work_id": str(target.id), "reason": "same"}

    ask = await client.post(path, json=body, headers=lib)
    assert ask.status_code == 422
    assert ask.json()["detail"]["consequences"] == {"threads": 0, "shelves": 0, "editions": 1, "genre_votes": 0}
    assert "cannot be undone" in ask.json()["detail"]["message"]

    done = await client.post(path, json={**body, "confirm": True}, headers=lib)
    assert done.status_code == 201 and done.json()["undoable"] is False
    again = await client.post(path, json={**body, "confirm": True}, headers=lib)
    assert again.status_code == 409


async def test_split_through_the_editions_listing(client, db_session):
    lib = headers_for(await make_user(db_session, librarian=True))
    work = await make_work(db_session, "Dune", ol_id="OL100W")
    await make_edition(db_session, work, ol_id="OL1M")
    await make_edition(db_session, work, ol_id="OL2M", title="Dune Messiah")
    editions = (await client.get(f"/api/librarian/works/{work.id}/editions", headers=lib)).json()
    assert {e["title"] for e in editions} == {"Dune", "Dune Messiah"}
    messiah = next(e["id"] for e in editions if e["title"] == "Dune Messiah")
    resp = await client.post(f"/api/librarian/works/{work.id}/split",
                             json={"edition_ids": [messiah], "reason": "sequel", "confirm": True}, headers=lib)
    assert resp.status_code == 201 and resp.json()["op"] == "split_work"


async def test_series_routes(client, db_session):
    lib = headers_for(await make_user(db_session, librarian=True))
    saga = await make_series(db_session, "Saga", release=R)
    x = await make_work(db_session, "X", series=saga, ol_id="OL1W")
    y = await make_work(db_session, "Y", series=saga, ol_id="OL2W")
    await make_member(db_session, saga, x, 1.0)
    await make_member(db_session, saga, y, 2.0)
    base = f"/api/librarian/series/{saga.id}"
    for path, body, op in [
        (f"{base}/position", {"work_id": str(x.id), "position": 3, "reason": "r"}, "set_position"),
        (f"{base}/rename", {"name": "The Saga", "reason": "r"}, "rename_series"),
        (f"{base}/remove", {"work_id": str(y.id), "reason": "r"}, "remove_from_series"),
        (f"{base}/dissolve", {"reason": "r"}, "reject_series"),
    ]:
        resp = await client.post(path, json=body, headers=lib)
        assert resp.status_code == 201, (path, resp.text)
        assert resp.json()["op"] == op


async def test_corrections_list_filters_runtime_only(client, db_session):
    lib = headers_for(await make_user(db_session, librarian=True))
    ol = await make_work(db_session, "Exportable", ol_id="OL1W")
    heuristic = await make_work(db_session, "Runtime Only")
    for w in (ol, heuristic):
        await client.post(f"/api/librarian/works/{w.id}/move",
                          json={"new_series_name": f"S {w.title}", "reason": "r"}, headers=lib)
    all_rows = (await client.get("/api/librarian/corrections", headers=lib)).json()
    assert len(all_rows) == 2 and all_rows[0]["subject"] == "Runtime Only"  # newest first
    runtime = (await client.get("/api/librarian/corrections?runtime_only=true", headers=lib)).json()
    assert [r["subject"] for r in runtime] == ["Runtime Only"]
    assert "no Open Library id" in runtime[0]["runtime_only_reason"]


async def test_series_search_offers_only_real_top_level_live_series(client, db_session):
    lib = headers_for(await make_user(db_session, librarian=True))
    top = await make_series(db_session, "Discworld", release=R)
    await make_series(db_session, "Discworld Death", release=R, parent=top)
    gone = await make_series(db_session, "Discworld Old")
    from datetime import datetime, timezone
    gone.dissolved_at = datetime.now(timezone.utc)
    await make_work(db_session, "Discworld")  # its singleton is named Discworld too
    await make_work(db_session, "Mort", series=top, ol_id="OL7W")
    await db_session.flush()
    hits = (await client.get("/api/librarian/series-search?q=discworld", headers=lib)).json()
    assert [(h["name"], h["book_count"]) for h in hits] == [("Discworld", 1)]

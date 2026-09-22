"""Thread creation (book XOR genre target), fetch, and upvote."""


async def test_create_book_thread_and_fetch(client, auth_headers, book):
    resp = await client.post(
        "/api/threads/",
        json={"title": "What did you make of the ending?", "book_id": str(book.id)},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    thread = resp.json()
    assert thread["title"] == "What did you make of the ending?"
    assert thread["book_id"] == str(book.id)
    assert thread["score"] == 0

    got = await client.get(f"/api/threads/{thread['id']}")
    assert got.status_code == 200
    assert got.json()["id"] == thread["id"]
    assert got.json()["posts"] == []


async def test_create_thread_with_opening_post(client, auth_headers, book):
    resp = await client.post(
        "/api/threads/",
        json={"title": "Chapter 3 discussion", "book_id": str(book.id), "content": "Opening thoughts."},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    thread_id = resp.json()["id"]

    got = await client.get(f"/api/threads/{thread_id}")
    assert got.status_code == 200
    posts = got.json()["posts"]
    assert len(posts) == 1
    assert posts[0]["content"] == "Opening thoughts."


async def test_thread_requires_exactly_one_target(client, auth_headers, book):
    # Neither target → validation error.
    neither = await client.post(
        "/api/threads/", json={"title": "No target"}, headers=auth_headers
    )
    assert neither.status_code == 422

    # Both targets → validation error.
    both = await client.post(
        "/api/threads/",
        json={"title": "Two targets", "book_id": str(book.id), "genre_slug": "fantasy"},
        headers=auth_headers,
    )
    assert both.status_code == 422


async def test_create_thread_requires_auth(client, book):
    resp = await client.post(
        "/api/threads/", json={"title": "Anon thread", "book_id": str(book.id)}
    )
    assert resp.status_code in (401, 403)


async def test_thread_vote_sets_score(client, auth_headers, book):
    created = await client.post(
        "/api/threads/",
        json={"title": "Vote me", "book_id": str(book.id)},
        headers=auth_headers,
    )
    thread_id = created.json()["id"]

    up = await client.put(
        f"/api/threads/{thread_id}/vote", json={"value": 1}, headers=auth_headers
    )
    assert up.status_code == 200, up.text
    assert up.json()["score"] == 1
    assert up.json()["my_vote"] == 1

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


async def test_thread_detail_names_authors_and_anchor(client, auth_headers, book):
    """The detail response carries usernames and the book it hangs off.

    The frontend colours people and renders a filesystem path from these, and
    both are resolved with explicit queries rather than ORM relationships, so a
    regression here would surface as MissingGreenlet or as blank bylines.
    """
    me = (await client.get("/api/auth/me", headers=auth_headers)).json()

    created = await client.post(
        "/api/threads/",
        json={
            "title": "Is Anarres a utopia?",
            "book_id": str(book.id),
            "content": "Opening argument.",
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    # Even the create response names its author, since it never round-trips.
    assert created.json()["author"] == me["username"]

    thread_id = created.json()["id"]
    reply_author_headers = await _other_user(client)
    root_id = (await client.get(f"/api/threads/{thread_id}")).json()["posts"][0]["id"]
    replied = await client.post(
        "/api/posts/",
        json={"thread_id": thread_id, "parent_id": root_id, "content": "Counterpoint."},
        headers=reply_author_headers,
    )
    assert replied.status_code == 201, replied.text

    detail = (await client.get(f"/api/threads/{thread_id}")).json()
    assert detail["author"] == me["username"]
    assert detail["book"] == {"id": str(book.id), "title": book.title}
    assert detail["genre"] is None

    root = detail["posts"][0]
    assert root["author"] == me["username"]
    # A reply by someone else is attributed to that someone else, not the
    # thread's author — the whole point of resolving per post.
    assert root["replies"][0]["author"] != me["username"]
    assert root["replies"][0]["author"] == replied.json()["author"]


async def test_genre_thread_detail_carries_its_genre(client, auth_headers, db_session):
    from app.models.genre import Genre

    genre = Genre(name="Science Fiction", slug="science-fiction-detail")
    db_session.add(genre)
    await db_session.commit()
    await db_session.refresh(genre)

    created = await client.post(
        "/api/threads/",
        json={"title": "Best first contact novel?", "genre_slug": genre.slug},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text

    detail = (await client.get(f"/api/threads/{created.json()['id']}")).json()
    assert detail["genre"] == {
        "id": str(genre.id),
        "name": genre.name,
        "slug": genre.slug,
    }
    assert detail["book"] is None


async def _other_user(client):
    import uuid as _uuid

    unique = _uuid.uuid4().hex[:8]
    resp = await client.post(
        "/api/auth/register",
        json={
            "email": f"other_{unique}@example.com",
            "username": f"other_{unique}",
            "password": "hunter2hunter2",
        },
    )
    assert resp.status_code == 201, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


async def test_thread_listing_carries_created_at_for_the_age_column(
    client, auth_headers, book
):
    """The book/genre listings render a thread's age, so they must date it."""
    created = await client.post(
        "/api/threads/",
        json={"title": "Dated thread", "book_id": str(book.id)},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text

    rows = (await client.get(f"/api/books/{book.id}/threads")).json()
    row = next(r for r in rows if r["id"] == created.json()["id"])
    assert row["created_at"] == created.json()["created_at"]
    assert row["author"]

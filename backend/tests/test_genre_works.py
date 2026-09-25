import uuid

from app.models import Book, Genre, Work, WorkKind, WorkProvenance, WorkSource


async def seed_work(db_session, genre, title, kind=WorkKind.single):
    work = Work(
        source=WorkSource.openlibrary,
        external_id=f"OL{uuid.uuid4().hex[:8]}W",
        canonical_key=f"{title.lower()}\x1fauthor",
        title=title,
        author="Author",
        kind=kind,
        identity_provenance=WorkProvenance.isbn,
        genre_id=genre.id,
    )
    db_session.add(work)
    await db_session.flush()
    edition = Book(
        source="google_books",
        external_id=uuid.uuid4().hex[:12],
        title=title,
        author="Author",
        cover_url="https://x/cover.jpg",
        work_id=work.id,
    )
    db_session.add(edition)
    await db_session.flush()
    work.representative_book_id = edition.id
    await db_session.flush()
    return work


async def test_genre_lists_works_with_their_covers(client, db_session):
    genre = Genre(name="Science Fiction", slug="science-fiction")
    db_session.add(genre)
    await db_session.flush()
    await seed_work(db_session, genre, "Red Rising")
    await db_session.commit()

    resp = await client.get("/api/genres/science-fiction/works")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["title"] == "Red Rising"
    assert body[0]["cover_url"] == "https://x/cover.jpg"
    assert body[0]["edition_count"] == 1


async def test_genre_listing_hides_collections(client, db_session):
    genre = Genre(name="Science Fiction", slug="science-fiction")
    db_session.add(genre)
    await db_session.flush()
    await seed_work(db_session, genre, "Red Rising")
    await seed_work(db_session, genre, "Red Rising Box Set", kind=WorkKind.collection)
    await db_session.commit()

    body = (await client.get("/api/genres/science-fiction/works")).json()
    assert [w["title"] for w in body] == ["Red Rising"]


async def test_genre_listing_skips_merged_works(client, db_session):
    genre = Genre(name="Science Fiction", slug="science-fiction")
    db_session.add(genre)
    await db_session.flush()
    keeper = await seed_work(db_session, genre, "Red Rising")
    merged = await seed_work(db_session, genre, "Red Rising")
    merged.merged_into_id = keeper.id
    await db_session.commit()

    body = (await client.get("/api/genres/science-fiction/works")).json()
    assert len(body) == 1
    assert body[0]["id"] == str(keeper.id)

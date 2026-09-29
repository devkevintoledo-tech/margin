"""Row builders for librarian tests. Plain functions, not fixtures, so a test
reads as the catalog state it sets up."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.models import (
    AuthProvider, Book, CatalogRelease, MembershipConfidence, Series, SeriesKind, SeriesMember,
    SeriesProvenance, SeriesSource, Thread, User, Work, WorkKind, WorkProvenance, WorkSource,
)
from app.services.auth import create_access_token
from app.services.series_identity import series_key, slugify
from app.services.work_identity import canonical_key, heuristic_external_id


async def make_user(db, *, librarian=False, username=None):
    name = username or f"u{uuid.uuid4().hex[:10]}"
    user = User(email=f"{name}@example.com", username=name, auth_provider=AuthProvider.email,
                password_hash="x", is_librarian=librarian)
    db.add(user)
    await db.flush()
    return user


def headers_for(user):
    return {"Authorization": f"Bearer {create_access_token({'sub': str(user.id)})}"}


async def make_release(db, version="2026.10.1"):
    found = await db.get(CatalogRelease, version)
    if found is None:
        found = CatalogRelease(version=version, manifest={})
        db.add(found)
        await db.flush()
    return found


async def make_series(db, name, *, key=None, release=None, kind=SeriesKind.series, parent=None):
    """A real series. ``release`` (a version string) makes it a catalog series
    whose ``external_id`` is its pipeline key (``key`` or ``ol:<name>``)."""
    if release is not None:
        await make_release(db, release)
    s = Series(
        source=SeriesSource.openlibrary if release else SeriesSource.heuristic,
        external_id=key or (f"ol:{series_key(name)}" if release else f"franchise:{series_key(name)}"),
        name=name, slug=f"{slugify(name)}-{uuid.uuid4().hex[:4]}", canonical_key=series_key(name),
        kind=kind, provenance=SeriesProvenance.ol_tag, catalog_release=release,
        parent_series_id=parent.id if parent else None,
    )
    db.add(s)
    await db.flush()
    return s


async def make_work(db, title, *, series=None, ol_id=None, author="A. Author", release=None):
    """An Open Library work when ``ol_id`` is given, otherwise a heuristic one.
    With no ``series`` the flush listener gives it a singleton."""
    key = canonical_key(title, author)
    w = Work(
        source=WorkSource.openlibrary if ol_id else WorkSource.heuristic,
        external_id=ol_id or heuristic_external_id(key),
        canonical_key=key, title=title, author=author, kind=WorkKind.single,
        identity_provenance=WorkProvenance.isbn if ol_id else WorkProvenance.heuristic,
        series_id=series.id if series else None, catalog_release=release,
        # Already enriched: opening a series page would otherwise call Google Books.
        enriched_at=datetime.now(timezone.utc),
    )
    db.add(w)
    await db.flush()
    return w


async def make_member(db, series, work, position=None, provenance=SeriesProvenance.ol_tag):
    m = SeriesMember(series_id=series.id, work_id=work.id, position=position,
                     provenance=provenance, confidence=MembershipConfidence.medium)
    db.add(m)
    await db.flush()
    return m


async def make_thread(db, user, series, work=None, title="A thread"):
    t = Thread(title=title, user_id=user.id, series_id=series.id, work_id=work.id if work else None)
    db.add(t)
    await db.flush()
    return t


async def fresh(db, column, row_id):
    """Read one column straight from the database. ``retire_series`` updates rows
    with raw SQL, so objects already in the session can be stale."""
    return await db.scalar(select(column).where(column.class_.id == row_id))


async def make_edition(db, work, *, ol_id=None, title=None, language="en"):
    """An Open Library edition when ``ol_id`` is given, otherwise a Google volume."""
    b = Book(source="openlibrary" if ol_id else "google_books",
             external_id=ol_id or uuid.uuid4().hex[:12], title=title or work.title,
             author=work.author, language=language, work_id=work.id)
    db.add(b)
    await db.flush()
    return b

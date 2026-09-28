"""Pytest fixtures for the MARGIN backend test suite.

Tests run async (``asyncio_mode = auto``) against a dedicated ``margin_test``
Postgres database — separate from the dev database so a test run can never touch
real data. Set ``DATABASE_URL`` to the test DB before running (see CLAUDE.md);
the defaults below match ``docker compose up db``.

The schema is built with ``Base.metadata.create_all`` (not Alembic) so tests are
self-contained and fast to reset. Each test gets a fresh schema and a single
``AsyncSession`` that the app's ``get_db`` dependency is overridden to reuse, so
data written through the API is visible to assertions in the same test.
"""

import os
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio

# Settings reads these at import time — populate before importing the app.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://margin:margin@localhost:5432/margin_test",
)
os.environ.setdefault("SECRET_KEY", "test-secret-key")

from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.database import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, Book, Genre, Work, WorkKind, WorkProvenance, WorkSource  # noqa: E402  (imports the package → full metadata)

TEST_DB_URL = os.environ["DATABASE_URL"]


@pytest_asyncio.fixture
async def db_session():
    """A clean schema + one session per test.

    NullPool keeps every connection bound to the current event loop, avoiding
    cross-loop pool reuse issues with the per-function asyncio loop.
    """
    engine = create_async_engine(TEST_DB_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session):
    """HTTP client over the ASGI app with get_db pinned to the test session."""

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def auth_headers(client):
    """Register a fresh user and return a ready-to-use bearer auth header."""
    unique = uuid.uuid4().hex[:8]
    resp = await client.post(
        "/api/auth/register",
        json={
            "email": f"user_{unique}@example.com",
            "username": f"user_{unique}",
            "password": "hunter2hunter2",
        },
    )
    assert resp.status_code == 201, resp.text
    token = resp.json()["token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def work(db_session):
    """Seed a work and one edition (no upstream round-trip) for thread/shelf tests.

    ``enriched_at`` is set because opening a work page enriches it from Google
    Books on first view. Without it, every test that GETs this work would make
    a live HTTP request — which is exactly what this fixture exists to avoid.
    """
    w = Work(
        source=WorkSource.openlibrary,
        external_id=f"OL{uuid.uuid4().hex[:8]}W",
        canonical_key="the test book\x1fa tester",
        title="The Test Book",
        author="A. Tester",
        kind=WorkKind.single,
        identity_provenance=WorkProvenance.isbn,
        enriched_at=datetime.now(timezone.utc),
    )
    db_session.add(w)
    await db_session.flush()

    edition = Book(
        source="google_books",
        external_id=uuid.uuid4().hex[:12],
        title="The Test Book",
        author="A. Tester",
        work_id=w.id,
    )
    db_session.add(edition)
    await db_session.flush()

    w.representative_book_id = edition.id
    await db_session.commit()
    await db_session.refresh(w)
    return w


@pytest.fixture
async def genre(db_session):
    g = Genre(name=f"Sci-Fi {uuid.uuid4().hex[:4]}", slug=f"sci-fi-{uuid.uuid4().hex[:4]}")
    db_session.add(g)
    await db_session.flush()
    await db_session.refresh(g)
    return g


_ARROW = {"uuid": "string", "text": "string", "int": "int32", "bigint": "int64", "numeric": "float64"}


@pytest.fixture
def write_release(tmp_path):
    """Write a catalog release folder the way the pipeline's publish stage does.

    ``write_release("2026.10.1", works=[...], series=[...], ...)`` takes rows as
    dicts; unspecified columns are filled with neutral values. Returns the folder.
    """
    import hashlib
    import json

    import pyarrow as pa
    import pyarrow.parquet as pq

    from app.services.catalog_loader import COLUMNS

    defaults = {
        "works": {"subtitle": None, "author": "A. Author", "first_publish_year": None, "kind": "single",
                  "ol_cover_id": None, "ol_edition_count": 1, "readinglog_count": 0, "ratings_count": 0,
                  "subjects": None, "representative_edition_id": None},
        "editions": {"subtitle": None, "author": "A. Author", "publisher": None, "published_year": None,
                     "isbn_13": None, "page_count": None, "cover_url": None, "language": "en"},
        "series": {"source": "openlibrary", "provenance": "ol_tag", "kind": "series", "parent_series_id": None},
        "series_members": {"position": None, "provenance": "ol_tag", "confidence": "medium"},
        "work_aliases": {},
    }

    def write(version, **tables):
        folder = tmp_path / f"catalog-{version}"
        folder.mkdir()
        files = {}
        for name, columns in COLUMNS.items():
            schema = pa.schema([(c, getattr(pa, _ARROW[t])()) for c, t in columns])
            rows = []
            for row in tables.get(name, []):
                full = {**defaults[name], **row}
                if name == "works":
                    full.setdefault("canonical_key", f"{full['title'].lower()}\x1f{full['author'].lower()}")
                if name == "series":
                    full.setdefault("canonical_key", full["name"].lower())
                    full.setdefault("key", f"ol:{full['name'].lower()}")
                rows.append({c: (str(full[c]) if t == "uuid" and full.get(c) is not None else full.get(c))
                             for c, t in columns})
            pq.write_table(pa.Table.from_pylist(rows, schema=schema), folder / f"{name}.parquet")
            files[f"{name}.parquet"] = hashlib.sha256((folder / f"{name}.parquet").read_bytes()).hexdigest()
        (folder / "manifest.json").write_text(json.dumps(
            {"version": version, "schema_version": 1, "files": files, "sources": [], "row_counts": {}}))
        return folder

    return write

"""The genre migrations, run by Alembic against a scratch database (not create_all)."""

import asyncpg

from migration_db import alembic, plain_url as _plain, scratch_db  # noqa: F401  (fixture)


async def test_genre_schema_upgrades_and_downgrades(scratch_db):
    alembic(scratch_db, "upgrade", "c7d2e4f6a8b1")
    conn = await asyncpg.connect(_plain(scratch_db))
    try:
        assert await conn.fetchval("SELECT count(*) FROM effective_work_genres") == 0
        assert await conn.fetchval("SELECT 'veto_genre'::correction_op_enum::text") == "veto_genre"
        assert await conn.fetchval("SELECT count(*) FROM genres WHERE parent_id IS NULL") == 8
    finally:
        await conn.close()
    alembic(scratch_db, "downgrade", "b4e8d2f6a0c9")
    alembic(scratch_db, "upgrade", "c7d2e4f6a8b1")  # re-upgrade must not trip on leftovers



async def test_work_genre_ids_become_open_library_inferences(scratch_db):
    alembic(scratch_db, "upgrade", "c7d2e4f6a8b1")
    conn = await asyncpg.connect(_plain(scratch_db))
    try:
        series = await conn.fetchval("""
            INSERT INTO series (source, external_id, name, slug, canonical_key, kind, provenance)
            VALUES ('heuristic', 'x', 'Dune', 'dune', 'dune', 'singleton', 'single') RETURNING id""")
        genre = await conn.fetchval("SELECT id FROM genres WHERE slug = 'science-fiction'")
        work = await conn.fetchval("""
            INSERT INTO works (source, external_id, canonical_key, title, author, kind, identity_provenance,
                               series_id, genre_id)
            VALUES ('openlibrary', 'OL1W', 'dune', 'Dune', 'Frank Herbert', 'single', 'isbn', $1, $2)
            RETURNING id""", series, genre)
    finally:
        await conn.close()
    alembic(scratch_db, "upgrade", "d8e3f5a7b9c2")
    conn = await asyncpg.connect(_plain(scratch_db))
    try:
        assert await conn.fetch("SELECT genre_id, source FROM genre_inferences WHERE work_id = $1", work) == [
            (genre, "open_library")]
        assert await conn.fetchval(
            "SELECT source FROM effective_work_genres WHERE work_id = $1", work) == "inferred"
        assert await conn.fetchval(
            "SELECT count(*) FROM information_schema.columns WHERE table_name='works' AND column_name='genre_id'") == 0
    finally:
        await conn.close()
    alembic(scratch_db, "downgrade", "c7d2e4f6a8b1")

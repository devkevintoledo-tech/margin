"""The edit/delete columns, added and removed by real Alembic."""

import asyncpg

from migration_db import alembic, plain_url, scratch_db  # noqa: F401  (fixture)

COLUMNS = """
    SELECT table_name, column_name FROM information_schema.columns
    WHERE (table_name, column_name) IN (
        ('posts', 'edited_at'), ('posts', 'deleted_at'), ('threads', 'deleted_at'))
    ORDER BY 1, 2"""


async def test_content_columns_upgrade_and_downgrade(scratch_db):
    alembic(scratch_db, "upgrade", "head")
    conn = await asyncpg.connect(plain_url(scratch_db))
    try:
        rows = [tuple(r) for r in await conn.fetch(COLUMNS)]
        assert rows == [("posts", "deleted_at"), ("posts", "edited_at"), ("threads", "deleted_at")]
    finally:
        await conn.close()

    alembic(scratch_db, "downgrade", "d8e3f5a7b9c2")
    conn = await asyncpg.connect(plain_url(scratch_db))
    try:
        assert await conn.fetch(COLUMNS) == []
    finally:
        await conn.close()

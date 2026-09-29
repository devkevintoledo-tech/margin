"""The genre migrations, run by Alembic against a scratch database (not create_all)."""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest

BACKEND = Path(__file__).resolve().parents[1]


def _plain(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


@pytest.fixture
async def scratch_db():
    base = os.environ["DATABASE_URL"].rsplit("/", 1)[0]
    name = f"margin_migrate_{uuid.uuid4().hex[:8]}"
    try:
        admin = await asyncpg.connect(_plain(f"{base}/postgres"))
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"cannot reach the postgres database: {exc}")
    try:
        await admin.execute(f'CREATE DATABASE "{name}"')
    except asyncpg.InsufficientPrivilegeError:  # pragma: no cover
        await admin.close()
        pytest.skip("role cannot CREATE DATABASE")
    try:
        yield f"{base}/{name}"
    finally:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.close()


def alembic(url: str, *args: str) -> None:
    env = {**os.environ, "DATABASE_URL": url}
    done = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env,
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


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

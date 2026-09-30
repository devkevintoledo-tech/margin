"""A throwaway database migrated by real Alembic, for migration tests (not create_all)."""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest

BACKEND = Path(__file__).resolve().parents[1]


def plain_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


@pytest.fixture
async def scratch_db():
    base = os.environ["DATABASE_URL"].rsplit("/", 1)[0]
    name = f"margin_migrate_{uuid.uuid4().hex[:8]}"
    try:
        admin = await asyncpg.connect(plain_url(f"{base}/postgres"))
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

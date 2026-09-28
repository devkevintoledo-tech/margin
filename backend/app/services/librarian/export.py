"""Corrections as pipeline/overrides YAML (spec §9). Same database, same bytes."""

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CatalogCorrection, User

HEADER = (
    "# In-app librarian fixes, written by `python -m scripts.export_overrides`.\n"
    "# Do not edit by hand: undo the fix in the app and export again.\n"
)


async def _unreverted(db: AsyncSession, *, exportable: bool) -> list[tuple[CatalogCorrection, str]]:
    query = (
        select(CatalogCorrection, User.username)
        .join(User, User.id == CatalogCorrection.user_id)
        .where(CatalogCorrection.reverted_at.is_(None),
               CatalogCorrection.override.is_not(None) if exportable else CatalogCorrection.override.is_(None))
        .order_by(CatalogCorrection.created_at, CatalogCorrection.id)
    )
    return [(c, username) for c, username in (await db.execute(query)).all()]


async def exportable(db: AsyncSession) -> list[tuple[CatalogCorrection, str]]:
    return await _unreverted(db, exportable=True)


async def runtime_only(db: AsyncSession) -> list[tuple[CatalogCorrection, str]]:
    return await _unreverted(db, exportable=False)


def _comment(c: CatalogCorrection, username: str) -> str:
    lines = c.reason.splitlines() or [""]
    stamp = f"  ({username}, {c.created_at:%Y-%m-%d}, correction {str(c.id)[:8]})"
    out = [f"# {lines[0]}{stamp}\n"]
    out += [f"# {line}\n" if line else "#\n" for line in lines[1:]]
    return "".join(out)


def render(rows: list[tuple[CatalogCorrection, str]]) -> str:
    """The whole file. The pipeline reads overrides in name order and applies
    entries in order, so a later fix to the same book wins."""
    parts = [HEADER]
    for c, username in rows:
        parts.append("\n")
        parts.append(_comment(c, username))
        for entry in c.override:
            parts.append(yaml.safe_dump([entry], default_flow_style=None, sort_keys=False,
                                        allow_unicode=True, width=4096))
    return "".join(parts)

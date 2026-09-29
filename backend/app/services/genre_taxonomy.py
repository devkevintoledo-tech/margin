"""Syncing ``app/data/genres.yaml`` into the ``genres`` table (spec §5.2)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Genre, Thread
from app.services.genre_inference import Taxonomy, TaxonomyError


async def sync_genres(db: AsyncSession, taxonomy: Taxonomy) -> list[str]:
    """Upsert every entry by slug, retire rows missing from the file, unretire
    ones that reappear. Idempotent. Validates everything before writing."""
    existing = {g.slug: g for g in (await db.execute(select(Genre))).scalars()}
    entries = taxonomy.by_slug()

    # A thread's room must stay a parent (D9): refuse, don't strand discussion.
    for entry in taxonomy.entries:
        row = existing.get(entry.slug)
        if entry.parent is not None and row is not None and row.parent_id is None:
            threads = await db.scalar(select(func.count()).select_from(Thread).where(Thread.genre_id == row.id))
            if threads:
                raise TaxonomyError(f"{entry.slug} has discussion threads and cannot become a subgenre")

    changes: list[str] = []
    now = datetime.now(timezone.utc)
    # Parents first, so a child can point at its parent's id.
    for entry in sorted(taxonomy.entries, key=lambda e: e.parent is not None):
        row = existing.get(entry.slug)
        parent_id = existing[entry.parent].id if entry.parent else None
        if row is None:
            row = Genre(slug=entry.slug, name=entry.name, description=entry.description,
                        parent_id=parent_id, position=entry.position)
            db.add(row)
            await db.flush()
            existing[entry.slug] = row
            changes.append(f"+ {entry.slug}")
            continue
        wanted = {"name": entry.name, "description": entry.description,
                  "parent_id": parent_id, "position": entry.position}
        diff = [k for k, v in wanted.items() if getattr(row, k) != v]
        for key in diff:
            setattr(row, key, wanted[key])
        if row.retired_at is not None:
            row.retired_at = None
            diff.append("unretired")
        if diff:
            changes.append(f"~ {entry.slug} ({', '.join(diff)})")

    for slug, row in existing.items():
        if slug not in entries and row.retired_at is None:
            row.retired_at = now
            changes.append(f"- retired {slug}")
    await db.flush()
    return changes

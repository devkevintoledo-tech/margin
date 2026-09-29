"""Sync app/data/genres.yaml into the genres table. Idempotent.

    python -m scripts.sync_genres

Compose runs it after `alembic upgrade head`. After changing a `match` or
`exclude` list, or moving a genre to another parent, also run
`python -m scripts.rebuild_work_genres --reinfer`.
"""

import asyncio
import sys

from app.database import AsyncSessionLocal
from app.services.genre_inference import TaxonomyError, load_taxonomy
from app.services.genre_taxonomy import sync_genres


async def main() -> int:
    try:
        taxonomy = load_taxonomy()
    except TaxonomyError as exc:
        print(f"genres.yaml is invalid: {exc}", file=sys.stderr)
        return 1
    async with AsyncSessionLocal() as session:
        try:
            changes = await sync_genres(session, taxonomy)
        except TaxonomyError as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 1
        await session.commit()
    print("\n".join(changes) if changes else "genres already in sync")
    if any("parent_id" in c for c in changes):
        print("a genre changed parent: run `python -m scripts.rebuild_work_genres`")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

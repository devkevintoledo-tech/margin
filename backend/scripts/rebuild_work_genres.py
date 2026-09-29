"""Rebuild work_genres from its sources. Idempotent; batched.

    python -m scripts.rebuild_work_genres            # recompute every summary row
    python -m scripts.rebuild_work_genres --reinfer  # first redo open_library/catalog
                                                     # inferences from works.subjects

Run --reinfer after changing a `match`/`exclude` list in app/data/genres.yaml.
"""

import argparse
import asyncio

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import Work
from app.services import genres as genres_service
from app.services.genre_inference import infer_genres, shipped_taxonomy
from app.services.series_identity import SUBJECT_SEPARATOR

_BATCH = 2000


async def rebuild_chunk(db, ids, reinfer: bool) -> None:
    """Recompute these works' summaries, first redoing inferences when asked."""
    if reinfer:
        taxonomy = shipped_taxonomy()
        rows = (await db.execute(select(Work.id, Work.subjects, Work.catalog_release)
                                 .where(Work.id.in_(ids)))).all()
        for source in ("open_library", "catalog"):
            await genres_service.set_inferences_bulk(db, {
                wid: infer_genres([s for s in (subjects or "").split(SUBJECT_SEPARATOR) if s], taxonomy)
                for wid, subjects, release in rows
                # No stored subjects is no evidence: keep what the work has
                # (for older works, the genre the works.genre_id migration copied).
                if subjects and (release is not None) == (source == "catalog")}, source)
    await genres_service.recompute(db, ids)


async def main(reinfer: bool) -> None:
    async with AsyncSessionLocal() as session:
        ids = (await session.execute(select(Work.id).where(Work.merged_into_id.is_(None))
                                     .order_by(Work.id))).scalars().all()
    for start in range(0, len(ids), _BATCH):
        chunk = ids[start:start + _BATCH]
        async with AsyncSessionLocal() as session:
            await rebuild_chunk(session, chunk, reinfer)
            await session.commit()
        print(f"{min(start + _BATCH, len(ids))}/{len(ids)} works")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reinfer", action="store_true")
    asyncio.run(main(parser.parse_args().reinfer))

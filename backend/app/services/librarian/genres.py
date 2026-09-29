"""Librarian genre fixes (spec 2026-09-29 §7.2). The corrections log's only writer
stays this package, so the merge path's veto re-pointing lives here too."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def repoint_vetoes(db: AsyncSession, source_id: UUID, target_id: UUID) -> None:
    """A merged book's live vetoes keep holding on the survivor."""
    await db.execute(text("""
        UPDATE catalog_corrections
        SET work_id = CAST(:dst AS uuid),
            payload = jsonb_set(payload, '{work_id}', to_jsonb(CAST(CAST(:dst AS uuid) AS text)))
        WHERE op = 'veto_genre' AND reverted_at IS NULL AND work_id = :src"""),
        {"src": source_id, "dst": target_id})

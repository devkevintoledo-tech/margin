"""retire works.genre_id: its values become open_library inferences

Revision ID: d8e3f5a7b9c2
Revises: c7d2e4f6a8b1
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d8e3f5a7b9c2"
down_revision: Union[str, None] = "c7d2e4f6a8b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO genre_inferences (work_id, genre_id, source)
        SELECT id, genre_id, 'open_library' FROM works WHERE genre_id IS NOT NULL
        ON CONFLICT DO NOTHING""")
    # The eight seeded genres are parents, so there is nothing to roll up, and
    # no votes or vetoes exist yet: an inferred row per copied value is the summary.
    op.execute("""
        INSERT INTO work_genres (work_id, genre_id, direct_votes, score, inferred, vetoed)
        SELECT id, genre_id, 0, 0, true, false FROM works
        WHERE genre_id IS NOT NULL AND merged_into_id IS NULL
        ON CONFLICT (work_id, genre_id) DO UPDATE SET inferred = true""")
    op.drop_column("works", "genre_id")  # drops its index and FK with it


def downgrade() -> None:
    op.add_column("works", sa.Column("genre_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("works_genre_id_fkey", "works", "genres", ["genre_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_works_genre_id", "works", ["genre_id"])
    op.execute("""
        UPDATE works w SET genre_id = sub.genre_id FROM (
            SELECT DISTINCT ON (i.work_id) i.work_id, i.genre_id
            FROM genre_inferences i JOIN genres g ON g.id = i.genre_id
            WHERE i.source = 'open_library' AND g.parent_id IS NULL
            ORDER BY i.work_id, g.position) sub
        WHERE w.id = sub.work_id""")

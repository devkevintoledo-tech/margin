"""require works.series_id; constrain a thread's home

Revision ID: f8c4d0e3b2a5
Revises: e7b3c9d2a1f4

Refuses to run until `python -m scripts.backfill_series` has given every work
a series. The same guard the works migration uses against unresolved editions.
The thread constraints are NOT VALID: ten legacy threads have no home at all,
and the constraint must still hold for every row written from now on.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f8c4d0e3b2a5"
down_revision: Union[str, None] = "e7b3c9d2a1f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM works WHERE series_id IS NULL) THEN
                RAISE EXCEPTION
                    'works without a series remain; run python -m scripts.backfill_series first';
            END IF;
        END $$;
        """
    )
    op.alter_column("works", "series_id", existing_type=sa.UUID(), nullable=False)
    op.execute(
        "ALTER TABLE threads ADD CONSTRAINT ck_threads_one_home "
        "CHECK ((series_id IS NOT NULL) <> (genre_id IS NOT NULL)) NOT VALID"
    )
    op.execute(
        "ALTER TABLE threads ADD CONSTRAINT ck_threads_tag_needs_series "
        "CHECK (work_id IS NULL OR series_id IS NOT NULL) NOT VALID"
    )


def downgrade() -> None:
    op.drop_constraint("ck_threads_tag_needs_series", "threads", type_="check")
    op.drop_constraint("ck_threads_one_home", "threads", type_="check")
    op.alter_column("works", "series_id", existing_type=sa.UUID(), nullable=True)

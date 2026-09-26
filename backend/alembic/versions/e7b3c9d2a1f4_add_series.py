"""series: the discussion home above works

Revision ID: e7b3c9d2a1f4
Revises: d4e9b21c6f07

Nullable columns only. `scripts.backfill_series` fills them; Migration B
(f8c4d0e3b2a5) then requires works.series_id and adds the thread constraints.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e7b3c9d2a1f4"
down_revision: Union[str, None] = "d4e9b21c6f07"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "series",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("source", sa.Enum("openlibrary", "heuristic", name="series_source_enum"), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("canonical_key", sa.Text(), nullable=False),
        sa.Column("kind", sa.Enum("series", "singleton", name="series_kind_enum"), nullable=False),
        sa.Column("merged_into_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["merged_into_id"], ["series.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "external_id", name="uq_series_source_external_id"),
    )
    op.create_index("ix_series_slug", "series", ["slug"], unique=True)
    op.create_index("ix_series_canonical_key", "series", ["canonical_key"])
    op.create_index("ix_series_merged_into_id", "series", ["merged_into_id"])

    op.add_column("works", sa.Column("series_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("works_series_id_fkey", "works", "series", ["series_id"], ["id"])
    op.create_index("ix_works_series_id", "works", ["series_id"])

    op.add_column("threads", sa.Column("series_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "threads_series_id_fkey", "threads", "series", ["series_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_threads_series_id", "threads", ["series_id"])


def downgrade() -> None:
    op.drop_index("ix_threads_series_id", table_name="threads")
    op.drop_constraint("threads_series_id_fkey", "threads", type_="foreignkey")
    op.drop_column("threads", "series_id")
    op.drop_index("ix_works_series_id", table_name="works")
    op.drop_constraint("works_series_id_fkey", "works", type_="foreignkey")
    op.drop_column("works", "series_id")
    op.drop_index("ix_series_merged_into_id", table_name="series")
    op.drop_index("ix_series_canonical_key", table_name="series")
    op.drop_index("ix_series_slug", table_name="series")
    op.drop_table("series")
    sa.Enum(name="series_kind_enum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="series_source_enum").drop(op.get_bind(), checkfirst=True)

"""librarian tools: corrections log, librarian flag, dissolved series

Revision ID: b4e8d2f6a0c9
Revises: a9d3e5f7c1b2
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b4e8d2f6a0c9"
down_revision: Union[str, None] = "a9d3e5f7c1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OPS = ("merge_works", "split_work", "set_series", "set_position", "remove_from_series",
       "reject_series", "rename_series")


def upgrade() -> None:
    # ADD VALUE cannot run in a transaction block on older Postgres, and nothing
    # below uses the new value in this transaction.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE work_provenance_enum ADD VALUE IF NOT EXISTS 'override'")

    op.add_column("users", sa.Column("is_librarian", sa.Boolean(), server_default=sa.text("false"),
                                     nullable=False))
    op.add_column("series", sa.Column("dissolved_at", sa.DateTime(timezone=True), nullable=True))

    op_enum = postgresql.ENUM(*OPS, name="correction_op_enum", create_type=False)
    op_enum.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "catalog_corrections",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"),
                  nullable=False),
        sa.Column("op", op_enum, nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("override", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("runtime_only_reason", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("work_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("series_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("clock_timestamp()"),
                  nullable=False),
        sa.Column("reverted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reverted_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint("(override IS NULL) = (runtime_only_reason IS NOT NULL)",
                           name="ck_catalog_corrections_export_state"),
        sa.ForeignKeyConstraint(["work_id"], ["works.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["series_id"], ["series.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["reverted_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_catalog_corrections_work_id", "catalog_corrections", ["work_id"])
    op.create_index("ix_catalog_corrections_series_id", "catalog_corrections", ["series_id"])
    op.create_index("ix_catalog_corrections_user_id", "catalog_corrections", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_catalog_corrections_user_id", table_name="catalog_corrections")
    op.drop_index("ix_catalog_corrections_series_id", table_name="catalog_corrections")
    op.drop_index("ix_catalog_corrections_work_id", table_name="catalog_corrections")
    op.drop_table("catalog_corrections")
    sa.Enum(name="correction_op_enum").drop(op.get_bind(), checkfirst=True)
    op.drop_column("series", "dissolved_at")
    op.drop_column("users", "is_librarian")
    # Postgres cannot drop an enum value. 'override' stays on
    # work_provenance_enum; nothing references it once split works are gone,
    # and ADD VALUE IF NOT EXISTS makes re-upgrading safe.

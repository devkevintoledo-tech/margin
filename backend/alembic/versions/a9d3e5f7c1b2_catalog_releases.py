"""catalog releases: release bookkeeping, series membership, nesting, aliases

Revision ID: a9d3e5f7c1b2
Revises: f8c4d0e3b2a5

Everything the catalog loader (scripts.load_catalog_release) writes. Existing
runtime series get a provenance from what created them: a singleton is
`single`, a tag series `ol_tag`.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a9d3e5f7c1b2"
down_revision: Union[str, None] = "f8c4d0e3b2a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PROVENANCE = ("wikidata", "ol_tag", "ol_edition_series", "title_pattern", "single", "override")


def upgrade() -> None:
    op.create_table(
        "catalog_releases",
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("loaded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("version"),
    )

    # ADD VALUE cannot run inside a transaction block on older Postgres, and the
    # new value cannot be used in the transaction that adds it — nothing here does.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE series_source_enum ADD VALUE IF NOT EXISTS 'wikidata'")

    provenance = postgresql.ENUM(*PROVENANCE, name="series_provenance_enum", create_type=False)
    provenance.create(op.get_bind(), checkfirst=True)
    op.add_column("series", sa.Column("provenance", provenance, nullable=True))
    op.execute("UPDATE series SET provenance = CASE WHEN kind = 'singleton' "
               "THEN 'single' ELSE 'ol_tag' END::series_provenance_enum")
    op.alter_column("series", "provenance", nullable=False)
    op.add_column("series", sa.Column("catalog_release", sa.String(length=32), nullable=True))
    op.create_foreign_key("series_catalog_release_fkey", "series", "catalog_releases",
                          ["catalog_release"], ["version"])
    op.create_index("ix_series_catalog_release", "series", ["catalog_release"])
    op.add_column("series", sa.Column("parent_series_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("series_parent_series_id_fkey", "series", "series",
                          ["parent_series_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_series_parent_series_id", "series", ["parent_series_id"])

    op.add_column("works", sa.Column("catalog_release", sa.String(length=32), nullable=True))
    op.create_foreign_key("works_catalog_release_fkey", "works", "catalog_releases",
                          ["catalog_release"], ["version"])
    op.create_index("ix_works_catalog_release", "works", ["catalog_release"])

    op.create_table(
        "series_members",
        sa.Column("series_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("work_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Numeric(), nullable=True),
        sa.Column("provenance", provenance, nullable=False),
        sa.Column("confidence", sa.Enum("high", "medium", "low", name="membership_confidence_enum"), nullable=False),
        sa.ForeignKeyConstraint(["series_id"], ["series.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["work_id"], ["works.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("series_id", "work_id"),
    )
    op.create_index("ix_series_members_work_id", "series_members", ["work_id"])

    op.create_table(
        "work_aliases",
        sa.Column("ol_work_id", sa.String(length=64), nullable=False),
        sa.Column("work_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["work_id"], ["works.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("ol_work_id"),
    )
    op.create_index("ix_work_aliases_work_id", "work_aliases", ["work_id"])


def downgrade() -> None:
    op.drop_index("ix_work_aliases_work_id", table_name="work_aliases")
    op.drop_table("work_aliases")
    op.drop_index("ix_series_members_work_id", table_name="series_members")
    op.drop_table("series_members")
    op.drop_index("ix_works_catalog_release", table_name="works")
    op.drop_constraint("works_catalog_release_fkey", "works", type_="foreignkey")
    op.drop_column("works", "catalog_release")
    op.drop_index("ix_series_parent_series_id", table_name="series")
    op.drop_constraint("series_parent_series_id_fkey", "series", type_="foreignkey")
    op.drop_column("series", "parent_series_id")
    op.drop_index("ix_series_catalog_release", table_name="series")
    op.drop_constraint("series_catalog_release_fkey", "series", type_="foreignkey")
    op.drop_column("series", "catalog_release")
    op.drop_column("series", "provenance")
    op.drop_table("catalog_releases")
    sa.Enum(name="membership_confidence_enum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="series_provenance_enum").drop(op.get_bind(), checkfirst=True)

    # Postgres cannot drop an enum value: rebuild the type without 'wikidata'.
    # Wikidata series only exist via a catalog load; downgrading past this
    # revision relabels them rather than losing their rows.
    op.execute("UPDATE series SET source = 'openlibrary' WHERE source = 'wikidata'")
    op.execute("ALTER TYPE series_source_enum RENAME TO series_source_enum_old")
    op.execute("CREATE TYPE series_source_enum AS ENUM ('openlibrary', 'heuristic')")
    op.execute("ALTER TABLE series ALTER COLUMN source TYPE series_source_enum "
               "USING source::text::series_source_enum")
    op.execute("DROP TYPE series_source_enum_old")

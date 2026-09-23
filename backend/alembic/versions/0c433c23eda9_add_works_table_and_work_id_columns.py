"""add works table and work_id columns

Revision ID: 0c433c23eda9
Revises: c3a7e1b8d904
Create Date: 2026-09-23 18:45:32.491198

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0c433c23eda9'
down_revision: Union[str, None] = 'c3a7e1b8d904'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    work_source = sa.Enum("openlibrary", "heuristic", name="work_source_enum")
    work_kind = sa.Enum("single", "collection", name="work_kind_enum")
    work_provenance = sa.Enum("isbn", "title_author", "heuristic", name="work_provenance_enum")

    op.create_table(
        "works",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("source", work_source, nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("canonical_key", sa.Text(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("subtitle", sa.String(length=500), nullable=True),
        sa.Column("author", sa.String(length=500), nullable=False),
        sa.Column("first_publish_year", sa.Integer(), nullable=True),
        sa.Column("kind", work_kind, nullable=False),
        sa.Column("identity_provenance", work_provenance, nullable=False),
        sa.Column("representative_book_id", sa.UUID(), nullable=True),
        sa.Column("genre_id", sa.UUID(), nullable=True),
        sa.Column("merged_into_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["representative_book_id"],
            ["books.id"],
            name="fk_works_representative_book_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["genre_id"], ["genres.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["merged_into_id"], ["works.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "external_id", name="uq_works_source_external_id"),
    )
    op.create_index("ix_works_canonical_key", "works", ["canonical_key"])
    op.create_index("ix_works_genre_id", "works", ["genre_id"])
    op.create_index("ix_works_merged_into_id", "works", ["merged_into_id"])

    for table in ("books", "threads", "shelves"):
        op.add_column(table, sa.Column("work_id", sa.UUID(), nullable=True))
        op.create_index(f"ix_{table}_work_id", table, ["work_id"])
        op.create_foreign_key(
            f"fk_{table}_work_id", table, "works", ["work_id"], ["id"], ondelete="CASCADE"
        )

    # A shelf row created between this migration and the next one knows only its
    # work, so book_id has to stop being mandatory. The column is dropped in the
    # next migration; this is purely to make the in-between state legal.
    op.alter_column("shelves", "book_id", existing_type=sa.UUID(), nullable=True)


def downgrade() -> None:
    # Restoring NOT NULL fails if any shelf row was created work-first. That is
    # the point: those rows have no edition to fall back to.
    op.alter_column("shelves", "book_id", existing_type=sa.UUID(), nullable=False)

    for table in ("shelves", "threads", "books"):
        op.drop_constraint(f"fk_{table}_work_id", table, type_="foreignkey")
        op.drop_index(f"ix_{table}_work_id", table_name=table)
        op.drop_column(table, "work_id")

    op.drop_index("ix_works_merged_into_id", table_name="works")
    op.drop_index("ix_works_genre_id", table_name="works")
    op.drop_index("ix_works_canonical_key", table_name="works")
    op.drop_table("works")

    # Autogenerate does NOT drop enum types; without this, re-upgrading fails
    # with "type already exists" (see CLAUDE.md).
    for name in ("work_provenance_enum", "work_kind_enum", "work_source_enum"):
        sa.Enum(name=name).drop(op.get_bind(), checkfirst=True)

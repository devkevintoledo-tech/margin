"""local-first search: work ranking columns and search_queries

Revision ID: d4e9b21c6f07
Revises: a03fcabf38e0
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d4e9b21c6f07"
down_revision: Union[str, None] = "a03fcabf38e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SEARCH_DOC = (
    "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('english', coalesce(author, '')), 'B') || "
    "setweight(to_tsvector('english', coalesce(subjects, '')), 'C')"
)


def upgrade() -> None:
    op.add_column("works", sa.Column("ol_cover_id", sa.Integer(), nullable=True))
    op.add_column(
        "works",
        sa.Column("ol_edition_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "works",
        sa.Column("readinglog_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "works",
        sa.Column("ratings_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("works", sa.Column("subjects", sa.Text(), nullable=True))
    op.add_column("works", sa.Column("description", sa.Text(), nullable=True))
    op.add_column(
        "works", sa.Column("enriched_at", sa.DateTime(timezone=True), nullable=True)
    )
    # Generated column: Postgres maintains it, so it can never drift.
    op.add_column(
        "works",
        sa.Column(
            "search_doc",
            postgresql.TSVECTOR(),
            sa.Computed(_SEARCH_DOC, persisted=True),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_works_search_doc", "works", ["search_doc"], postgresql_using="gin"
    )

    op.create_table(
        "search_queries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("normalized_query", sa.Text(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_search_queries_normalized_query",
        "search_queries",
        ["normalized_query"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_search_queries_normalized_query", table_name="search_queries")
    op.drop_table("search_queries")
    op.drop_index("ix_works_search_doc", table_name="works")
    for column in (
        "search_doc",
        "enriched_at",
        "description",
        "subjects",
        "ratings_count",
        "readinglog_count",
        "ol_edition_count",
        "ol_cover_id",
    ):
        op.drop_column("works", column)

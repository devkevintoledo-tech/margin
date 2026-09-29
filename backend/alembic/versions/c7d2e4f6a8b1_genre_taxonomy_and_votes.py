"""genre taxonomy, votes, inferences, summary and search columns

Revision ID: c7d2e4f6a8b1
Revises: b4e8d2f6a0c9

Downgrade note: Postgres cannot drop an enum value, so `veto_genre` stays on
correction_op_enum after a downgrade. It is harmless: nothing writes it.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.models.genre import EFFECTIVE_WORK_GENRES_VIEW

revision: str = "c7d2e4f6a8b1"
down_revision: Union[str, None] = "b4e8d2f6a0c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE correction_op_enum ADD VALUE IF NOT EXISTS 'veto_genre'")

    op.add_column("genres", sa.Column("parent_id", UUID, nullable=True))
    op.add_column("genres", sa.Column("position", sa.Integer(), server_default=sa.text("0"), nullable=False))
    op.add_column("genres", sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key("genres_parent_id_fkey", "genres", "genres", ["parent_id"], ["id"])
    op.create_index("ix_genres_parent_id", "genres", ["parent_id"])

    op.create_table(
        "genre_votes",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("work_id", UUID, nullable=False),
        sa.Column("genre_id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["work_id"], ["works.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["genre_id"], ["genres.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "work_id", "genre_id", name="uq_genre_votes_user_work_genre"),
    )
    op.create_index("ix_genre_votes_work_id", "genre_votes", ["work_id"])

    op.create_table(
        "genre_inferences",
        sa.Column("work_id", UUID, nullable=False),
        sa.Column("genre_id", UUID, nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.CheckConstraint("source IN ('open_library', 'google', 'catalog')", name="ck_genre_inferences_source"),
        sa.ForeignKeyConstraint(["work_id"], ["works.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["genre_id"], ["genres.id"]),
        sa.PrimaryKeyConstraint("work_id", "genre_id", "source", name="pk_genre_inferences"),
    )

    op.create_table(
        "work_genres",
        sa.Column("work_id", UUID, nullable=False),
        sa.Column("genre_id", UUID, nullable=False),
        sa.Column("direct_votes", sa.Integer(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("inferred", sa.Boolean(), nullable=False),
        sa.Column("vetoed", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["work_id"], ["works.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["genre_id"], ["genres.id"]),
        sa.PrimaryKeyConstraint("work_id", "genre_id", name="pk_work_genres"),
    )
    op.create_index("ix_work_genres_genre_score", "work_genres", ["genre_id", sa.text("score DESC")])
    op.execute(EFFECTIVE_WORK_GENRES_VIEW)

    op.add_column("works", sa.Column(
        "author_doc", postgresql.TSVECTOR(),
        sa.Computed("to_tsvector('simple', coalesce(author, ''))", persisted=True), nullable=False))
    op.create_index("ix_works_author_doc", "works", ["author_doc"], postgresql_using="gin")
    op.create_index("ix_works_first_publish_year", "works", ["first_publish_year"])


def downgrade() -> None:
    op.drop_index("ix_works_first_publish_year", table_name="works")
    op.drop_index("ix_works_author_doc", table_name="works")
    op.drop_column("works", "author_doc")
    op.execute("DROP VIEW IF EXISTS effective_work_genres")
    op.drop_table("work_genres")
    op.drop_table("genre_inferences")
    op.drop_index("ix_genre_votes_work_id", table_name="genre_votes")
    op.drop_table("genre_votes")
    op.drop_index("ix_genres_parent_id", table_name="genres")
    op.drop_constraint("genres_parent_id_fkey", "genres", type_="foreignkey")
    op.drop_column("genres", "retired_at")
    op.drop_column("genres", "position")
    op.drop_column("genres", "parent_id")
    # veto_genre stays on correction_op_enum: Postgres cannot drop an enum value.

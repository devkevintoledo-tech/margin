"""drop book fks in favour of works

Revision ID: a03fcabf38e0
Revises: 0c433c23eda9
Create Date: 2026-09-24 12:24:08.293363

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a03fcabf38e0'
down_revision: Union[str, None] = '0c433c23eda9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("uq_shelf_user_book", "shelves", type_="unique")
    op.create_unique_constraint("uq_shelf_user_work", "shelves", ["user_id", "work_id"])

    op.drop_column("shelves", "book_id")
    op.drop_column("threads", "book_id")
    op.drop_column("books", "genre_id")

    # books.work_id stays nullable: editions are flushed before they are
    # resolved. shelves.work_id is always known at insert time.
    op.alter_column("shelves", "work_id", existing_type=sa.UUID(), nullable=False)


def downgrade() -> None:
    op.alter_column("shelves", "work_id", existing_type=sa.UUID(), nullable=True)

    op.add_column("books", sa.Column("genre_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "books_genre_id_fkey", "books", "genres", ["genre_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_books_genre_id", "books", ["genre_id"])

    op.add_column("threads", sa.Column("book_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "threads_book_id_fkey", "threads", "books", ["book_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_threads_book_id", "threads", ["book_id"])

    op.add_column("shelves", sa.Column("book_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "shelves_book_id_fkey", "shelves", "books", ["book_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_shelves_book_id", "shelves", ["book_id"])

    op.drop_constraint("uq_shelf_user_work", "shelves", type_="unique")
    op.create_unique_constraint("uq_shelf_user_book", "shelves", ["user_id", "book_id"])

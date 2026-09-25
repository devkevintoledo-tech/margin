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
    # --- Carry the edition-level links onto works, before anything is dropped.
    # This has to happen in SQL, here: `scripts.resolve_works` gives every
    # edition a work (which needs HTTP, so it cannot live in a migration), but
    # moving threads and shelves onto those works is pure relational work and
    # is the only chance to do it — a moment later the columns are gone.
    op.execute(
        """
        UPDATE threads t SET work_id = b.work_id
        FROM books b
        WHERE t.book_id = b.id AND t.work_id IS NULL AND b.work_id IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE shelves s SET work_id = b.work_id
        FROM books b
        WHERE s.book_id = b.id AND s.work_id IS NULL AND b.work_id IS NOT NULL
        """
    )

    # Refuse to continue rather than drop the only link these rows have. The
    # cause is always the same: scripts.resolve_works was not run after the
    # previous migration, so editions have no work to hand over.
    op.execute(
        """
        DO $$
        DECLARE stranded integer;
        BEGIN
            SELECT count(*) INTO stranded FROM shelves WHERE work_id IS NULL;
            IF stranded > 0 THEN
                RAISE EXCEPTION
                    '% shelf row(s) have no work. Run `python -m scripts.resolve_works` '
                    'against this database first, then re-run this migration.', stranded;
            END IF;
            SELECT count(*) INTO stranded
            FROM threads WHERE book_id IS NOT NULL AND work_id IS NULL;
            IF stranded > 0 THEN
                RAISE EXCEPTION
                    '% thread(s) reference an edition with no work. Run '
                    '`python -m scripts.resolve_works` first, then re-run this migration.',
                    stranded;
            END IF;
        END $$
        """
    )

    # One shelf row per (user, work) from here on, so a user who shelved two
    # editions of the same book has to collapse to one. Keep the oldest, which
    # is what merge_works() does with the same collision.
    op.execute(
        """
        DELETE FROM shelves s
        USING shelves keep
        WHERE s.user_id = keep.user_id
          AND s.work_id = keep.work_id
          AND (keep.created_at, keep.id) < (s.created_at, s.id)
        """
    )

    op.drop_constraint("uq_shelf_user_book", "shelves", type_="unique")
    op.create_unique_constraint("uq_shelf_user_work", "shelves", ["user_id", "work_id"])

    op.drop_column("shelves", "book_id")
    op.drop_column("threads", "book_id")

    # Genre moves from the edition to the work before the column goes. Without
    # this, every genre page empties out on deploy and only refills as users
    # search. DISTINCT ON picks one genre per work; editions of a work
    # effectively never disagree, and if they did, either answer is as good.
    op.execute(
        """
        UPDATE works w
        SET genre_id = sub.genre_id
        FROM (
            SELECT DISTINCT ON (work_id) work_id, genre_id
            FROM books
            WHERE work_id IS NOT NULL AND genre_id IS NOT NULL
            ORDER BY work_id, genre_id
        ) AS sub
        WHERE w.id = sub.work_id AND w.genre_id IS NULL
        """
    )
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

    # Same reasoning as the shelves backfill below: which edition is arbitrary,
    # but pointing a thread back at its work's representative keeps a
    # downgrade/upgrade cycle from silently orphaning every book thread.
    op.execute(
        """
        UPDATE threads t SET book_id = COALESCE(
            (SELECT w.representative_book_id FROM works w WHERE w.id = t.work_id),
            (SELECT b.id FROM books b WHERE b.work_id = t.work_id ORDER BY b.id LIMIT 1)
        )
        WHERE t.work_id IS NOT NULL
        """
    )

    op.add_column("shelves", sa.Column("book_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "shelves_book_id_fkey", "shelves", "books", ["book_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_shelves_book_id", "shelves", ["book_id"])

    # Point each shelf back at *an* edition of its work, so migration 1's
    # downgrade can restore book_id NOT NULL. Which edition is arbitrary — the
    # edition-level link was never recoverable once this migration ran, and
    # only the representative is a defensible choice.
    op.execute(
        """
        UPDATE shelves s SET book_id = COALESCE(
            (SELECT w.representative_book_id FROM works w WHERE w.id = s.work_id),
            (SELECT b.id FROM books b WHERE b.work_id = s.work_id ORDER BY b.id LIMIT 1)
        )
        WHERE s.work_id IS NOT NULL
        """
    )

    op.drop_constraint("uq_shelf_user_work", "shelves", type_="unique")
    op.create_unique_constraint("uq_shelf_user_book", "shelves", ["user_id", "book_id"])

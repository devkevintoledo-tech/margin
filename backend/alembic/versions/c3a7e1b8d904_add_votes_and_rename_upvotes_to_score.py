"""add votes table; rename upvotes to score

Revision ID: c3a7e1b8d904
Revises: 80f2ffa56f79
Create Date: 2026-09-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3a7e1b8d904'
down_revision: Union[str, None] = '80f2ffa56f79'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('threads', 'upvotes', new_column_name='score')
    op.alter_column('posts', 'upvotes', new_column_name='score')
    # The legacy counts have no user attribution, so they cannot be represented
    # as vote rows. Reset them so `score` is always exactly SUM(votes.value).
    op.execute('UPDATE threads SET score = 0')
    op.execute('UPDATE posts SET score = 0')

    op.create_table(
        'votes',
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('thread_id', sa.Uuid(), nullable=True),
        sa.Column('post_id', sa.Uuid(), nullable=True),
        sa.Column('value', sa.SmallInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['thread_id'], ['threads.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['post_id'], ['posts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint('value IN (-1, 1)', name='ck_vote_value'),
        sa.CheckConstraint(
            '(thread_id IS NOT NULL) <> (post_id IS NOT NULL)',
            name='ck_vote_exactly_one_target',
        ),
    )
    op.create_index(op.f('ix_votes_user_id'), 'votes', ['user_id'], unique=False)
    op.create_index(op.f('ix_votes_thread_id'), 'votes', ['thread_id'], unique=False)
    op.create_index(op.f('ix_votes_post_id'), 'votes', ['post_id'], unique=False)
    op.create_index(
        'uq_vote_user_thread', 'votes', ['user_id', 'thread_id'],
        unique=True, postgresql_where=sa.text('thread_id IS NOT NULL'),
    )
    op.create_index(
        'uq_vote_user_post', 'votes', ['user_id', 'post_id'],
        unique=True, postgresql_where=sa.text('post_id IS NOT NULL'),
    )


def downgrade() -> None:
    op.drop_index('uq_vote_user_post', table_name='votes')
    op.drop_index('uq_vote_user_thread', table_name='votes')
    op.drop_index(op.f('ix_votes_post_id'), table_name='votes')
    op.drop_index(op.f('ix_votes_thread_id'), table_name='votes')
    op.drop_index(op.f('ix_votes_user_id'), table_name='votes')
    op.drop_table('votes')
    # Counts were discarded on the way up; the column comes back at 0.
    op.alter_column('posts', 'score', new_column_name='upvotes')
    op.alter_column('threads', 'score', new_column_name='upvotes')

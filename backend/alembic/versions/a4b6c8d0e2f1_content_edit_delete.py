"""edit and delete threads and posts: edited_at and deleted_at tombstones

Revision ID: a4b6c8d0e2f1
Revises: d8e3f5a7b9c2
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a4b6c8d0e2f1"
down_revision: Union[str, None] = "d8e3f5a7b9c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("posts", sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("posts", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("threads", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("threads", "deleted_at")
    op.drop_column("posts", "deleted_at")
    op.drop_column("posts", "edited_at")

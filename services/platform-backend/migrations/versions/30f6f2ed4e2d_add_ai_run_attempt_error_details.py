"""add ai run attempt error details

Revision ID: 30f6f2ed4e2d
Revises: 9c81b6e53ad4
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "30f6f2ed4e2d"
down_revision: str | None = "9c81b6e53ad4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("ai_run_attempts") as batch_op:
        batch_op.add_column(sa.Column("purpose", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("error_code", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("error_message", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("ai_run_attempts") as batch_op:
        batch_op.drop_column("error_message")
        batch_op.drop_column("error_code")
        batch_op.drop_column("purpose")

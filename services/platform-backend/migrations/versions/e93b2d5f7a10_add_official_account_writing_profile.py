"""add official account writing profile

Revision ID: e93b2d5f7a10
Revises: c4d2a71e8f90
Create Date: 2026-09-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e93b2d5f7a10"
down_revision: str | None = "c4d2a71e8f90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "official_accounts",
        sa.Column("writing_profile", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("official_accounts", "writing_profile")

"""expand official account token secret reference

Revision ID: c4d2a71e8f90
Revises: b6c8e91a24f3
Create Date: 2026-09-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4d2a71e8f90"
down_revision: str | None = "b6c8e91a24f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "official_accounts",
        "token_secret_ref",
        existing_type=sa.String(length=255),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "official_accounts",
        "token_secret_ref",
        existing_type=sa.Text(),
        type_=sa.String(length=255),
        existing_nullable=True,
    )

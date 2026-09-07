"""remove administrator TOTP configuration

Revision ID: 7b2d6c1a4e90
Revises: e5f147b8c9d2
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7b2d6c1a4e90"
down_revision: str | None = "e5f147b8c9d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("admins") as batch_op:
        batch_op.drop_column("totp_secret_ref")


def downgrade() -> None:
    with op.batch_alter_table("admins") as batch_op:
        batch_op.add_column(sa.Column("totp_secret_ref", sa.String(length=255), nullable=True))

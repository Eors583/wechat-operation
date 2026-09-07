"""allow encrypted model API keys

Revision ID: 9c81b6e53ad4
Revises: 7b2d6c1a4e90
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9c81b6e53ad4"
down_revision: str | None = "7b2d6c1a4e90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("model_providers") as batch_op:
        batch_op.alter_column(
            "secret_ref", existing_type=sa.String(length=255), type_=sa.Text(), nullable=False
        )


def downgrade() -> None:
    with op.batch_alter_table("model_providers") as batch_op:
        batch_op.alter_column(
            "secret_ref", existing_type=sa.Text(), type_=sa.String(length=255), nullable=False
        )

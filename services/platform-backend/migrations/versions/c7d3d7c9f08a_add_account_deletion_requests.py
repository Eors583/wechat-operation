"""add account deletion requests

Revision ID: c7d3d7c9f08a
Revises: 0540e296bea2
Create Date: 2026-09-01 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7d3d7c9f08a"
down_revision: str | None = "0540e296bea2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "account_deletion_requests",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("purge_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_account_deletion_user"),
        sa.CheckConstraint(
            "status IN ('scheduled','processing','completed','failed')",
            name="ck_account_deletion_status",
        ),
    )
    op.create_index(
        "ix_account_deletion_due",
        "account_deletion_requests",
        ["status", "purge_after"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_account_deletion_due", table_name="account_deletion_requests")
    op.drop_table("account_deletion_requests")

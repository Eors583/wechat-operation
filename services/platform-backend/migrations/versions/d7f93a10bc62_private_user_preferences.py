"""Separate private user preference memory from explicit writing styles."""

import sqlalchemy as sa
from alembic import op

revision = "d7f93a10bc62"
down_revision = "c4d2a71e8f90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_preference_memories",
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("user_preference_memories")

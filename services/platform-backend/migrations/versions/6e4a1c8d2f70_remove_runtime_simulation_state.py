"""remove runtime simulation state

Revision ID: 6e4a1c8d2f70
Revises: b43c2c1f81a9
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "6e4a1c8d2f70"
down_revision: str | None = "b43c2c1f81a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE article_revisions SET status = 'failed', "
        "error_code = COALESCE(error_code, 'LEGACY_SIMULATION_REMOVED'), "
        "error_message = COALESCE(error_message, 'Legacy simulated result was invalidated.') "
        "WHERE simulated = true"
    )
    op.execute("UPDATE assets SET scan_status = 'pending' WHERE scan_status = 'mocked_clean'")
    op.execute(
        "UPDATE wechat_operations SET status = 'failed', "
        "error_code = COALESCE(error_code, 'LEGACY_SIMULATION_REMOVED') "
        "WHERE status = 'mocked'"
    )
    op.execute(
        "UPDATE articles SET status = 'wechat_draft_failed' "
        "WHERE status = 'wechat_draft_mocked'"
    )
    op.execute("UPDATE articles SET status = 'publish_failed' WHERE status = 'publish_mocked'")
    op.execute(
        "UPDATE library_items SET display_status = 'wechat_draft_failed' "
        "WHERE display_status = 'wechat_draft_mocked'"
    )
    op.execute(
        "UPDATE library_items SET display_status = 'publish_failed' "
        "WHERE display_status = 'publish_mocked'"
    )
    with op.batch_alter_table("article_revisions") as batch_op:
        batch_op.drop_column("simulated")


def downgrade() -> None:
    with op.batch_alter_table("article_revisions") as batch_op:
        batch_op.add_column(
            sa.Column("simulated", sa.Boolean(), nullable=False, server_default=sa.false())
        )

"""add WeChat direct authorization credentials

Revision ID: b43c2c1f81a9
Revises: 8b5a2b621b77
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b43c2c1f81a9"
down_revision: str | None = "8b5a2b621b77"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("wechat_platform_configs") as batch_op:
        batch_op.add_column(sa.Column("component_verify_ticket_ref", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("component_access_token_ref", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "component_access_token_expires_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch_op.add_column(sa.Column("last_token_refresh_at", sa.DateTime(timezone=True)))
    with op.batch_alter_table("wechat_authorization_states") as batch_op:
        batch_op.add_column(sa.Column("platform_config_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_wechat_authorization_state_platform_config",
            "wechat_platform_configs",
            ["platform_config_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("wechat_authorization_states") as batch_op:
        batch_op.drop_constraint(
            "fk_wechat_authorization_state_platform_config", type_="foreignkey"
        )
        batch_op.drop_column("platform_config_id")
    with op.batch_alter_table("wechat_platform_configs") as batch_op:
        batch_op.drop_column("last_token_refresh_at")
        batch_op.drop_column("component_access_token_expires_at")
        batch_op.drop_column("component_access_token_ref")
        batch_op.drop_column("component_verify_ticket_ref")

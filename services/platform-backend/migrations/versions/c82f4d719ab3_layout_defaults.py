"""Make saved layouts available and retain one default per official account."""

import sqlalchemy as sa
from alembic import op

revision = "c82f4d719ab3"
down_revision = "b71d9e2a5c04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")
        op.execute("SET LOCAL statement_timeout = '30s'")
    op.add_column(
        "layout_templates",
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(
        "WITH ranked AS (SELECT id, row_number() OVER "
        "(PARTITION BY owner_id, official_account_id "
        "ORDER BY enabled DESC, updated_at DESC, id DESC) n "
        "FROM layout_templates WHERE deleted_at IS NULL AND official_account_id IS NOT NULL "
        "AND current_version_no > 0) "
        "UPDATE layout_templates SET is_default = true "
        "WHERE id IN (SELECT id FROM ranked WHERE n = 1)"
    )
    op.execute(
        "UPDATE layout_templates SET enabled = true "
        "WHERE deleted_at IS NULL AND current_version_no > 0"
    )
    op.create_index(
        "uq_layout_account_default",
        "layout_templates",
        ["owner_id", "official_account_id"],
        unique=True,
        postgresql_where=sa.text("is_default AND deleted_at IS NULL"),
        sqlite_where=sa.text("is_default AND deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_layout_account_default", table_name="layout_templates")
    op.drop_column("layout_templates", "is_default")

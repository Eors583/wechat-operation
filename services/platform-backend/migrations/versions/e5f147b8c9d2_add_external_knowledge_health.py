"""add external knowledge health

Revision ID: e5f147b8c9d2
Revises: d18f4b99e2a0
Create Date: 2026-09-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5f147b8c9d2"
down_revision: str | None = "d18f4b99e2a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "external_knowledge_sources",
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "external_knowledge_sources",
        sa.Column("last_test_result", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "external_knowledge_sources",
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "external_knowledge_sources",
        sa.Column("sync_cursor", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "external_knowledge_sources",
        sa.Column("error_code", sa.String(length=80), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("external_knowledge_sources", "error_code")
    op.drop_column("external_knowledge_sources", "sync_cursor")
    op.drop_column("external_knowledge_sources", "last_synced_at")
    op.drop_column("external_knowledge_sources", "last_test_result")
    op.drop_column("external_knowledge_sources", "last_tested_at")

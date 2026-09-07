"""version document chunking

Revision ID: a81e2de20d21
Revises: c7d3d7c9f08a
Create Date: 2026-09-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a81e2de20d21"
down_revision: str | None = "c7d3d7c9f08a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "document_chunks",
        sa.Column(
            "chunking_version",
            sa.String(length=40),
            server_default="zh-char-v1",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("document_chunks", "chunking_version")

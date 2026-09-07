"""add chunk source locations

Revision ID: f31a5cc40f87
Revises: a81e2de20d21
Create Date: 2026-09-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f31a5cc40f87"
down_revision: str | None = "a81e2de20d21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "document_chunks", sa.Column("section_title", sa.String(length=255), nullable=True)
    )
    op.add_column("document_chunks", sa.Column("page_no", sa.Integer(), nullable=True))
    op.add_column("document_chunks", sa.Column("start_ms", sa.Integer(), nullable=True))
    op.add_column("document_chunks", sa.Column("end_ms", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("document_chunks", "end_ms")
    op.drop_column("document_chunks", "start_ms")
    op.drop_column("document_chunks", "page_no")
    op.drop_column("document_chunks", "section_title")

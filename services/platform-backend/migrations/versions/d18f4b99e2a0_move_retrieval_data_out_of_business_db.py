"""move retrieval data out of business db

Revision ID: d18f4b99e2a0
Revises: f31a5cc40f87
Create Date: 2026-09-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d18f4b99e2a0"
down_revision: str | None = "f31a5cc40f87"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("retrieval_results")
    op.drop_index("ix_retrieval_user_task_created", table_name="retrieval_queries")
    op.drop_table("retrieval_queries")
    op.drop_column("document_chunks", "embedding")


def downgrade() -> None:
    op.add_column("document_chunks", sa.Column("embedding", sa.JSON(), nullable=True))
    op.create_table(
        "retrieval_queries",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.Column("original_query", sa.Text(), nullable=False),
        sa.Column("rewritten_query", sa.Text(), nullable=True),
        sa.Column("filters", sa.JSON(), nullable=False),
        sa.Column("total_duration_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_retrieval_user_task_created",
        "retrieval_queries",
        ["user_id", "task_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "retrieval_results",
        sa.Column("query_id", sa.String(length=36), nullable=False),
        sa.Column("chunk_id", sa.String(length=36), nullable=False),
        sa.Column("stage", sa.String(length=24), nullable=False),
        sa.Column("fulltext_score", sa.Numeric(precision=12, scale=8), nullable=True),
        sa.Column("vector_score", sa.Numeric(precision=12, scale=8), nullable=True),
        sa.Column("fused_score", sa.Numeric(precision=12, scale=8), nullable=True),
        sa.Column("rerank_score", sa.Numeric(precision=12, scale=8), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["chunk_id"], ["document_chunks.id"]),
        sa.ForeignKeyConstraint(["query_id"], ["retrieval_queries.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("query_id", "stage", "chunk_id", name="uq_retrieval_stage_chunk"),
    )

"""Keep an immutable layout snapshot alongside article content versions.

Additive and nullable: the previous application can continue reading/writing
articles. Application rollback must leave this column and its saved data intact.
"""

import sqlalchemy as sa
from alembic import op

revision = "b71d9e2a5c04"
down_revision = "a60e912f4bd8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")
        op.execute("SET LOCAL statement_timeout = '30s'")
    op.add_column("article_versions", sa.Column("layout_snapshot", sa.JSON(), nullable=True))


def downgrade() -> None:
    # Refuse to silently discard saved user layouts when rolling back application code.
    connection = op.get_bind()
    if connection.scalar(
        sa.text("SELECT count(*) FROM article_versions WHERE layout_snapshot IS NOT NULL")
    ):
        raise RuntimeError("Archive saved article layouts before removing layout_snapshot")
    op.drop_column("article_versions", "layout_snapshot")

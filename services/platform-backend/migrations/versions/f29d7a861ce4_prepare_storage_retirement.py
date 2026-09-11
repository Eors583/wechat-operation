"""Allow the compatibility release to stop writing retired non-null columns."""

import sqlalchemy as sa
from alembic import op

revision = "f29d7a861ce4"
down_revision = "e8c20f7a913b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("tasks", "use_preferences", server_default=sa.true())
    op.alter_column("user_preferences", "confidence", server_default=sa.text("1"))


def downgrade() -> None:
    op.alter_column("user_preferences", "confidence", server_default=None)
    op.alter_column("tasks", "use_preferences", server_default=None)

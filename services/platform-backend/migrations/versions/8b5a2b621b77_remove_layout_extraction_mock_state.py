"""remove layout extraction mock state

Revision ID: 8b5a2b621b77
Revises: 30f6f2ed4e2d
Create Date: 2026-09-02
"""

from collections.abc import Sequence

from alembic import op

revision: str = "8b5a2b621b77"
down_revision: str | None = "30f6f2ed4e2d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    legacy_status = "completed_" + "mock"
    op.execute(
        "UPDATE layout_templates "
        "SET extraction_status = 'failed' "
        f"WHERE extraction_status = '{legacy_status}'"
    )
    op.execute(
        "UPDATE job_records "
        "SET status = 'failed', stage = 'provider_failed', "
        "error_code = 'LAYOUT_PROVIDER_FAILED', "
        "error_message = 'Layout extraction used legacy simulated data.' "
        f"WHERE resource_type = 'layout_template' AND stage = '{legacy_status}'"
    )


def downgrade() -> None:
    pass

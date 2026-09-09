"""seed default mptext article api

Revision ID: 7f7b7d0c41a2
Revises: 6e4a1c8d2f70
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7f7b7d0c41a2"
down_revision: str | None = "6e4a1c8d2f70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULT_ID = "7f7b7d0c-41a2-4d00-9000-000000000001"


def upgrade() -> None:
    sources = sa.table(
        "external_knowledge_sources",
        sa.column("id", sa.String),
        sa.column("source_type", sa.String),
        sa.column("name", sa.String),
        sa.column("configuration", sa.JSON),
        sa.column("secret_ref", sa.String),
        sa.column("scope", sa.JSON),
        sa.column("status", sa.String),
        sa.column("last_test_result", sa.JSON),
        sa.column("sync_cursor", sa.JSON),
    )
    op.bulk_insert(
        sources,
        [
            {
                "id": _DEFAULT_ID,
                "source_type": "wechat_article_api",
                "name": "mptext 免费 API",
                "configuration": {
                    "base_url": "https://down.mptext.top/api/public/v1/download",
                    "priority": 10,
                    "auth_header": "X-Auth-Key",
                    "auth_prefix": "",
                    "is_default": True,
                },
                "secret_ref": None,
                "scope": {},
                "status": "active",
                "last_test_result": {},
                "sync_cursor": {},
            }
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM external_knowledge_sources WHERE id = :source_id").bindparams(
            source_id=_DEFAULT_ID
        )
    )

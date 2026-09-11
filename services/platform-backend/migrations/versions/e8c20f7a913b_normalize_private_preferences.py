"""Expand private memory into scoped entries and independent confirmation records.

The previous tables/JSON remain rollback copies for one compatibility window.
Pause API/worker/scheduler writers for the backfill and application switch.
"""

import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "e8c20f7a913b"
down_revision = "d7f93a10bc62"
branch_labels = None
depends_on = None

MEMORY_FIELDS = (
    "key",
    "value",
    "evidence",
    "project_id",
    "status",
    "source_type",
    "source_message_id",
    "confirmation_message_id",
    "source_at",
)
PROPOSAL_FIELDS = (
    "key",
    "value",
    "evidence",
    "project_id",
    "status",
    "base",
    "previous_value",
    "expires_at",
    "suggested_at",
    "decision_message_id",
)


def _fingerprint(item: dict | None) -> str:
    return hashlib.sha256(json.dumps(item, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def upgrade() -> None:
    entries = op.create_table(
        "user_memory_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id")),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("source_message_id", sa.String(36), sa.ForeignKey("messages.id")),
        sa.Column("confirmation_message_id", sa.String(36), sa.ForeignKey("messages.id")),
        sa.Column("source_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("user_id", "project_id", "key", name="uq_memory_project_key"),
        sa.CheckConstraint("status IN ('active','revoked')", name="ck_memory_entry_status"),
    )
    op.create_index(
        "uq_memory_personal_key",
        "user_memory_entries",
        ["user_id", "key"],
        unique=True,
        postgresql_where=sa.text("project_id IS NULL"),
        sqlite_where=sa.text("project_id IS NULL"),
    )
    op.create_index("ix_memory_user_status", "user_memory_entries", ["user_id", "status"])
    proposals = op.create_table(
        "preference_proposals",
        sa.Column(
            "id", sa.String(36), sa.ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column(
            "user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id")),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("base", sa.String(64), nullable=False),
        sa.Column("previous_value", sa.Text()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("suggested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision_message_id", sa.String(36), sa.ForeignKey("messages.id")),
        sa.CheckConstraint(
            "status IN ('observed','pending','confirmed','dismissed','suppressed','expired')",
            name="ck_preference_proposal_status",
        ),
    )
    op.create_index(
        "ix_proposals_user_key_scope", "preference_proposals", ["user_id", "key", "project_id"]
    )
    connection = op.get_bind()
    legacy = sa.table(
        "user_preference_memories",
        sa.column("user_id", sa.String(36)),
        sa.column("items", sa.JSON()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    messages = sa.table(
        "messages",
        sa.column("id", sa.String(36)),
        sa.column("task_id", sa.String(36)),
        sa.column("role", sa.String(16)),
        sa.column("content_json", sa.JSON()),
    )
    tasks = sa.table("tasks", sa.column("id", sa.String(36)), sa.column("owner_id", sa.String(36)))
    canonical_fingerprints = {}
    entry_count = 0
    for profile in connection.execute(sa.select(legacy)).mappings():
        canonical_items = []
        for item in profile["items"]:
            if not isinstance(item, dict) or set(item) - set(MEMORY_FIELDS):
                raise RuntimeError("Unrecognized private memory fields; backfill aborted")
            canonical = {field: item.get(field) for field in MEMORY_FIELDS}
            source_at = datetime.fromisoformat(canonical["source_at"])
            if source_at.tzinfo is None:
                raise RuntimeError("Private memory timestamp has no timezone; backfill aborted")
            source_at = source_at.astimezone(UTC)
            canonical["source_at"] = source_at.isoformat()
            canonical_fingerprints[(profile["user_id"], item["key"], item.get("project_id"))] = (
                _fingerprint(item),
                _fingerprint(canonical),
            )
            connection.execute(
                entries.insert().values(
                    **{**canonical, "source_at": source_at},
                    id=str(uuid4()),
                    user_id=profile["user_id"],
                    created_at=profile["created_at"],
                    updated_at=source_at,
                )
            )
            canonical_items.append(canonical)
            entry_count += 1
        if canonical_items != profile["items"]:
            connection.execute(
                legacy.update()
                .where(legacy.c.user_id == profile["user_id"])
                .values(items=canonical_items)
            )
    proposal_count = 0
    query = (
        sa.select(messages.c.id, messages.c.content_json, tasks.c.owner_id)
        .select_from(messages.join(tasks, messages.c.task_id == tasks.c.id))
        .where(
            messages.c.role == "user",
            messages.c.content_json["preference_proposal"]["status"].as_string().is_not(None),
        )
    )
    for row in connection.execute(query).mappings():
        item = row["content_json"]["preference_proposal"]
        if not isinstance(item, dict) or set(item) - set(PROPOSAL_FIELDS):
            raise RuntimeError("Unrecognized preference proposal fields; backfill aborted")
        values = {field: item.get(field) for field in PROPOSAL_FIELDS}
        fingerprints = canonical_fingerprints.get(
            (row["owner_id"], item["key"], item.get("project_id"))
        )
        if fingerprints and values["base"] == fingerprints[0]:
            values["base"] = fingerprints[1]
            connection.execute(
                messages.update()
                .where(messages.c.id == row["id"])
                .values(
                    content_json={
                        **row["content_json"],
                        "preference_proposal": {**item, "base": values["base"]},
                    }
                )
            )
        for field in ("expires_at", "suggested_at"):
            values[field] = datetime.fromisoformat(values[field])
            if values[field].tzinfo is None:
                raise RuntimeError(
                    "Preference proposal timestamp has no timezone; backfill aborted"
                )
        connection.execute(
            proposals.insert().values(**values, id=row["id"], user_id=row["owner_id"])
        )
        proposal_count += 1
    # Transactional data-movement guard, not a post-deployment functional test.
    if connection.scalar(sa.select(sa.func.count()).select_from(entries)) != entry_count:
        raise RuntimeError("Private memory backfill count mismatch")
    if connection.scalar(sa.select(sa.func.count()).select_from(proposals)) != proposal_count:
        raise RuntimeError("Preference proposal backfill count mismatch")


def downgrade() -> None:
    # Application rollback needs no downgrade: both legacy copies are maintained.
    # Retain normalized records to avoid losing newer data during an accidental downgrade.
    raise RuntimeError("Roll back the application image only; retain this additive schema")

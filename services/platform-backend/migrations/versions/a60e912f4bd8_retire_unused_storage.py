"""Retire audited storage after deploying the compatible reader/writer release.

Pause all writers and archive the old records before passing the explicit release
acknowledgement. Rollback is to the f29d7a861ce4-compatible application, not old DDL.
"""

import logging

import sqlalchemy as sa
from alembic import context, op

revision = "a60e912f4bd8"
down_revision = "f29d7a861ce4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if context.get_x_argument(as_dictionary=True).get("storage_retirement_confirmed") != "1":
        raise RuntimeError(
            "Deploy the storage-compatible application, pause writers and archive the database; "
            "then pass -x storage_retirement_confirmed=1. See the storage retirement runbook."
        )
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        raise RuntimeError("This audited storage retirement requires PostgreSQL")
    connection.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    connection.execute(sa.text("SET LOCAL statement_timeout = '30s'"))
    # Lock the audited objects before inspecting them so the guards and deletion
    # see one stable state. No CASCADE: unexpected dependencies must stop release.
    connection.execute(
        sa.text(
            "LOCK TABLE article_assets, auth_identities, context_snapshots, "
            "user_preference_memories, messages, tasks, user_preferences, "
            "article_renders, job_records, ai_run_events, user_memory_entries, "
            "preference_proposals IN ACCESS EXCLUSIVE MODE"
        )
    )
    guards = {
        "Article asset associations are no longer empty": "SELECT count(*) FROM article_assets",
        "Authentication identities are no longer empty": "SELECT count(*) FROM auth_identities",
        "Render object keys now carry data": (
            "SELECT count(*) FROM article_renders WHERE html_object_key IS NOT NULL"
        ),
        "Job retry timestamps now carry data": (
            "SELECT count(*) FROM job_records WHERE next_retry_at IS NOT NULL"
        ),
        "Unreviewed non-style preferences exist": (
            "SELECT count(*) FROM user_preferences WHERE preference_type <> 'writing_style' "
            "AND NOT (preference_type IN ('tone', 'article_length') "
            "AND source_type IN ('dialogue_feedback', 'confirmed_article') "
            "AND status IN ('candidate', 'revoked'))"
        ),
        "Legacy proposal has no corresponding normalized record": (
            "SELECT count(*) FROM messages m JOIN tasks t ON t.id = m.task_id "
            "WHERE m.content_json::jsonb ? 'preference_proposal' AND NOT EXISTS "
            "(SELECT 1 FROM preference_proposals p WHERE p.id = m.id "
            "AND p.user_id = t.owner_id "
            "AND p.key = m.content_json->'preference_proposal'->>'key' "
            "AND p.project_id IS NOT DISTINCT FROM "
            "(m.content_json->'preference_proposal'->>'project_id'))"
        ),
        "Legacy memory has no corresponding normalized entry": (
            "SELECT count(*) FROM user_preference_memories m, "
            "LATERAL jsonb_array_elements(m.items::jsonb) item WHERE NOT EXISTS "
            "(SELECT 1 FROM user_memory_entries e WHERE e.user_id = m.user_id "
            "AND e.key = item->>'key' "
            "AND e.project_id IS NOT DISTINCT FROM (item->>'project_id'))"
        ),
    }
    for reason, query in guards.items():
        if connection.scalar(sa.text(query)):
            raise RuntimeError(f"{reason}; storage retirement aborted without deleting data")
    unique_constraints = sa.inspect(connection).get_unique_constraints("ai_run_events")
    if not any(
        item["name"] == "uq_ai_event_seq" and item["column_names"] == ["run_id", "seq"]
        for item in unique_constraints
    ):
        raise RuntimeError("Required AI event unique index is missing; retirement aborted")

    archived_snapshots = connection.scalar(sa.text("SELECT count(*) FROM context_snapshots"))
    archived_profiles = connection.scalar(sa.text("SELECT count(*) FROM user_preference_memories"))
    removed_proposal_copies = connection.execute(
        sa.text(
            "UPDATE messages SET content_json = "
            "(content_json::jsonb - 'preference_proposal')::json "
            "WHERE content_json::jsonb ? 'preference_proposal'"
        )
    ).rowcount
    removed_legacy_preferences = connection.execute(
        sa.text("DELETE FROM user_preferences WHERE preference_type <> 'writing_style'")
    ).rowcount
    for table in (
        "article_assets",
        "auth_identities",
        "context_snapshots",
        "user_preference_memories",
    ):
        op.drop_table(table)
    for table, column in (
        ("tasks", "use_preferences"),
        ("user_preferences", "confidence"),
        ("article_renders", "html_object_key"),
        ("job_records", "next_retry_at"),
    ):
        op.drop_column(table, column)
    op.drop_index("ix_ai_events_run_seq", table_name="ai_run_events")
    logging.getLogger("alembic.runtime.migration").info(
        "Retired 4 tables, 4 columns and 1 duplicate index; "
        "archived snapshots=%s, archived profiles=%s, removed proposal copies=%s, "
        "archived non-style preferences=%s",
        archived_snapshots,
        archived_profiles,
        removed_proposal_copies,
        removed_legacy_preferences,
    )


def downgrade() -> None:
    raise RuntimeError(
        "Roll back only to the storage-compatible application image. "
        "Recover retired records from the secured backup with an explicit recovery plan; "
        "do not recreate empty tables or overwrite the live database."
    )

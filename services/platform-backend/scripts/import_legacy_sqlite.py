"""One-shot, insert-only recovery into PostgreSQL; dry-run unless --apply is supplied.

Back up both databases first. The source is opened read-only; any constraint conflict
rolls back the entire import. Existing target records are never overwritten.
LEGACY_MODEL_SECRET_KEY supplies the source encryption key, never a command argument.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Numeric, select
from sqlalchemy.exc import SQLAlchemyError

from app.api.admin import _model_configuration_fingerprint
from app.config import Settings
from app.database import Database
from app.domains.common import audit
from app.models import Base, ModelDeployment, ModelProviderRecord, utcnow
from app.providers import EnvironmentSecretProvider


def convert(value: Any, column_type: Any) -> Any:
    if value is None:
        return None
    if isinstance(column_type, JSON):
        return json.loads(value)
    if isinstance(column_type, DateTime):
        parsed = datetime.fromisoformat(value)
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed
    if isinstance(column_type, Boolean):
        return bool(value)
    if isinstance(column_type, Numeric):
        return Decimal(str(value))
    return value


def reencrypt(value: Any, old: EnvironmentSecretProvider, new: EnvironmentSecretProvider) -> Any:
    if isinstance(value, str) and value.startswith("encrypted:v1:"):
        return new.protect(old.resolve(value))
    if isinstance(value, dict):
        return {key: reencrypt(item, old, new) for key, item in value.items()}
    if isinstance(value, list):
        return [reencrypt(item, old, new) for item in value]
    return value


async def migrate(source: Path, *, apply: bool) -> dict[str, Any]:
    settings = Settings.from_env()
    if not settings.database_url.startswith("postgresql+asyncpg://"):
        raise RuntimeError("Target must be PostgreSQL")
    old = EnvironmentSecretProvider(os.environ["LEGACY_MODEL_SECRET_KEY"])
    new = EnvironmentSecretProvider(settings.model_secret_master_key or settings.token_secret)
    database = Database(settings)
    connection = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    report: dict[str, Any] = {"applied": apply, "imported": {}, "sessions_revoked": 0}
    try:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Source integrity check failed")
        names = {
            r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        unknown = names - set(Base.metadata.tables) - {"alembic_version"}
        if unknown:
            raise RuntimeError("Unknown legacy tables: " + ", ".join(sorted(unknown)))
        async with database.session_maker() as session:
            async with session.begin():
                for table in Base.metadata.sorted_tables:
                    if table.name not in names:
                        continue
                    rows = connection.execute(f'SELECT * FROM "{table.name}"').fetchall()
                    if not rows:
                        continue
                    # Reject overlap instead of guessing how two owners/configurations should merge.
                    ids = [row["id"] for row in rows]
                    if await session.scalar(select(table.c.id).where(table.c.id.in_(ids)).limit(1)):
                        raise RuntimeError("Target ID conflict in " + table.name)
                    for source_row in rows:
                        row = {
                            col.name: convert(source_row[col.name], col.type)
                            for col in table.columns
                            if col.name in source_row.keys()
                        }
                        if table.name == "outbox_events" and row["status"] != "published":
                            raise RuntimeError("Pending legacy outbox requires explicit review")
                        if table.name in {"admin_sessions", "refresh_tokens"}:
                            row["revoked_at"] = row.get("revoked_at") or utcnow()
                            report["sessions_revoked"] += 1
                        # Preserve a valid historical test after changing only encryption wrapping.
                        old_ref = row.get("secret_ref")
                        row = reencrypt(row, old, new)
                        if table.name == "model_providers" and old_ref:
                            test = row["last_test_result"]
                            deployment_id = test.get("configuration_id")
                            raw = connection.execute(
                                "SELECT * FROM model_deployments WHERE id=?", (deployment_id,)
                            ).fetchone()
                            if raw:
                                deployment = ModelDeployment(
                                    **{
                                        col.name: convert(raw[col.name], col.type)
                                        for col in ModelDeployment.__table__.columns
                                    }
                                )
                                provider = ModelProviderRecord(**{**row, "secret_ref": old_ref})
                                if test.get("configuration_fingerprint") == (
                                    _model_configuration_fingerprint(provider, deployment)
                                ):
                                    provider.secret_ref = row["secret_ref"]
                                    test["configuration_fingerprint"] = (
                                        _model_configuration_fingerprint(provider, deployment)
                                    )
                        try:
                            await session.execute(table.insert().values(**row))
                        except SQLAlchemyError:
                            # Never print SQL parameters: they can contain credentials or user text.
                            raise RuntimeError(
                                "Insert/constraint failure in " + table.name
                            ) from None
                    report["imported"][table.name] = len(rows)
                audit(
                    session,
                    actor_type="system",
                    actor_id="legacy-postgresql-migration",
                    action="database.legacy_import",
                    target_type="database",
                    target_id=None,
                    request_id=None,
                    reason="User requested PostgreSQL-only development",
                    details=report,
                )
                await session.flush()
                if not apply:
                    await session.rollback()
        return report
    finally:
        connection.close()
        await database.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(migrate(args.source, apply=args.apply)), ensure_ascii=False))

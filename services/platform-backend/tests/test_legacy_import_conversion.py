from datetime import UTC
from decimal import Decimal

from sqlalchemy import JSON, Boolean, DateTime, Numeric

from app.providers import EnvironmentSecretProvider
from scripts.import_legacy_sqlite import convert, reencrypt


def test_legacy_values_preserve_json_numbers_and_utc() -> None:
    assert convert('{"permissions":["*"]}', JSON()) == {"permissions": ["*"]}
    assert convert("2026-09-03 12:00:00", DateTime(timezone=True)).tzinfo == UTC
    assert convert("0.00012345", Numeric()) == Decimal("0.00012345")
    assert convert(0, Boolean()) is False
    assert convert(None, JSON()) is None


def test_legacy_secrets_are_rewrapped_including_frozen_snapshots() -> None:
    old = EnvironmentSecretProvider("old-test-key")
    new = EnvironmentSecretProvider("new-test-key")
    source = {"snapshot": [{"secret_ref": old.protect("test-secret"), "model": "test"}]}
    migrated = reencrypt(source, old, new)
    assert migrated != source
    assert new.resolve(migrated["snapshot"][0]["secret_ref"]) == "test-secret"
    assert old.resolve(source["snapshot"][0]["secret_ref"]) == "test-secret"
    assert migrated["snapshot"][0]["model"] == "test"

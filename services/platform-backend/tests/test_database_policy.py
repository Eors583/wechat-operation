from dataclasses import replace

import pytest

from app.config import Settings
from app.database import Database


def test_runtime_defaults_are_postgresql(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("RETRIEVAL_DATABASE_URL", raising=False)
    settings = Settings.from_env()
    assert settings.database_url.startswith("postgresql+asyncpg://")
    assert settings.retrieval_database_url.startswith("postgresql+asyncpg://")
    assert settings.retrieval_database_url != settings.database_url


@pytest.mark.parametrize("environment", ["development", "production", "staging"])
def test_runtime_rejects_sqlite(environment: str) -> None:
    settings = Settings(environment=environment, database_url="sqlite+aiosqlite:///old.db")
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        settings.validate()
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        Database(settings)
    replace(settings, environment="test").validate()

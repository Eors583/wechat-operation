from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.models import Base


class Database:
    def __init__(self, settings: Settings) -> None:
        if settings.environment != "test" and not settings.database_url.startswith(
            "postgresql+asyncpg://"
        ):
            raise RuntimeError("Application databases must use PostgreSQL outside isolated tests")
        kwargs: dict[str, object] = {"pool_pre_ping": True}
        if settings.database_url in {"sqlite+aiosqlite://", "sqlite+aiosqlite:///:memory:"}:
            kwargs["poolclass"] = StaticPool
            kwargs["connect_args"] = {"check_same_thread": False}
        self.engine: AsyncEngine = create_async_engine(settings.database_url, **kwargs)
        self.session_maker = async_sessionmaker(
            self.engine, expire_on_commit=False, autoflush=False
        )

        if settings.database_url.startswith("sqlite"):
            event.listen(self.engine.sync_engine, "connect", _enable_sqlite_foreign_keys)

    async def create_schema(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def drop_schema(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)

    async def dispose(self) -> None:
        await self.engine.dispose()


def _enable_sqlite_foreign_keys(dbapi_connection: object, _: object) -> None:
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    # AsyncSession is stateful; every request receives its own instance.
    database: Database = request.app.state.database
    async with database.session_maker() as session:
        yield session


def sync_database_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql+psycopg://").replace(
        "sqlite+aiosqlite://", "sqlite://"
    )


def metadata_engine_for_testing(url: str) -> Engine:
    """Only used by migration smoke tooling that needs a synchronous URL."""
    from sqlalchemy import create_engine

    return create_engine(sync_database_url(url))

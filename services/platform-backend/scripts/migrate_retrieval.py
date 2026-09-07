from __future__ import annotations

import asyncio
from pathlib import Path

import asyncpg

from app.config import Settings


async def main() -> None:
    settings = Settings.from_env()
    if not settings.retrieval_database_url:
        print("RETRIEVAL_DATABASE_URL is empty; retrieval schema migration skipped.")
        return
    dsn = settings.retrieval_database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    schema_path = Path(__file__).resolve().parents[1] / "retrieval-schema.sql"
    sql = schema_path.read_text(encoding="utf-8")
    connection = await asyncpg.connect(dsn)
    try:
        await connection.execute(sql)
    finally:
        await connection.close()
    print("Retrieval schema is up to date.")


if __name__ == "__main__":
    asyncio.run(main())

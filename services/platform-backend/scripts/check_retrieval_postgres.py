"""Read-only regression check against the configured PostgreSQL retrieval database.

Run with: uv run python -m scripts.check_retrieval_postgres [document_id]
Uses one existing indexed chunk; never logs source text, vectors or credentials.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid

from sqlalchemy import text

from app.retrieval import PostgresRetrievalBackend


async def check(document_id: str | None = None) -> None:
    url = os.environ["RETRIEVAL_DATABASE_URL"]
    if not url.startswith("postgresql+asyncpg://"):
        raise ValueError("This check requires PostgreSQL/asyncpg")
    backend = PostgresRetrievalBackend(url)
    try:
        async with backend._engine.connect() as connection:
            sample = (
                (
                    await connection.execute(
                        text(
                            "SELECT owner_id, project_id, document_id, embedding::text AS vector "
                            "FROM retrieval_chunks WHERE embedding IS NOT NULL "
                            "AND (CAST(:document_id AS varchar) IS NULL OR document_id = "
                            "CAST(:document_id AS varchar)) LIMIT 1"
                        ),
                        {"document_id": document_id},
                    )
                )
                .mappings()
                .first()
            )
        if sample is None:
            raise AssertionError("No indexed document available for the regression check")
        arguments = {
            "owner_id": sample["owner_id"],
            "project_id": None,
            "document_ids": [sample["document_id"]],
            "query": "写文章",
            "query_vector": json.loads(sample["vector"]),
            "limit": 5,
        }
        hits = await backend.candidates(**arguments)
        assert hits and all(hit.document_id == sample["document_id"] for hit in hits)
        print(f"PASS: null project hybrid retrieval returned {len(hits)} chunks")
        if sample["project_id"]:
            assert await backend.candidates(**{**arguments, "project_id": sample["project_id"]})
        assert not await backend.candidates(**{**arguments, "owner_id": str(uuid.uuid4())})
        assert not await backend.candidates(**{**arguments, "project_id": str(uuid.uuid4())})
        assert not await backend.candidates(**{**arguments, "document_ids": [str(uuid.uuid4())]})
        print("PASS: non-null project, owner and document isolation; no writes performed")
    finally:
        await backend.dispose()


if __name__ == "__main__":
    asyncio.run(check(sys.argv[1] if len(sys.argv) > 1 else None))

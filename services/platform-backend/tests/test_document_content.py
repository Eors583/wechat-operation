from __future__ import annotations

import hashlib

from fastapi import FastAPI
from httpx import AsyncClient

from app.models import Asset, Document
from tests.conftest import bearer, register_and_login
from tests.fakes import InMemoryStorageProvider


async def test_document_content_returns_owned_original_file(
    app: FastAPI, client: AsyncClient
) -> None:
    owner = await register_and_login(client, "document-owner@example.com")
    stranger = await register_and_login(client, "document-stranger@example.com")
    owner_id = owner["registered_user"]["id"]
    content = b"pptx-original-bytes"
    digest = hashlib.sha256(content).hexdigest()
    storage = app.state.storage_provider
    assert isinstance(storage, InMemoryStorageProvider)
    await storage.put_bytes(
        object_key="owner/presentation",
        content=content,
        mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        sha256=digest,
    )
    async with app.state.database.session_maker() as session:
        session.add(
            Asset(
                id="presentation-asset",
                owner_id=owner_id,
                filename="战略规划.pptx",
                mime_type=(
                    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
                ),
                size_bytes=len(content),
                sha256=digest,
                object_key="owner/presentation",
                scan_status="clean",
            )
        )
        await session.flush()
        session.add(
            Document(
                id="presentation-document",
                owner_id=owner_id,
                asset_id="presentation-asset",
                title="战略规划.pptx",
                status="completed",
            )
        )
        await session.commit()

    response = await client.get(
        "/api/v1/documents/presentation-document/content",
        headers=bearer(owner["access_token"]),
    )
    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    )
    assert (
        "filename*=UTF-8''%E6%88%98%E7%95%A5%E8%A7%84%E5%88%92.pptx"
        in response.headers["content-disposition"]
    )
    assert response.headers["cache-control"] == "private, no-store"

    hidden = await client.get(
        "/api/v1/documents/presentation-document/content",
        headers=bearer(stranger["access_token"]),
    )
    assert hidden.status_code == 404

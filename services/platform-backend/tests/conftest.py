from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app
from tests.fakes import InMemoryStorageProvider, LocalDocumentProcessingProvider


@pytest_asyncio.fixture
async def app(tmp_path: Path) -> AsyncIterator[FastAPI]:
    settings = Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        token_secret="test-token-secret-with-at-least-thirty-two-characters",
        auto_create_schema=True,
        wechat_provider_mode="direct",
        allowed_origins=("http://localhost:9000", "capacitor://localhost"),
    )
    application = create_app(settings)
    storage = InMemoryStorageProvider()
    application.state.storage_provider = storage
    application.state.document_processing_provider = LocalDocumentProcessingProvider(storage)
    async with application.router.lifespan_context(application):
        yield application


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as test_client:
        yield test_client


async def register_and_login(
    client: AsyncClient,
    email: str,
    *,
    display_name: str = "测试用户",
    platform: str = "windows",
) -> dict[str, Any]:
    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "display_name": display_name,
            "password": "correct-horse-battery-staple",
            "accepted_terms": True,
        },
    )
    assert registered.status_code == 201, registered.text
    logged_in = await client.post(
        "/api/v1/auth/login",
        json={
            "identifier": email,
            "password": "correct-horse-battery-staple",
            "platform": platform,
            "device_name": "pytest",
        },
    )
    assert logged_in.status_code == 200, logged_in.text
    return {**logged_in.json(), "registered_user": registered.json()}


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}

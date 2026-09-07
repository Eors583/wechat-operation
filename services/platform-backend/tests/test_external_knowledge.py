from __future__ import annotations

import json

import httpx
from fastapi import FastAPI
from sqlalchemy import select

from app.domains.external_knowledge import enqueue_due_lexiang_syncs, sync_lexiang_source
from app.external_knowledge import (
    LexiangEntry,
    LexiangEntryPage,
    LexiangKnowledgeProvider,
)
from app.models import (
    Document,
    ExternalKnowledgeMapping,
    ExternalKnowledgeSource,
    JobRecord,
    OutboxEvent,
    User,
)
from app.security import hash_password


async def test_lexiang_search_uses_scoped_targets_and_calling_staff_identity() -> None:
    token_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_requests
        if request.url.path == "/cgi-bin/token":
            token_requests += 1
            assert json.loads(request.content) == {
                "grant_type": "client_credentials",
                "app_key": "app-key",
                "app_secret": "app-secret",
            }
            return httpx.Response(
                200,
                json={"access_token": "access-token", "token_type": "Bearer", "expires_in": 7200},
            )
        assert request.url.path == "/cgi-bin/v1/ai/search"
        assert request.headers["Authorization"] == "Bearer access-token"
        assert request.headers["x-staff-id"] == "employee-1001"
        assert json.loads(request.content)["targets"] == [{"type": "space", "id": "space-1"}]
        return httpx.Response(
            200,
            json={
                "code": 0,
                "message": "success",
                "data": {
                    "list": [
                        {
                            "title": "企业知识",
                            "content": "只返回该成员有权查看的片段",
                            "url": "https://lexiangla.com/pages/entry-1",
                            "score": 0.93,
                        }
                    ]
                },
            },
        )

    provider = LexiangKnowledgeProvider(
        app_key="app-key",
        app_secret="app-secret",
        transport=httpx.MockTransport(handler),
    )
    hits = await provider.search(
        query="季度目标",
        staff_id="employee-1001",
        targets=[{"type": "space", "id": "space-1"}],
    )
    assert token_requests == 1
    assert hits[0].title == "企业知识"
    assert hits[0].score == 0.93


async def test_lexiang_entry_listing_and_page_content_preserve_sync_metadata() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/cgi-bin/token":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 7200})
        if request.url.path == "/cgi-bin/v1/kb/entries":
            assert request.url.params["space_id"] == "space-1"
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "entry-1",
                            "attributes": {
                                "name": "操作手册",
                                "entry_type": "page",
                                "has_children": True,
                                "updated_at": "2026-09-01T01:00:00Z",
                            },
                        }
                    ],
                    "meta": {"page_token": "next-page"},
                },
            )
        assert request.url.path == "/cgi-bin/v1/kb/entries/entry-1/content"
        assert request.url.params["content_type"] == "html"
        return httpx.Response(
            200,
            json={
                "data": {
                    "attributes": {"html_content": "<h1>操作手册</h1><p>第一步 &amp; 第二步</p>"}
                }
            },
        )

    provider = LexiangKnowledgeProvider(
        app_key="app-key",
        app_secret="app-secret",
        transport=httpx.MockTransport(handler),
    )
    page = await provider.list_entries(space_id="space-1")
    assert page.next_page_token == "next-page"
    assert page.entries[0].version == "2026-09-01T01:00:00Z"
    assert await provider.page_content("entry-1") == "操作手册\n第一步 & 第二步"


class StaticLexiangProvider:
    async def list_entries(
        self,
        *,
        space_id: str,
        parent_id: str | None = None,
        page_token: str | None = None,
        limit: int = 100,
    ) -> LexiangEntryPage:
        del parent_id, page_token, limit
        assert space_id == "space-1"
        return LexiangEntryPage(
            entries=[
                LexiangEntry(
                    id="entry-1",
                    name="同步知识页",
                    entry_type="page",
                    has_children=False,
                    version="v1",
                )
            ],
            next_page_token=None,
        )

    async def page_content(self, entry_id: str) -> str:
        assert entry_id == "entry-1"
        return "这是从乐享同步到本地检索副本的正文。"


async def test_lexiang_sync_upserts_mapping_document_and_skips_unchanged_version(
    app: FastAPI,
) -> None:
    async with app.state.database.session_maker() as session:
        user = User(
            email="lexiang-owner@example.com",
            display_name="乐享所有者",
            password_hash=hash_password("lexiang-owner-test-password"),
        )
        session.add(user)
        await session.flush()
        source = ExternalKnowledgeSource(
            source_type="lexiang",
            name="企业知识库",
            configuration={"app_key": "app-key"},
            scope={
                "sync_owner_id": user.id,
                "owner_staff_ids": {user.id: "employee-1"},
                "targets": [{"type": "space", "id": "space-1"}],
            },
            status="active",
        )
        session.add(source)
        await session.flush()
        first = await sync_lexiang_source(
            session,
            source=source,
            provider=StaticLexiangProvider(),  # type: ignore[arg-type]
            chunk_target_characters=800,
            chunk_overlap_characters=120,
            chunking_version="zh-char-v1",
            retrieval_required=False,
        )
        assert first["synced"] == 1
        mapping = await session.scalar(
            select(ExternalKnowledgeMapping).where(ExternalKnowledgeMapping.source_id == source.id)
        )
        assert mapping is not None and mapping.document_id is not None
        document = await session.get(Document, mapping.document_id)
        assert document is not None
        assert document.owner_id == user.id
        assert document.source_type == "lexiang"
        assert document.extracted_text == "这是从乐享同步到本地检索副本的正文。"

        second = await sync_lexiang_source(
            session,
            source=source,
            provider=StaticLexiangProvider(),  # type: ignore[arg-type]
            chunk_target_characters=800,
            chunk_overlap_characters=120,
            chunking_version="zh-char-v1",
            retrieval_required=False,
        )
        assert second["unchanged"] == 1
        await session.rollback()


async def test_scheduler_enqueues_each_due_source_only_once(app: FastAPI) -> None:
    async with app.state.database.session_maker() as session:
        user = User(
            email="lexiang-scheduler@example.com",
            display_name="乐享定时同步所有者",
            password_hash=hash_password("lexiang-scheduler-test-password"),
        )
        session.add(user)
        await session.flush()
        source = ExternalKnowledgeSource(
            source_type="lexiang",
            name="定时同步知识库",
            configuration={"app_key": "app-key"},
            scope={
                "sync_owner_id": user.id,
                "owner_staff_ids": {user.id: "employee-1"},
                "targets": [{"type": "space", "id": "space-1"}],
            },
            status="active",
        )
        session.add(source)
        await session.flush()

        assert await enqueue_due_lexiang_syncs(session, interval_seconds=300) == 1
        assert await enqueue_due_lexiang_syncs(session, interval_seconds=300) == 0
        job = await session.scalar(
            select(JobRecord).where(
                JobRecord.resource_type == "external_knowledge_source",
                JobRecord.resource_id == source.id,
            )
        )
        event = await session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.event_type == "external_knowledge.sync.requested",
                OutboxEvent.aggregate_id == source.id,
            )
        )
        assert job is not None
        assert job.owner_id == user.id
        assert job.frozen_payload["trigger"] == "scheduled"
        assert event is not None
        await session.rollback()

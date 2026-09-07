from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select

from app.domains.ai import freeze_ai_pipeline
from app.domains.layout import process_layout_extraction
from app.domains.wechat import process_wechat_operation, reconcile_wechat_operation
from app.models import (
    AIRun,
    AIRunEvent,
    AuditLog,
    InboxMessage,
    LayoutTemplate,
    ModelDeployment,
    ModelProviderRecord,
    ModelRouteVersion,
    OfficialAccount,
    Task,
    WechatOperation,
)
from app.providers import (
    LayoutExtractionResult,
    MockModelProvider,
    ModelResult,
    ProviderResultUnknown,
    ProviderUnavailable,
    WechatResult,
)
from app.worker_tasks import _process_ai

from .conftest import bearer, register_and_login

ARTICLE = {
    "type": "doc",
    "content": [
        {
            "type": "heading",
            "attrs": {"level": 1},
            "content": [{"type": "text", "text": "标题"}],
        },
        {
            "type": "paragraph",
            "attrs": {"module": "lead"},
            "content": [{"type": "text", "text": "导语"}],
        },
        {
            "type": "paragraph",
            "attrs": {"module": "body"},
            "content": [
                {"type": "text", "text": "粗体", "marks": [{"type": "bold"}]},
                {"type": "text", "text": "斜体", "marks": [{"type": "italic"}]},
                {
                    "type": "text",
                    "text": "链接",
                    "marks": [{"type": "link", "attrs": {"href": "https://example.com/reference"}}],
                },
                {"type": "text", "text": "正文 <script>alert(1)</script>"},
            ],
        },
        {
            "type": "paragraph",
            "attrs": {"module": "highlight"},
            "content": [{"type": "text", "text": "重点"}],
        },
        {
            "type": "paragraph",
            "attrs": {"module": "caption"},
            "content": [{"type": "text", "text": "图注"}],
        },
    ],
}


async def test_task_detail_exposes_safe_latest_ai_run_summary(
    app: FastAPI, client: AsyncClient
) -> None:
    login = await register_and_login(client, "latest-run-summary@example.com")
    user_id = login["registered_user"]["id"]
    async with app.state.database.session_maker() as session:
        task = Task(owner_id=user_id, title="失败恢复任务")
        session.add(task)
        await session.flush()
        run = AIRun(
            owner_id=user_id,
            task_id=task.id,
            run_type="article_generation",
            status="failed",
            model_route_snapshot={"secret_ref": "must-not-leak"},
            context_snapshot={"private": "must-not-leak"},
            idempotency_key="latest-run-summary-1",
            error_code="ModelRouteExhausted",
            error_message="All frozen model-route deployments failed",
        )
        session.add(run)
        await session.commit()
        task_id = task.id
        run_id = run.id

    response = await client.get(f"/api/v1/tasks/{task_id}", headers=bearer(login["access_token"]))

    assert response.status_code == 200
    summary = response.json()["latest_ai_run"]
    assert summary["id"] == run_id
    assert summary["status"] == "failed"
    assert summary["run_type"] == "article_generation"
    assert summary["error_code"] == "ModelRouteExhausted"
    assert summary["error_message"] == "All frozen model-route deployments failed"
    assert summary["created_at"]
    assert summary["completed_at"] is None
    assert set(summary) == {
        "id",
        "status",
        "run_type",
        "error_code",
        "error_message",
        "created_at",
        "completed_at",
    }


class RealLayoutExtractionProvider:
    async def extract(self, *, source_url: str) -> LayoutExtractionResult:
        return LayoutExtractionResult(
            style_tokens={
                "title": {"font_size": 28, "font_weight": 700, "color": "#111827"},
                "body": {"font_size": 16, "line_height": 1.8, "color": "#1f2937"},
            },
            source_snapshot={
                "source_url": source_url,
                "title": "真实公众号文章",
                "text_sample": "从真实抓取链路返回的样式样本。",
            },
            extractor_version="wechat-public-dom-test",
            simulated=False,
        )


class FailingLayoutExtractionProvider:
    async def extract(self, *, source_url: str) -> LayoutExtractionResult:
        del source_url
        raise ProviderUnavailable("没有读取到微信公众号正文，请确认文章链接仍然有效。")


class LearningLayoutModel(MockModelProvider):
    async def generate(self, *, purpose: str, prompt: str, context: dict[str, Any]) -> ModelResult:
        assert purpose == "layout_extraction"
        assert "只返回一个 JSON 对象" in prompt
        assert context["deterministic_baseline_style_tokens"]["body"]["font_size"] == 16
        return ModelResult(
            text=(
                '{"style_tokens":{"body":{"font_size":17,"line_height":1.9,'
                '"color":"#123456"},"heading1":{"font_size":21,"font_weight":700,'
                '"color":"#123456"}},"confidence":0.91,"module_evidence":'
                '{"body":["block-1","block-1"],"heading1":["block-2"]}}'
            ),
            structured={
                "type": "doc",
                "content": [{"type": "paragraph", "content": []}],
            },
            input_tokens=120,
            output_tokens=48,
            provider_request_id="layout-agent-request",
            simulated=False,
        )


class FailPublishOnceProvider:
    def __init__(self) -> None:
        self.draft_calls = 0
        self.publish_calls = 0

    async def authorization_url(self, *, state: str, redirect_uri: str) -> str:
        raise AssertionError("authorization is not part of this test")

    async def create_or_update_draft(
        self, *, account_ref: str, html: str, title: str, cover_ref: str | None
    ) -> WechatResult:
        self.draft_calls += 1
        return WechatResult(status="succeeded", media_id="media-existing")

    async def publish(self, *, account_ref: str, media_id: str) -> WechatResult:
        self.publish_calls += 1
        if self.publish_calls == 1:
            raise ProviderUnavailable("known pre-response failure")
        return WechatResult(status="succeeded", publish_id="publish-retried")

    async def reconcile(self, *, operation_type: str, external_id: str) -> WechatResult:
        return WechatResult(status="succeeded", publish_id=external_id)


class UnknownDraftProvider:
    def __init__(self) -> None:
        self.draft_calls = 0
        self.publish_calls = 0
        self.reconcile_calls: list[tuple[str, str]] = []

    async def authorization_url(self, *, state: str, redirect_uri: str) -> str:
        raise AssertionError("authorization is not part of this test")

    async def create_or_update_draft(
        self, *, account_ref: str, html: str, title: str, cover_ref: str | None
    ) -> WechatResult:
        self.draft_calls += 1
        raise ProviderResultUnknown("response lost", external_id="media-to-reconcile")

    async def publish(self, *, account_ref: str, media_id: str) -> WechatResult:
        self.publish_calls += 1
        return WechatResult(status="succeeded", publish_id="publish-after-reconcile")

    async def reconcile(self, *, operation_type: str, external_id: str) -> WechatResult:
        self.reconcile_calls.append((operation_type, external_id))
        return WechatResult(status="succeeded", media_id=external_id)


class AuthorizationProvider:
    def __init__(self) -> None:
        self.state: str | None = None

    async def authorization_url(self, *, state: str, redirect_uri: str) -> str:
        self.state = state
        return f"https://open.weixin.qq.com/mock-authorize?state={state}"

    async def create_or_update_draft(
        self, *, account_ref: str, html: str, title: str, cover_ref: str | None
    ) -> WechatResult:
        raise AssertionError("draft creation is not part of this test")

    async def publish(self, *, account_ref: str, media_id: str) -> WechatResult:
        raise AssertionError("publishing is not part of this test")

    async def reconcile(self, *, operation_type: str, external_id: str) -> WechatResult:
        raise AssertionError("reconciliation is not part of this test")


class BlockingArticleModel(MockModelProvider):
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def generate(self, *, purpose: str, prompt: str, context: dict[str, Any]) -> ModelResult:
        if purpose == "article_generation":
            self.started.set()
            await self.release.wait()
        return await super().generate(purpose=purpose, prompt=prompt, context=context)


async def test_ai_run_idempotency_quota_and_sse(
    app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    login = await register_and_login(client, "ai@example.com")
    headers = {**bearer(login["access_token"]), "Idempotency-Key": "task-create-1"}
    payload = {
        "title": "AI 任务",
        "first_message": {
            "text": "写一篇关于春天的文章",
            "content": {"source": "pytest"},
            "client_message_id": "client-message-1",
        },
    }
    created = await client.post("/api/v1/tasks", headers=headers, json=payload)
    assert created.status_code == 202, created.text
    run_id = created.json()["ai_run"]["id"]
    task_id = created.json()["task"]["id"]

    repeated = await client.post("/api/v1/tasks", headers=headers, json=payload)
    assert repeated.status_code == 202
    assert repeated.json()["ai_run"]["id"] == run_id

    run = await client.get(f"/api/v1/ai-runs/{run_id}", headers=bearer(login["access_token"]))
    assert run.status_code == 200
    assert run.json()["status"] == "completed"
    assert run.json()["quota_reserved"] == 0

    quota = await client.get("/api/v1/quota", headers=bearer(login["access_token"]))
    assert quota.json()["balance"] == 499
    reserves = [
        item for item in quota.json()["ledger"] if item["business_type"] == "ai_run_reserve"
    ]
    assert len(reserves) == 1

    events = await client.get(
        f"/api/v1/ai-runs/{run_id}/events", headers=bearer(login["access_token"])
    )
    assert events.status_code == 200
    assert "event: run.accepted" in events.text
    assert "event: text.delta" in events.text
    assert "event: warning" in events.text
    assert "event: run.completed" in events.text
    stage_positions = [
        events.text.index(f'"stage":"{stage}"')
        for stage in (
            "validating",
            "retrieving",
            "planning",
            "generating",
            "validating_output",
            "saving_version",
            "ready_for_formatting",
        )
    ]
    assert stage_positions == sorted(stage_positions)
    resumed_events = await client.get(
        f"/api/v1/ai-runs/{run_id}/events",
        headers={**bearer(login["access_token"]), "Last-Event-ID": "2"},
    )
    assert resumed_events.status_code == 200
    assert "id: 1\n" not in resumed_events.text
    assert "id: 2\n" not in resumed_events.text
    assert "event: run.completed" in resumed_events.text

    task = await client.get(f"/api/v1/tasks/{task_id}", headers=bearer(login["access_token"]))
    article = await client.get(
        f"/api/v1/articles/{task.json()['current_article_id']}",
        headers=bearer(login["access_token"]),
    )
    version = article.json()["version"]
    assert version["plain_text"]
    assert version["content_json"]["type"] == "doc"
    for block in version["content_json"]["content"]:
        assert "text" not in block
        assert block["content"][0]["type"] == "text"
        assert block["content"][0]["text"]
    round_trip = await client.put(
        f"/api/v1/articles/{article.json()['article']['id']}/content",
        headers={**bearer(login["access_token"]), "Idempotency-Key": "tiptap-round-trip-1"},
        json={
            "base_version_no": 1,
            "title": article.json()["article"]["title"],
            "summary": article.json()["article"]["summary"],
            "content": version["content_json"],
            "source": "manual",
        },
    )
    assert round_trip.status_code == 200, round_trip.text
    assert round_trip.json()["version"]["content_json"] == version["content_json"]

    conflict = await client.post(
        "/api/v1/tasks",
        headers=headers,
        json={**payload, "title": "同一个键，不同请求"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "IDEMPOTENCY_KEY_CONFLICT"

    skill = await client.post(
        "/api/v1/skills",
        headers=bearer(login["access_token"]),
        json={
            "name": "品牌语气",
            "scenario": "品牌公众号文章",
            "instructions": "保持专业、简洁，并清楚标注不确定信息。",
        },
    )
    assert skill.status_code == 201, skill.text
    skill_id = skill.json()["skill"]["id"]
    initial_skill_version_id = skill.json()["version"]["id"]
    edited_skill = await client.patch(
        f"/api/v1/skills/{skill_id}",
        headers=bearer(login["access_token"]),
        json={"instructions": "使用第二版的专业、简洁品牌语气。"},
    )
    assert edited_skill.status_code == 200, edited_skill.text
    assert edited_skill.json()["version"]["version_no"] == 2
    skill_version_id = edited_skill.json()["version"]["id"]
    assert skill_version_id != initial_skill_version_id
    first_run_with_skill = await client.post(
        "/api/v1/tasks",
        headers={
            **bearer(login["access_token"]),
            "Idempotency-Key": "task-create-with-skill-1",
        },
        json={
            "title": "首轮技能任务",
            "current_skill_id": skill_id,
            "use_preferences": False,
            "first_message": {
                "text": "首轮就使用品牌语气",
                "content": {},
                "client_message_id": "client-message-skill-first",
            },
        },
    )
    assert first_run_with_skill.status_code == 202, first_run_with_skill.text
    assert first_run_with_skill.json()["task"]["current_skill_id"] == skill_id
    assert first_run_with_skill.json()["task"]["use_preferences"] is False
    first_frozen = await client.get(
        f"/api/v1/ai-runs/{first_run_with_skill.json()['ai_run']['id']}",
        headers=bearer(login["access_token"]),
    )
    assert first_frozen.json()["skill_version_id"] == skill_version_id
    selected = await client.patch(
        f"/api/v1/tasks/{task_id}",
        headers=bearer(login["access_token"]),
        json={"current_skill_id": skill_id},
    )
    assert selected.status_code == 200
    preference_project = await client.post(
        "/api/v1/projects",
        headers=bearer(login["access_token"]),
        json={"name": "偏好隔离项目"},
    )
    personal_preference = await client.post(
        "/api/v1/preferences",
        headers=bearer(login["access_token"]),
        json={
            "preference_type": "tone",
            "value": "个人偏好：简洁",
            "scope": "personal",
        },
    )
    project_preference = await client.post(
        "/api/v1/preferences",
        headers=bearer(login["access_token"]),
        json={
            "preference_type": "project-tone",
            "value": "只属于另一个项目",
            "scope": "project",
            "project_id": preference_project.json()["id"],
        },
    )
    assert personal_preference.status_code == 201
    assert project_preference.status_code == 201
    preference_page = await client.get(
        "/api/v1/preferences", headers=bearer(login["access_token"]), params={"limit": 1}
    )
    assert len(preference_page.json()["items"]) == 1
    assert preference_page.json()["next_cursor"]
    preference_page_2 = await client.get(
        "/api/v1/preferences",
        headers=bearer(login["access_token"]),
        params={"limit": 1, "cursor": preference_page.json()["next_cursor"]},
    )
    assert len(preference_page_2.json()["items"]) == 1
    assert preference_page_2.json()["items"][0]["id"] != preference_page.json()["items"][0]["id"]
    next_run = await client.post(
        f"/api/v1/tasks/{task_id}/messages",
        headers={
            **bearer(login["access_token"]),
            "Idempotency-Key": "task-message-with-skill-1",
        },
        json={
            "text": "用品牌语气重写",
            "content": {},
            "client_message_id": "client-message-2",
        },
    )
    assert next_run.status_code == 202, next_run.text
    frozen_run = await client.get(
        f"/api/v1/ai-runs/{next_run.json()['ai_run']['id']}",
        headers=bearer(login["access_token"]),
    )
    assert frozen_run.json()["skill_version_id"] == skill_version_id
    assert frozen_run.json()["context_snapshot"]["skill_version_id"] == skill_version_id
    assert (
        frozen_run.json()["context_snapshot"]["task_memory_summary"]["facts"]["source"]
        == "model-route-memory-summary-v1"
    )
    assert (
        frozen_run.json()["context_snapshot"]["current_article"]["article_id"]
        == article.json()["article"]["id"]
    )
    assert frozen_run.json()["context_snapshot"]["current_article"]["version_no"] == 2
    assert [item["value"] for item in frozen_run.json()["context_snapshot"]["preferences"]] == [
        "个人偏好：简洁"
    ]
    rewritten_article = await client.get(
        f"/api/v1/articles/{article.json()['article']['id']}",
        headers=bearer(login["access_token"]),
    )
    assert rewritten_article.json()["article"]["current_version_no"] == 3
    assert rewritten_article.json()["version"]["source"] == "ai"
    detail_with_recent_messages = await client.get(
        f"/api/v1/tasks/{task_id}", headers=bearer(login["access_token"])
    )
    assert len(detail_with_recent_messages.json()["messages"]) <= 30
    assert "messages_next_cursor" in detail_with_recent_messages.json()
    assert detail_with_recent_messages.json()["latest_ai_run"]["status"] == "completed"
    recent_messages = await client.get(
        f"/api/v1/tasks/{task_id}/messages",
        headers=bearer(login["access_token"]),
        params={"limit": 2},
    )
    assert len(recent_messages.json()["items"]) == 2
    assert recent_messages.json()["next_cursor"]
    assert (
        recent_messages.json()["items"][0]["created_at"]
        <= recent_messages.json()["items"][1]["created_at"]
    )
    older_messages = await client.get(
        f"/api/v1/tasks/{task_id}/messages",
        headers=bearer(login["access_token"]),
        params={"limit": 2, "cursor": recent_messages.json()["next_cursor"]},
    )
    assert older_messages.status_code == 200
    assert {item["id"] for item in older_messages.json()["items"]}.isdisjoint(
        {item["id"] for item in recent_messages.json()["items"]}
    )

    monkeypatch.setenv("DATABASE_URL", app.state.settings.database_url)
    first_delivery = await _process_ai(run_id, "outbox-message-1")
    repeated_delivery = await _process_ai(run_id, "outbox-message-1")
    assert repeated_delivery == first_delivery
    async with app.state.database.session_maker() as session:
        inbox_count = await session.scalar(
            select(func.count(InboxMessage.id)).where(
                InboxMessage.consumer == "process_ai_run",
                InboxMessage.message_id == "outbox-message-1",
            )
        )
    assert inbox_count == 1


async def test_article_versions_conflict_and_render_invalidation(client: AsyncClient) -> None:
    login = await register_and_login(client, "versions@example.com")
    auth = bearer(login["access_token"])
    created = await client.post(
        "/api/v1/articles",
        headers=auth,
        json={"title": "初版", "summary": "摘要", "content": ARTICLE},
    )
    assert created.status_code == 201, created.text
    article_id = created.json()["article"]["id"]

    saved = await client.post(
        f"/api/v1/articles/{article_id}/save-local",
        headers={**auth, "Idempotency-Key": "article-save-local-1"},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["library_item"]["id"]
    assert saved.json()["library_item"]["created_at"]

    revision_payload = {
        "base_version_no": 1,
        "selected_text": "正文",
        "instruction": "改得更简洁",
        "selection_from": 0,
        "selection_to": 2,
    }
    revision_headers = {**auth, "Idempotency-Key": "article-revision-1"}
    proposed = await client.post(
        f"/api/v1/articles/{article_id}/revisions",
        headers=revision_headers,
        json=revision_payload,
    )
    assert proposed.status_code == 202, proposed.text
    revision_id = proposed.json()["id"]
    assert proposed.json()["status"] == "accepted"
    proposal = await client.get(f"/api/v1/article-revisions/{revision_id}", headers=auth)
    assert proposal.status_code == 200, proposal.text
    assert proposal.json()["status"] == "completed"
    assert proposal.json()["replacement_text"]
    assert proposal.json()["simulated"] is True
    unchanged = await client.get(f"/api/v1/articles/{article_id}", headers=auth)
    assert unchanged.json()["article"]["current_version_no"] == 1
    repeated_proposal = await client.post(
        f"/api/v1/articles/{article_id}/revisions",
        headers=revision_headers,
        json=revision_payload,
    )
    assert repeated_proposal.json() == proposed.json()
    conflicting_proposal = await client.post(
        f"/api/v1/articles/{article_id}/revisions",
        headers=revision_headers,
        json={**revision_payload, "instruction": "改得更详细"},
    )
    assert conflicting_proposal.status_code == 409
    assert conflicting_proposal.json()["code"] == "IDEMPOTENCY_KEY_CONFLICT"

    render = await client.post(
        "/api/v1/article-renders", headers=auth, json={"article_id": article_id}
    )
    assert render.status_code == 201, render.text
    render_id = render.json()["id"]
    assert "<script>" not in render.json()["html"]
    assert "&lt;script&gt;" in render.json()["html"]
    assert "<strong>粗体</strong>" in render.json()["html"]
    assert "<em>斜体</em>" in render.json()["html"]
    assert 'href="https://example.com/reference"' in render.json()["html"]
    assert "font-size:17px" in render.json()["html"]
    assert "background-color:#ecfdf5" in render.json()["html"]
    assert "font-size:13px" in render.json()["html"]
    assert "text-align:center" in render.json()["html"]
    confirmation = await client.post(
        f"/api/v1/article-renders/{render_id}/confirm",
        headers=auth,
        json={"action": "draft"},
    )
    assert confirmation.status_code == 200

    update_payload = {
        "base_version_no": 1,
        "title": "第二版",
        "summary": "新摘要",
        "content": {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "新正文"}],
                }
            ],
        },
        "source": "manual",
    }
    idem_headers = {**auth, "Idempotency-Key": "article-save-1"}
    updated = await client.put(
        f"/api/v1/articles/{article_id}/content",
        headers=idem_headers,
        json=update_payload,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["version"]["version_no"] == 2
    version_page = await client.get(
        f"/api/v1/articles/{article_id}/versions",
        headers=auth,
        params={"limit": 1},
    )
    assert len(version_page.json()["items"]) == 1
    assert version_page.json()["next_cursor"]
    older_version_page = await client.get(
        f"/api/v1/articles/{article_id}/versions",
        headers=auth,
        params={"limit": 1, "cursor": version_page.json()["next_cursor"]},
    )
    assert older_version_page.json()["items"][0]["version_no"] == 1

    replay = await client.put(
        f"/api/v1/articles/{article_id}/content",
        headers=idem_headers,
        json=update_payload,
    )
    assert replay.json() == updated.json()
    changed_payload = {**update_payload, "title": "冲突正文"}
    changed = await client.put(
        f"/api/v1/articles/{article_id}/content",
        headers=idem_headers,
        json=changed_payload,
    )
    assert changed.status_code == 409
    assert changed.json()["code"] == "IDEMPOTENCY_KEY_CONFLICT"

    stale_base = await client.put(
        f"/api/v1/articles/{article_id}/content",
        headers={**auth, "Idempotency-Key": "article-save-2"},
        json=update_payload,
    )
    assert stale_base.status_code == 409
    assert stale_base.json()["code"] == "ARTICLE_VERSION_CONFLICT"

    stale_render = await client.get(f"/api/v1/article-renders/{render_id}", headers=auth)
    assert stale_render.json()["stale_at"] is not None
    stale_confirmation = await client.post(
        f"/api/v1/article-renders/{render_id}/confirm",
        headers=auth,
        json={"action": "draft"},
    )
    assert stale_confirmation.status_code == 409


async def test_article_deletion_keeps_task_usable_and_candidate_requires_confirmation(
    client: AsyncClient,
) -> None:
    login = await register_and_login(client, "article-delete-task@example.com")
    auth = bearer(login["access_token"])
    created = await client.post(
        "/api/v1/tasks",
        headers={**auth, "Idempotency-Key": "deletion-task-create-1"},
        json={
            "title": "删除文章后继续对话",
            "first_message": {
                "text": "先生成第一篇文章",
                "content": {},
                "client_message_id": "deletion-message-1",
            },
        },
    )
    assert created.status_code == 202, created.text
    task_id = created.json()["task"]["id"]
    task = await client.get(f"/api/v1/tasks/{task_id}", headers=auth)
    first_article_id = task.json()["current_article_id"]
    edited = await client.put(
        f"/api/v1/articles/{first_article_id}/content",
        headers={**auth, "Idempotency-Key": "deletion-manual-edit-1"},
        json={
            "base_version_no": 1,
            "title": "第一篇文章",
            "summary": "用户确认前的手工修改",
            "content": ARTICLE,
            "source": "manual",
        },
    )
    assert edited.status_code == 200, edited.text
    saved = await client.post(
        f"/api/v1/articles/{first_article_id}/save-local",
        headers={**auth, "Idempotency-Key": "deletion-save-local-1"},
    )
    assert saved.status_code == 200, saved.text
    candidate_rows = (await client.get("/api/v1/preferences", headers=auth)).json()["items"]
    candidate = next(row for row in candidate_rows if row["source_id"] == first_article_id)
    assert candidate["status"] == "candidate"
    assert candidate["source_type"] == "saved_local_article"

    deleted_library_item = await client.delete(
        f"/api/v1/library-items/{saved.json()['library_item']['id']}", headers=auth
    )
    assert deleted_library_item.status_code == 204
    detached = await client.get(f"/api/v1/tasks/{task_id}", headers=auth)
    assert detached.json()["current_article_id"] is None

    continued = await client.post(
        f"/api/v1/tasks/{task_id}/messages",
        headers={**auth, "Idempotency-Key": "deletion-message-run-2"},
        json={
            "text": "删除文章后继续生成",
            "content": {},
            "client_message_id": "deletion-message-2",
        },
    )
    assert continued.status_code == 202, continued.text
    assert continued.json()["ai_run"]["context_snapshot"]["preferences"] == []
    continued_task = await client.get(f"/api/v1/tasks/{task_id}", headers=auth)
    second_article_id = continued_task.json()["current_article_id"]
    assert second_article_id and second_article_id != first_article_id

    confirmed_candidate = await client.patch(
        f"/api/v1/preferences/{candidate['id']}",
        headers=auth,
        json={"status": "confirmed"},
    )
    assert confirmed_candidate.status_code == 200
    direct_delete = await client.delete(f"/api/v1/articles/{second_article_id}", headers=auth)
    assert direct_delete.status_code == 204
    assert (await client.get(f"/api/v1/tasks/{task_id}", headers=auth)).json()[
        "current_article_id"
    ] is None

    continued_with_preference = await client.post(
        f"/api/v1/tasks/{task_id}/messages",
        headers={**auth, "Idempotency-Key": "deletion-message-run-3"},
        json={
            "text": "确认偏好后再生成",
            "content": {},
            "client_message_id": "deletion-message-3",
        },
    )
    assert continued_with_preference.status_code == 202, continued_with_preference.text
    assert [
        row["id"]
        for row in continued_with_preference.json()["ai_run"]["context_snapshot"]["preferences"]
    ] == [candidate["id"]]


async def test_upload_completion_creates_processing_library_item(client: AsyncClient) -> None:
    owner = await register_and_login(client, "files@example.com")
    stranger = await register_and_login(client, "stranger@example.com")
    owner_auth = bearer(owner["access_token"])
    file_content = "# 参考资料\n这是真正上传到本地 Mock 存储的正文。".encode()
    digest = hashlib.sha256(file_content).hexdigest()
    upload = await client.post(
        "/api/v1/uploads",
        headers={**owner_auth, "Idempotency-Key": "upload-create-1"},
        json={
            "filename": "..\\..\\reference.md",
            "mime_type": "text/markdown",
            "size_bytes": len(file_content),
            "sha256": digest,
        },
    )
    assert upload.status_code == 201, upload.text
    assert upload.json()["asset"]["filename"] == "reference.md"
    assert upload.json()["provider_mode"] == "mock"
    assert upload.json()["part_size_bytes"] == 8 * 1024 * 1024
    replayed_upload = await client.post(
        "/api/v1/uploads",
        headers={**owner_auth, "Idempotency-Key": "upload-create-1"},
        json={
            "filename": "..\\..\\reference.md",
            "mime_type": "text/markdown",
            "size_bytes": len(file_content),
            "sha256": digest,
        },
    )
    assert replayed_upload.status_code == 201
    assert replayed_upload.json() == upload.json()
    upload_id = upload.json()["upload"]["id"]
    uploaded_part = await client.put(
        upload.json()["part_urls"][0],
        headers={"Origin": "capacitor://localhost"},
        content=file_content,
    )
    assert uploaded_part.status_code == 204
    assert uploaded_part.headers["access-control-allow-origin"] == "capacitor://localhost"
    assert "ETag" in uploaded_part.headers["access-control-expose-headers"]
    uploaded_etag = uploaded_part.headers["etag"]

    hidden = await client.post(
        f"/api/v1/uploads/{upload_id}/complete",
        headers={
            **bearer(stranger["access_token"]),
            "Idempotency-Key": "stranger-complete-1",
        },
        json={
            "size_bytes": len(file_content),
            "sha256": digest,
            "completed_parts": [{"part_number": 1, "etag": uploaded_etag}],
            "save_to_library": True,
        },
    )
    assert hidden.status_code == 404

    bad_etag = await client.post(
        f"/api/v1/uploads/{upload_id}/complete",
        headers={**owner_auth, "Idempotency-Key": "upload-complete-bad-etag-1"},
        json={
            "size_bytes": len(file_content),
            "sha256": digest,
            "completed_parts": [{"part_number": 1, "etag": "wrong-etag"}],
            "save_to_library": True,
        },
    )
    assert bad_etag.status_code == 422
    assert bad_etag.json()["code"] == "UPLOAD_PARTS_INVALID"

    completed = await client.post(
        f"/api/v1/uploads/{upload_id}/complete",
        headers={**owner_auth, "Idempotency-Key": "upload-complete-1"},
        json={
            "size_bytes": len(file_content),
            "sha256": digest,
            "completed_parts": [{"part_number": 1, "etag": uploaded_etag}],
            "save_to_library": True,
        },
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["document"]["status"] == "completed"
    assert completed.json()["document"]["parser_version"] == "mock-text-bytes-v1"
    assert "真正上传到本地 Mock 存储" in completed.json()["document"]["extracted_text"]
    assert completed.json()["asset"]["scan_status"] == "mocked_clean"
    assert completed.json()["library_item"]["display_status"] == "ready"

    parsed_detail = await client.get(
        f"/api/v1/documents/{completed.json()['document']['id']}", headers=owner_auth
    )
    assert parsed_detail.status_code == 200, parsed_detail.text
    assert parsed_detail.json()["sections"][0]["page_no"] == 1
    assert (
        parsed_detail.json()["chunks"][0]["section_id"] == parsed_detail.json()["sections"][0]["id"]
    )
    assert parsed_detail.json()["chunks"][0]["page_no"] == 1

    replay = await client.post(
        f"/api/v1/uploads/{upload_id}/complete",
        headers={**owner_auth, "Idempotency-Key": "upload-complete-1"},
        json={
            "size_bytes": len(file_content),
            "sha256": digest,
            "completed_parts": [{"part_number": 1, "etag": uploaded_etag}],
            "save_to_library": True,
        },
    )
    assert replay.json() == completed.json()
    library = await client.get("/api/v1/library-items", headers=owner_auth)
    assert len(library.json()["items"]) == 1
    assert library.json()["items"][0]["display_status"] == "ready"
    item_id = library.json()["items"][0]["id"]
    renamed = await client.patch(
        f"/api/v1/library-items/{item_id}",
        headers=owner_auth,
        json={"title": "重命名后的参考资料"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "重命名后的参考资料"
    detail = await client.get(f"/api/v1/library-items/{item_id}", headers=owner_auth)
    assert detail.json()["source"]["document"]["title"] == "重命名后的参考资料"
    assert detail.json()["source"]["document"]["asset_id"] == completed.json()["asset"]["id"]

    document_id = completed.json()["document"]["id"]
    hidden_reference = await client.post(
        "/api/v1/tasks",
        headers={
            **bearer(stranger["access_token"]),
            "Idempotency-Key": "foreign-document-task-1",
        },
        json={
            "title": "越权引用",
            "first_message": {
                "text": "读取别人的文件",
                "content": {"document_ids": [document_id]},
                "client_message_id": "foreign-document-message-1",
            },
        },
    )
    assert hidden_reference.status_code == 404
    assert hidden_reference.json()["code"] == "DOCUMENT_NOT_FOUND"

    task = await client.post(
        "/api/v1/tasks",
        headers={**owner_auth, "Idempotency-Key": "document-context-task-1"},
        json={
            "title": "引用文件",
            "first_message": {
                "text": "结合参考资料写作",
                "content": {
                    "document_ids": [document_id],
                    "links": ["https://example.com/reference"],
                },
                "client_message_id": "document-context-message-1",
            },
        },
    )
    assert task.status_code == 202, task.text
    snapshot = task.json()["ai_run"]["context_snapshot"]
    assert snapshot["untrusted_documents"][0]["document_id"] == document_id
    assert snapshot["untrusted_documents"][0]["excerpts"][0]["chunk_id"]
    assert "真正上传到本地 Mock 存储" in snapshot["untrusted_documents"][0]["excerpts"][0]["text"]
    assert snapshot["untrusted_links"] == ["https://example.com/reference"]

    article = await client.post(
        "/api/v1/articles",
        headers=owner_auth,
        json={"title": "封面门禁", "content": ARTICLE},
    )
    wrong_type = await client.post(
        "/api/v1/article-renders",
        headers=owner_auth,
        json={
            "article_id": article.json()["article"]["id"],
            "cover_asset_id": completed.json()["asset"]["id"],
        },
    )
    assert wrong_type.status_code == 422
    assert wrong_type.json()["code"] == "COVER_ASSET_TYPE_INVALID"

    image_content = b"\x89PNG\r\n\x1a\nmock-cover"
    image_digest = hashlib.sha256(image_content).hexdigest()
    image_upload = await client.post(
        "/api/v1/uploads",
        headers={**owner_auth, "Idempotency-Key": "image-upload-create-1"},
        json={
            "filename": "cover.png",
            "mime_type": "image/png",
            "size_bytes": len(image_content),
            "sha256": image_digest,
        },
    )
    image_asset_id = image_upload.json()["asset"]["id"]
    image_part = await client.put(image_upload.json()["part_urls"][0], content=image_content)
    assert image_part.status_code == 204
    image_etag = image_part.headers["etag"]
    pending_cover = await client.post(
        "/api/v1/article-renders",
        headers=owner_auth,
        json={
            "article_id": article.json()["article"]["id"],
            "cover_asset_id": image_asset_id,
        },
    )
    assert pending_cover.status_code == 409
    assert pending_cover.json()["code"] == "COVER_ASSET_NOT_READY"
    completed_image = await client.post(
        f"/api/v1/uploads/{image_upload.json()['upload']['id']}/complete",
        headers={**owner_auth, "Idempotency-Key": "image-upload-complete-1"},
        json={
            "size_bytes": len(image_content),
            "sha256": image_digest,
            "completed_parts": [{"part_number": 1, "etag": image_etag}],
            "save_to_library": False,
        },
    )
    assert completed_image.json()["asset"]["scan_status"] == "mocked_clean"
    ready_cover = await client.post(
        "/api/v1/article-renders",
        headers=owner_auth,
        json={
            "article_id": article.json()["article"]["id"],
            "cover_asset_id": image_asset_id,
        },
    )
    assert ready_cover.status_code == 201, ready_cover.text


async def test_layout_extraction_creates_version_only_from_real_provider_result(
    app: FastAPI,
    client: AsyncClient,
) -> None:
    app.state.layout_extraction_provider = RealLayoutExtractionProvider()
    login = await register_and_login(client, "layout-extract@example.com")
    auth = bearer(login["access_token"])
    extracted = await client.post(
        "/api/v1/layout-templates/extract",
        headers=auth,
        json={
            "source_url": "https://mp.weixin.qq.com/s/pytest-layout",
            "name": "真实提取模板",
        },
    )
    assert extracted.status_code == 202, extracted.text
    assert extracted.json()["provider_status"] == "completed"
    assert extracted.json()["template"]["extraction_status"] == "completed"
    assert extracted.json()["version"]["style_tokens"]["title"]["color"] == "#111827"
    detail = await client.get(
        f"/api/v1/layout-templates/{extracted.json()['template']['id']}",
        headers=auth,
    )
    assert detail.status_code == 200
    assert len(detail.json()["versions"]) == 1
    version = detail.json()["versions"][0]
    assert version["extractor_version"] == "wechat-public-dom-test"
    assert version["source_snapshot"]["title"] == "真实公众号文章"
    assert version["source_snapshot"]["model_assist"] == {
        "purpose": "layout_extraction",
        "route_version_id": None,
        "agent_version": "layout-agent-v1",
        "status": "deterministic_fallback",
        "reason": "model_route_is_mock",
    }


async def test_layout_extraction_uses_learning_agent_and_sanitizes_evidence(
    app: FastAPI,
    client: AsyncClient,
) -> None:
    login = await register_and_login(client, "layout-learning-agent@example.com")
    async with app.state.database.session_maker() as session:
        template = LayoutTemplate(
            owner_id=login["registered_user"]["id"],
            name="智能学习模板",
            source_url="https://mp.weixin.qq.com/s/layout-learning-agent",
            extraction_status="queued",
        )
        session.add(template)
        await session.flush()
        await process_layout_extraction(
            session,
            template_id=template.id,
            provider=RealLayoutExtractionProvider(),
            route_snapshot={"route_version_id": "layout-route-v1"},
            model=LearningLayoutModel(),
            secrets=app.state.secret_provider,
            settings=app.state.settings,
        )
        await session.commit()
        detail = await client.get(
            f"/api/v1/layout-templates/{template.id}",
            headers=bearer(login["access_token"]),
        )

    assert detail.status_code == 200, detail.text
    version = detail.json()["versions"][0]
    assert version["extractor_version"] == "layout-agent-v1"
    assert version["style_tokens"]["body"]["font_size"] == 17
    assert version["style_tokens"]["body"]["line_height"] == 1.9
    assert version["style_tokens"]["body"]["color"] == "#123456"
    assist = version["source_snapshot"]["model_assist"]
    assert assist["status"] == "completed"
    assert assist["route_version_id"] == "layout-route-v1"
    assert assist["provider_request_id"] == "layout-agent-request"
    assert assist["confidence"] == 0.91
    assert assist["module_evidence"] == {
        "body": ["block-1"],
        "heading1": ["block-2"],
    }


async def test_layout_extraction_reports_provider_failure_immediately(
    app: FastAPI,
    client: AsyncClient,
) -> None:
    app.state.layout_extraction_provider = FailingLayoutExtractionProvider()
    login = await register_and_login(client, "layout-failed@example.com")
    extracted = await client.post(
        "/api/v1/layout-templates/extract",
        headers=bearer(login["access_token"]),
        json={
            "source_url": "https://mp.weixin.qq.com/s/not-found",
            "name": "失败提取模板",
        },
    )

    assert extracted.status_code == 422, extracted.text
    assert extracted.json()["code"] == "LAYOUT_PROVIDER_FAILED"
    assert "没有读取到微信公众号正文" in extracted.json()["message"]
    async with app.state.database.session_maker() as session:
        templates = await session.scalar(
            select(func.count())
            .select_from(LayoutTemplate)
            .where(LayoutTemplate.name == "失败提取模板")
        )
        session.add(
            LayoutTemplate(
                owner_id=login["registered_user"]["id"],
                name="历史失败空模板",
                source_url="https://mp.weixin.qq.com/s/not-found",
                extraction_status="failed",
                current_version_no=0,
            )
        )
        await session.commit()
    assert templates == 0
    listed = await client.get("/api/v1/layout-templates", headers=bearer(login["access_token"]))
    assert listed.status_code == 200, listed.text
    assert all(item["name"] != "历史失败空模板" for item in listed.json()["items"])


async def test_layout_extraction_freezes_and_audits_model_gateway_route(
    app: FastAPI,
    client: AsyncClient,
) -> None:
    app.state.layout_extraction_provider = RealLayoutExtractionProvider()
    login = await register_and_login(client, "layout-route@example.com")
    auth = bearer(login["access_token"])
    async with app.state.database.session_maker() as session:
        provider = ModelProviderRecord(
            code="layout-route-provider",
            name="版式模型供应商",
            adapter="openai_responses",
            base_url="https://layout-model.example/v1",
            secret_ref="env:LAYOUT_MODEL_TEST_KEY",
            status="active",
        )
        session.add(provider)
        await session.flush()
        deployment = ModelDeployment(
            provider_id=provider.id,
            model_id="layout-model",
            alias="版式识别模型",
            model_type="chat",
            capabilities=["structured_output"],
            context_window=16_000,
            max_output_tokens=1_000,
            input_cost=0,
            output_cost=0,
            status="available",
        )
        session.add(deployment)
        await session.flush()
        route = ModelRouteVersion(
            purpose="layout_extraction",
            version_no=1,
            primary_deployment_id=deployment.id,
            fallback_deployment_ids=[],
            policy={"max_attempts": 1},
            status="published",
        )
        session.add(route)
        await session.commit()
        route_id = route.id

    extracted = await client.post(
        "/api/v1/layout-templates/extract",
        headers=auth,
        json={
            "source_url": "https://mp.weixin.qq.com/s/pytest-layout-route",
            "name": "模型辅助提取模板",
        },
    )
    assert extracted.status_code == 202, extracted.text
    detail = await client.get(
        f"/api/v1/layout-templates/{extracted.json()['template']['id']}",
        headers=auth,
    )
    version = detail.json()["versions"][0]
    assert version["style_tokens"]["body"]["color"] == "#1f2937"
    assert version["source_snapshot"]["model_assist"]["route_version_id"] == route_id
    assert version["source_snapshot"]["model_assist"]["status"] == "deterministic_fallback"
    assert version["source_snapshot"]["model_assist"]["reason"] == "ModelRouteExhausted"
    async with app.state.database.session_maker() as session:
        model_audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.action == "model_gateway.layout_extraction",
                AuditLog.target_id == extracted.json()["template"]["id"],
            )
        )
        assert model_audit is not None
        assert model_audit.details["status"] == "deterministic_fallback"
        assert model_audit.details["reason"] == "ModelRouteExhausted"


async def test_selected_model_is_legacy_fallback_for_unpublished_auxiliary_routes(
    app: FastAPI,
) -> None:
    async with app.state.database.session_maker() as session:
        provider = ModelProviderRecord(
            code="selected-pipeline-provider",
            name="用户选择模型供应商",
            adapter="openai_responses",
            base_url="https://selected-model.example/v1",
            secret_ref="env:SELECTED_MODEL_KEY",
            status="active",
        )
        session.add(provider)
        await session.flush()
        deployment = ModelDeployment(
            provider_id=provider.id,
            model_id="selected-chat",
            alias="用户选择模型",
            model_type="chat",
            capabilities=["structured_output"],
            context_window=16_000,
            max_output_tokens=1_000,
            input_cost=0,
            output_cost=0,
            status="available",
        )
        session.add(deployment)
        await session.flush()

        routes, _prompts = await freeze_ai_pipeline(
            session,
            route_purpose="article_generation",
            has_images=False,
            settings=app.state.settings,
            model_deployment_id=deployment.id,
        )

        assert set(routes) == {
            "article_planning",
            "article_revision",
            "memory_summary",
        }
        assert all(route.get("selected_by_user") is True for route in routes.values())
        assert all(route.get("primary_deployment_id") == deployment.id for route in routes.values())


async def test_created_run_keeps_legacy_intent_route_for_rolling_workers(
    app: FastAPI,
    client: AsyncClient,
) -> None:
    login = await register_and_login(client, "rolling-worker@example.com")
    response = await client.post(
        "/api/v1/tasks",
        headers={
            **bearer(login["access_token"]),
            "Idempotency-Key": "rolling-worker-run",
        },
        json={
            "first_message": {
                "text": "写一篇关于团队协作的完整公众号文章",
                "content": {},
                "client_message_id": "rolling-worker-message",
            }
        },
    )
    assert response.status_code == 202, response.text
    async with app.state.database.session_maker() as session:
        run = await session.get(AIRun, response.json()["ai_run"]["id"])
        assert run is not None
        routes = run.model_route_snapshot["pipeline_routes"]
        assert routes["intent_detection"]["purpose"] == "article_generation"
        assert set(routes) >= {
            "intent_detection",
            "article_planning",
            "article_revision",
            "memory_summary",
        }


async def test_final_confirmation_and_mock_wechat_never_claims_success(
    app: FastAPI, client: AsyncClient
) -> None:
    login = await register_and_login(client, "wechat@example.com")
    auth = bearer(login["access_token"])
    user_id = login["registered_user"]["id"]
    async with app.state.database.session_maker() as session:
        account = OfficialAccount(
            owner_id=user_id,
            authorizer_appid="wx-pytest",
            name="Pytest 公众号",
            status="connected",
            capability_flags=["draft", "publish"],
            token_secret_ref="env:UNUSED_IN_MOCK",
        )
        session.add(account)
        await session.commit()
        account_id = account.id

    article = await client.post(
        "/api/v1/articles",
        headers=auth,
        json={"title": "公众号文章", "content": ARTICLE},
    )
    article_id = article.json()["article"]["id"]
    render = await client.post(
        "/api/v1/article-renders",
        headers=auth,
        json={"article_id": article_id, "official_account_id": account_id},
    )
    render_id = render.json()["id"]

    not_confirmed = await client.post(
        "/api/v1/wechat-publishes",
        headers={**auth, "Idempotency-Key": "publish-without-confirmation"},
        json={"render_id": render_id},
    )
    assert not_confirmed.status_code == 409
    assert not_confirmed.json()["code"] == "FINAL_PREVIEW_CONFIRMATION_REQUIRED"

    confirmed = await client.post(
        f"/api/v1/article-renders/{render_id}/confirm",
        headers=auth,
        json={"action": "publish"},
    )
    assert confirmed.status_code == 200
    async with app.state.database.session_maker() as session:
        account = await session.get(OfficialAccount, account_id)
        assert account is not None
        account.capability_flags = ["draft"]
        await session.commit()
    forbidden = await client.post(
        "/api/v1/wechat-publishes",
        headers={**auth, "Idempotency-Key": "publish-capability-missing"},
        json={"render_id": render_id},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "WECHAT_CAPABILITY_UNAVAILABLE"
    async with app.state.database.session_maker() as session:
        account = await session.get(OfficialAccount, account_id)
        assert account is not None
        account.capability_flags = ["draft", "publish"]
        await session.commit()
    queued = await client.post(
        "/api/v1/wechat-publishes",
        headers={**auth, "Idempotency-Key": "publish-confirmed-1"},
        json={"render_id": render_id},
    )
    assert queued.status_code == 202, queued.text

    operation = await client.get(f"/api/v1/wechat-operations/{queued.json()['id']}", headers=auth)
    assert operation.status_code == 200
    assert operation.json()["status"] == "mocked"
    assert operation.json()["media_id"] is None
    assert operation.json()["publish_id"] is None
    assert operation.json()["result"]["external_action_performed"] is False

    library = await client.get("/api/v1/library-items", headers=auth)
    assert len(library.json()["items"]) == 1
    assert library.json()["items"][0]["item_type"] == "article"
    assert library.json()["items"][0]["display_status"] == "publish_mocked"
    mocked_article = await client.get(f"/api/v1/articles/{article_id}", headers=auth)
    assert mocked_article.json()["article"]["status"] == "publish_mocked"

    fail_once = FailPublishOnceProvider()
    app.state.wechat_provider = fail_once
    failed_submission = await client.post(
        "/api/v1/wechat-publishes",
        headers={**auth, "Idempotency-Key": "publish-reuse-draft-1"},
        json={"render_id": render_id},
    )
    failed_operation_id = failed_submission.json()["id"]
    failed_operation = await client.get(
        f"/api/v1/wechat-operations/{failed_operation_id}", headers=auth
    )
    assert failed_operation.json()["status"] == "failed"
    assert failed_operation.json()["error_code"] == "DRAFT_CREATED_PUBLISH_FAILED"
    assert failed_operation.json()["media_id"] == "media-existing"
    failed_library = await client.get("/api/v1/library-items", headers=auth)
    assert failed_library.json()["items"][0]["display_status"] == "publish_failed"

    async with app.state.database.session_maker() as session:
        operation = await session.get(WechatOperation, failed_operation_id)
        assert operation is not None
        operation.status = "queued"
        retried = await process_wechat_operation(
            session, operation_id=failed_operation_id, provider=fail_once
        )
        await session.commit()
    assert retried.status == "succeeded"
    assert retried.publish_id == "publish-retried"
    assert fail_once.draft_calls == 1
    assert fail_once.publish_calls == 2
    published_library = await client.get("/api/v1/library-items", headers=auth)
    assert published_library.json()["items"][0]["display_status"] == "published"

    unknown_provider = UnknownDraftProvider()
    app.state.wechat_provider = unknown_provider
    unknown_submission = await client.post(
        "/api/v1/wechat-publishes",
        headers={**auth, "Idempotency-Key": "publish-unknown-draft-1"},
        json={"render_id": render_id},
    )
    unknown_operation_id = unknown_submission.json()["id"]
    unknown_operation = await client.get(
        f"/api/v1/wechat-operations/{unknown_operation_id}", headers=auth
    )
    assert unknown_operation.json()["status"] == "unknown"
    assert unknown_operation.json()["result"]["unknown_stage"] == "draft"
    assert unknown_operation.json()["media_id"] == "media-to-reconcile"

    restored = await client.get(
        f"/api/v1/articles/{article_id}/wechat-operation",
        headers=auth,
        params={"operation_type": "publish"},
    )
    assert restored.status_code == 200
    assert restored.json()["operation"]["id"] == unknown_operation_id
    assert restored.json()["operation"]["status"] == "unknown"
    duplicate_from_another_device = await client.post(
        "/api/v1/wechat-publishes",
        headers={**auth, "Idempotency-Key": "publish-unknown-cross-device-2"},
        json={"render_id": render_id},
    )
    assert duplicate_from_another_device.status_code == 409
    assert duplicate_from_another_device.json()["code"] == "WECHAT_OPERATION_ALREADY_PENDING"
    assert duplicate_from_another_device.json()["details"] == {
        "operation_id": unknown_operation_id,
        "status": "unknown",
        "operation_type": "publish",
    }

    async with app.state.database.session_maker() as session:
        unchanged = await process_wechat_operation(
            session,
            operation_id=unknown_operation_id,
            provider=unknown_provider,
        )
        await session.commit()
    assert unchanged.status == "unknown"
    assert unknown_provider.draft_calls == 1

    async with app.state.database.session_maker() as session:
        reconciled = await reconcile_wechat_operation(
            session,
            operation_id=unknown_operation_id,
            provider=unknown_provider,
        )
        await session.commit()
    assert unknown_provider.reconcile_calls == [("draft", "media-to-reconcile")]
    assert reconciled.status == "failed"
    assert reconciled.error_code == "DRAFT_RECONCILED_PUBLISH_PENDING"

    async with app.state.database.session_maker() as session:
        retryable = await session.get(WechatOperation, unknown_operation_id)
        assert retryable is not None
        retryable.status = "queued"
        await session.commit()
        completed = await process_wechat_operation(
            session,
            operation_id=unknown_operation_id,
            provider=unknown_provider,
        )
        await session.commit()
    assert completed.status == "succeeded"
    assert completed.publish_id == "publish-after-reconcile"
    assert unknown_provider.draft_calls == 1
    assert unknown_provider.publish_calls == 1


async def test_signed_authorization_callback_binds_account_to_state_owner(
    app: FastAPI,
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    login = await register_and_login(client, "authorize@example.com")
    auth = bearer(login["access_token"])
    provider = AuthorizationProvider()
    app.state.wechat_provider = provider

    rejected_redirect = await client.post(
        "/api/v1/official-accounts/authorize-url",
        headers=auth,
        json={"redirect_uri": "http://localhost:9000.evil.example/callback"},
    )
    assert rejected_redirect.status_code == 422

    authorization = await client.post(
        "/api/v1/official-accounts/authorize-url",
        headers=auth,
        json={"redirect_uri": "http://localhost:9000/wechat/callback"},
    )
    assert authorization.status_code == 200, authorization.text
    assert provider.state

    callback_secret = "pytest-callback-secret"
    monkeypatch.setenv("WECHAT_CALLBACK_HMAC_SECRET", callback_secret)
    payload = {
        "event_key": "authorization-event-1",
        "state": provider.state,
        "encrypted_payload": "opaque-wechat-callback",
        "authorizer_appid": "wx-authorized",
        "name": "授权测试公众号",
        "capability_flags": ["draft", "publish"],
        "token_secret_ref": "secret:wechat/authorized",
    }
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    signature = hmac.new(callback_secret.encode(), body, hashlib.sha256).hexdigest()
    callback = await client.post(
        "/callbacks/v1/wechat/authorizations",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Callback-Signature": signature,
        },
    )
    assert callback.status_code == 200, callback.text
    assert callback.json()["duplicate"] is False

    accounts = await client.get("/api/v1/official-accounts", headers=auth)
    assert len(accounts.json()["items"]) == 1
    assert accounts.json()["items"][0]["name"] == "授权测试公众号"

    replay = await client.post(
        "/callbacks/v1/wechat/authorizations",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Callback-Signature": signature,
        },
    )
    assert replay.status_code == 200
    assert replay.json()["duplicate"] is True


async def test_ai_progress_is_committed_and_cancel_stops_followup_steps(
    app: FastAPI, client: AsyncClient
) -> None:
    login = await register_and_login(client, "ai-live-progress@example.com")
    model = BlockingArticleModel()
    app.state.model_provider = model
    create_request = asyncio.create_task(
        client.post(
            "/api/v1/tasks",
            headers={
                **bearer(login["access_token"]),
                "Idempotency-Key": "live-progress-cancel-1",
            },
            json={
                "title": "可取消任务",
                "first_message": {
                    "text": "写一篇可取消的文章",
                    "content": {},
                    "client_message_id": "live-progress-message-1",
                },
            },
        )
    )
    try:
        await asyncio.wait_for(model.started.wait(), timeout=5)
        async with app.state.database.session_maker() as session:
            run = await session.scalar(select(AIRun).where(AIRun.owner_id == login["user"]["id"]))
            assert run is not None
            stages = [
                event.payload["stage"]
                for event in (
                    await session.scalars(
                        select(AIRunEvent)
                        .where(
                            AIRunEvent.run_id == run.id,
                            AIRunEvent.event_type == "stage.changed",
                        )
                        .order_by(AIRunEvent.seq)
                    )
                ).all()
            ]
            assert stages[-1] == "generating"
            run_id = run.id

        cancelled = await client.post(
            f"/api/v1/ai-runs/{run_id}/cancel",
            headers=bearer(login["access_token"]),
        )
        assert cancelled.status_code == 200, cancelled.text
    finally:
        model.release.set()

    created = await asyncio.wait_for(create_request, timeout=5)
    assert created.status_code == 202, created.text
    run_response = await client.get(
        f"/api/v1/ai-runs/{run_id}", headers=bearer(login["access_token"])
    )
    assert run_response.json()["status"] == "cancelled"
    events = await client.get(
        f"/api/v1/ai-runs/{run_id}/events", headers=bearer(login["access_token"])
    )
    assert "event: run.cancelled" in events.text
    assert "event: run.completed" not in events.text
    quota = await client.get("/api/v1/quota", headers=bearer(login["access_token"]))
    assert quota.json()["balance"] == 500

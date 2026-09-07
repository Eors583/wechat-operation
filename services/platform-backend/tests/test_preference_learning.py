from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select

from app.domains.ai import classify_run_type
from app.domains.preference_learning import extract_feedback, learn_preferences, parse_memory
from app.models import AIRunEvent, ArticleVersion, Message, Project, Task, UserPreference
from app.providers import ModelResult, ProviderUnavailable
from tests.conftest import bearer, register_and_login
from tests.fakes import UnavailableModelProvider


@pytest.fixture(autouse=True)
def configured_test_model(monkeypatch: pytest.MonkeyPatch) -> None:
    # The app's unconfigured provider intentionally fails; tests explicitly supply one.
    async def generate(self, *, purpose, prompt, context):
        text = "PASS"
        structured = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "组织成长需要明确职责并建立反馈机制。" * 100}
                    ],
                }
            ],
        }
        if purpose == "article_generation":
            text = json.dumps(structured, ensure_ascii=False)
        if purpose == "memory_summary":
            assert "preferences" in prompt
            evidence = "以后用像朋友聊天的语气"
            candidates = (
                [{"type": "tone", "value": "语言温暖亲切，像朋友聊天", "evidence": evidence}]
                if evidence in context["user_input"]
                else []
            )
            text = json.dumps(
                {"summary": "已生成文章，待用户确认", "preferences": candidates}, ensure_ascii=False
            )
        return ModelResult(
            text=text,
            structured=structured,
            input_tokens=1,
            output_tokens=1,
            provider_request_id="preference-test",
        )

    monkeypatch.setattr(UnavailableModelProvider, "generate", generate)


FINAL_ARTICLE = {
    "type": "doc",
    "content": [
        {
            "type": "heading",
            "attrs": {"level": 1},
            "content": [{"type": "text", "text": "组织成长的关键判断"}],
        },
        {
            "type": "paragraph",
            "attrs": {"module": "body"},
            "content": [{"type": "text", "text": "组织成长必须先明确责任，再优化流程。"}],
        },
    ],
}


async def _article_task(client: AsyncClient, token: str, *, key: str) -> tuple[str, str]:
    response = await client.post(
        "/api/v1/tasks",
        headers={**bearer(token), "Idempotency-Key": key},
        json={
            "first_message": {
                "text": "写一篇关于组织成长的公众号文章",
                "content": {},
                "client_message_id": f"message-{key}",
            }
        },
    )
    assert response.status_code == 202, response.text
    task_id = response.json()["task"]["id"]
    task = await client.get(f"/api/v1/tasks/{task_id}", headers=bearer(token))
    return task_id, task.json()["current_article_id"]


async def test_unchanged_ai_draft_does_not_become_user_preference(client: AsyncClient) -> None:
    login = await register_and_login(client, "preference-unchanged@example.com")
    token = login["access_token"]
    _, article_id = await _article_task(client, token, key="preference-unchanged-task")
    saved = await client.post(
        f"/api/v1/articles/{article_id}/save-local",
        headers={**bearer(token), "Idempotency-Key": "preference-unchanged-save"},
    )
    assert saved.status_code == 200, saved.text
    preferences = await client.get("/api/v1/preferences", headers=bearer(token))
    assert preferences.json()["items"] == []


async def test_explicit_long_term_revision_is_confirmed_when_final_article_is_saved(
    client: AsyncClient,
) -> None:
    login = await register_and_login(client, "preference-explicit@example.com")
    token = login["access_token"]
    task_id, article_id = await _article_task(client, token, key="preference-explicit-task")
    revised = await client.post(
        f"/api/v1/tasks/{task_id}/messages",
        headers={**bearer(token), "Idempotency-Key": "preference-explicit-revision"},
        json={
            "text": "以后文章开头不要铺垫，直接进入主题",
            "content": {},
            "client_message_id": "preference-explicit-message",
        },
    )
    assert revised.status_code == 202, revised.text
    assert revised.json()["ai_run"]["run_type"] == "discussion"
    article = await client.get(f"/api/v1/articles/{article_id}", headers=bearer(token))
    edited = await client.put(
        f"/api/v1/articles/{article_id}/content",
        headers={**bearer(token), "Idempotency-Key": "preference-explicit-final-edit"},
        json={
            "base_version_no": article.json()["article"]["current_version_no"],
            "title": "组织成长的关键判断",
            "summary": "直接进入主题的最终稿",
            "content": FINAL_ARTICLE,
            "source": "manual",
        },
    )
    assert edited.status_code == 200, edited.text
    saved = await client.post(
        f"/api/v1/articles/{article_id}/save-local",
        headers={**bearer(token), "Idempotency-Key": "preference-explicit-save"},
    )
    assert saved.status_code == 200, saved.text
    preferences = (await client.get("/api/v1/preferences", headers=bearer(token))).json()["items"]
    learned = next(item for item in preferences if item["preference_type"] == "direct_opening")
    assert learned["status"] == "confirmed"
    assert learned["scope"] == "personal"
    assert learned["value"] == "文章开头直接进入主题，不要长篇铺垫"


@pytest.mark.parametrize(
    "text",
    [
        "这篇文章开头直接一点",
        "本次语言简洁",
        "引用：“以后文章开头直接进入主题”",
        "```以后文章开头直接进入主题```",
        "> 以后文章开头直接进入主题",
        "示例：以后文章开头直接进入主题",
        "不要记录我的偏好，以后文章开头直接进入主题",
        "以后语言不要简洁，要详细一些",
        "如果以后文章开头直接进入主题会怎么样",
    ],
)
def test_local_or_reference_text_is_not_a_preference(text: str) -> None:
    assert extract_feedback(text) == []


def test_model_candidates_require_exact_user_evidence() -> None:
    item = {
        "type": "tone",
        "value": "语言温暖亲切，像朋友聊天",
        "evidence": "我喜欢像朋友聊天的语气",
    }
    assert extract_feedback("我喜欢像朋友聊天的语气", [item]) == [item]
    assert extract_feedback("请帮我写文章", [item]) == []
    assert extract_feedback("这篇像朋友聊天", [{**item, "evidence": "这篇像朋友聊天"}]) == []
    assert parse_memory('{"summary":"任务继续","preferences":[]}') == ("任务继续", [])
    assert parse_memory("旧模型纯文本摘要") == ("旧模型纯文本摘要", [])


async def test_feedback_is_saved_before_article_save_and_used_by_next_task(
    client: AsyncClient,
) -> None:
    login = await register_and_login(client, "daily-preference@example.com")
    auth = bearer(login["access_token"])
    response = await client.post(
        "/api/v1/tasks",
        headers={**auth, "Idempotency-Key": "daily-first"},
        json={
            "first_message": {
                "text": "写一篇组织成长的文章。以后文章开头直接进入主题",
                "content": {},
                "client_message_id": "daily-first",
            }
        },
    )
    assert response.status_code == 202, response.text
    preferences = (await client.get("/api/v1/preferences", headers=auth)).json()["items"]
    learned = next(p for p in preferences if p["preference_type"] == "direct_opening")
    assert learned["status"] == "confirmed"
    assert learned["source_type"] == "dialogue_feedback"
    again = await client.post(
        "/api/v1/tasks",
        headers={**auth, "Idempotency-Key": "daily-next"},
        json={
            "first_message": {
                "text": "写一篇团队管理文章",
                "content": {},
                "client_message_id": "daily-next",
            }
        },
    )
    assert again.status_code == 202, again.text
    assert learned["id"] in [
        p["id"] for p in again.json()["ai_run"]["context_snapshot"]["preferences"]
    ]


async def test_summary_model_candidates_are_learned_in_real_workflow(client: AsyncClient) -> None:
    login = await register_and_login(client, "summary-feedback@example.com")
    auth = bearer(login["access_token"])
    response = await client.post(
        "/api/v1/tasks",
        headers={**auth, "Idempotency-Key": "semantic-run"},
        json={
            "first_message": {
                "text": "写一篇团队管理文章。以后用像朋友聊天的语气",
                "content": {},
                "client_message_id": "semantic-run",
            }
        },
    )
    assert response.status_code == 202, response.text
    preferences = (await client.get("/api/v1/preferences", headers=auth)).json()["items"]
    learned = next(p for p in preferences if p["preference_type"] == "tone")
    assert learned["status"] == "confirmed"
    assert learned["value"] == "语言温暖亲切，像朋友聊天"


async def test_evidence_dedup_scope_revocation_and_ownership(
    app: FastAPI, client: AsyncClient
) -> None:
    login = await register_and_login(client, "evidence@example.com")
    owner = login["registered_user"]["id"]
    other = (await register_and_login(client, "other-evidence@example.com"))["registered_user"][
        "id"
    ]
    async with app.state.database.session_maker() as session:
        first = Task(owner_id=owner, title="一")
        second = Task(owner_id=owner, title="二")
        disabled = Task(owner_id=owner, title="关闭", use_preferences=False)
        session.add_all([first, second, disabled])
        await session.flush()
        messages = [
            Message(task_id=t.id, role="user", plain_text="语言简洁一些")
            for t in [first, first, second, disabled]
        ]
        session.add_all(messages)
        await session.flush()
        assert await learn_preferences(session, owner_id=other, message_id=messages[0].id) == []
        assert await learn_preferences(session, owner_id=owner, message_id=messages[3].id) == []
        await learn_preferences(session, owner_id=owner, message_id=messages[0].id)
        assert await learn_preferences(session, owner_id=owner, message_id=messages[0].id) == []
        await learn_preferences(session, owner_id=owner, message_id=messages[1].id)
        preference = await session.scalar(
            select(UserPreference).where(UserPreference.user_id == owner)
        )
        assert preference.status == "candidate"
        await learn_preferences(session, owner_id=owner, message_id=messages[2].id)
        assert preference.status == "confirmed"
        preference.status = "revoked"
        await session.flush()
        assert await learn_preferences(session, owner_id=owner, message_id=messages[2].id) == []
        assert preference.status == "revoked"


async def test_semantic_preference_replaces_conflicting_long_term_choice(
    app: FastAPI, client: AsyncClient
) -> None:
    owner = (await register_and_login(client, "semantic@example.com"))["registered_user"]["id"]
    async with app.state.database.session_maker() as session:
        task = Task(owner_id=owner, title="语气")
        session.add(task)
        await session.flush()
        old = UserPreference(
            user_id=owner,
            preference_type="tone",
            value="严肃正式的语气",
            scope="personal",
            confidence=0.9,
            source_type="explicit",
            status="confirmed",
        )
        message = Message(task_id=task.id, role="user", plain_text="以后用像朋友聊天的语气")
        session.add_all([old, message])
        await session.flush()
        ids = await learn_preferences(
            session,
            owner_id=owner,
            message_id=message.id,
            proposed=[
                {
                    "type": "tone",
                    "value": "语言温暖亲切，像朋友聊天",
                    "evidence": message.plain_text,
                }
            ],
        )
        assert len(ids) == 1
        assert old.status == "revoked"
        assert (await session.get(UserPreference, ids[0])).status == "confirmed"


async def test_project_feedback_does_not_change_personal_preference(
    app: FastAPI, client: AsyncClient
) -> None:
    owner = (await register_and_login(client, "project-feedback@example.com"))["registered_user"][
        "id"
    ]
    async with app.state.database.session_maker() as session:
        project = Project(owner_id=owner, name="项目偏好隔离")
        session.add(project)
        await session.flush()
        task = Task(owner_id=owner, title="项目文章", project_id=project.id)
        personal = UserPreference(
            user_id=owner,
            preference_type="tone",
            value="正式严肃",
            scope="personal",
            confidence=0.9,
            source_type="explicit",
            status="confirmed",
        )
        session.add_all([task, personal])
        await session.flush()
        message = Message(task_id=task.id, role="user", plain_text="以后用像朋友聊天的语气")
        session.add(message)
        await session.flush()
        ids = await learn_preferences(
            session,
            owner_id=owner,
            message_id=message.id,
            proposed=[
                {
                    "type": "tone",
                    "value": "语言温暖亲切，像朋友聊天",
                    "evidence": message.plain_text,
                }
            ],
        )
        learned = await session.get(UserPreference, ids[0])
        assert learned.scope == "project" and learned.project_id == project.id
        assert personal.status == "confirmed"


async def test_explicit_feedback_survives_model_failure(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail(self, **kwargs):
        raise ProviderUnavailable("test unavailable")

    monkeypatch.setattr(UnavailableModelProvider, "generate", fail)
    login = await register_and_login(client, "failed-feedback@example.com")
    auth = bearer(login["access_token"])
    response = await client.post(
        "/api/v1/tasks",
        headers={**auth, "Idempotency-Key": "failed-run"},
        json={
            "first_message": {
                "text": "写一篇团队管理文章。以后文章开头直接进入主题",
                "content": {},
                "client_message_id": "failed-run",
            }
        },
    )
    assert response.status_code == 202, response.text
    preferences = (await client.get("/api/v1/preferences", headers=auth)).json()["items"]
    assert any(
        p["preference_type"] == "direct_opening" and p["status"] == "confirmed" for p in preferences
    )


@pytest.mark.parametrize(
    "text, expected",
    [
        ("你以后都帮我生成偏严肃专业的文章，记录到我的偏好中", "discussion"),
        ("以后文章开头不要铺垫，直接进入主题", "discussion"),
        ("只记录我的写作偏好，不要生成文章", "discussion"),
        ("帮我记住我的写作习惯：表达简洁", "discussion"),
        ("以后语言简洁，同时帮我写一篇企业管理文章", "article_generation"),
        ("以后用专业语气，现在修改这篇文章", "article_generation"),
        ("记录我的偏好：专业语气，并生成一篇企业管理文章", "article_generation"),
        ("把这篇文章改成专业严肃风格", "article_generation"),
        (
            "你这个文章不要出现本资料这种话，后面好多论点但是没有论述",
            "article_generation",
        ),
        (
            "为什么你这边会出现 作者｜蓝血创作组 的字样？这不是文章中的东西",
            "discussion",
        ),
        ("请把文章里的“作者｜蓝血创作组”去掉", "article_generation"),
    ],
)
def test_preference_intent_is_not_current_article_permission(text: str, expected: str) -> None:
    assert classify_run_type(text, has_current_article=True) == expected


async def test_screenshot_request_saves_preference_without_creating_article_version(
    app: FastAPI,
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    login = await register_and_login(client, "preference-intent@example.com")
    token = login["access_token"]
    task_id, article_id = await _article_task(client, token, key="intent-article")
    assert article_id
    async with app.state.database.session_maker() as session:
        before = await session.scalar(
            select(func.count())
            .select_from(ArticleVersion)
            .where(ArticleVersion.article_id == article_id)
        )
    original = UnavailableModelProvider.generate
    purposes = []

    async def capture(self, **kwargs):
        purposes.append(kwargs["purpose"])
        result = await original(self, **kwargs)
        if kwargs["purpose"] == "fast_task":
            # Even a misleading model acknowledgement must not create an article or leak to SSE.
            return ModelResult(
                text="文章已生成",
                structured=result.structured,
                input_tokens=1,
                output_tokens=1,
                provider_request_id="test-intent",
            )
        return result

    monkeypatch.setattr(UnavailableModelProvider, "generate", capture)
    response = await client.post(
        f"/api/v1/tasks/{task_id}/messages",
        headers={**bearer(token), "Idempotency-Key": "preference-only-message"},
        json={
            "text": "你以后都帮我生成偏严肃专业的文章，记录到我的偏好中",
            "content": {},
            "client_message_id": "preference-only-message",
        },
    )
    assert response.status_code == 202, response.text
    run = response.json()["ai_run"]
    assert run["run_type"] == "discussion"
    assert "article_generation" not in purposes and "article_planning" not in purposes
    async with app.state.database.session_maker() as session:
        after = await session.scalar(
            select(func.count())
            .select_from(ArticleVersion)
            .where(ArticleVersion.article_id == article_id)
        )
        assert before == after
        message = await session.scalar(
            select(Message)
            .where(Message.task_id == task_id, Message.role == "assistant")
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        assert "已记录写作偏好" in message.plain_text
        assert "没有生成或修改文章" in message.plain_text
        assert not message.content_json.get("article_id")
        events = list(
            (await session.scalars(select(AIRunEvent).where(AIRunEvent.run_id == run["id"]))).all()
        )
        assert not any(e.event_type == "article.ready" for e in events)
        assert not any(
            e.event_type == "text.delta" and e.payload.get("text") == "文章已生成" for e in events
        )

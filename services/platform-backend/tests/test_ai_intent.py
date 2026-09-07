from __future__ import annotations

from httpx import AsyncClient

from app.domains.ai import auxiliary_model_context, needs_article_planning
from tests.conftest import bearer, register_and_login


def test_simple_new_article_skips_separate_planning_call() -> None:
    assert not needs_article_planning({"untrusted_user_input": "写一篇关于团队管理的公众号文章"})


def test_complex_article_keeps_separate_planning_call() -> None:
    assert needs_article_planning(
        {
            "untrusted_user_input": "根据资料写一篇文章",
            "untrusted_documents": [{"title": "资料"}],
        }
    )
    assert needs_article_planning({"untrusted_user_input": "写一篇3000字的公众号文章"})


def test_native_provider_file_skips_redundant_planning_and_is_hidden_from_auxiliary_models(
) -> None:
    native_file = {
        "filename": "战略规划.pptx",
        "provider_file_id": "manus-file",
        "delivery": "manus_files_api",
        "content": "",
    }
    context = {"untrusted_user_input": "根据资料写文章", "untrusted_model_files": [native_file]}
    assert not needs_article_planning(context)
    assert auxiliary_model_context(context)["untrusted_model_files"] == []

    extracted = {**native_file, "content": "第一章：市场洞察"}
    extracted_context = {**context, "untrusted_model_files": [extracted]}
    assert needs_article_planning(extracted_context)
    assert auxiliary_model_context(extracted_context)["untrusted_extracted_files"] == [
        {"title": "战略规划.pptx", "text": "第一章：市场洞察"}
    ]


async def _create_task(client: AsyncClient, token: str, *, text: str, key: str) -> dict:
    response = await client.post(
        "/api/v1/tasks",
        headers={**bearer(token), "Idempotency-Key": key},
        json={
            "first_message": {
                "text": text,
                "content": {},
                "client_message_id": f"message-{key}",
            }
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


async def test_topic_discussion_returns_chat_response_without_creating_article(
    client: AsyncClient,
) -> None:
    login = await register_and_login(client, "intent-discussion@example.com")
    created = await _create_task(
        client,
        login["access_token"],
        text="帮我分析一下人工智能办公这个选题是否值得写",
        key="intent-discussion-1",
    )
    assert created["ai_run"]["run_type"] == "discussion"

    task = await client.get(
        f"/api/v1/tasks/{created['task']['id']}",
        headers=bearer(login["access_token"]),
    )
    assert task.status_code == 200
    assert task.json()["current_article_id"] is None
    assistant = task.json()["messages"][-1]
    assert assistant["role"] == "assistant"
    assert assistant["content_json"]["response_kind"] == "discussion"
    assert assistant["content_json"]["suggestions"] == ["继续生成完整文章"]


async def test_outline_and_title_requests_do_not_overwrite_current_article(
    client: AsyncClient,
) -> None:
    login = await register_and_login(client, "intent-outline@example.com")
    created = await _create_task(
        client,
        login["access_token"],
        text="写一篇关于组织变革的公众号文章",
        key="intent-article-1",
    )
    token = login["access_token"]
    task_id = created["task"]["id"]
    task = await client.get(f"/api/v1/tasks/{task_id}", headers=bearer(token))
    article_id = task.json()["current_article_id"]
    assert article_id

    for index, (text, expected) in enumerate(
        [("给我五个标题", "titles"), ("先列一个文章提纲", "outline")], start=1
    ):
        response = await client.post(
            f"/api/v1/tasks/{task_id}/messages",
            headers={**bearer(token), "Idempotency-Key": f"intent-followup-{index}"},
            json={
                "text": text,
                "content": {},
                "client_message_id": f"intent-followup-message-{index}",
            },
        )
        assert response.status_code == 202, response.text
        assert response.json()["ai_run"]["run_type"] == expected

    unchanged = await client.get(f"/api/v1/tasks/{task_id}", headers=bearer(token))
    assert unchanged.json()["current_article_id"] == article_id
    assert unchanged.json()["messages"][-1]["content_json"]["response_kind"] == "outline"


async def test_vague_article_request_asks_at_most_two_questions_without_charging(
    client: AsyncClient,
) -> None:
    login = await register_and_login(client, "intent-clarification@example.com")
    created = await _create_task(
        client,
        login["access_token"],
        text="帮我写一篇文章",
        key="intent-clarification-1",
    )
    assert created["ai_run"]["run_type"] == "clarification"
    task = await client.get(
        f"/api/v1/tasks/{created['task']['id']}",
        headers=bearer(login["access_token"]),
    )
    assistant = task.json()["messages"][-1]
    assert assistant["content_json"]["suggestions"] == ["按你的理解直接写"]
    assert assistant["plain_text"].count("？") <= 2
    assert task.json()["current_article_id"] is None
    quota = await client.get("/api/v1/quota", headers=bearer(login["access_token"]))
    assert quota.json()["balance"] == 500


async def test_second_article_request_requires_overwrite_or_new_task_choice(
    client: AsyncClient,
) -> None:
    login = await register_and_login(client, "intent-conflict@example.com")
    token = login["access_token"]
    created = await _create_task(
        client,
        token,
        text="写一篇关于品牌增长的公众号文章",
        key="intent-conflict-first",
    )
    task_id = created["task"]["id"]
    before = await client.get(f"/api/v1/tasks/{task_id}", headers=bearer(token))
    article_id = before.json()["current_article_id"]

    response = await client.post(
        f"/api/v1/tasks/{task_id}/messages",
        headers={**bearer(token), "Idempotency-Key": "intent-conflict-second"},
        json={
            "text": "再写一篇同主题文章",
            "content": {},
            "client_message_id": "intent-conflict-message-second",
        },
    )
    assert response.status_code == 202, response.text
    assert response.json()["ai_run"]["run_type"] == "article_conflict_confirmation"
    after = await client.get(f"/api/v1/tasks/{task_id}", headers=bearer(token))
    assert after.json()["current_article_id"] == article_id
    assistant = after.json()["messages"][-1]
    assert assistant["content_json"]["suggestions"] == ["覆盖当前文章", "新建任务"]

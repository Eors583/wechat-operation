from __future__ import annotations

from httpx import AsyncClient

from .conftest import bearer, register_and_login


async def test_enabled_matching_skill_is_selected_and_version_is_frozen(
    client: AsyncClient,
) -> None:
    login = await register_and_login(client, "auto-skill@example.com")
    headers = bearer(login["access_token"])
    skill = await client.post(
        "/api/v1/skills",
        headers=headers,
        json={
            "name": "科技产品评测",
            "scenario": "科技产品评测",
            "instructions": "从真实使用场景、优点和局限三个方面进行评测。",
        },
    )
    assert skill.status_code == 201, skill.text
    skill_id = skill.json()["skill"]["id"]
    version_id = skill.json()["version"]["id"]

    created = await client.post(
        "/api/v1/tasks",
        headers={**headers, "Idempotency-Key": "auto-skill-task"},
        json={
            "first_message": {
                "text": "请写一篇科技产品评测，主题是折叠屏手机",
                "content": {},
                "client_message_id": "auto-skill-message",
            }
        },
    )
    assert created.status_code == 202, created.text
    assert created.json()["task"]["current_skill_id"] == skill_id
    run = await client.get(f"/api/v1/ai-runs/{created.json()['ai_run']['id']}", headers=headers)
    assert run.json()["skill_version_id"] == version_id
    assert run.json()["context_snapshot"]["skill_selection"] == "automatic"


async def test_disabled_skill_is_not_selected_automatically(client: AsyncClient) -> None:
    login = await register_and_login(client, "disabled-auto-skill@example.com")
    headers = bearer(login["access_token"])
    skill = await client.post(
        "/api/v1/skills",
        headers=headers,
        json={
            "name": "餐厅探店",
            "scenario": "餐厅探店",
            "instructions": "描述环境、菜品和服务。",
        },
    )
    skill_id = skill.json()["skill"]["id"]
    disabled = await client.patch(
        f"/api/v1/skills/{skill_id}/setting",
        headers=headers,
        json={"enabled": False},
    )
    assert disabled.status_code == 200

    created = await client.post(
        "/api/v1/tasks",
        headers={**headers, "Idempotency-Key": "disabled-auto-skill-task"},
        json={
            "first_message": {
                "text": "请写一篇餐厅探店文章",
                "content": {},
                "client_message_id": "disabled-auto-skill-message",
            }
        },
    )
    assert created.status_code == 202, created.text
    assert created.json()["task"]["current_skill_id"] is None
    assert created.json()["ai_run"]["skill_version_id"] is None

from __future__ import annotations

from fastapi import FastAPI
from httpx import AsyncClient

from .conftest import bearer, register_and_login


class RejectInputSafety:
    async def check_text(self, text: str) -> tuple[bool, str | None]:
        return (False, "blocked input") if "拒绝测试" in text else (True, None)


async def test_unsafe_user_input_fails_run_and_releases_reserved_quota(
    app: FastAPI, client: AsyncClient
) -> None:
    app.state.content_safety_provider = RejectInputSafety()
    login = await register_and_login(client, "input-safety@example.com")
    headers = bearer(login["access_token"])
    initial_balance = (await client.get("/api/v1/me", headers=headers)).json()["quota_balance"]
    created = await client.post(
        "/api/v1/tasks",
        headers={**headers, "Idempotency-Key": "unsafe-input-task"},
        json={
            "first_message": {
                "text": "请写一篇拒绝测试文章",
                "content": {},
                "client_message_id": "unsafe-input-message",
            }
        },
    )
    assert created.status_code == 202, created.text
    run = await client.get(f"/api/v1/ai-runs/{created.json()['ai_run']['id']}", headers=headers)
    assert run.json()["status"] == "failed"
    assert run.json()["error_code"] == "CONTENT_SAFETY_BLOCKED"
    detail = await client.get(f"/api/v1/tasks/{created.json()['task']['id']}", headers=headers)
    assert detail.status_code == 200
    failure_messages = [
        message
        for message in detail.json()["messages"]
        if message["content_json"].get("response_kind") == "ai_error"
    ]
    assert len(failure_messages) == 1
    assert failure_messages[0]["role"] == "assistant"
    assert failure_messages[0]["plain_text"] == "本轮要求未通过安全检查。"
    assert failure_messages[0]["content_json"] == {
        "response_kind": "ai_error",
        "ai_run_id": created.json()["ai_run"]["id"],
        "error_code": "CONTENT_SAFETY_BLOCKED",
        "retryable": False,
        "source_message_id": created.json()["message"]["id"],
    }
    continued = await client.post(
        f"/api/v1/tasks/{created.json()['task']['id']}/messages",
        headers={**headers, "Idempotency-Key": "safe-followup-message"},
        json={
            "text": "请写一篇文章",
            "content": {},
            "client_message_id": "safe-followup-client-message",
        },
    )
    assert continued.status_code == 202
    continued_run = await client.get(
        f"/api/v1/ai-runs/{continued.json()['ai_run']['id']}", headers=headers
    )
    assert continued_run.json()["status"] == "completed"
    assert failure_messages[0]["id"] not in {
        message["id"] for message in continued_run.json()["context_snapshot"]["recent_messages"]
    }
    continued_detail = await client.get(
        f"/api/v1/tasks/{created.json()['task']['id']}", headers=headers
    )
    assert any(
        message["id"] == failure_messages[0]["id"]
        for message in continued_detail.json()["messages"]
    )
    me = await client.get("/api/v1/me", headers=headers)
    assert me.json()["quota_balance"] == initial_balance

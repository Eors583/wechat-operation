from __future__ import annotations

from httpx import AsyncClient

from app.domains.ai import estimate_tokens, trim_document_context, truncate_to_token_budget

from .conftest import bearer, register_and_login


def test_token_estimate_and_truncation_are_conservative_for_chinese() -> None:
    text = "中文内容" * 100
    assert estimate_tokens(text) == 400
    truncated = truncate_to_token_budget(text, 73)
    assert 0 < estimate_tokens(truncated) <= 73
    assert text.startswith(truncated)


def test_document_budget_keeps_high_ranked_excerpts_first() -> None:
    documents = [
        {
            "document_id": "high",
            "title": "高相关",
            "excerpts": [{"text": "高" * 100, "retrieval_score": 0.9}],
        },
        {
            "document_id": "low",
            "title": "低相关",
            "excerpts": [{"text": "低" * 100, "retrieval_score": 0.1}],
        },
    ]
    trimmed = trim_document_context(documents, 60)
    assert [item["document_id"] for item in trimmed] == ["high"]
    assert estimate_tokens(trimmed[0]["excerpts"][0]["text"]) < 60


async def test_latest_user_request_is_rejected_instead_of_silently_truncated(
    client: AsyncClient,
) -> None:
    login = await register_and_login(client, "context-limit@example.com")
    response = await client.post(
        "/api/v1/tasks",
        headers={**bearer(login["access_token"]), "Idempotency-Key": "context-limit-task"},
        json={
            "first_message": {
                "text": "写" * 30_000,
                "content": {},
                "client_message_id": "context-limit-message",
            }
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == "AI_INPUT_CONTEXT_LIMIT_EXCEEDED"
    tasks = await client.get("/api/v1/tasks", headers=bearer(login["access_token"]))
    assert tasks.json()["items"] == []

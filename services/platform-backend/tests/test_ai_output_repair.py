from __future__ import annotations

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select

from app.models import AIRunAttempt, AIRunEvent
from app.providers import ModelResult

from .conftest import bearer, register_and_login


class InvalidThenRepairedModel:
    def __init__(self) -> None:
        self.calls = 0
        self.generation_calls = 0
        self.purposes: list[str] = []

    async def generate(
        self, *, purpose: str, prompt: str, context: dict[str, object]
    ) -> ModelResult:
        del prompt, context
        self.calls += 1
        self.purposes.append(purpose)
        if purpose == "article_generation":
            self.generation_calls += 1
        if purpose == "article_generation" and self.generation_calls == 1:
            structured = {
                "type": "doc",
                "content": [{"type": "unsupported-node", "text": "无效"}],
            }
        else:
            structured = {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "修复后的文章正文" * 200}],
                    }
                ],
            }
        return ModelResult(
            text="修复后的文章正文",
            structured=structured,
            input_tokens=10,
            output_tokens=10,
            provider_request_id=f"repair-{self.calls}",
            simulated=False,
        )


async def test_invalid_article_structure_is_repaired_once_and_audited(
    app: FastAPI, client: AsyncClient
) -> None:
    model = InvalidThenRepairedModel()
    app.state.model_provider = model
    login = await register_and_login(client, "output-repair@example.com")
    headers = bearer(login["access_token"])
    created = await client.post(
        "/api/v1/tasks",
        headers={**headers, "Idempotency-Key": "output-repair-task"},
        json={
            "first_message": {
                "text": "请写一篇关于结构化输出修复的完整文章",
                "content": {},
                "client_message_id": "output-repair-message",
            }
        },
    )
    assert created.status_code == 202, created.text
    assert model.calls == 3
    assert model.generation_calls == 2
    assert model.purposes == [
        "article_generation",
        "article_generation",
        "memory_summary",
    ]
    run_id = created.json()["ai_run"]["id"]
    run = await client.get(f"/api/v1/ai-runs/{run_id}", headers=headers)
    assert run.json()["status"] == "completed"
    async with app.state.database.session_maker() as session:
        attempts = list(
            (
                await session.scalars(
                    select(AIRunAttempt)
                    .where(AIRunAttempt.run_id == run_id)
                    .order_by(AIRunAttempt.attempt_no)
                )
            ).all()
        )
        assert [item.attempt_no for item in attempts] == [1, 2, 3]
        events = list(
            (await session.scalars(select(AIRunEvent).where(AIRunEvent.run_id == run_id))).all()
        )
        assert any(item.payload.get("code") == "MODEL_OUTPUT_REPAIR_STARTED" for item in events)

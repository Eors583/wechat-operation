import json

import pytest
from sqlalchemy import select

from app.models import Article, ArticleVersion, Message
from app.production_providers import _structured_output
from app.providers import ModelResult
from tests.conftest import bearer, register_and_login


@pytest.mark.parametrize("repair_valid", [True, False])
async def test_broken_json_is_repaired_once_or_never_saved(app, client, repair_valid):
    calls = []
    valid = {
        "type": "doc",
        "content": [
            {
                "type": "heading",
                "attrs": {"level": 1},
                "content": [{"type": "text", "text": "真正的文章标题"}],
            },
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "真正正文需要完整展开。" * 180}],
            },
        ],
    }

    class Model:
        async def generate(self, *, purpose, prompt, context):
            calls.append(context)
            text = "PASS"
            if purpose == "article_generation":
                text = json.dumps(valid)
                if "invalid_article_json" not in context or not repair_valid:
                    text += ',{"type":"paragraph"}]}'
            return ModelResult(
                text,
                _structured_output(text, article_output=purpose == "article_generation"),
                1,
                1,
                "test-only",
                False,
            )

    app.state.model_provider = Model()
    login = await register_and_login(client, "broken-json@example.com")
    response = await client.post(
        "/api/v1/tasks",
        headers={**bearer(login["access_token"]), "Idempotency-Key": "broken"},
        json={
            "first_message": {
                "text": "请写一篇完整文章",
                "content": {},
                "client_message_id": "broken",
            }
        },
    )
    assert response.status_code == 202, response.text
    assert sum("invalid_article_json" in context for context in calls) == 1
    async with app.state.database.session_maker() as session:
        article = await session.scalar(select(Article))
        if repair_valid:
            assert article is not None
            assert article.title == "真正的文章标题"
        else:
            assert article is None


async def test_chat_preface_is_stored_in_dialogue_but_never_in_article_preview(app, client):
    assistant_message = "已按你的要求处理，正式文章从 article 字段开始。"
    article_document = {
        "type": "doc",
        "content": [
            {
                "type": "heading",
                "attrs": {"level": 1},
                "content": [{"type": "text", "text": "组织转型的真正起点"}],
            },
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "组织转型需要从责任边界、协作机制和反馈闭环开始。" * 100,
                    }
                ],
            },
        ],
    }

    class Model:
        async def generate(self, *, purpose, prompt, context):
            text = "PASS"
            if purpose == "article_generation":
                assert "assistant_message" in prompt and "article" in prompt
                text = json.dumps(
                    {"assistant_message": assistant_message, "article": article_document},
                    ensure_ascii=False,
                )
            return ModelResult(
                text,
                _structured_output(text, article_output=purpose == "article_generation"),
                1,
                1,
                "article-boundary-test",
                False,
            )

    app.state.model_provider = Model()
    login = await register_and_login(client, "article-boundary@example.com")
    response = await client.post(
        "/api/v1/tasks",
        headers={**bearer(login["access_token"]), "Idempotency-Key": "article-boundary"},
        json={
            "first_message": {
                "text": "写一篇关于组织转型的完整文章",
                "content": {},
                "client_message_id": "article-boundary",
            }
        },
    )
    assert response.status_code == 202, response.text

    async with app.state.database.session_maker() as session:
        article = await session.scalar(select(Article))
        assert article is not None
        version = await session.scalar(
            select(ArticleVersion).where(ArticleVersion.article_id == article.id)
        )
        assert version is not None
        stored_json = json.dumps(version.content_json, ensure_ascii=False)
        assert version.content_json == article_document
        assert assistant_message not in stored_json
        dialogue = await session.scalar(
            select(Message).where(Message.role == "assistant").order_by(Message.created_at.desc())
        )
        assert dialogue is not None
        assert dialogue.plain_text == assistant_message
        assert dialogue.content_json["article_id"] == article.id

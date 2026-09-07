from __future__ import annotations

import hashlib

from fastapi import FastAPI
from httpx import AsyncClient

from app.models import Admin, SystemSetting, utcnow
from app.security import hash_password

from .conftest import bearer, register_and_login


async def _publish_runtime_settings(app: FastAPI) -> None:
    sections = {
        "home": {"welcome_message": "从已发布配置开始创作", "example_prompts": ["测试示例"]},
        "files": {"allowed_extensions": ["txt"], "max_file_mb": 1, "link_fetch_enabled": False},
        "ai": {
            "max_clarification_rounds": 0,
            "min_article_length": 500,
            "max_article_length": 2000,
            "preference_enabled_by_default": False,
        },
        "articles": {"autosave_seconds": 45, "history_versions": 1},
        "wechat": {
            "wechat_draft_enabled": False,
            "wechat_publish_enabled": False,
            "max_article_images": 0,
        },
        "features": {
            "feature_flags": {
                "personal_skills": False,
                "template_extraction": False,
                "external_knowledge": False,
                "visual_understanding": False,
            }
        },
    }
    async with app.state.database.session_maker() as session:
        admin = Admin(
            username="runtime-settings-admin",
            password_hash=hash_password("runtime-settings-admin-password"),
            permissions=["*"],
        )
        session.add(admin)
        await session.flush()
        for section, values in sections.items():
            session.add(
                SystemSetting(
                    section=section,
                    version_no=1,
                    values=values,
                    status="published",
                    published_at=utcnow(),
                    created_by_admin_id=admin.id,
                )
            )
        await session.commit()


async def _publish_ai_run_credit_cost(app: FastAPI, cost: int) -> None:
    async with app.state.database.session_maker() as session:
        admin = Admin(
            username="credit-cost-admin",
            password_hash=hash_password("credit-cost-admin-password"),
            permissions=["*"],
        )
        session.add(admin)
        await session.flush()
        session.add(
            SystemSetting(
                section="ai",
                version_no=1,
                values={"ai_run_credit_cost": cost},
                status="published",
                published_at=utcnow(),
                created_by_admin_id=admin.id,
            )
        )
        await session.commit()


async def test_public_settings_and_file_limits_use_published_bundle(
    app: FastAPI, client: AsyncClient
) -> None:
    await _publish_runtime_settings(app)
    login = await register_and_login(client, "runtime-files@example.com")
    auth = bearer(login["access_token"])
    public = await client.get("/api/v1/public-settings", headers=auth)
    assert public.status_code == 200
    assert public.json()["home"]["welcome_message"] == "从已发布配置开始创作"
    assert public.json()["articles"]["autosave_seconds"] == 45

    blocked_type = await client.post(
        "/api/v1/uploads",
        headers={**auth, "Idempotency-Key": "runtime-file-type"},
        json={
            "filename": "blocked.pdf",
            "mime_type": "application/pdf",
            "size_bytes": 10,
            "sha256": hashlib.sha256(b"0123456789").hexdigest(),
        },
    )
    assert blocked_type.status_code == 422
    assert blocked_type.json()["code"] == "FILE_TYPE_NOT_ALLOWED"

    blocked_size = await client.post(
        "/api/v1/uploads",
        headers={**auth, "Idempotency-Key": "runtime-file-size"},
        json={
            "filename": "too-large.txt",
            "mime_type": "text/plain",
            "size_bytes": 2 * 1024 * 1024,
            "sha256": "a" * 64,
        },
    )
    assert blocked_size.status_code == 413
    assert blocked_size.json()["details"]["max_bytes"] == 1024 * 1024


async def test_published_ai_and_feature_switches_are_enforced(
    app: FastAPI, client: AsyncClient
) -> None:
    await _publish_runtime_settings(app)
    login = await register_and_login(client, "runtime-features@example.com")
    auth = bearer(login["access_token"])
    created = await client.post(
        "/api/v1/tasks",
        headers={**auth, "Idempotency-Key": "runtime-no-clarification"},
        json={
            "first_message": {
                "text": "帮我写一篇文章",
                "content": {},
                "client_message_id": "runtime-no-clarification-message",
            }
        },
    )
    assert created.status_code == 202, created.text
    assert created.json()["ai_run"]["run_type"] == "article_generation"
    assert created.json()["task"]["use_preferences"] is False
    task = await client.get(f"/api/v1/tasks/{created.json()['task']['id']}", headers=auth)
    assert task.json()["current_article_id"]

    skill = await client.post(
        "/api/v1/skills",
        headers=auth,
        json={
            "name": "停用技能",
            "scenario": "测试",
            "instructions": "测试要求",
            "example_article": None,
        },
    )
    assert skill.status_code == 403
    assert skill.json()["code"] == "PERSONAL_SKILLS_DISABLED"

    extraction = await client.post(
        "/api/v1/layout-templates/extract",
        headers=auth,
        json={
            "name": "停用提取",
            "source_url": "https://mp.weixin.qq.com/s/example",
            "save_template": True,
        },
    )
    assert extraction.status_code == 403
    assert extraction.json()["code"] == "TEMPLATE_EXTRACTION_DISABLED"

    blocked_link = await client.post(
        "/api/v1/tasks",
        headers={**auth, "Idempotency-Key": "runtime-link-disabled"},
        json={
            "first_message": {
                "text": "参考这个链接写文章",
                "content": {"links": ["https://example.com/reference"]},
                "client_message_id": "runtime-link-disabled-message",
            }
        },
    )
    assert blocked_link.status_code == 403
    assert blocked_link.json()["code"] == "LINK_FETCH_DISABLED"

    blocked_image = await client.post(
        "/api/v1/uploads",
        headers={**auth, "Idempotency-Key": "runtime-visual-disabled"},
        json={
            "filename": "blocked.png",
            "mime_type": "image/png",
            "size_bytes": 10,
            "sha256": hashlib.sha256(b"0123456789").hexdigest(),
        },
    )
    assert blocked_image.status_code == 403
    assert blocked_image.json()["code"] == "VISUAL_UNDERSTANDING_DISABLED"


async def test_ai_run_credit_cost_defaults_then_uses_exact_published_balance(
    app: FastAPI, client: AsyncClient
) -> None:
    object.__setattr__(app.state.settings, "inline_mock_workers", False)
    default_login = await register_and_login(client, "runtime-default-credit-cost@example.com")
    default_auth = bearer(default_login["access_token"])
    default_created = await client.post(
        "/api/v1/tasks",
        headers={**default_auth, "Idempotency-Key": "runtime-credit-cost-default"},
        json={
            "first_message": {
                "text": "写一篇关于默认积分的公众号文章",
                "content": {},
                "client_message_id": "runtime-credit-cost-default-message",
            }
        },
    )
    assert default_created.status_code == 202, default_created.text
    assert default_created.json()["ai_run"]["quota_reserved"] == 1
    default_quota = await client.get("/api/v1/quota", headers=default_auth)
    assert default_quota.json()["balance"] == 499

    await _publish_ai_run_credit_cost(app, 500)
    login = await register_and_login(client, "runtime-credit-cost@example.com")
    auth = bearer(login["access_token"])

    created = await client.post(
        "/api/v1/tasks",
        headers={**auth, "Idempotency-Key": "runtime-credit-cost-first"},
        json={
            "first_message": {
                "text": "写一篇关于精益运营的公众号文章",
                "content": {},
                "client_message_id": "runtime-credit-cost-first-message",
            }
        },
    )
    assert created.status_code == 202, created.text
    assert created.json()["ai_run"]["quota_reserved"] == 500
    quota = await client.get("/api/v1/quota", headers=auth)
    assert quota.json()["balance"] == 0
    assert (
        next(item for item in quota.json()["ledger"] if item["business_type"] == "ai_run_reserve")[
            "amount"
        ]
        == 500
    )

    rejected = await client.post(
        "/api/v1/tasks",
        headers={**auth, "Idempotency-Key": "runtime-credit-cost-second"},
        json={
            "first_message": {
                "text": "再写一篇关于流程改进的公众号文章",
                "content": {},
                "client_message_id": "runtime-credit-cost-second-message",
            }
        },
    )
    assert rejected.status_code == 402
    assert rejected.json()["code"] == "QUOTA_INSUFFICIENT"
    assert rejected.json()["details"] == {"balance": 0, "required": 500}


async def test_published_image_limit_is_enforced_before_render(
    app: FastAPI, client: AsyncClient
) -> None:
    await _publish_runtime_settings(app)
    login = await register_and_login(client, "runtime-images@example.com")
    auth = bearer(login["access_token"])
    article = await client.post(
        "/api/v1/articles",
        headers=auth,
        json={
            "title": "含图文章",
            "content": {
                "type": "doc",
                "content": [
                    {
                        "type": "image",
                        "attrs": {"src": "https://example.com/image.png", "alt": "示例"},
                    }
                ],
            },
        },
    )
    assert article.status_code == 201, article.text
    rendered = await client.post(
        "/api/v1/article-renders",
        headers=auth,
        json={"article_id": article.json()["article"]["id"]},
    )
    assert rendered.status_code == 422
    assert rendered.json()["code"] == "ARTICLE_IMAGE_LIMIT_EXCEEDED"

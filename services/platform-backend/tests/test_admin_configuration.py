from __future__ import annotations

import os
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select

from app.models import (
    Admin,
    JobRecord,
    ModelDeployment,
    ModelProviderRecord,
    ModelRouteVersion,
    OutboxEvent,
    WechatPlatformConfig,
    utcnow,
)
from app.providers import ModelResult, ProviderUnavailable
from app.security import hash_password

from .conftest import bearer, register_and_login


async def _admin_headers(app: FastAPI, client: AsyncClient) -> dict[str, str]:
    async with app.state.database.session_maker() as session:
        session.add(
            Admin(
                username="configuration-admin",
                password_hash=hash_password("configuration-admin-password"),
                permissions=["*"],
            )
        )
        await session.commit()
    response = await client.post(
        "/admin-api/v1/auth/login",
        json={
            "username": "configuration-admin",
            "password": "configuration-admin-password",
        },
    )
    assert response.status_code == 200, response.text
    return bearer(response.json()["access_token"])


async def test_wechat_platform_secrets_are_encrypted_and_never_returned(
    app: FastAPI, client: AsyncClient
) -> None:
    headers = await _admin_headers(app, client)
    raw_secret = "wechat-component-app-secret"
    response = await client.put(
        "/admin-api/v1/wechat-platform-configs/production",
        headers=headers,
        json={
            "environment": "production",
            "component_appid": "wx-component-appid",
            "component_appsecret": raw_secret,
            "message_token": "wechat-message-token",
            "encoding_aes_key": "abcdefghijklmnopqrstuvwxyzABCDEFGH123456789",
            "authorization_callback_url": "https://app.example.com/callbacks/v1/wechat/authorize",
            "ticket_callback_url": "https://app.example.com/callbacks/v1/wechat/tickets",
            "permission_set": ["draft", "publish"],
        },
    )
    assert response.status_code == 200, response.text
    assert raw_secret not in response.text
    assert response.json()["component_secret_configured"] is True

    async with app.state.database.session_maker() as session:
        config = await session.scalar(select(WechatPlatformConfig))
        assert config is not None
        assert raw_secret not in config.component_secret_ref
        assert app.state.secret_provider.resolve(config.component_secret_ref) == raw_secret


async def test_admin_accounts_use_password_only_contract(app: FastAPI, client: AsyncClient) -> None:
    headers = await _admin_headers(app, client)
    created = await client.post(
        "/admin-api/v1/admins",
        headers=headers,
        json={
            "username": "password-only-admin",
            "password": "password-only-admin-2026",
            "permissions": ["dashboard:read"],
        },
    )
    assert created.status_code == 201, created.text

    listed = await client.get("/admin-api/v1/admins", headers=headers)
    assert listed.status_code == 200, listed.text
    account = next(item for item in listed.json()["items"] if item["id"] == created.json()["id"])
    assert set(account) == {
        "id",
        "username",
        "status",
        "permissions",
        "last_login_at",
        "created_at",
    }

    login = await client.post(
        "/admin-api/v1/auth/login",
        json={
            "username": "password-only-admin",
            "password": "password-only-admin-2026",
        },
    )
    assert login.status_code == 200, login.text


async def test_skill_draft_is_updated_in_place_and_runs_model_test(
    app: FastAPI, client: AsyncClient
) -> None:
    try:
        headers = await _admin_headers(app, client)
        skill_response = await client.post(
            "/admin-api/v1/official-skills",
            headers=headers,
            json={"code": "evidence_writer", "name": "事实写作", "category": "content"},
        )
        assert skill_response.status_code == 201, skill_response.text
        skill_id = skill_response.json()["id"]
        version_response = await client.post(
            f"/admin-api/v1/official-skills/{skill_id}/versions",
            headers=headers,
            json={
                "instructions": "仅根据给定资料写作。",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
                "tool_policy": {"wechat_publish": False},
            },
        )
        assert version_response.status_code == 201, version_response.text
        version_id = version_response.json()["id"]

        patched = await client.patch(
            f"/admin-api/v1/skill-versions/{version_id}",
            headers=headers,
            json={"instructions": "仅根据给定资料写作，并明确标注无法核验的信息。"},
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["id"] == version_id
        assert patched.json()["version_no"] == 1
        versions = await client.get(
            f"/admin-api/v1/official-skills/{skill_id}/versions", headers=headers
        )
        assert len(versions.json()["items"]) == 1

        tested = await client.post(
            f"/admin-api/v1/skill-versions/{version_id}/test",
            headers=headers,
            json={"input": "根据脱敏的行业摘要生成两段内容。"},
        )
        assert tested.status_code == 200, tested.text
        assert tested.json()["passed"] is True
        assert tested.json()["simulated"] is True
        assert tested.json()["provider_request_id"] == "mock-local"

        published = await client.post(
            f"/admin-api/v1/skill-versions/{version_id}/publish", headers=headers
        )
        assert published.status_code == 200, published.text
        immutable = await client.patch(
            f"/admin-api/v1/skill-versions/{version_id}",
            headers=headers,
            json={"instructions": "不得覆盖已发布版本。"},
        )
        assert immutable.status_code == 409
    finally:
        pass


async def test_prompt_fixed_case_invokes_model_and_records_usage(
    app: FastAPI, client: AsyncClient
) -> None:
    try:
        headers = await _admin_headers(app, client)
        bundle = await client.post(
            "/admin-api/v1/prompt-bundles",
            headers=headers,
            json={"code": "article_writer", "name": "文章生成"},
        )
        assert bundle.status_code == 201, bundle.text
        version = await client.post(
            f"/admin-api/v1/prompt-bundles/{bundle.json()['id']}/versions",
            headers=headers,
            json={
                "system_template": "你是公众号文章助手，只能使用输入中的事实。",
                "operation_templates": {"default": "生成文章"},
                "variable_schema": {"type": "object"},
                "output_schema": {"type": "object"},
            },
        )
        assert version.status_code == 201, version.text
        tested = await client.post(
            f"/admin-api/v1/prompt-versions/{version.json()['id']}/test",
            headers=headers,
            json={"input": "使用一份脱敏摘要生成文章。"},
        )
        assert tested.status_code == 200, tested.text
        body = tested.json()
        assert body["passed"] is True
        assert body["provider_request_id"] == "mock-local"
        assert body["input_tokens"] > 0
        assert body["output_tokens"] > 0
    finally:
        pass


def _setting_sections() -> dict[str, dict[str, object]]:
    return {
        "home": {"welcome_message": "开始创作", "example_prompts": ["生成行业文章"]},
        "files": {
            "allowed_extensions": ["pdf", "docx"],
            "max_file_mb": 100,
            "link_fetch_enabled": False,
        },
        "ai": {
            "min_article_length": 300,
            "max_article_length": 20_000,
            "max_clarification_rounds": 3,
            "preference_enabled_by_default": True,
        },
        "articles": {"autosave_seconds": 10, "history_versions": 50},
        "wechat": {
            "wechat_draft_enabled": True,
            "wechat_publish_enabled": True,
            "max_article_images": 20,
        },
        "features": {"feature_flags": {"personal_skills": True}},
    }


async def test_system_settings_are_validated_and_published_as_one_six_section_bundle(
    app: FastAPI, client: AsyncClient
) -> None:
    try:
        headers = await _admin_headers(app, client)
        sections = _setting_sections()
        invalid = {**sections, "wechat": {**sections["wechat"], "wechat_draft_enabled": False}}
        validation = await client.post(
            "/admin-api/v1/system-settings/validate",
            headers=headers,
            json={"sections": invalid},
        )
        assert validation.status_code == 200
        assert validation.json()["passed"] is False

        created = await client.post(
            "/admin-api/v1/system-settings/bulk-drafts",
            headers=headers,
            json={"sections": sections},
        )
        assert created.status_code == 201, created.text
        setting_ids = [item["id"] for item in created.json()["items"]]
        assert len(setting_ids) == 6
        published = await client.post(
            "/admin-api/v1/system-settings/bulk-publish",
            headers=headers,
            json={"setting_ids": setting_ids, "reason": "pytest 发布完整设置"},
        )
        assert published.status_code == 200, published.text
        assert {item["section"] for item in published.json()["items"]} == set(sections)
        assert all(item["status"] == "published" for item in published.json()["items"])

        audits = await client.get(
            "/admin-api/v1/audit-logs?action=system_settings.bundle_publish",
            headers=headers,
        )
        assert audits.status_code == 200
        assert audits.json()["items"][0]["reason"] == "pytest 发布完整设置"
    finally:
        pass


async def test_ai_run_credit_cost_is_strict_but_missing_value_keeps_default(
    app: FastAPI, client: AsyncClient
) -> None:
    try:
        headers = await _admin_headers(app, client)
        compatible = await client.post(
            "/admin-api/v1/system-settings",
            headers=headers,
            json={"section": "ai", "values": {}},
        )
        assert compatible.status_code == 201, compatible.text

        for invalid in (-1, 10_001, 1.5, True, "1"):
            rejected = await client.post(
                "/admin-api/v1/system-settings",
                headers=headers,
                json={"section": "ai", "values": {"ai_run_credit_cost": invalid}},
            )
            assert rejected.status_code == 422, rejected.text
            assert rejected.json()["code"] == "SYSTEM_SETTINGS_INVALID"

        sections = _setting_sections()
        sections["ai"]["ai_run_credit_cost"] = True
        validation = await client.post(
            "/admin-api/v1/system-settings/validate",
            headers=headers,
            json={"sections": sections},
        )
        assert validation.status_code == 200
        assert validation.json()["passed"] is False
        assert "单次 AI 运行积分必须是 0—10000 之间的整数。" in validation.json()["checks"]

        rejected_bundle = await client.post(
            "/admin-api/v1/system-settings/bulk-drafts",
            headers=headers,
            json={"sections": sections},
        )
        assert rejected_bundle.status_code == 422
        assert rejected_bundle.json()["code"] == "SYSTEM_SETTINGS_INVALID"
    finally:
        pass


async def test_model_deployment_patch_supports_simplified_model_fields(
    app: FastAPI, client: AsyncClient
) -> None:
    os.environ["PYTEST_MODEL_PATCH_KEY"] = "model-patch-secret"
    try:
        headers = await _admin_headers(app, client)
        providers = []
        for code in ("model_patch_primary", "model_patch_secondary"):
            response = await client.post(
                "/admin-api/v1/model-providers",
                headers=headers,
                json={
                    "code": code,
                    "name": code,
                    "adapter": "openai_responses",
                    "base_url": "https://models.example/v1",
                    "secret_ref": "env:PYTEST_MODEL_PATCH_KEY",
                },
            )
            assert response.status_code == 201, response.text
            providers.append(response.json())

        created = await client.post(
            "/admin-api/v1/model-deployments",
            headers=headers,
            json={
                "provider_id": providers[0]["id"],
                "model_id": "model-before",
                "alias": "简化模型配置",
                "model_type": "chat",
            },
        )
        assert created.status_code == 201, created.text
        deployment_id = created.json()["id"]

        missing_provider = await client.patch(
            f"/admin-api/v1/model-deployments/{deployment_id}",
            headers=headers,
            json={"provider_id": "missing-provider"},
        )
        assert missing_provider.status_code == 404
        assert missing_provider.json()["code"] == "MODEL_PROVIDER_NOT_FOUND"

        patched = await client.patch(
            f"/admin-api/v1/model-deployments/{deployment_id}",
            headers=headers,
            json={
                "provider_id": providers[1]["id"],
                "model_id": "model-after",
                "model_type": "vision",
            },
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["provider_id"] == providers[1]["id"]
        assert patched.json()["model_id"] == "model-after"
        assert patched.json()["model_type"] == "vision"
    finally:
        os.environ.pop("PYTEST_MODEL_PATCH_KEY", None)


async def _create_model_configuration(
    client: AsyncClient, headers: dict[str, str], *, name: str = "Primary model"
) -> dict[str, Any]:
    response = await client.post(
        "/admin-api/v1/model-configurations",
        headers=headers,
        json={
            "name": name,
            "base_url": "https://models.example/v1",
            "secret_ref": "env:PYTEST_MODEL_CONFIGURATION_KEY",
            "model_id": "model-primary",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_model_configuration_create_is_atomic_and_never_returns_secret_reference(
    app: FastAPI, client: AsyncClient
) -> None:
    os.environ["PYTEST_MODEL_CONFIGURATION_KEY"] = "model-configuration-secret"
    try:
        headers = await _admin_headers(app, client)
        rejected = await client.post(
            "/admin-api/v1/model-configurations",
            headers=headers,
            json={
                "name": "Rejected model",
                "base_url": "https://models.example/v1",
                "secret_ref": "env:MISSING_MODEL_CONFIGURATION_KEY",
                "model_id": "model-rejected",
            },
        )
        assert rejected.status_code == 422
        assert rejected.json()["code"] == "MODEL_SECRET_UNAVAILABLE"
        async with app.state.database.session_maker() as session:
            assert await session.scalar(select(ModelProviderRecord)) is None
            assert await session.scalar(select(ModelDeployment)) is None

        created = await _create_model_configuration(client, headers)
        assert created["name"] == "Primary model"
        assert "alias" not in created
        assert created["adapter"] == "openai_chat_completions"
        assert created["model_type"] == "chat"
        assert created["secret_configured"] is True
        assert created["status"] == "draft"
        assert "secret_ref" not in created
        assert "PYTEST_MODEL_CONFIGURATION_KEY" not in str(created)

        listed = await client.get("/admin-api/v1/model-configurations", headers=headers)
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()["items"]] == [created["id"]]
        assert "secret_ref" not in listed.text
        assert "alias" not in listed.json()["items"][0]
    finally:
        os.environ.pop("PYTEST_MODEL_CONFIGURATION_KEY", None)


async def test_model_configuration_accepts_api_key_and_only_stores_ciphertext(
    app: FastAPI, client: AsyncClient
) -> None:
    headers = await _admin_headers(app, client)
    raw_key = "manus_test_secret_that_must_not_be_stored"
    response = await client.post(
        "/admin-api/v1/model-configurations",
        headers=headers,
        json={
            "name": "Manus Standard",
            "base_url": "https://api.manus.ai",
            "api_key": raw_key,
            "model_id": "standard",
            "adapter": "manus_v2",
        },
    )
    assert response.status_code == 201, response.text
    assert raw_key not in response.text
    async with app.state.database.session_maker() as session:
        provider = await session.scalar(select(ModelProviderRecord))
        assert provider is not None
        assert provider.secret_ref.startswith("encrypted:v1:")
        assert raw_key not in provider.secret_ref
        assert app.state.secret_provider.resolve(provider.secret_ref) == raw_key


async def test_new_model_must_keep_the_configuration_that_passed_preflight(
    app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def successful_probe(**_: Any) -> str:
        return "连接成功。"

    monkeypatch.setattr("app.api.admin.probe_model_provider", successful_probe)
    headers = await _admin_headers(app, client)
    payload = {
        "name": "Manus Lite",
        "base_url": "https://api.manus.ai",
        "api_key": "manus-secret",
        "model_id": "lite",
        "model_type": "chat",
        "adapter": "manus_v2",
    }
    tested = await client.post(
        "/admin-api/v1/model-configurations/test", headers=headers, json=payload
    )
    assert tested.status_code == 200, tested.text
    assert tested.json()["passed"] is True
    token = tested.json()["validation_token"]
    assert token and "manus-secret" not in token

    changed = await client.post(
        "/admin-api/v1/model-configurations",
        headers=headers,
        json={**payload, "model_id": "max", "validation_token": token},
    )
    assert changed.status_code == 422
    assert changed.json()["code"] == "MODEL_CONFIGURATION_CHANGED"

    created = await client.post(
        "/admin-api/v1/model-configurations",
        headers=headers,
        json={**payload, "validation_token": token},
    )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "available"
    assert created.json()["last_test_result"]["passed"] is True


async def test_model_configuration_delete_repairs_route_usage_and_removes_provider(
    app: FastAPI, client: AsyncClient
) -> None:
    os.environ["PYTEST_MODEL_CONFIGURATION_KEY"] = "model-configuration-secret"
    try:
        headers = await _admin_headers(app, client)
        created = await _create_model_configuration(client, headers)
        replacement = await _create_model_configuration(client, headers, name="Replacement model")
        async with app.state.database.session_maker() as session:
            session.add_all(
                [
                ModelRouteVersion(
                    purpose="fast_task",
                    version_no=1,
                    primary_deployment_id=created["id"],
                    fallback_deployment_ids=[replacement["id"]],
                    policy={},
                    status="published",
                ),
                ModelRouteVersion(
                    purpose="content_check",
                    version_no=1,
                    primary_deployment_id=replacement["id"],
                    fallback_deployment_ids=[created["id"]],
                    policy={},
                    status="published",
                ),
                ModelRouteVersion(
                    purpose="memory_summary",
                    version_no=1,
                    primary_deployment_id=created["id"],
                    fallback_deployment_ids=[],
                    policy={},
                    status="draft",
                ),
                ]
            )
            await session.commit()

        deleted = await client.delete(
            f"/admin-api/v1/model-configurations/{created['id']}", headers=headers
        )
        assert deleted.status_code == 204
        async with app.state.database.session_maker() as session:
            routes = list((await session.scalars(select(ModelRouteVersion))).all())
            assert {(route.purpose, route.primary_deployment_id) for route in routes} == {
                ("fast_task", replacement["id"]),
                ("content_check", replacement["id"]),
            }
            assert all(route.fallback_deployment_ids == [] for route in routes)
            assert await session.get(ModelDeployment, created["id"]) is None
            assert await session.get(ModelDeployment, replacement["id"]) is not None
            providers = list((await session.scalars(select(ModelProviderRecord))).all())
            assert len(providers) == 1
    finally:
        os.environ.pop("PYTEST_MODEL_CONFIGURATION_KEY", None)


async def test_model_configuration_patch_isolates_a_shared_provider(
    app: FastAPI, client: AsyncClient
) -> None:
    os.environ["PYTEST_MODEL_CONFIGURATION_KEY"] = "model-configuration-secret"
    try:
        headers = await _admin_headers(app, client)
        created = await _create_model_configuration(client, headers)
        async with app.state.database.session_maker() as session:
            target = await session.get(ModelDeployment, created["id"])
            assert target is not None
            original_provider_id = target.provider_id
            session.add(
                ModelDeployment(
                    provider_id=original_provider_id,
                    model_id="model-sibling",
                    alias="Sibling model",
                    model_type="chat",
                )
            )
            await session.commit()

        rejected = await client.patch(
            f"/admin-api/v1/model-configurations/{created['id']}",
            headers=headers,
            json={
                "base_url": "https://rejected.example/v1",
                "secret_ref": "env:MISSING_MODEL_CONFIGURATION_KEY",
            },
        )
        assert rejected.status_code == 422

        patched = await client.patch(
            f"/admin-api/v1/model-configurations/{created['id']}",
            headers=headers,
            json={
                "name": "Isolated model",
                "base_url": "https://isolated.example/v1",
                "model_id": "model-isolated",
            },
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["name"] == "Isolated model"
        assert patched.json()["model_id"] == "model-isolated"
        assert patched.json()["status"] == "draft"
        assert "secret_ref" not in patched.json()

        async with app.state.database.session_maker() as session:
            target = await session.get(ModelDeployment, created["id"])
            sibling = await session.scalar(
                select(ModelDeployment).where(ModelDeployment.alias == "Sibling model")
            )
            original_provider = await session.get(ModelProviderRecord, original_provider_id)
            assert target is not None and sibling is not None and original_provider is not None
            assert target.provider_id != original_provider_id
            assert sibling.provider_id == original_provider_id
            assert original_provider.base_url == "https://models.example/v1"
            isolated_provider = await session.get(ModelProviderRecord, target.provider_id)
            assert isolated_provider is not None
            assert isolated_provider.base_url == "https://isolated.example/v1"
            assert isolated_provider.name == "Isolated model"
            assert target.alias == "Isolated model"
    finally:
        os.environ.pop("PYTEST_MODEL_CONFIGURATION_KEY", None)


async def test_model_configuration_test_publish_and_shared_disable_are_coordinated(
    app: FastAPI, client: AsyncClient, monkeypatch: Any
) -> None:
    async def failing_probe(**kwargs: Any) -> str:
        del kwargs
        raise ProviderUnavailable("Model connection failed.")

    async def passing_probe(**kwargs: Any) -> str:
        assert kwargs["api_key"] == "model-configuration-secret"
        assert kwargs["model_id"] == "model-primary"
        return "Model connection passed."

    os.environ["PYTEST_MODEL_CONFIGURATION_KEY"] = "model-configuration-secret"
    try:
        headers = await _admin_headers(app, client)
        created = await _create_model_configuration(client, headers)
        async with app.state.database.session_maker() as session:
            target = await session.get(ModelDeployment, created["id"])
            assert target is not None
            original_provider_id = target.provider_id
            session.add(
                ModelDeployment(
                    provider_id=original_provider_id,
                    model_id="historical-sibling",
                    alias="Historical sibling",
                    model_type="chat",
                )
            )
            original_provider = await session.get(ModelProviderRecord, original_provider_id)
            assert original_provider is not None
            original_provider.last_tested_at = utcnow()
            original_provider.last_test_result = {
                "passed": True,
                "message": "Stale target result.",
                "configuration_id": target.id,
                "configuration_fingerprint": "stale-fingerprint",
            }
            await session.commit()
        premature = await client.patch(
            f"/admin-api/v1/model-configurations/{created['id']}/status",
            headers=headers,
            json={"status": "available"},
        )
        assert premature.status_code == 409
        assert premature.json()["code"] == "MODEL_CONFIGURATION_TEST_REQUIRED"

        monkeypatch.setattr("app.api.admin.probe_model_provider", failing_probe)
        failed = await client.post(
            f"/admin-api/v1/model-configurations/{created['id']}/test",
            headers=headers,
        )
        assert failed.status_code == 200, failed.text
        assert failed.json()["passed"] is False
        listed = await client.get("/admin-api/v1/model-configurations", headers=headers)
        failed_item = next(item for item in listed.json()["items"] if item["id"] == created["id"])
        assert failed_item["status"] == "draft"
        assert failed_item["last_test_result"]["passed"] is False
        rejected = await client.patch(
            f"/admin-api/v1/model-configurations/{created['id']}/status",
            headers=headers,
            json={"status": "available"},
        )
        assert rejected.status_code == 409

        monkeypatch.setattr("app.api.admin.probe_model_provider", passing_probe)
        tested = await client.post(
            f"/admin-api/v1/model-configurations/{created['id']}/test",
            headers=headers,
        )
        assert tested.status_code == 200, tested.text
        assert tested.json()["passed"] is True
        async with app.state.database.session_maker() as session:
            deployment = await session.get(ModelDeployment, created["id"])
            assert deployment is not None
            provider = await session.get(ModelProviderRecord, deployment.provider_id)
            original_provider = await session.get(ModelProviderRecord, original_provider_id)
            assert provider is not None
            assert original_provider is not None
            assert deployment.provider_id != original_provider_id
            assert deployment.status == "available"
            assert provider.status == "active"
            assert original_provider.status == "draft"
            assert original_provider.last_test_result["message"] == "Stale target result."
            assert provider.last_test_result["configuration_id"] == deployment.id

        listed = await client.get("/admin-api/v1/model-configurations", headers=headers)
        assert listed.status_code == 200
        historical = next(
            item for item in listed.json()["items"] if item["name"] == "Historical sibling"
        )
        assert historical["last_tested_at"] is None
        assert historical["last_test_result"] == {}

        published = await client.patch(
            f"/admin-api/v1/model-configurations/{created['id']}/status",
            headers=headers,
            json={"status": "available"},
        )
        assert published.status_code == 200, published.text
        assert published.json()["status"] == "available"
        async with app.state.database.session_maker() as session:
            deployment = await session.get(ModelDeployment, created["id"])
            assert deployment is not None
            provider = await session.get(ModelProviderRecord, deployment.provider_id)
            assert provider is not None
            assert deployment.status == "available"
            assert provider.status == "active"
            session.add(
                ModelDeployment(
                    provider_id=provider.id,
                    model_id="model-sibling",
                    alias="Active sibling",
                    model_type="chat",
                    status="available",
                )
            )
            await session.commit()

        disabled = await client.patch(
            f"/admin-api/v1/model-configurations/{created['id']}/status",
            headers=headers,
            json={"status": "disabled"},
        )
        assert disabled.status_code == 200, disabled.text
        assert disabled.json()["status"] == "disabled"
        async with app.state.database.session_maker() as session:
            deployment = await session.get(ModelDeployment, created["id"])
            assert deployment is not None
            provider = await session.get(ModelProviderRecord, deployment.provider_id)
            sibling = await session.scalar(
                select(ModelDeployment).where(ModelDeployment.alias == "Active sibling")
            )
            assert provider is not None and sibling is not None
            assert deployment.status == "disabled"
            assert sibling.status == "available"
            assert provider.status == "active"
    finally:
        os.environ.pop("PYTEST_MODEL_CONFIGURATION_KEY", None)


async def test_layout_agent_route_can_be_configured_tested_and_published(
    app: FastAPI, client: AsyncClient, monkeypatch: Any
) -> None:
    class LayoutRouteModel:
        valid = False

        def __init__(self, **_: Any) -> None:
            pass

        async def generate(self, **kwargs: Any) -> ModelResult:
            assert kwargs["purpose"] == "layout_extraction"
            assert "只返回一个 JSON 对象" in kwargs["prompt"]
            return ModelResult(
                text=(
                    '{"style_tokens":{"body":{"font_size":16,"color":"#1f2937"}},'
                    '"confidence":0.9,"module_evidence":{"body":["block-1"]}}'
                    if self.valid
                    else '{"style_tokens":{},"confidence":0.0,"module_evidence":{}}'
                ),
                structured={
                    "type": "doc",
                    "content": [{"type": "paragraph", "content": []}],
                },
                input_tokens=40,
                output_tokens=20,
                provider_request_id="layout-route-test",
                simulated=False,
            )

    os.environ["PYTEST_LAYOUT_AGENT_KEY"] = "layout-agent-secret"
    monkeypatch.setattr("app.model_gateway.OpenAICompatibleModelProvider", LayoutRouteModel)
    try:
        headers = await _admin_headers(app, client)
        async with app.state.database.session_maker() as session:
            provider = ModelProviderRecord(
                code="layout-agent-provider",
                name="排版智能体供应商",
                adapter="openai_responses",
                base_url="https://layout-agent.example/v1",
                secret_ref="env:PYTEST_LAYOUT_AGENT_KEY",
                status="active",
            )
            session.add(provider)
            await session.flush()
            deployment = ModelDeployment(
                provider_id=provider.id,
                model_id="layout-vision-model",
                alias="排版视觉模型",
                model_type="vision",
                capabilities=["vision", "structured_output"],
                status="available",
            )
            session.add(deployment)
            await session.commit()
            deployment_id = deployment.id

        created = await client.post(
            "/admin-api/v1/model-routes",
            headers=headers,
            json={
                "purpose": "layout_extraction",
                "primary_deployment_id": deployment_id,
                "fallback_deployment_ids": [],
                "policy": {
                    "display_name": "公众号排版学习智能体",
                    "timeout_ms": 120000,
                    "max_attempts": 2,
                },
            },
        )
        assert created.status_code == 201, created.text
        route_id = created.json()["id"]

        listed = await client.get(
            "/admin-api/v1/model-routes?purpose=layout_extraction", headers=headers
        )
        assert listed.status_code == 200, listed.text
        assert [item["id"] for item in listed.json()["items"]] == [route_id]

        rejected = await client.post(f"/admin-api/v1/model-routes/{route_id}/test", headers=headers)
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["passed"] is False
        assert "未通过 StyleToken 结构校验" in rejected.json()["message"]

        LayoutRouteModel.valid = True
        tested = await client.post(f"/admin-api/v1/model-routes/{route_id}/test", headers=headers)
        assert tested.status_code == 200, tested.text
        assert tested.json()["passed"] is True
        assert tested.json()["provider_request_id"] == "layout-route-test"
        assert "排版智能体固定案例通过" in tested.json()["message"]

        published = await client.post(
            f"/admin-api/v1/model-routes/{route_id}/publish", headers=headers
        )
        assert published.status_code == 200, published.text
        assert published.json()["status"] == "published"
    finally:
        os.environ.pop("PYTEST_LAYOUT_AGENT_KEY", None)


async def test_external_knowledge_source_requires_test_before_enable_and_queues_sync(
    app: FastAPI,
    client: AsyncClient,
    monkeypatch: Any,
) -> None:
    class FakeLexiangProvider:
        def __init__(self, *, app_key: str, app_secret: str) -> None:
            assert app_key == "pytest-app-key"
            assert app_secret == "pytest-secret-value"

        async def test_connection(self) -> None:
            return None

    try:
        headers = await _admin_headers(app, client)
        user_session = await register_and_login(client, "lexiang-owner@example.com")
        owner_id = user_session["registered_user"]["id"]
        os.environ["PYTEST_LEXIANG_SECRET"] = "pytest-secret-value"

        created = await client.post(
            "/admin-api/v1/external-knowledge-sources",
            headers=headers,
            json={
                "name": "公司知识空间",
                "app_key": "pytest-app-key",
                "secret_ref": "env:PYTEST_LEXIANG_SECRET",
                "targets": [{"type": "space", "id": "space-1"}],
                "owner_staff_ids": {owner_id: "staff-1001"},
                "sync_owner_id": owner_id,
            },
        )
        assert created.status_code == 201, created.text
        source_id = created.json()["id"]
        assert created.json()["secret_configured"] is True
        assert "secret_ref" not in created.json()

        premature_enable = await client.patch(
            f"/admin-api/v1/external-knowledge-sources/{source_id}",
            headers=headers,
            json={"status": "active", "reason": "pytest 尝试提前启用"},
        )
        assert premature_enable.status_code == 409
        assert premature_enable.json()["code"] == "LEXIANG_TEST_REQUIRED"

        monkeypatch.setattr("app.api.admin.LexiangKnowledgeProvider", FakeLexiangProvider)
        tested = await client.post(
            f"/admin-api/v1/external-knowledge-sources/{source_id}/test",
            headers=headers,
        )
        assert tested.status_code == 200, tested.text
        assert tested.json()["passed"] is True
        enabled = await client.patch(
            f"/admin-api/v1/external-knowledge-sources/{source_id}",
            headers=headers,
            json={"status": "active", "reason": "pytest 测试通过后启用"},
        )
        assert enabled.status_code == 200, enabled.text
        assert enabled.json()["status"] == "active"

        queued = await client.post(
            f"/admin-api/v1/external-knowledge-sources/{source_id}/sync",
            headers=headers,
            json={"reason": "pytest 请求乐享增量同步"},
        )
        assert queued.status_code == 202, queued.text
        assert queued.json()["job_type"] == "external_knowledge_sync"
        assert queued.json()["queue"] == "sync"
        async with app.state.database.session_maker() as session:
            job = await session.scalar(select(JobRecord).where(JobRecord.id == queued.json()["id"]))
            outbox = await session.scalar(
                select(OutboxEvent).where(
                    OutboxEvent.aggregate_id == source_id,
                    OutboxEvent.event_type == "external_knowledge.sync.requested",
                )
            )
            assert job is not None
            assert job.owner_id == owner_id
            assert outbox is not None

        audits = await client.get(
            "/admin-api/v1/audit-logs?action=external_knowledge_source.sync_request",
            headers=headers,
        )
        assert audits.status_code == 200
        assert audits.json()["items"][0]["reason"] == "pytest 请求乐享增量同步"
    finally:
        os.environ.pop("PYTEST_LEXIANG_SECRET", None)

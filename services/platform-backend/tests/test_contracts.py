from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.api.contracts import TiptapDocument
from app.config import Settings
from app.domains.layout import (
    merge_learned_style_tokens,
    validate_source_url,
    validate_style_tokens,
)
from app.errors import ApiError
from app.worker_tasks import EVENT_TASKS


def test_tiptap_contract_rejects_non_canonical_tree_shapes() -> None:
    valid = TiptapDocument.model_validate(
        {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "attrs": {"module": "highlight"},
                    "content": [{"type": "text", "text": "重点"}],
                }
            ],
        }
    )
    assert valid.content[0].attrs is not None
    assert valid.content[0].attrs.module == "highlight"

    with pytest.raises(ValueError):
        TiptapDocument.model_validate(
            {
                "type": "doc",
                "content": [{"type": "text", "text": "根节点不能直接包含文本"}],
            }
        )
    with pytest.raises(ValueError):
        TiptapDocument.model_validate(
            {
                "type": "doc",
                "content": [
                    {
                        "type": "bulletList",
                        "content": [{"type": "paragraph", "content": []}],
                    }
                ],
            }
        )


def test_openapi_exposes_separate_user_admin_and_callback_boundaries(app: FastAPI) -> None:
    schema = app.openapi()
    serialized_schema = str(schema).lower()
    paths = set(schema["paths"])
    assert len(paths) >= 90
    assert "/api/v1/auth/login" in paths
    assert "/admin-api/v1/auth/login" in paths
    assert "/callbacks/v1/wechat/operations" in paths
    assert "totp" not in serialized_schema
    assert "dynamic verification" not in serialized_schema
    assert all(
        path.startswith(("/api/v1", "/admin-api/v1", "/callbacks", "/health")) for path in paths
    )


def test_openapi_success_and_error_contracts_are_generator_safe(app: FastAPI) -> None:
    schema = app.openapi()
    assert not [
        name
        for name, component in schema["components"]["schemas"].items()
        if component.get("additionalProperties") is True
    ]
    for path, path_item in schema["paths"].items():
        if not path.startswith(("/api/v1", "/admin-api/v1", "/callbacks/v1")):
            continue
        for method, operation in path_item.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            for status, response in operation["responses"].items():
                if not status.startswith("2"):
                    continue
                for content in response.get("content", {}).values():
                    assert content.get("schema", {}).get("additionalProperties") is not True
            assert operation["responses"]["422"]["content"]["application/json"]["schema"] == {
                "$ref": "#/components/schemas/ErrorResponse"
            }

    sse = schema["paths"]["/api/v1/ai-runs/{run_id}/events"]["get"]
    assert set(sse["responses"]["200"]["content"]) == {"text/event-stream"}
    idem = schema["paths"]["/api/v1/tasks"]["post"]["parameters"]
    assert next(item for item in idem if item["name"] == "Idempotency-Key")["required"]
    revision_idem = schema["paths"]["/api/v1/articles/{article_id}/revisions"]["post"]["parameters"]
    assert next(item for item in revision_idem if item["name"] == "Idempotency-Key")["required"]
    upload_idem = schema["paths"]["/api/v1/uploads"]["post"]["parameters"]
    assert next(item for item in upload_idem if item["name"] == "Idempotency-Key")["required"]

    tokens = schema["components"]["schemas"]["StyleTokenPayload"]
    assert tokens["additionalProperties"] is False
    assert set(tokens["properties"]) == {
        "table_header",
        "table_cell",
        "title",
        "lead",
        "heading_marker",
        "heading1",
        "heading2",
        "body",
        "highlight",
        "quote",
        "list",
        "caption",
        "divider",
    }
    assert schema["components"]["schemas"]["TiptapDocument-Input"]["additionalProperties"] is False
    assert schema["components"]["schemas"]["TiptapDocument-Output"]["additionalProperties"] is False
    for name in (
        "TiptapNode-Output",
        "TiptapNodeAttrs",
        "TiptapMark",
        "TiptapMarkAttrs",
        "MessageContent",
        "MessageAttachment",
        "UploadPartCompletion",
    ):
        assert schema["components"]["schemas"][name]["additionalProperties"] is False
    upload_complete = schema["components"]["schemas"]["UploadComplete"]
    assert "completed_parts" in upload_complete["required"]
    assert set(schema["components"]["schemas"]["UploadPartCompletion"]["required"]) == {
        "part_number",
        "etag",
    }
    for path in (
        "/api/v1/projects",
        "/api/v1/tasks",
        "/api/v1/tasks/{task_id}/messages",
        "/api/v1/library-items",
        "/api/v1/skills",
        "/api/v1/preferences",
        "/api/v1/layout-templates",
        "/api/v1/official-accounts",
        "/api/v1/articles/{article_id}/versions",
    ):
        operation = schema["paths"][path]["get"]
        parameters = {parameter["name"] for parameter in operation["parameters"]}
        assert {"cursor", "limit"} <= parameters
        response_ref = operation["responses"]["200"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        response_schema = schema["components"]["schemas"][response_ref.rsplit("/", 1)[-1]]
        assert "next_cursor" in response_schema["required"]
    task_detail_schema = schema["components"]["schemas"]["TaskDetailResponse"]
    assert "messages_next_cursor" in task_detail_schema["required"]
    assert "latest_ai_run" in task_detail_schema["required"]
    node_attrs = schema["components"]["schemas"]["TiptapNodeAttrs"]
    assert node_attrs["additionalProperties"] is False
    assert set(node_attrs["properties"]["module"]["anyOf"][0]["enum"]) == {
        "lead",
        "body",
        "highlight",
        "caption",
    }
    article_create = schema["components"]["schemas"]["ArticleCreate"]
    assert article_create["properties"]["content"]["$ref"].endswith("/TiptapDocument-Input")

    refresh_parameters = schema["paths"]["/api/v1/auth/refresh"]["post"]["parameters"]
    assert (
        next(item for item in refresh_parameters if item["name"] == "ua_session")["required"]
        is False
    )
    assert (
        next(item for item in refresh_parameters if item["name"] == "X-CSRF-Token")["required"]
        is False
    )
    assert (
        "Set-Cookie" in schema["paths"]["/api/v1/auth/login"]["post"]["responses"]["200"]["headers"]
    )
    assert "requestBody" in schema["paths"]["/api/v1/auth/logout"]["post"]


async def test_web_csrf_cookie_is_readable_from_spa_routes(client: AsyncClient) -> None:
    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "csrf-contract@example.com",
            "display_name": "CSRF contract",
            "password": "correct-horse-battery-staple",
            "accepted_terms": True,
        },
    )
    assert registered.status_code == 201
    login = await client.post(
        "/api/v1/auth/login",
        json={
            "identifier": "csrf-contract@example.com",
            "password": "correct-horse-battery-staple",
            "platform": "web",
        },
    )
    assert login.status_code == 200
    assert login.json()["expires_in"] == 604_800
    cookies = login.headers.get_list("set-cookie")
    csrf = next(value for value in cookies if value.startswith("ua_csrf="))
    session = next(value for value in cookies if value.startswith("ua_session="))
    assert "Path=/;" in csrf
    assert "Max-Age=604800;" in csrf
    assert "Path=/api/v1/auth;" in session
    assert "Max-Age=604800;" in session

    missing_csrf = await client.post(
        "/api/v1/auth/logout", headers={"Authorization": f"Bearer {login.json()['access_token']}"}
    )
    assert missing_csrf.status_code == 403
    logged_out = await client.post(
        "/api/v1/auth/logout",
        headers={
            "Authorization": f"Bearer {login.json()['access_token']}",
            "X-CSRF-Token": client.cookies["ua_csrf"],
        },
    )
    assert logged_out.status_code == 204


@pytest.mark.parametrize(
    "url",
    [
        "http://mp.weixin.qq.com/s/demo",
        "https://mp.weixin.qq.com.evil.example/s/demo",
        "https://user@mp.weixin.qq.com/s/demo",
        "https://127.0.0.1/s/demo",
    ],
)
def test_layout_source_url_rejects_ssrf_variants(url: str) -> None:
    with pytest.raises(ApiError) as raised:
        validate_source_url(url)
    assert raised.value.code == "LAYOUT_SOURCE_URL_INVALID"


def test_style_token_whitelist_rejects_executable_css() -> None:
    with pytest.raises(ApiError) as raised:
        validate_style_tokens({"body": {"background": "red;url(javascript:alert(1))"}})
    assert raised.value.code == "STYLE_TOKEN_INVALID"

    with pytest.raises(ApiError) as raised_border:
        validate_style_tokens({"quote": {"border_left": "1px solid #fff;display:none"}})
    assert raised_border.value.code == "STYLE_TOKEN_INVALID"

    with pytest.raises(ApiError) as raised_css_unit:
        validate_style_tokens({"body": {"font_size": "16px"}})
    assert raised_css_unit.value.details["path"] == "style_tokens.body.font_size"


def test_learned_body_bold_requires_bold_baseline_evidence() -> None:
    merged = merge_learned_style_tokens(
        {"body": {"font_size": 16, "line_height": 1.8, "color": "#595959"}},
        {"body": {"font_weight": 700, "line_height": 2}},
    )
    assert "font_weight" not in merged["body"]
    assert merged["body"] == {
        "font_size": 16,
        "line_height": 2,
        "color": "#595959",
    }


def test_production_rejects_sqlite() -> None:
    with pytest.raises(RuntimeError):
        Settings(environment="production").validate()


def test_production_allows_public_wechat_layout_without_layout_secret() -> None:
    Settings(
        environment="production",
        database_url="postgresql+asyncpg://wechat:secret@db.example/wechat",
        retrieval_database_url="postgresql+asyncpg://wechat:secret@retrieval.example/wechat",
        token_secret="a-production-token-secret-longer-than-32-characters",
        model_secret_master_key="a-different-model-secret-longer-than-32-chars",
        cookie_secure=True,
        model_provider_mode="openai_compatible",
        model_api_base="https://model.example/v1",
        model_api_key_ref="env:MODEL_API_KEY",
        model_name="production-model",
        embedding_provider_mode="openai_compatible",
        embedding_api_base="https://model.example/v1",
        embedding_api_key_ref="env:MODEL_API_KEY",
        embedding_model="embedding-model",
        rerank_provider_mode="http",
        rerank_api_base="https://rerank.example/v1",
        rerank_api_key_ref="env:RERANK_KEY",
        rerank_model="rerank-model",
        content_safety_provider_mode="openai",
        content_safety_api_base="https://model.example/v1",
        content_safety_api_key_ref="env:MODEL_API_KEY",
        verification_provider_mode="http",
        verification_service_url="https://verification.example",
        verification_secret_ref="env:VERIFICATION_SECRET",
        storage_provider_mode="s3",
        object_storage_endpoint="https://s3.example",
        object_storage_bucket="quarantine",
        object_storage_access_key_ref="env:S3_ACCESS_KEY",
        object_storage_secret_key_ref="env:S3_SECRET_KEY",
        document_provider_mode="http",
        document_service_url="https://documents.example",
        document_service_secret_ref="env:DOCUMENT_SECRET",
        layout_provider_mode="wechat_public",
        wechat_provider_mode="http_gateway",
        wechat_gateway_url="https://wechat-gateway.example",
        wechat_gateway_secret_ref="env:WECHAT_GATEWAY_SECRET",
        allowed_origins=("https://app.example.com",),
    ).validate()


def test_production_allows_only_https_and_exact_ios_webview_origin() -> None:
    base = {
        "environment": "production",
        "database_url": "postgresql+asyncpg://wechat:secret@db.example/wechat",
        "retrieval_database_url": (
            "postgresql+asyncpg://wechat:secret@retrieval.example/wechat_retrieval"
        ),
        "token_secret": "a-production-token-secret-longer-than-32-characters",
        "model_secret_master_key": "a-different-model-secret-longer-than-32-chars",
        "cookie_secure": True,
        "auto_create_schema": False,
        "model_provider_mode": "openai_compatible",
        "model_api_base": "https://model.example/v1",
        "model_api_key_ref": "env:MODEL_API_KEY",
        "model_name": "production-model",
        "embedding_provider_mode": "openai_compatible",
        "embedding_api_base": "https://model.example/v1",
        "embedding_api_key_ref": "env:MODEL_API_KEY",
        "embedding_model": "embedding-model",
        "rerank_provider_mode": "http",
        "rerank_api_base": "https://rerank.example/v1",
        "rerank_api_key_ref": "env:RERANK_KEY",
        "rerank_model": "rerank-model",
        "content_safety_provider_mode": "openai",
        "content_safety_api_base": "https://model.example/v1",
        "content_safety_api_key_ref": "env:MODEL_API_KEY",
        "verification_provider_mode": "http",
        "verification_service_url": "https://verification.example",
        "verification_secret_ref": "env:VERIFICATION_SECRET",
        "storage_provider_mode": "s3",
        "object_storage_endpoint": "https://s3.example",
        "object_storage_bucket": "quarantine",
        "object_storage_access_key_ref": "env:S3_ACCESS_KEY",
        "object_storage_secret_key_ref": "env:S3_SECRET_KEY",
        "document_provider_mode": "http",
        "document_service_url": "https://documents.example",
        "document_service_secret_ref": "env:DOCUMENT_SECRET",
        "layout_provider_mode": "http",
        "layout_service_url": "https://layouts.example",
        "layout_service_secret_ref": "env:LAYOUT_SECRET",
        "wechat_provider_mode": "http_gateway",
        "wechat_gateway_url": "https://wechat-gateway.example",
        "wechat_gateway_secret_ref": "env:WECHAT_GATEWAY_SECRET",
    }
    Settings(
        **base,
        allowed_origins=("https://app.example.com", "capacitor://localhost"),
    ).validate()
    for invalid_origin in (
        "*",
        "http://app.example.com",
        "capacitor://example.com",
        "capacitor://localhost/",
    ):
        with pytest.raises(RuntimeError):
            Settings(**base, allowed_origins=(invalid_origin,)).validate()


async def test_capacitor_origin_passes_cors_preflight(client: AsyncClient) -> None:
    response = await client.options(
        "/api/v1/tasks",
        headers={
            "Origin": "capacitor://localhost",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": (
                "authorization,content-type,idempotency-key,last-event-id"
            ),
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "capacitor://localhost"
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "last-event-id" in response.headers["access-control-allow-headers"].lower()


def test_outbox_has_a_non_resubmitting_wechat_reconciliation_route() -> None:
    task_name, payload_key = EVENT_TASKS["wechat.operation.reconcile.requested"]
    assert task_name == "app.worker_tasks.reconcile_wechat_operation_task"
    assert payload_key == "operation_id"

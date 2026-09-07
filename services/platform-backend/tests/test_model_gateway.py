from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI

from app.config import Settings
from app.model_gateway import (
    FrozenEmbeddingRouteProvider,
    FrozenRerankRouteProvider,
    ModelRouteExhausted,
    active_route_snapshot,
    freeze_deployment_snapshot,
    freeze_preferred_deployment_snapshot,
    generate_with_frozen_route,
)
from app.models import ModelDeployment, ModelProviderRecord, ModelRouteVersion
from app.providers import (
    EmbeddingResult,
    ModelContractViolation,
    ModelResult,
    ProviderAuthenticationError,
    ProviderTransientError,
    ProviderUnavailable,
    RerankResult,
)


class StaticSecrets:
    def resolve(self, reference: str) -> str:
        return {"env:PRIMARY": "primary-key", "env:FALLBACK": "fallback-key"}[reference]


async def test_published_route_freezes_execution_config_and_uses_ordered_fallback(
    app: FastAPI,
    monkeypatch: Any,
) -> None:
    async with app.state.database.session_maker() as session:
        primary_provider = ModelProviderRecord(
            code="primary-provider",
            name="主供应商",
            adapter="openai_responses",
            base_url="https://primary.example/v1",
            secret_ref="env:PRIMARY",
            status="active",
        )
        fallback_provider = ModelProviderRecord(
            code="fallback-provider",
            name="备用供应商",
            adapter="openai_chat_completions",
            base_url="https://fallback.example/v1",
            secret_ref="env:FALLBACK",
            status="active",
        )
        session.add_all([primary_provider, fallback_provider])
        await session.flush()
        primary = ModelDeployment(
            provider_id=primary_provider.id,
            model_id="primary-fail",
            alias="主模型",
            model_type="chat",
            capabilities=["structured_output"],
            context_window=128_000,
            max_output_tokens=8_192,
            input_cost=1,
            output_cost=2,
            status="available",
        )
        fallback = ModelDeployment(
            provider_id=fallback_provider.id,
            model_id="fallback-ok",
            alias="备用模型",
            model_type="chat",
            capabilities=["structured_output"],
            context_window=128_000,
            max_output_tokens=8_192,
            input_cost=3,
            output_cost=4,
            status="available",
        )
        session.add_all([primary, fallback])
        await session.flush()
        route = ModelRouteVersion(
            purpose="article_generation",
            version_no=1,
            primary_deployment_id=primary.id,
            fallback_deployment_ids=[fallback.id],
            policy={"max_attempts": 2, "timeout_ms": 12_000},
            status="published",
        )
        session.add(route)
        await session.flush()
        snapshot = await active_route_snapshot(
            session,
            purpose="article_generation",
            settings=Settings(mock_external_services=True),
        )
        assert [item["deployment_id"] for item in snapshot["execution_configs"]] == [
            primary.id,
            fallback.id,
        ]
        primary_provider.base_url = "https://changed-after-run.example/v1"
        assert snapshot["execution_configs"][0]["base_url"] == "https://primary.example/v1"

        calls: list[tuple[str, str, str, float]] = []

        class FakeOpenAIModel:
            def __init__(
                self,
                *,
                api_base: str,
                api_key: str,
                model: str,
                api_style: str,
                timeout_seconds: float,
                max_output_tokens: int | None = None,
            ) -> None:
                self.model = model
                calls.append((api_base, api_key, api_style, timeout_seconds))
                assert max_output_tokens in {None, 8_192}

            async def generate(
                self, *, purpose: str, prompt: str, context: dict[str, Any]
            ) -> ModelResult:
                del purpose, prompt, context
                if self.model == "primary-fail":
                    raise ProviderAuthenticationError("primary credential rejected")
                return ModelResult(
                    text="备用模型结果",
                    structured={"type": "doc", "content": []},
                    input_tokens=10,
                    output_tokens=5,
                    provider_request_id="fallback-request",
                    simulated=False,
                )

        monkeypatch.setattr("app.model_gateway.OpenAICompatibleModelProvider", FakeOpenAIModel)
        routed = await generate_with_frozen_route(
            snapshot=snapshot,
            fallback_model=FakeOpenAIModel(
                api_base="https://unused.example",
                api_key="unused",
                model="unused",
                api_style="responses",
                timeout_seconds=1,
            ),
            secrets=StaticSecrets(),
            purpose="article_generation",
            prompt="生成文章",
            context={},
            default_timeout_seconds=120,
            session=session,
        )
        assert routed.result.text == "备用模型结果"
        assert [attempt.status for attempt in routed.attempts] == [
            "authentication_failed",
            "completed",
        ]
        assert primary.status == "disabled"
        assert routed.attempts[1].deployment_id == fallback.id
        assert routed.attempts[1].cost > 0
        assert calls[1:] == [
            ("https://primary.example/v1", "primary-key", "responses", 12.0),
            ("https://fallback.example/v1", "fallback-key", "chat_completions", 12.0),
        ]
        await session.rollback()


async def test_transient_failure_gets_one_bounded_retry_before_fallback(
    monkeypatch: Any,
) -> None:
    calls = 0

    class FlakyModel:
        def __init__(self, **_: Any) -> None:
            pass

        async def generate(self, **_: Any) -> ModelResult:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ProviderTransientError("temporary connection failure")
            return ModelResult(
                text="重试成功",
                structured={"type": "doc", "content": []},
                input_tokens=1,
                output_tokens=1,
                provider_request_id="retry-success",
                simulated=False,
            )

    monkeypatch.setattr("app.model_gateway.OpenAICompatibleModelProvider", FlakyModel)
    snapshot = {
        "policy": {"max_attempts": 2},
        "execution_configs": [
            {
                "deployment_id": "deployment-1",
                "adapter": "openai_responses",
                "base_url": "https://models.example/v1",
                "secret_ref": "env:PRIMARY",
                "model_id": "flaky-model",
                "input_cost": "0",
                "output_cost": "0",
            }
        ],
    }
    routed = await generate_with_frozen_route(
        snapshot=snapshot,
        fallback_model=FlakyModel(),
        secrets=StaticSecrets(),
        purpose="article_generation",
        prompt="生成文章",
        context={},
        default_timeout_seconds=120,
    )
    assert routed.result.text == "重试成功"
    assert [attempt.status for attempt in routed.attempts] == [
        "transient_failed",
        "completed",
    ]
    assert calls == 2


async def test_selected_deployment_freezes_only_the_user_choice(app: FastAPI) -> None:
    async with app.state.database.session_maker() as session:
        providers = [
            ModelProviderRecord(
                code=f"selected-fallback-provider-{index}",
                name=f"供应商 {index}",
                adapter="openai_chat_completions",
                base_url=f"https://model-{index}.example/v1",
                secret_ref="env:PRIMARY",
                status="active",
            )
            for index in range(3)
        ]
        session.add_all(providers)
        await session.flush()
        deployments = [
            ModelDeployment(
                provider_id=provider.id,
                model_id=f"model-{index}",
                alias=f"模型 {index}",
                model_type="chat",
                capabilities=["structured_output"],
                context_window=128_000,
                max_output_tokens=8_192,
                input_cost=0,
                output_cost=0,
                status="available",
            )
            for index, provider in enumerate(providers)
        ]
        session.add_all(deployments)
        await session.flush()

        snapshot = await freeze_deployment_snapshot(
            session,
            deployment_id=deployments[0].id,
            purpose="article_generation",
        )

        assert snapshot["primary_deployment_id"] == deployments[0].id
        assert snapshot["fallback_deployment_ids"] == []
        assert snapshot["policy"] == {
            "timeout_ms": 240_000,
            "max_attempts": 2,
            "retry_current": True,
            "max_retry_after_seconds": 5,
        }
        assert [item["deployment_id"] for item in snapshot["execution_configs"]] == [
            deployments[0].id
        ]
        await session.rollback()


async def test_preferred_deployment_uses_published_route_as_failover(app: FastAPI) -> None:
    async with app.state.database.session_maker() as session:
        provider = ModelProviderRecord(
            code="preferred-route-provider",
            name="首选路由供应商",
            adapter="openai_chat_completions",
            base_url="https://models.example/v1",
            secret_ref="env:PRIMARY",
            status="active",
        )
        session.add(provider)
        await session.flush()
        preferred = ModelDeployment(
            provider_id=provider.id,
            model_id="preferred-model",
            alias="首选模型",
            model_type="chat",
            capabilities=[],
            context_window=128_000,
            max_output_tokens=8_192,
            input_cost=0,
            output_cost=0,
            status="available",
        )
        platform_primary = ModelDeployment(
            provider_id=provider.id,
            model_id="platform-model",
            alias="平台模型",
            model_type="chat",
            capabilities=[],
            context_window=128_000,
            max_output_tokens=8_192,
            input_cost=0,
            output_cost=0,
            status="available",
        )
        session.add_all([preferred, platform_primary])
        await session.flush()
        session.add(
            ModelRouteVersion(
                purpose="article_generation",
                version_no=1,
                primary_deployment_id=platform_primary.id,
                fallback_deployment_ids=[],
                policy={"max_attempts": 2},
                status="published",
            )
        )
        await session.flush()

        snapshot = await freeze_preferred_deployment_snapshot(
            session,
            deployment_id=preferred.id,
            purpose="article_generation",
            settings=Settings(),
        )

        assert snapshot["preferred_by_user"] is True
        assert snapshot["selected_by_user"] is False
        assert snapshot["fallback_deployment_ids"] == [platform_primary.id]
        assert [item["deployment_id"] for item in snapshot["execution_configs"]] == [
            preferred.id,
            platform_primary.id,
        ]
        assert snapshot["policy"]["max_attempts"] == 3
        await session.rollback()


async def test_user_selected_snapshot_retries_same_model_but_never_uses_fallback(
    monkeypatch: Any,
) -> None:
    calls: list[str] = []

    class FailingSelectedModel:
        def __init__(self, *, model: str, **_: Any) -> None:
            self.model = model

        async def generate(self, **_: Any) -> ModelResult:
            calls.append(self.model)
            if self.model == "selected-model":
                raise ProviderTransientError("selected model failed")
            return ModelResult("不应返回", {}, 1, 1, "fallback", False)

    monkeypatch.setattr("app.model_gateway.OpenAICompatibleModelProvider", FailingSelectedModel)
    base_config = {
        "adapter": "openai_chat_completions",
        "base_url": "https://models.example/v1",
        "secret_ref": "env:PRIMARY",
        "input_cost": "0",
        "output_cost": "0",
    }

    with pytest.raises(ModelRouteExhausted):
        await generate_with_frozen_route(
            snapshot={
                "selected_by_user": True,
                "policy": {"max_attempts": 3, "retry_current": True},
                "execution_configs": [
                    {
                        **base_config,
                        "deployment_id": "selected",
                        "model_id": "selected-model",
                    },
                    {
                        **base_config,
                        "deployment_id": "fallback",
                        "model_id": "fallback-model",
                    },
                ],
            },
            fallback_model=FailingSelectedModel(model="unused"),
            secrets=StaticSecrets(),
            purpose="article_generation",
            prompt="生成文章",
            context={},
            default_timeout_seconds=120,
        )

    assert calls == ["selected-model", "selected-model"]


async def test_manus_task_create_is_not_retried_without_provider_idempotency(
    monkeypatch: Any,
) -> None:
    calls = 0

    class FailingManus:
        def __init__(self, **_: Any) -> None:
            pass

        async def generate(self, **_: Any) -> ModelResult:
            nonlocal calls
            calls += 1
            raise ProviderTransientError("uncertain task create")

    monkeypatch.setattr("app.model_gateway.ManusModelProvider", FailingManus)
    with pytest.raises(ModelRouteExhausted) as captured:
        await generate_with_frozen_route(
            snapshot={
                "selected_by_user": True,
                "policy": {"max_attempts": 2, "retry_current": True},
                "execution_configs": [
                    {
                        "deployment_id": "manus",
                        "adapter": "manus_v2",
                        "base_url": "https://api.manus.ai",
                        "secret_ref": "env:PRIMARY",
                        "model_id": "lite",
                        "input_cost": "0",
                        "output_cost": "0",
                    }
                ],
            },
            fallback_model=FailingManus(),
            secrets=StaticSecrets(),
            purpose="article_generation",
            prompt="生成文章",
            context={},
            default_timeout_seconds=120,
        )

    assert calls == 1
    assert captured.value.attempts[0].error_message == "uncertain task create"


async def test_selected_route_falls_back_without_repeating_slow_primary(
    monkeypatch: Any,
) -> None:
    calls: list[str] = []

    class FailoverModel:
        def __init__(self, *, model: str, **_: Any) -> None:
            self.model = model

        async def generate(self, **_: Any) -> ModelResult:
            calls.append(self.model)
            if self.model == "slow-primary":
                raise ProviderTransientError("timed out")
            return ModelResult(
                text="备用模型完成",
                structured={"type": "doc", "content": []},
                input_tokens=1,
                output_tokens=1,
                provider_request_id="fallback-ok",
                simulated=False,
            )

    monkeypatch.setattr("app.model_gateway.OpenAICompatibleModelProvider", FailoverModel)
    base_config = {
        "adapter": "openai_chat_completions",
        "base_url": "https://models.example/v1",
        "secret_ref": "env:PRIMARY",
        "input_cost": "0",
        "output_cost": "0",
    }
    routed = await generate_with_frozen_route(
        snapshot={
            "policy": {"max_attempts": 2, "retry_current": False},
            "execution_configs": [
                {**base_config, "deployment_id": "primary", "model_id": "slow-primary"},
                {**base_config, "deployment_id": "fallback", "model_id": "fallback-ok"},
            ],
        },
        fallback_model=FailoverModel(model="unused"),
        secrets=StaticSecrets(),
        purpose="article_generation",
        prompt="生成文章",
        context={},
        default_timeout_seconds=120,
    )

    assert calls == ["slow-primary", "fallback-ok"]
    assert [attempt.status for attempt in routed.attempts] == [
        "transient_failed",
        "completed",
    ]


async def test_failed_route_attempt_records_purpose_and_error(monkeypatch: Any) -> None:
    class FailingModel:
        def __init__(self, **_: Any) -> None:
            pass

        async def generate(self, **_: Any) -> ModelResult:
            raise ProviderUnavailable("Manus task failed")

    monkeypatch.setattr("app.model_gateway.OpenAICompatibleModelProvider", FailingModel)
    snapshot = {
        "policy": {"max_attempts": 1},
        "execution_configs": [
            {
                "deployment_id": "deployment-1",
                "adapter": "openai_responses",
                "base_url": "https://models.example/v1",
                "secret_ref": "env:PRIMARY",
                "model_id": "failing-model",
            }
        ],
    }

    try:
        await generate_with_frozen_route(
            snapshot=snapshot,
            fallback_model=FailingModel(),
            secrets=StaticSecrets(),
            purpose="article_generation",
            prompt="生成文章",
            context={},
            default_timeout_seconds=120,
        )
    except ProviderUnavailable as exc:
        attempts = exc.attempts
    else:
        raise AssertionError("route should fail")

    assert attempts[0].purpose == "article_generation"
    assert attempts[0].error_code == "ProviderUnavailable"
    assert attempts[0].error_message == "Manus task failed"


async def test_contract_failure_uses_next_deployment(monkeypatch: Any) -> None:
    class ContractModel:
        def __init__(self, *, model: str, **_: Any) -> None:
            self.model = model

        async def generate(self, **_: Any) -> ModelResult:
            text = "invalid" if self.model == "primary" else "valid"
            return ModelResult(text, {}, 1, 1, self.model, False)

    def require_valid(result: ModelResult) -> None:
        if result.text != "valid":
            raise ModelContractViolation(
                "排版样式字段不安全 (style_tokens.body.font_weight)",
                code="STYLE_TOKEN_INVALID",
            )

    monkeypatch.setattr("app.model_gateway.OpenAICompatibleModelProvider", ContractModel)
    routed = await generate_with_frozen_route(
        snapshot={
            "policy": {"max_attempts": 2},
            "execution_configs": [
                {
                    "deployment_id": "primary-id",
                    "adapter": "openai_chat_completions",
                    "base_url": "https://primary.example/v1",
                    "secret_ref": "env:PRIMARY",
                    "model_id": "primary",
                    "capabilities": ["structured_output"],
                },
                {
                    "deployment_id": "fallback-id",
                    "adapter": "openai_chat_completions",
                    "base_url": "https://fallback.example/v1",
                    "secret_ref": "env:FALLBACK",
                    "model_id": "fallback",
                    "capabilities": ["structured_output"],
                },
            ],
        },
        fallback_model=ContractModel(model="unused"),
        secrets=StaticSecrets(),
        purpose="layout_extraction",
        prompt="提取排版",
        context={},
        default_timeout_seconds=120,
        response_schema={"type": "object"},
        result_validator=require_valid,
    )
    assert routed.result.text == "valid"
    assert [attempt.status for attempt in routed.attempts] == ["failed", "completed"]
    assert routed.attempts[0].error_code == "STYLE_TOKEN_INVALID"
    assert "style_tokens.body.font_weight" in (routed.attempts[0].error_message or "")


async def test_frozen_embedding_route_uses_ordered_fallback(monkeypatch: Any) -> None:
    calls: list[str] = []

    class FakeEmbedding:
        def __init__(self, *, model: str, **_: Any) -> None:
            self.model = model

        async def embed(self, texts: list[str]) -> EmbeddingResult:
            calls.append(self.model)
            if self.model == "embedding-primary":
                raise ProviderAuthenticationError("credential rejected")
            return EmbeddingResult([[0.1, 0.2]], self.model, "embedding-ok", False)

    monkeypatch.setattr("app.model_gateway.OpenAICompatibleEmbeddingProvider", FakeEmbedding)
    snapshot = {
        "execution_configs": [
            {
                "model_id": "embedding-primary",
                "base_url": "https://primary.example/v1",
                "secret_ref": "env:PRIMARY",
            },
            {
                "model_id": "embedding-fallback",
                "base_url": "https://fallback.example/v1",
                "secret_ref": "env:FALLBACK",
            },
        ]
    }
    provider = FrozenEmbeddingRouteProvider(
        snapshot=snapshot,
        fallback=FakeEmbedding(model="unused"),
        secrets=StaticSecrets(),
        dimension=2,
    )
    result = await provider.embed(["查询"])
    assert result.model == "embedding-fallback"
    assert calls == ["embedding-primary", "embedding-fallback"]


async def test_frozen_rerank_route_retries_transient_failure_once(monkeypatch: Any) -> None:
    calls = 0

    class FakeRerank:
        def __init__(self, **_: Any) -> None:
            pass

        async def rerank(self, *, query: str, documents: list[str]) -> RerankResult:
            del query, documents
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ProviderTransientError("temporary")
            return RerankResult([0.9], "rerank-ok", False)

    monkeypatch.setattr("app.model_gateway.HttpRerankProvider", FakeRerank)
    provider = FrozenRerankRouteProvider(
        snapshot={
            "policy": {"max_attempts": 2},
            "execution_configs": [
                {
                    "model_id": "rerank-primary",
                    "base_url": "https://rerank.example/v1",
                    "secret_ref": "env:PRIMARY",
                }
            ],
        },
        fallback=FakeRerank(),
        secrets=StaticSecrets(),
    )
    result = await provider.rerank(query="查询", documents=["文档"])
    assert result.scores == [0.9]
    assert calls == 2

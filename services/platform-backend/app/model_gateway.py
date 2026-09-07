from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from time import perf_counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import ApiError
from app.models import ModelDeployment, ModelProviderRecord, ModelRouteVersion
from app.production_providers import (
    HttpRerankProvider,
    ManusModelProvider,
    OpenAICompatibleEmbeddingProvider,
    OpenAICompatibleModelProvider,
)
from app.providers import (
    EmbeddingProvider,
    EmbeddingResult,
    ModelContractViolation,
    ModelProvider,
    ModelResult,
    ProviderAuthenticationError,
    ProviderRateLimited,
    ProviderTimeoutError,
    ProviderTransientError,
    ProviderUnavailable,
    RerankProvider,
    RerankResult,
    SecretProvider,
)


@dataclass(frozen=True, slots=True)
class ModelExecutionAttempt:
    attempt_no: int
    deployment_id: str | None
    status: str
    duration_ms: int
    purpose: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    provider_request_id: str | None = None
    cost: Decimal = Decimal(0)


@dataclass(frozen=True, slots=True)
class RoutedModelResult:
    result: ModelResult
    attempts: tuple[ModelExecutionAttempt, ...]


class ModelRouteExhausted(ProviderUnavailable):
    def __init__(self, attempts: tuple[ModelExecutionAttempt, ...]) -> None:
        super().__init__("All frozen model-route deployments failed")
        self.attempts = attempts

    def user_message(self) -> str:
        failed = [attempt for attempt in self.attempts if attempt.status != "completed"]
        if not failed:
            return "当前模型未能完成请求，已保留本轮消息和附件。"
        last = failed[-1]
        stage = {
            "intent_detection": "识别要求",
            "article_planning": "规划文章",
            "article_generation": "生成正文",
            "article_revision": "改写成稿",
            "file_extraction": "读取原文件",
            "content_check": "检查内容",
        }.get(last.purpose or "", "模型处理")
        reason = {
            "ProviderTimeoutError": "等待模型响应超时",
            "MODEL_OUTPUT_TRUNCATED": "模型输出达到长度上限，正文尚未完整返回",
            "ProviderAuthenticationError": "模型凭据被拒绝",
            "ProviderRateLimited": "模型服务限流",
        }.get(last.error_code or "", "模型请求未成功完成")
        deployments = {a.deployment_id for a in self.attempts if a.purpose == last.purpose}
        recovery = "已尝试备用模型。" if len(deployments) > 1 else "未切换到其他模型。"
        return f"{stage}阶段：{reason}。{recovery}本轮消息和附件已保留，可稍后重试。"


async def active_route_snapshot(
    session: AsyncSession,
    *,
    purpose: str,
    settings: Settings,
) -> dict[str, Any]:
    """Freeze every execution field needed by a run without resolving secret values."""
    route = await session.scalar(
        select(ModelRouteVersion)
        .where(ModelRouteVersion.purpose == purpose, ModelRouteVersion.status == "published")
        .order_by(ModelRouteVersion.version_no.desc())
        .limit(1)
    )
    if not route:
        raise ApiError(503, "MODEL_ROUTE_UNAVAILABLE", "AI 模型路由尚未配置。")

    return await freeze_route_snapshot(session, route=route, purpose=purpose)


async def freeze_route_snapshot(
    session: AsyncSession,
    *,
    route: ModelRouteVersion,
    purpose: str | None = None,
) -> dict[str, Any]:
    """Resolve a route draft or release into the immutable shape used by workers."""

    deployment_ids = [route.primary_deployment_id, *route.fallback_deployment_ids]
    deployments = {
        item.id: item
        for item in (
            await session.scalars(
                select(ModelDeployment).where(ModelDeployment.id.in_(deployment_ids))
            )
        ).all()
    }
    provider_ids = {item.provider_id for item in deployments.values()}
    providers = {
        item.id: item
        for item in (
            await session.scalars(
                select(ModelProviderRecord).where(ModelProviderRecord.id.in_(provider_ids))
            )
        ).all()
    }
    route_purpose = purpose or route.purpose
    expected_types = (
        {"embedding"}
        if route_purpose == "embedding"
        else {"rerank"}
        if route_purpose == "rerank"
        else {"chat", "vision"}
    )
    execution_configs: list[dict[str, Any]] = []
    for deployment_id in deployment_ids:
        deployment = deployments.get(deployment_id)
        provider = providers.get(deployment.provider_id) if deployment else None
        if (
            not deployment
            or deployment.status != "available"
            or deployment.model_type not in expected_types
            or not provider
            or provider.status != "active"
        ):
            raise ApiError(
                503,
                "MODEL_ROUTE_DEPLOYMENT_UNAVAILABLE",
                "模型路由引用的部署当前不可用。",
                details={"deployment_id": deployment_id},
            )
        execution_configs.append(
            {
                "deployment_id": deployment.id,
                "provider_id": provider.id,
                "adapter": provider.adapter,
                "base_url": provider.base_url,
                "secret_ref": provider.secret_ref,
                "model_id": deployment.model_id,
                "model_type": deployment.model_type,
                "context_window": deployment.context_window,
                "max_output_tokens": deployment.max_output_tokens,
                "input_cost": str(deployment.input_cost),
                "output_cost": str(deployment.output_cost),
            }
        )
    return {
        "route_version_id": route.id,
        "purpose": route_purpose,
        "primary_deployment_id": route.primary_deployment_id,
        "fallback_deployment_ids": route.fallback_deployment_ids,
        "policy": route.policy,
        "execution_configs": execution_configs,
    }


async def freeze_deployment_snapshot(
    session: AsyncSession,
    *,
    deployment_id: str,
    purpose: str,
) -> dict[str, Any]:
    """Freeze exactly the deployment explicitly selected by the user."""

    rows = list(
        (
            await session.execute(
                select(ModelDeployment, ModelProviderRecord)
                .join(ModelProviderRecord, ModelProviderRecord.id == ModelDeployment.provider_id)
                .where(
                    ModelDeployment.status == "available",
                    ModelDeployment.model_type.in_({"chat", "vision"}),
                    ModelProviderRecord.status == "active",
                )
                .order_by(ModelDeployment.updated_at.desc(), ModelDeployment.id)
            )
        ).all()
    )
    selected = next((item for item in rows if item[0].id == deployment_id), None)
    deployment, provider = selected or (None, None)
    if not deployment or not provider:
        raise ApiError(422, "MODEL_DEPLOYMENT_UNAVAILABLE", "所选模型当前不可用，请重新选择。")

    def execution_config(
        item: ModelDeployment, item_provider: ModelProviderRecord
    ) -> dict[str, Any]:
        return {
            "deployment_id": item.id,
            "provider_id": item_provider.id,
            "adapter": item_provider.adapter,
            "base_url": item_provider.base_url,
            "secret_ref": item_provider.secret_ref,
            "model_id": item.model_id,
            "model_type": item.model_type,
            "context_window": item.context_window,
            "max_output_tokens": item.max_output_tokens,
            "input_cost": str(item.input_cost),
            "output_cost": str(item.output_cost),
        }

    execution_configs = [execution_config(deployment, provider)]
    timeout_ms = {
        "article_generation": 240_000,
        "article_revision": 240_000,
        "file_extraction": 240_000,
        "article_planning": 180_000,
    }.get(purpose, 120_000)
    return {
        "purpose": purpose,
        "selected_by_user": True,
        "primary_deployment_id": deployment.id,
        "fallback_deployment_ids": [],
        "policy": {
            "timeout_ms": timeout_ms,
            "max_attempts": 2,
            "retry_current": True,
            "max_retry_after_seconds": 5,
        },
        "execution_configs": execution_configs,
    }


async def freeze_preferred_deployment_snapshot(
    session: AsyncSession,
    *,
    deployment_id: str,
    purpose: str,
    settings: Settings,
) -> dict[str, Any]:
    """Prefer the user's model, then reuse the platform route as its failover chain."""
    preferred = await freeze_deployment_snapshot(
        session,
        deployment_id=deployment_id,
        purpose=purpose,
    )
    try:
        platform_route = await active_route_snapshot(
            session,
            purpose=purpose,
            settings=settings,
        )
    except ApiError as exc:
        if exc.code != "MODEL_ROUTE_UNAVAILABLE":
            raise
        return preferred

    preferred_configs = preferred["execution_configs"]
    platform_configs = platform_route.get("execution_configs")
    failovers = (
        [
            config
            for config in platform_configs
            if isinstance(config, dict) and config.get("deployment_id") != deployment_id
        ]
        if isinstance(platform_configs, list)
        else []
    )
    if not failovers:
        return preferred

    execution_configs = [*preferred_configs, *failovers]
    policy = dict(preferred["policy"])
    policy["max_attempts"] = max(int(policy["max_attempts"]), len(execution_configs) + 1)
    return {
        **preferred,
        "selected_by_user": False,
        "preferred_by_user": True,
        "fallback_deployment_ids": [config["deployment_id"] for config in failovers],
        "policy": policy,
        "execution_configs": execution_configs,
    }


def _positive_int(value: object, default: int) -> int:
    return int(value) if isinstance(value, int) and value > 0 else default


def _execution_cost(config: dict[str, Any], result: ModelResult) -> Decimal:
    try:
        input_cost = Decimal(str(config.get("input_cost", "0")))
        output_cost = Decimal(str(config.get("output_cost", "0")))
    except Exception:
        return Decimal(0)
    return (
        Decimal(result.input_tokens) * input_cost + Decimal(result.output_tokens) * output_cost
    ) / Decimal(1000)


async def _execute_specialized_route[RouteResult](
    *,
    snapshot: dict[str, Any],
    invoke: Callable[[dict[str, Any]], Awaitable[RouteResult]],
    fallback: Callable[[], Awaitable[RouteResult]],
) -> RouteResult:
    """Execute a frozen non-chat route with the same bounded retry/fallback semantics."""
    configs = snapshot.get("execution_configs")
    if not isinstance(configs, list) or not configs:
        return await fallback()
    if snapshot.get("selected_by_user") is True:
        # Old frozen snapshots may still contain fallback deployments. A user's explicit
        # selection is an ownership boundary: only another user action may change it.
        configs = configs[:1]

    raw_policy = snapshot.get("policy")
    policy: dict[str, Any] = raw_policy if isinstance(raw_policy, dict) else {}
    max_attempts = max(
        len(configs) + 1,
        _positive_int(policy.get("max_attempts"), len(configs) + 1),
    )
    max_retry_after = _positive_int(policy.get("max_retry_after_seconds"), 30)
    attempts = 0
    for raw_config in configs:
        if not isinstance(raw_config, dict):
            continue
        deployment_attempts = 0
        retry_current = True
        while retry_current and attempts < max_attempts:
            retry_current = False
            attempts += 1
            deployment_attempts += 1
            try:
                return await invoke(raw_config)
            except ProviderAuthenticationError:
                break
            except ProviderRateLimited as exc:
                delay = exc.retry_after_seconds
                if (
                    deployment_attempts == 1
                    and attempts < max_attempts
                    and (delay is None or 0 <= delay <= max_retry_after)
                ):
                    await asyncio.sleep(delay or 0.25)
                    retry_current = True
            except ProviderTransientError:
                if deployment_attempts == 1 and attempts < max_attempts:
                    await asyncio.sleep(0.25)
                    retry_current = True
            except ProviderUnavailable:
                break
        if attempts >= max_attempts:
            break
    raise ProviderUnavailable("All frozen specialized-route deployments failed")


class FrozenEmbeddingRouteProvider:
    def __init__(
        self,
        *,
        snapshot: dict[str, Any],
        fallback: EmbeddingProvider,
        secrets: SecretProvider,
        dimension: int,
    ) -> None:
        self._snapshot = snapshot
        self._fallback = fallback
        self._secrets = secrets
        self._dimension = dimension

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        async def invoke(config: dict[str, Any]) -> EmbeddingResult:
            secret_ref = config.get("secret_ref")
            if not isinstance(secret_ref, str):
                raise ProviderUnavailable("Frozen embedding secret reference is invalid")
            return await OpenAICompatibleEmbeddingProvider(
                api_base=str(config.get("base_url", "")),
                api_key=self._secrets.resolve(secret_ref),
                model=str(config.get("model_id", "")),
                dimension=self._dimension,
            ).embed(texts)

        return await _execute_specialized_route(
            snapshot=self._snapshot,
            invoke=invoke,
            fallback=lambda: self._fallback.embed(texts),
        )


class FrozenRerankRouteProvider:
    def __init__(
        self,
        *,
        snapshot: dict[str, Any],
        fallback: RerankProvider,
        secrets: SecretProvider,
    ) -> None:
        self._snapshot = snapshot
        self._fallback = fallback
        self._secrets = secrets

    async def rerank(self, *, query: str, documents: list[str]) -> RerankResult:
        async def invoke(config: dict[str, Any]) -> RerankResult:
            secret_ref = config.get("secret_ref")
            if not isinstance(secret_ref, str):
                raise ProviderUnavailable("Frozen rerank secret reference is invalid")
            return await HttpRerankProvider(
                api_base=str(config.get("base_url", "")),
                api_key=self._secrets.resolve(secret_ref),
                model=str(config.get("model_id", "")),
            ).rerank(query=query, documents=documents)

        return await _execute_specialized_route(
            snapshot=self._snapshot,
            invoke=invoke,
            fallback=lambda: self._fallback.rerank(query=query, documents=documents),
        )


async def generate_with_frozen_route(
    *,
    snapshot: dict[str, Any],
    fallback_model: ModelProvider,
    secrets: SecretProvider,
    purpose: str,
    prompt: str,
    context: dict[str, Any],
    default_timeout_seconds: float,
    session: AsyncSession | None = None,
    response_schema: dict[str, Any] | None = None,
    result_validator: Callable[[ModelResult], None] | None = None,
) -> RoutedModelResult:
    """Execute the immutable primary/fallback chain captured when the run began."""
    configs = snapshot.get("execution_configs")
    if not isinstance(configs, list) or not configs:
        started = perf_counter()
        result = await fallback_model.generate(purpose=purpose, prompt=prompt, context=context)
        if result_validator is not None:
            result_validator(result)
        return RoutedModelResult(
            result=result,
            attempts=(
                ModelExecutionAttempt(
                    attempt_no=1,
                    deployment_id=None,
                    status="completed",
                    duration_ms=max(0, round((perf_counter() - started) * 1000)),
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    provider_request_id=result.provider_request_id,
                ),
            ),
        )

    raw_policy = snapshot.get("policy")
    policy: dict[str, Any] = raw_policy if isinstance(raw_policy, dict) else {}
    timeout_ms = _positive_int(policy.get("timeout_ms"), round(default_timeout_seconds * 1000))
    selected_by_user = snapshot.get("selected_by_user") is True
    allow_same_deployment_retry = policy.get("retry_current") is not False
    selected_configs = configs[:1] if selected_by_user else configs
    minimum_attempts = len(selected_configs) + (1 if allow_same_deployment_retry else 0)
    max_attempts = max(
        minimum_attempts,
        _positive_int(policy.get("max_attempts"), minimum_attempts),
    )
    max_retry_after = _positive_int(policy.get("max_retry_after_seconds"), 30)
    attempts: list[ModelExecutionAttempt] = []
    attempt_no = 0
    for raw_config in selected_configs:
        if not isinstance(raw_config, dict):
            continue
        deployment_id = raw_config.get("deployment_id")
        adapter = str(raw_config.get("adapter", ""))
        # Manus task.create has no idempotency key. Retrying an uncertain create could
        # launch and bill a duplicate remote task, so only direct request/response models
        # receive the bounded same-deployment retry.
        retry_this_deployment = allow_same_deployment_retry and adapter != "manus_v2"
        retry_current = True
        deployment_attempts = 0
        while retry_current and attempt_no < max_attempts:
            retry_current = False
            attempt_no += 1
            deployment_attempts += 1
            started = perf_counter()
            try:
                secret_ref = raw_config.get("secret_ref")
                if not isinstance(secret_ref, str):
                    raise ProviderUnavailable("Frozen model secret reference is invalid")
                model: ModelProvider
                if adapter == "manus_v2":
                    model = ManusModelProvider(
                        api_base=str(raw_config.get("base_url", "")),
                        api_key=secrets.resolve(secret_ref),
                        agent_profile=str(raw_config.get("model_id", "standard")),
                        timeout_seconds=timeout_ms / 1000,
                    )
                else:
                    model_kwargs: dict[str, Any] = {
                        "api_base": str(raw_config.get("base_url", "")),
                        "api_key": secrets.resolve(secret_ref),
                        "model": str(raw_config.get("model_id", "")),
                        "api_style": ("chat_completions" if "chat" in adapter else "responses"),
                        "timeout_seconds": timeout_ms / 1000,
                        "max_output_tokens": _positive_int(raw_config.get("max_output_tokens"), 0)
                        or None,
                    }
                    if response_schema is not None:
                        model_kwargs["response_schema"] = response_schema
                    model = OpenAICompatibleModelProvider(
                        **model_kwargs,
                    )
                result = await model.generate(purpose=purpose, prompt=prompt, context=context)
                if result_validator is not None:
                    result_validator(result)
                attempts.append(
                    ModelExecutionAttempt(
                        attempt_no=attempt_no,
                        deployment_id=(deployment_id if isinstance(deployment_id, str) else None),
                        status="completed",
                        duration_ms=max(0, round((perf_counter() - started) * 1000)),
                        purpose=purpose,
                        input_tokens=result.input_tokens,
                        output_tokens=result.output_tokens,
                        provider_request_id=result.provider_request_id,
                        cost=_execution_cost(raw_config, result),
                    )
                )
                return RoutedModelResult(result=result, attempts=tuple(attempts))
            except ProviderAuthenticationError:
                attempts.append(
                    ModelExecutionAttempt(
                        attempt_no=attempt_no,
                        deployment_id=(deployment_id if isinstance(deployment_id, str) else None),
                        status="authentication_failed",
                        duration_ms=max(0, round((perf_counter() - started) * 1000)),
                        purpose=purpose,
                        error_code="ProviderAuthenticationError",
                        error_message="Provider credential was rejected",
                    )
                )
                if session is not None and isinstance(deployment_id, str):
                    deployment = await session.get(ModelDeployment, deployment_id)
                    if deployment:
                        deployment.status = "disabled"
            except ProviderRateLimited as exc:
                attempts.append(
                    ModelExecutionAttempt(
                        attempt_no=attempt_no,
                        deployment_id=(deployment_id if isinstance(deployment_id, str) else None),
                        status="rate_limited",
                        duration_ms=max(0, round((perf_counter() - started) * 1000)),
                        purpose=purpose,
                        error_code="ProviderRateLimited",
                        error_message=str(exc)[:1000],
                    )
                )
                delay = exc.retry_after_seconds
                if (
                    retry_this_deployment
                    and deployment_attempts == 1
                    and attempt_no < max_attempts
                    and (delay is None or 0 <= delay <= max_retry_after)
                ):
                    await asyncio.sleep(delay or 0.25)
                    retry_current = True
            except ProviderTransientError as exc:
                attempts.append(
                    ModelExecutionAttempt(
                        attempt_no=attempt_no,
                        deployment_id=(deployment_id if isinstance(deployment_id, str) else None),
                        status="transient_failed",
                        duration_ms=max(0, round((perf_counter() - started) * 1000)),
                        purpose=purpose,
                        error_code=(
                            "ProviderTimeoutError"
                            if isinstance(exc, ProviderTimeoutError)
                            else "ProviderTransientError"
                        ),
                        error_message=(
                            "Provider request timed out"
                            if isinstance(exc, ProviderTimeoutError)
                            else str(exc)[:1000] or "Provider request failed temporarily"
                        ),
                    )
                )
                if retry_this_deployment and deployment_attempts == 1 and attempt_no < max_attempts:
                    await asyncio.sleep(0.25)
                    retry_current = True
            except ProviderUnavailable as exc:
                attempts.append(
                    ModelExecutionAttempt(
                        attempt_no=attempt_no,
                        deployment_id=(deployment_id if isinstance(deployment_id, str) else None),
                        status="failed",
                        duration_ms=max(0, round((perf_counter() - started) * 1000)),
                        purpose=purpose,
                        error_code=(
                            exc.code
                            if isinstance(exc, ModelContractViolation)
                            else type(exc).__name__[:80]
                        ),
                        error_message=str(exc)[:1000],
                    )
                )
        if attempt_no >= max_attempts:
            break
    raise ModelRouteExhausted(tuple(attempts))

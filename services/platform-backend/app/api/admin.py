from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Cookie, Depends, Header, Query, Request, Response
from pydantic import BaseModel, Field, HttpUrl, SecretStr
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.config import Settings
from app.database import get_session
from app.dependencies import (
    content_safety_provider,
    current_admin,
    embedding_provider,
    model_provider,
    rate_limiter,
    require_admin_permission,
    rerank_provider,
    secret_provider,
    settings,
    validate_csrf,
    wechat_provider,
)
from app.domains.common import (
    audit,
    begin_idempotency,
    complete_idempotency,
    create_job,
    emit_outbox,
)
from app.domains.identity import login_admin, revoke_admin_session
from app.domains.layout import (
    LAYOUT_AGENT_PROMPT,
    LAYOUT_AGENT_RESPONSE_SCHEMA,
    validate_layout_agent_model_result,
    validated_layout_agent_payload,
)
from app.domains.quota import apply_quota_change
from app.errors import ApiError
from app.external_knowledge import LexiangKnowledgeProvider
from app.model_gateway import (
    FrozenEmbeddingRouteProvider,
    FrozenRerankRouteProvider,
    ModelRouteExhausted,
    freeze_route_snapshot,
    generate_with_frozen_route,
)
from app.models import (
    Admin,
    AdminSession,
    AIRun,
    AIRunAttempt,
    AuditLog,
    Document,
    ExternalKnowledgeSource,
    JobRecord,
    ModelDeployment,
    ModelProviderRecord,
    ModelRouteVersion,
    OfficialAccount,
    PromptBundle,
    PromptVersion,
    QuotaAccount,
    RefreshToken,
    ResourceLimit,
    Skill,
    SkillVersion,
    SystemSetting,
    User,
    WechatOperation,
    WechatPlatformConfig,
    utcnow,
)
from app.production_providers import probe_model_provider
from app.providers import (
    ContentSafetyProvider,
    EmbeddingProvider,
    ModelProvider,
    ProviderResultUnknown,
    ProviderUnavailable,
    RerankProvider,
    SecretProvider,
    WechatProvider,
)
from app.security import (
    RateLimiter,
    decode_access_token,
    hash_password,
    hash_token,
    issue_access_token,
    new_uuid,
    request_hash,
)
from app.system_settings import ai_run_credit_cost
from app.wechat_open_platform import WechatOpenPlatformClient, component_access_token
from app.wechat_public_layout import WeChatArticleApiConfig, WeChatPublicLayoutExtractionProvider

from . import contracts as contract
from .utils import model_dict

router = APIRouter(prefix="/admin-api/v1", responses=contract.COMMON_ERROR_RESPONSES)


class AdminLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=128)
    device_name: str | None = Field(default=None, max_length=120)


def _set_admin_cookies(response: Response, token: str, csrf: str, config: Settings) -> None:
    response.set_cookie(
        "admin_session",
        token,
        httponly=True,
        secure=config.cookie_secure,
        samesite="strict",
        max_age=config.admin_session_ttl_seconds,
        path="/admin-api/v1/auth",
    )
    response.set_cookie(
        "admin_csrf",
        csrf,
        httponly=False,
        secure=config.cookie_secure,
        samesite="strict",
        max_age=config.admin_session_ttl_seconds,
        path="/",
    )


def _clear_admin_cookies(response: Response, config: Settings) -> None:
    response.delete_cookie(
        "admin_session",
        path="/admin-api/v1/auth",
        secure=config.cookie_secure,
        samesite="strict",
    )
    response.delete_cookie(
        "admin_csrf",
        path="/",
        secure=config.cookie_secure,
        samesite="strict",
    )


@router.post(
    "/auth/login",
    response_model=contract.AdminAuthResponse,
    responses={200: {"headers": contract.ADMIN_SESSION_COOKIE_HEADERS}},
)
async def admin_login(
    payload: AdminLoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
    limiter: RateLimiter = Depends(rate_limiter),
    config: Settings = Depends(settings),
) -> dict[str, Any]:
    client = request.client.host if request.client else "unknown"
    await limiter.check(f"admin-login:{client}:{payload.username}", 5, 600)
    admin, tokens = await login_admin(
        session,
        username=payload.username,
        password=payload.password,
        device_name=payload.device_name,
        settings=config,
    )
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="admin.login",
        target_type="admin_session",
        target_id=None,
        request_id=request.state.request_id,
    )
    await session.commit()
    _set_admin_cookies(response, tokens.session_token, tokens.csrf_token, config)
    return {
        "access_token": tokens.access_token,
        "token_type": "bearer",
        "expires_in": tokens.access_expires_in,
        "admin": {"id": admin.id, "username": admin.username, "permissions": admin.permissions},
    }


@router.post(
    "/auth/refresh",
    response_model=contract.AdminRefreshResponse,
    responses={200: {"headers": contract.ADMIN_SESSION_COOKIE_HEADERS}},
)
async def admin_refresh(
    request: Request,
    response: Response,
    csrf_token: Annotated[
        str,
        Header(alias="X-CSRF-Token", description="Must match the admin_csrf cookie."),
    ],
    session_cookie: Annotated[
        str | None,
        Cookie(alias="admin_session", description="HttpOnly administrator session cookie."),
    ] = None,
    session: AsyncSession = Depends(get_session),
    config: Settings = Depends(settings),
) -> dict[str, Any]:
    del csrf_token
    validate_csrf(request, "admin_csrf")
    raw_token = session_cookie
    if not raw_token:
        raise ApiError(401, "ADMIN_SESSION_REQUIRED", "管理端登录已过期。")
    record = await session.scalar(
        select(AdminSession).where(
            AdminSession.token_hash == hash_token(raw_token),
            AdminSession.revoked_at.is_(None),
            AdminSession.expires_at > utcnow(),
        )
    )
    admin = await session.get(Admin, record.admin_id) if record else None
    if not record or not admin or admin.status != "active":
        raise ApiError(401, "INVALID_ADMIN_SESSION", "管理端登录状态无效。")
    access = issue_access_token(
        subject=admin.id,
        session_id=record.id,
        kind="admin_access",
        secret=config.token_secret,
        ttl_seconds=config.admin_access_token_ttl_seconds,
    )
    return {
        "access_token": access,
        "token_type": "bearer",
        "expires_in": config.admin_access_token_ttl_seconds,
    }


@router.post(
    "/auth/logout",
    status_code=204,
    responses={204: {"headers": contract.ADMIN_SESSION_COOKIE_HEADERS}},
)
async def admin_logout(
    request: Request,
    response: Response,
    csrf_token: Annotated[
        str,
        Header(alias="X-CSRF-Token", description="Must match the admin_csrf cookie."),
    ],
    session_cookie: Annotated[
        str | None,
        Cookie(alias="admin_session", description="HttpOnly administrator session cookie."),
    ] = None,
    admin: Admin = Depends(current_admin),
    session: AsyncSession = Depends(get_session),
    config: Settings = Depends(settings),
) -> Response:
    del csrf_token, session_cookie
    validate_csrf(request, "admin_csrf")
    await revoke_admin_session(
        session,
        admin_id=admin.id,
        session_id=getattr(request.state, "admin_session_id", None),
    )
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="admin.logout",
        target_type="admin_session",
        target_id=getattr(request.state, "admin_session_id", None),
        request_id=request.state.request_id,
    )
    await session.commit()
    _clear_admin_cookies(response, config)
    response.status_code = 204
    return response


@router.get("/me", response_model=contract.AdminIdentityResponse)
async def admin_me(admin: Admin = Depends(current_admin)) -> dict[str, Any]:
    return {"id": admin.id, "username": admin.username, "permissions": admin.permissions}


@router.get("/dashboard", response_model=contract.DashboardResponse)
async def dashboard(
    admin: Admin = Depends(require_admin_permission("dashboard:read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    del admin
    day_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    user_count = await session.scalar(select(func.count(User.id)).where(User.deleted_at.is_(None)))
    active_users = await session.scalar(
        select(func.count(User.id)).where(User.status == "active", User.deleted_at.is_(None))
    )
    new_users = await session.scalar(
        select(func.count(User.id)).where(
            User.created_at >= day_start,
            User.deleted_at.is_(None),
        )
    )
    ai_total = await session.scalar(select(func.count(AIRun.id)))
    ai_failed = await session.scalar(
        select(func.count(AIRun.id)).where(
            AIRun.status == "failed",
            AIRun.created_at >= day_start,
        )
    )
    ai_today = await session.scalar(
        select(func.count(AIRun.id)).where(AIRun.created_at >= day_start)
    )
    ai_average_latency = await session.scalar(
        select(func.avg(AIRunAttempt.duration_ms)).where(
            AIRunAttempt.status == "completed",
            AIRunAttempt.created_at >= day_start,
        )
    )
    documents_processing = await session.scalar(
        select(func.count(Document.id)).where(Document.status.in_(["queued", "processing"]))
    )
    wechat_failed = await session.scalar(
        select(func.count(WechatOperation.id)).where(WechatOperation.status == "failed")
    )
    jobs_failed = await session.scalar(
        select(func.count(JobRecord.id)).where(JobRecord.status == "failed")
    )
    abnormal_models = await session.scalar(
        select(func.count(ModelDeployment.id)).where(ModelDeployment.status == "disabled")
    )
    account_health_rows = (
        await session.execute(
            select(OfficialAccount.status, func.count(OfficialAccount.id))
            .where(OfficialAccount.deleted_at.is_(None))
            .group_by(OfficialAccount.status)
        )
    ).all()
    account_counts = {str(status): int(count) for status, count in account_health_rows}

    route_changes = list(
        (
            await session.scalars(
                select(ModelRouteVersion)
                .where(ModelRouteVersion.status == "published")
                .order_by(ModelRouteVersion.published_at.desc())
                .limit(5)
            )
        ).all()
    )
    prompt_changes = (
        await session.execute(
            select(PromptVersion, PromptBundle.name)
            .join(PromptBundle, PromptBundle.id == PromptVersion.bundle_id)
            .where(PromptVersion.status == "published")
            .order_by(PromptVersion.created_at.desc())
            .limit(5)
        )
    ).all()
    skill_changes = list(
        (
            await session.scalars(
                select(Skill)
                .where(Skill.scope == "official", Skill.status == "published")
                .order_by(Skill.updated_at.desc())
                .limit(5)
            )
        ).all()
    )
    changes: list[dict[str, Any]] = [
        {
            "id": row.id,
            "type": "模型路由",
            "name": row.purpose,
            "version": f"v{row.version_no}",
            "published_at": row.published_at or row.created_at,
        }
        for row in route_changes
    ]
    changes.extend(
        {
            "id": row.id,
            "type": "提示词",
            "name": name,
            "version": f"v{row.version_no}",
            "published_at": row.created_at,
        }
        for row, name in prompt_changes
    )
    changes.extend(
        {
            "id": row.id,
            "type": "官方技能",
            "name": row.name,
            "version": f"v{row.current_version_no}",
            "published_at": row.updated_at,
        }
        for row in skill_changes
    )
    changes.sort(key=lambda item: item["published_at"], reverse=True)
    return {
        "users": {
            "total": user_count or 0,
            "active": active_users or 0,
            "new_today": new_users or 0,
        },
        "ai": {"total": ai_total or 0, "failed": ai_failed or 0, "today": ai_today or 0},
        "documents": {"processing": documents_processing or 0},
        "wechat": {"failed": wechat_failed or 0},
        "jobs": {"failed": jobs_failed or 0},
        "ai_average_latency_ms": round(float(ai_average_latency or 0)),
        "abnormal_models": abnormal_models or 0,
        "account_health": {
            "healthy": account_counts.get("connected", 0),
            "degraded": account_counts.get("reconnect_required", 0),
            "down": account_counts.get("limited", 0),
        },
        "recent_changes": changes[:8],
    }


class AdminUserPatch(BaseModel):
    status: Literal["active", "disabled"] | None = None
    ai_enabled: bool | None = None
    wechat_enabled: bool | None = None
    storage_bytes: int | None = Field(default=None, ge=0)
    single_file_bytes: int | None = Field(default=None, ge=1)
    official_account_count: int | None = Field(default=None, ge=0)
    reason: str = Field(min_length=3, max_length=500)


class QuotaAdjustment(BaseModel):
    direction: Literal["credit", "debit"]
    amount: int = Field(gt=0)
    reason: str = Field(min_length=3, max_length=255)


@router.get("/users", response_model=contract.AdminUserListResponse)
async def list_users(
    query: str | None = Query(default=None, max_length=200),
    status: Literal["active", "disabled", "pending"] | None = None,
    limit: int = Query(50, ge=1, le=200),
    admin: Admin = Depends(require_admin_permission("users:read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    del admin
    conditions: list[ColumnElement[bool]] = [User.deleted_at.is_(None)]
    if query:
        conditions.append(
            or_(
                User.id == query,
                User.email.ilike(f"%{query}%"),
                User.phone.ilike(f"%{query}%"),
                User.display_name.ilike(f"%{query}%"),
            )
        )
    if status:
        conditions.append(User.status == status)
    rows = list(
        (
            await session.scalars(
                select(User).where(*conditions).order_by(User.created_at.desc()).limit(limit)
            )
        ).all()
    )
    return {"items": [model_dict(row, exclude={"password_hash", "deleted_at"}) for row in rows]}


@router.get("/users/{user_id}", response_model=contract.AdminUserDetailResponse)
async def get_user(
    user_id: str,
    admin: Admin = Depends(require_admin_permission("users:read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    del admin
    user = await session.get(User, user_id)
    if not user or user.deleted_at:
        raise ApiError(404, "USER_NOT_FOUND", "用户不存在。")
    quota = await session.scalar(select(QuotaAccount).where(QuotaAccount.owner_id == user.id))
    limits = await session.scalar(select(ResourceLimit).where(ResourceLimit.owner_id == user.id))
    accounts = list(
        (
            await session.scalars(
                select(OfficialAccount).where(
                    OfficialAccount.owner_id == user.id,
                    OfficialAccount.deleted_at.is_(None),
                )
            )
        ).all()
    )
    failures = list(
        (
            await session.scalars(
                select(JobRecord)
                .where(JobRecord.owner_id == user.id, JobRecord.status == "failed")
                .order_by(JobRecord.updated_at.desc())
                .limit(20)
            )
        ).all()
    )
    return {
        "user": model_dict(user, exclude={"password_hash", "deleted_at"}),
        "quota": model_dict(quota) if quota else None,
        "limits": model_dict(limits) if limits else None,
        "official_accounts": [
            {
                "id": account.id,
                "name": account.name,
                "status": account.status,
                "last_synced_at": account.last_synced_at,
            }
            for account in accounts
        ],
        "failed_jobs": [model_dict(job) for job in failures],
        "content_accessed": False,
    }


@router.patch("/users/{user_id}", response_model=contract.AdminUserPatchResponse)
async def patch_user(
    user_id: str,
    payload: AdminUserPatch,
    request: Request,
    admin: Admin = Depends(require_admin_permission("users:write")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user = await session.get(User, user_id)
    if not user or user.deleted_at:
        raise ApiError(404, "USER_NOT_FOUND", "用户不存在。")
    limits = await session.scalar(
        select(ResourceLimit).where(ResourceLimit.owner_id == user.id).with_for_update()
    )
    if not limits:
        raise ApiError(500, "RESOURCE_LIMIT_MISSING", "用户资源额度不存在。")
    changes = payload.model_dump(exclude_unset=True, exclude={"reason"})
    if payload.status is not None:
        user.status = payload.status
        if payload.status == "disabled":
            await session.execute(
                update(RefreshToken)
                .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
                .values(revoked_at=utcnow())
            )
    for key in (
        "ai_enabled",
        "wechat_enabled",
        "storage_bytes",
        "single_file_bytes",
        "official_account_count",
    ):
        value = getattr(payload, key)
        if value is not None:
            setattr(limits, key, value)
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="user.update",
        target_type="user",
        target_id=user.id,
        reason=payload.reason,
        request_id=request.state.request_id,
        details={"changes": changes},
    )
    await session.commit()
    return {
        "user": model_dict(user, exclude={"password_hash", "deleted_at"}),
        "limits": model_dict(limits),
    }


class UserDiagnosticRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


@router.post(
    "/users/{user_id}/diagnostics",
    response_model=contract.ValidationTestResponse,
)
async def record_user_diagnostic(
    user_id: str,
    payload: UserDiagnosticRequest,
    request: Request,
    admin: Admin = Depends(require_admin_permission("users:read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user = await session.get(User, user_id)
    if not user or user.deleted_at:
        raise ApiError(404, "USER_NOT_FOUND", "用户不存在。")
    failed_jobs = await session.scalar(
        select(func.count(JobRecord.id)).where(
            JobRecord.owner_id == user.id, JobRecord.status == "failed"
        )
    )
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="user.diagnostic.request",
        target_type="user",
        target_id=user.id,
        reason=payload.reason,
        request_id=request.state.request_id,
        details={"failed_job_count": int(failed_jobs or 0), "content_accessed": False},
    )
    await session.commit()
    return {
        "passed": True,
        "message": "排障请求已记录；仅收集任务状态与错误码，未读取用户正文。",
    }


@router.post(
    "/users/{user_id}/quota-adjustments",
    response_model=contract.QuotaAdjustmentResponse,
)
async def adjust_user_quota(
    user_id: str,
    payload: QuotaAdjustment,
    request: Request,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    admin: Admin = Depends(require_admin_permission("users:quota")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user = await session.get(User, user_id)
    if not user or user.deleted_at:
        raise ApiError(404, "USER_NOT_FOUND", "用户不存在。")
    attempt = await begin_idempotency(
        session,
        actor_type="admin",
        actor_id=admin.id,
        scope=f"users.{user_id}.quota",
        key=idempotency_key,
        payload=payload.model_dump(),
    )
    if attempt.cached_body:
        return attempt.cached_body
    account = await apply_quota_change(
        session,
        user_id=user.id,
        direction=payload.direction,
        amount=payload.amount,
        reason=payload.reason,
        business_type="admin_adjustment",
        business_id=attempt.record.id,
    )
    body = {"balance": account.balance, "version": account.version}
    complete_idempotency(attempt, body)
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="quota.adjust",
        target_type="user",
        target_id=user.id,
        reason=payload.reason,
        request_id=request.state.request_id,
        details={"direction": payload.direction, "amount": payload.amount},
    )
    await session.commit()
    return body


class ModelProviderCreate(BaseModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,79}$")
    name: str = Field(min_length=1, max_length=120)
    adapter: Literal[
        "openai_responses",
        "openai_chat_completions",
        "litellm_responses",
        "litellm_chat_completions",
    ]
    base_url: HttpUrl
    secret_ref: str = Field(min_length=5, max_length=255)


class ModelProviderPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    base_url: HttpUrl | None = None
    secret_ref: str | None = Field(default=None, min_length=5, max_length=255)
    status: Literal["draft", "testing", "active", "disabled"] | None = None


def _provider_public(provider: ModelProviderRecord) -> dict[str, Any]:
    return {
        "id": provider.id,
        "code": provider.code,
        "name": provider.name,
        "adapter": provider.adapter,
        "base_url": provider.base_url,
        "secret_configured": bool(provider.secret_ref),
        "status": provider.status,
        "last_tested_at": provider.last_tested_at,
        "last_test_result": provider.last_test_result,
        "created_at": provider.created_at,
        "updated_at": provider.updated_at,
    }


@router.get("/model-providers", response_model=contract.ModelProviderListResponse)
async def list_model_providers(
    admin: Admin = Depends(require_admin_permission("ai_config:read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    del admin
    rows = list(
        (
            await session.scalars(
                select(ModelProviderRecord).order_by(ModelProviderRecord.created_at)
            )
        ).all()
    )
    return {"items": [_provider_public(row) for row in rows]}


@router.post("/model-providers", status_code=201, response_model=contract.ModelProviderResponse)
async def create_model_provider(
    payload: ModelProviderCreate,
    request: Request,
    admin: Admin = Depends(require_admin_permission("ai_config:write")),
    session: AsyncSession = Depends(get_session),
    secrets: SecretProvider = Depends(secret_provider),
) -> dict[str, Any]:
    try:
        secrets.resolve(payload.secret_ref)
    except ProviderUnavailable as exc:
        raise ApiError(422, "MODEL_SECRET_UNAVAILABLE", "模型密钥引用不可用。") from exc
    provider = ModelProviderRecord(
        code=payload.code,
        name=payload.name,
        adapter=payload.adapter,
        base_url=str(payload.base_url),
        secret_ref=payload.secret_ref,
    )
    session.add(provider)
    await session.flush()
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="model_provider.create",
        target_type="model_provider",
        target_id=provider.id,
        request_id=request.state.request_id,
        details={"code": provider.code, "adapter": provider.adapter},
    )
    await session.commit()
    return _provider_public(provider)


@router.patch("/model-providers/{provider_id}", response_model=contract.ModelProviderResponse)
async def patch_model_provider(
    provider_id: str,
    payload: ModelProviderPatch,
    request: Request,
    admin: Admin = Depends(require_admin_permission("ai_config:write")),
    session: AsyncSession = Depends(get_session),
    secrets: SecretProvider = Depends(secret_provider),
) -> dict[str, Any]:
    provider = await session.get(ModelProviderRecord, provider_id)
    if not provider:
        raise ApiError(404, "MODEL_PROVIDER_NOT_FOUND", "模型供应商不存在。")
    values = payload.model_dump(exclude_unset=True)
    if payload.secret_ref:
        try:
            secrets.resolve(payload.secret_ref)
        except ProviderUnavailable as exc:
            raise ApiError(422, "MODEL_SECRET_UNAVAILABLE", "模型密钥引用不可用。") from exc
    if "base_url" in values:
        values["base_url"] = str(values["base_url"])
    if values.get("status") == "active" and not provider.last_test_result.get("passed"):
        raise ApiError(409, "PROVIDER_TEST_REQUIRED", "供应商需要先通过真实连接测试。")
    for key, value in values.items():
        setattr(provider, key, value)
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="model_provider.update",
        target_type="model_provider",
        target_id=provider.id,
        request_id=request.state.request_id,
        details={"fields": sorted(values)},
    )
    await session.commit()
    return _provider_public(provider)


@router.post("/model-providers/{provider_id}/test", response_model=contract.ProviderTestResponse)
async def test_model_provider(
    provider_id: str,
    request: Request,
    admin: Admin = Depends(require_admin_permission("ai_config:test")),
    session: AsyncSession = Depends(get_session),
    secrets: SecretProvider = Depends(secret_provider),
) -> dict[str, Any]:
    provider = await session.get(ModelProviderRecord, provider_id)
    if not provider:
        raise ApiError(404, "MODEL_PROVIDER_NOT_FOUND", "模型供应商不存在。")
    secret_available = False
    passed = False
    message = "模型供应商连接测试失败。"
    try:
        secret = secrets.resolve(provider.secret_ref)
        secret_available = True
        message = await probe_model_provider(
            api_base=provider.base_url,
            api_key=secret,
            adapter=provider.adapter,
        )
        passed = True
    except ProviderUnavailable:
        message = "密钥不可用或供应商连接测试失败。"
    provider.status = "testing"
    provider.last_tested_at = utcnow()
    provider.last_test_result = {
        "passed": passed,
        "secret_available": secret_available,
        "message": message,
    }
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="model_provider.test",
        target_type="model_provider",
        target_id=provider.id,
        request_id=request.state.request_id,
        details=provider.last_test_result,
    )
    await session.commit()
    return provider.last_test_result


class DeploymentCreate(BaseModel):
    provider_id: str
    model_id: str = Field(min_length=1, max_length=180)
    alias: str = Field(min_length=1, max_length=120)
    model_type: Literal["chat", "embedding", "rerank", "vision"]
    capabilities: list[str] = Field(default_factory=list)
    context_window: int = Field(default=0, ge=0)
    max_output_tokens: int = Field(default=0, ge=0)
    rpm_limit: int | None = Field(default=None, ge=1)
    tpm_limit: int | None = Field(default=None, ge=1)
    input_cost: Decimal = Field(default=Decimal(0), ge=0)
    output_cost: Decimal = Field(default=Decimal(0), ge=0)


class DeploymentPatch(BaseModel):
    provider_id: str | None = None
    model_id: str | None = Field(default=None, min_length=1, max_length=180)
    alias: str | None = Field(default=None, min_length=1, max_length=120)
    model_type: Literal["chat", "embedding", "rerank", "vision"] | None = None
    capabilities: list[str] | None = None
    context_window: int | None = Field(default=None, ge=0)
    max_output_tokens: int | None = Field(default=None, ge=0)
    rpm_limit: int | None = Field(default=None, ge=1)
    tpm_limit: int | None = Field(default=None, ge=1)
    status: Literal["draft", "testing", "available", "disabled"] | None = None


class ModelConfigurationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    base_url: HttpUrl = Field(max_length=1000)
    api_key: SecretStr | None = Field(default=None, min_length=1, max_length=4096)
    secret_ref: str | None = Field(default=None, min_length=5, max_length=255)
    validation_token: str | None = None
    model_id: str = Field(min_length=1, max_length=180)
    model_type: Literal["chat", "embedding", "rerank", "vision"] = "chat"
    adapter: Literal[
        "openai_responses",
        "openai_chat_completions",
        "litellm_responses",
        "litellm_chat_completions",
        "manus_v2",
    ] = "openai_chat_completions"


class ModelConfigurationPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    base_url: HttpUrl | None = Field(default=None, max_length=1000)
    api_key: SecretStr | None = Field(default=None, min_length=1, max_length=4096)
    secret_ref: str | None = Field(default=None, min_length=5, max_length=255)
    model_id: str | None = Field(default=None, min_length=1, max_length=180)
    model_type: Literal["chat", "embedding", "rerank", "vision"] | None = None
    adapter: (
        Literal[
            "openai_responses",
            "openai_chat_completions",
            "litellm_responses",
            "litellm_chat_completions",
            "manus_v2",
        ]
        | None
    ) = None


class ModelConfigurationTestRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    base_url: HttpUrl = Field(max_length=1000)
    api_key: SecretStr = Field(min_length=1, max_length=4096)
    model_id: str = Field(min_length=1, max_length=180)
    model_type: Literal["chat", "embedding", "rerank", "vision"] = "chat"
    adapter: Literal[
        "openai_responses",
        "openai_chat_completions",
        "litellm_responses",
        "litellm_chat_completions",
        "manus_v2",
    ] = "openai_chat_completions"


class ModelConfigurationTestResponse(BaseModel):
    passed: bool
    message: str
    validation_token: str | None = None


class ModelConfigurationStatusPatch(BaseModel):
    status: Literal["available", "disabled"]


def _model_configuration_code() -> str:
    return f"model_{new_uuid().replace('-', '')}"


def _model_secret_reference(
    secrets: SecretProvider, *, api_key: SecretStr | None, secret_ref: str | None
) -> str:
    if api_key is not None:
        return secrets.protect(api_key.get_secret_value())
    if secret_ref:
        secrets.resolve(secret_ref)
        return secret_ref
    raise ApiError(422, "MODEL_SECRET_REQUIRED", "请输入模型 API Key。")


def _model_test_subject(payload: Any, api_key: str) -> str:
    return request_hash(
        {
            "name": payload.name,
            "base_url": str(payload.base_url),
            "model_id": payload.model_id,
            "model_type": payload.model_type,
            "adapter": payload.adapter,
            "api_key_hash": hash_token(api_key),
        }
    )


def _model_configuration_fingerprint(
    provider: ModelProviderRecord, deployment: ModelDeployment
) -> str:
    payload = {
        "adapter": provider.adapter,
        "base_url": provider.base_url,
        "secret_ref": provider.secret_ref,
        "model_id": deployment.model_id,
        "model_type": deployment.model_type,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _model_configuration_public(
    provider: ModelProviderRecord, deployment: ModelDeployment
) -> dict[str, Any]:
    if provider.status == "disabled" or deployment.status == "disabled":
        status = "disabled"
    elif provider.status == "active" and deployment.status == "available":
        status = "available"
    elif provider.status == "testing" or deployment.status == "testing":
        status = "testing"
    else:
        status = "draft"
    has_current_test = provider.last_test_result.get(
        "configuration_id"
    ) == deployment.id and provider.last_test_result.get(
        "configuration_fingerprint"
    ) == _model_configuration_fingerprint(provider, deployment)
    test_result = (
        {
            key: provider.last_test_result[key]
            for key in ("passed", "secret_available", "message")
            if key in provider.last_test_result
        }
        if has_current_test
        else {}
    )
    return {
        "id": deployment.id,
        "name": deployment.alias,
        "base_url": provider.base_url,
        "model_id": deployment.model_id,
        "model_type": deployment.model_type,
        "adapter": provider.adapter,
        "secret_configured": bool(provider.secret_ref),
        "status": status,
        "last_tested_at": provider.last_tested_at if has_current_test else None,
        "last_test_result": test_result,
        "created_at": deployment.created_at,
        "updated_at": max(
            provider.updated_at,
            deployment.updated_at,
            key=lambda value: value.replace(tzinfo=None),
        ),
    }


async def _model_configuration_records(
    session: AsyncSession, configuration_id: str, *, lock: bool = False
) -> tuple[ModelDeployment, ModelProviderRecord]:
    statement = (
        select(ModelDeployment, ModelProviderRecord)
        .join(ModelProviderRecord, ModelProviderRecord.id == ModelDeployment.provider_id)
        .where(ModelDeployment.id == configuration_id)
    )
    if lock:
        statement = statement.with_for_update()
    row = (await session.execute(statement)).first()
    if not row:
        raise ApiError(404, "MODEL_CONFIGURATION_NOT_FOUND", "模型配置不存在。")
    return row[0], row[1]


async def _provider_deployment_count(session: AsyncSession, provider_id: str) -> int:
    count = await session.scalar(
        select(func.count(ModelDeployment.id)).where(ModelDeployment.provider_id == provider_id)
    )
    return int(count or 0)


@router.get("/model-deployments", response_model=contract.ModelDeploymentListResponse)
async def list_deployments(
    admin: Admin = Depends(require_admin_permission("ai_config:read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    del admin
    rows = list(
        (await session.scalars(select(ModelDeployment).order_by(ModelDeployment.created_at))).all()
    )
    return {"items": [model_dict(row) for row in rows]}


@router.post("/model-deployments", status_code=201, response_model=contract.ModelDeploymentResource)
async def create_deployment(
    payload: DeploymentCreate,
    request: Request,
    admin: Admin = Depends(require_admin_permission("ai_config:write")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    provider = await session.get(ModelProviderRecord, payload.provider_id)
    if not provider:
        raise ApiError(404, "MODEL_PROVIDER_NOT_FOUND", "模型供应商不存在。")
    deployment = ModelDeployment(**payload.model_dump())
    session.add(deployment)
    await session.flush()
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="model_deployment.create",
        target_type="model_deployment",
        target_id=deployment.id,
        request_id=request.state.request_id,
        details={"provider_id": provider.id, "model_id": deployment.model_id},
    )
    await session.commit()
    return model_dict(deployment)


@router.patch("/model-deployments/{deployment_id}", response_model=contract.ModelDeploymentResource)
async def patch_deployment(
    deployment_id: str,
    payload: DeploymentPatch,
    request: Request,
    admin: Admin = Depends(require_admin_permission("ai_config:write")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    deployment = await session.get(ModelDeployment, deployment_id)
    if not deployment:
        raise ApiError(404, "MODEL_DEPLOYMENT_NOT_FOUND", "模型部署不存在。")
    values = payload.model_dump(exclude_unset=True)
    provider_id = values.get("provider_id", deployment.provider_id)
    if not isinstance(provider_id, str):
        raise ApiError(422, "MODEL_PROVIDER_REQUIRED", "模型供应商不能为空。")
    provider = await session.get(ModelProviderRecord, provider_id)
    if not provider:
        raise ApiError(404, "MODEL_PROVIDER_NOT_FOUND", "模型供应商不存在。")
    for field in ("model_id", "model_type"):
        if field in values and values[field] is None:
            raise ApiError(422, "MODEL_DEPLOYMENT_FIELD_REQUIRED", "模型配置字段不能为空。")
    if values.get("status") == "available" and (not provider.last_test_result.get("passed")):
        raise ApiError(409, "PROVIDER_TEST_REQUIRED", "供应商需要先通过真实连接测试。")
    for key, value in values.items():
        setattr(deployment, key, value)
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="model_deployment.update",
        target_type="model_deployment",
        target_id=deployment.id,
        request_id=request.state.request_id,
        details={"fields": sorted(values)},
    )
    await session.commit()
    return model_dict(deployment)


@router.post(
    "/model-deployments/{deployment_id}/test",
    response_model=contract.ProviderTestResponse,
)
async def test_deployment(
    deployment_id: str,
    request: Request,
    admin: Admin = Depends(require_admin_permission("ai_config:test")),
    session: AsyncSession = Depends(get_session),
    secrets: SecretProvider = Depends(secret_provider),
) -> dict[str, Any]:
    deployment = await session.get(ModelDeployment, deployment_id)
    if not deployment:
        raise ApiError(404, "MODEL_DEPLOYMENT_NOT_FOUND", "模型部署不存在。")
    provider = await session.get(ModelProviderRecord, deployment.provider_id)
    if not provider:
        raise ApiError(404, "MODEL_PROVIDER_NOT_FOUND", "模型供应商不存在。")
    secret_available = False
    passed = False
    message = "模型部署连接测试失败。"
    try:
        secret = secrets.resolve(provider.secret_ref)
        secret_available = True
        message = await probe_model_provider(
            api_base=provider.base_url,
            api_key=secret,
            adapter=provider.adapter,
            model_id=deployment.model_id,
            model_type=deployment.model_type,
        )
        passed = True
    except ProviderUnavailable:
        message = "密钥不可用，或模型能力/结构化输出连接测试失败。"
    deployment.status = "testing" if passed else "draft"
    result = {
        "passed": passed,
        "secret_available": secret_available,
        "message": message,
    }
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="model_deployment.test",
        target_type="model_deployment",
        target_id=deployment.id,
        request_id=request.state.request_id,
        details=result,
    )
    await session.commit()
    return result


@router.get(
    "/model-configurations",
    response_model=contract.ModelConfigurationListResponse,
)
async def list_model_configurations(
    admin: Admin = Depends(require_admin_permission("ai_config:read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    del admin
    rows = (
        await session.execute(
            select(ModelDeployment, ModelProviderRecord)
            .join(ModelProviderRecord, ModelProviderRecord.id == ModelDeployment.provider_id)
            .order_by(ModelDeployment.created_at)
        )
    ).all()
    return {
        "items": [
            _model_configuration_public(provider, deployment) for deployment, provider in rows
        ]
    }


@router.post(
    "/model-configurations/test",
    response_model=ModelConfigurationTestResponse,
)
async def test_model_configuration_before_save(
    payload: ModelConfigurationTestRequest,
    request: Request,
    admin: Admin = Depends(require_admin_permission("ai_config:test")),
    session: AsyncSession = Depends(get_session),
    config: Settings = Depends(settings),
) -> dict[str, Any]:
    api_key = payload.api_key.get_secret_value()
    passed = False
    message = "模型连接测试失败。"
    validation_token = None
    try:
        message = await probe_model_provider(
            api_base=str(payload.base_url),
            api_key=api_key,
            adapter=payload.adapter,
            model_id=payload.model_id,
            model_type=payload.model_type,
        )
        passed = True
        validation_token = issue_access_token(
            subject=_model_test_subject(payload, api_key),
            session_id=admin.id,
            kind="model_configuration_test",
            secret=config.token_secret,
            ttl_seconds=600,
        )
    except ProviderUnavailable:
        message = "密钥不可用，或模型能力/结构化输出连接测试失败。"
    result = {"passed": passed, "message": message, "validation_token": validation_token}
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="model_configuration.test_before_save",
        target_type="model_configuration",
        target_id=None,
        request_id=request.state.request_id,
        details={"passed": passed, "adapter": payload.adapter, "model_type": payload.model_type},
    )
    await session.commit()
    return result


@router.post(
    "/model-configurations",
    status_code=201,
    response_model=contract.ModelConfigurationResponse,
)
async def create_model_configuration(
    payload: ModelConfigurationCreate,
    request: Request,
    admin: Admin = Depends(require_admin_permission("ai_config:write")),
    session: AsyncSession = Depends(get_session),
    secrets: SecretProvider = Depends(secret_provider),
    config: Settings = Depends(settings),
) -> dict[str, Any]:
    tested = False
    if payload.validation_token and payload.api_key:
        try:
            claims = decode_access_token(
                payload.validation_token, config.token_secret, "model_configuration_test"
            )
        except ApiError as exc:
            raise ApiError(422, "MODEL_TEST_EXPIRED", "模型测试已过期，请重新测试。") from exc
        tested = (
            claims.get("sub") == _model_test_subject(payload, payload.api_key.get_secret_value())
            and claims.get("sid") == admin.id
        )
        if not tested:
            raise ApiError(422, "MODEL_CONFIGURATION_CHANGED", "模型配置已修改，请重新测试。")
    try:
        secret_reference = _model_secret_reference(
            secrets, api_key=payload.api_key, secret_ref=payload.secret_ref
        )
    except ProviderUnavailable as exc:
        raise ApiError(422, "MODEL_SECRET_UNAVAILABLE", "模型密钥不可用。") from exc
    provider = ModelProviderRecord(
        code=_model_configuration_code(),
        name=payload.name,
        adapter=payload.adapter,
        base_url=str(payload.base_url),
        secret_ref=secret_reference,
    )
    session.add(provider)
    await session.flush()
    deployment = ModelDeployment(
        provider_id=provider.id,
        model_id=payload.model_id,
        alias=payload.name,
        model_type=payload.model_type,
    )
    session.add(deployment)
    await session.flush()
    if tested:
        provider.status = "active"
        deployment.status = "available"
        provider.last_tested_at = utcnow()
        provider.last_test_result = {
            "passed": True,
            "secret_available": True,
            "message": "保存前连接测试通过。",
            "configuration_id": deployment.id,
            "configuration_fingerprint": _model_configuration_fingerprint(provider, deployment),
        }
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="model_configuration.create",
        target_type="model_deployment",
        target_id=deployment.id,
        request_id=request.state.request_id,
        details={"adapter": provider.adapter, "model_type": deployment.model_type},
    )
    await session.commit()
    return _model_configuration_public(provider, deployment)


@router.patch(
    "/model-configurations/{configuration_id}",
    response_model=contract.ModelConfigurationResponse,
)
async def patch_model_configuration(
    configuration_id: str,
    payload: ModelConfigurationPatch,
    request: Request,
    admin: Admin = Depends(require_admin_permission("ai_config:write")),
    session: AsyncSession = Depends(get_session),
    secrets: SecretProvider = Depends(secret_provider),
) -> dict[str, Any]:
    deployment, provider = await _model_configuration_records(session, configuration_id, lock=True)
    values = payload.model_dump(exclude_unset=True)
    api_key = values.pop("api_key", None)
    if any(value is None for value in values.values()):
        raise ApiError(422, "MODEL_CONFIGURATION_FIELD_REQUIRED", "模型配置字段不能为空。")
    if "base_url" in values:
        values["base_url"] = str(values["base_url"])
    if api_key is not None:
        try:
            values["secret_ref"] = secrets.protect(api_key.get_secret_value())
        except ProviderUnavailable as exc:
            raise ApiError(422, "MODEL_SECRET_UNAVAILABLE", "模型密钥无法加密保存。") from exc
    elif "secret_ref" in values:
        try:
            secrets.resolve(str(values["secret_ref"]))
        except ProviderUnavailable as exc:
            raise ApiError(422, "MODEL_SECRET_UNAVAILABLE", "模型密钥引用不可用。") from exc

    provider_fields = {"name", "base_url", "secret_ref", "adapter"}
    deployment_fields = {"model_id", "model_type"}
    provider_changes = {
        key: value
        for key, value in values.items()
        if key in provider_fields and value != getattr(provider, key)
    }
    deployment_changes = {
        key: value
        for key, value in values.items()
        if key in deployment_fields and value != getattr(deployment, key)
    }
    if "name" in values and values["name"] != deployment.alias:
        deployment_changes["alias"] = values["name"]
    connection_changed = bool(provider_changes.keys() & {"base_url", "secret_ref", "adapter"})
    model_changed = bool(deployment_changes.keys() & {"model_id", "model_type"})
    shared_provider = await _provider_deployment_count(session, provider.id) > 1
    provider_cloned = False

    if shared_provider and (provider_changes or "alias" in deployment_changes):
        provider = ModelProviderRecord(
            code=_model_configuration_code(),
            name=str(provider_changes.get("name", provider.name)),
            adapter=str(provider_changes.get("adapter", provider.adapter)),
            base_url=str(provider_changes.get("base_url", provider.base_url)),
            secret_ref=str(provider_changes.get("secret_ref", provider.secret_ref)),
            status="draft" if connection_changed else provider.status,
            last_tested_at=None if connection_changed else provider.last_tested_at,
            last_test_result=({} if connection_changed else dict(provider.last_test_result)),
        )
        session.add(provider)
        await session.flush()
        deployment.provider_id = provider.id
        provider_cloned = True
    else:
        for key, value in provider_changes.items():
            setattr(provider, key, value)

    for key, value in deployment_changes.items():
        setattr(deployment, key, value)
    if connection_changed or model_changed:
        deployment.status = "draft"
        if not shared_provider or provider_cloned:
            provider.status = "draft"
            provider.last_tested_at = None
            provider.last_test_result = {}

    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="model_configuration.update",
        target_type="model_deployment",
        target_id=deployment.id,
        request_id=request.state.request_id,
        details={"fields": sorted(values), "provider_cloned": provider_cloned},
    )
    await session.commit()
    return _model_configuration_public(provider, deployment)


@router.delete("/model-configurations/{configuration_id}", status_code=204)
async def delete_model_configuration(
    configuration_id: str,
    request: Request,
    admin: Admin = Depends(require_admin_permission("ai_config:write")),
    session: AsyncSession = Depends(get_session),
) -> Response:
    deployment, provider = await _model_configuration_records(session, configuration_id, lock=True)
    routes = list(
        (await session.scalars(select(ModelRouteVersion).with_for_update())).all()
    )
    route_changes: list[dict[str, Any]] = []
    for route in routes:
        fallbacks = [item for item in route.fallback_deployment_ids if item != deployment.id]
        if route.primary_deployment_id == deployment.id:
            if fallbacks:
                route.primary_deployment_id = fallbacks[0]
                route.fallback_deployment_ids = fallbacks[1:]
                route_changes.append(
                    {
                        "route_id": route.id,
                        "purpose": route.purpose,
                        "action": "promoted_fallback",
                        "replacement_deployment_id": fallbacks[0],
                    }
                )
            else:
                await session.delete(route)
                route_changes.append(
                    {"route_id": route.id, "purpose": route.purpose, "action": "deleted"}
                )
        elif deployment.id in route.fallback_deployment_ids:
            route.fallback_deployment_ids = fallbacks
            route_changes.append(
                {"route_id": route.id, "purpose": route.purpose, "action": "removed_fallback"}
            )
    await session.flush()
    delete_provider = await _provider_deployment_count(session, provider.id) == 1
    await session.delete(deployment)
    await session.flush()
    if delete_provider:
        await session.delete(provider)
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="model_configuration.delete",
        target_type="model_deployment",
        target_id=configuration_id,
        request_id=request.state.request_id,
        details={"provider_deleted": delete_provider, "route_changes": route_changes},
    )
    await session.commit()
    return Response(status_code=204)


@router.post(
    "/model-configurations/{configuration_id}/test",
    response_model=contract.ProviderTestResponse,
)
async def test_model_configuration(
    configuration_id: str,
    request: Request,
    admin: Admin = Depends(require_admin_permission("ai_config:test")),
    session: AsyncSession = Depends(get_session),
    secrets: SecretProvider = Depends(secret_provider),
) -> dict[str, Any]:
    deployment, provider = await _model_configuration_records(session, configuration_id, lock=True)
    provider_cloned = False
    if await _provider_deployment_count(session, provider.id) > 1:
        provider = ModelProviderRecord(
            code=_model_configuration_code(),
            name=deployment.alias,
            adapter=provider.adapter,
            base_url=provider.base_url,
            secret_ref=provider.secret_ref,
        )
        session.add(provider)
        await session.flush()
        deployment.provider_id = provider.id
        provider_cloned = True
    secret_available = False
    passed = False
    message = "模型连接测试失败。"
    try:
        secret = secrets.resolve(provider.secret_ref)
        secret_available = True
        message = await probe_model_provider(
            api_base=provider.base_url,
            api_key=secret,
            adapter=provider.adapter,
            model_id=deployment.model_id,
            model_type=deployment.model_type,
        )
        passed = True
    except ProviderUnavailable:
        message = "密钥不可用，或模型能力/结构化输出连接测试失败。"
    result = {
        "passed": passed,
        "secret_available": secret_available,
        "message": message,
    }
    provider.last_tested_at = utcnow()
    provider.last_test_result = {
        **result,
        "configuration_id": deployment.id,
        "configuration_fingerprint": _model_configuration_fingerprint(provider, deployment),
    }
    provider.status = "active" if passed else "draft"
    deployment.status = "available" if passed else "draft"
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="model_configuration.test",
        target_type="model_deployment",
        target_id=deployment.id,
        request_id=request.state.request_id,
        details={
            **result,
            "provider_status": provider.status,
            "deployment_status": deployment.status,
            "provider_cloned": provider_cloned,
        },
    )
    await session.commit()
    return result


@router.patch(
    "/model-configurations/{configuration_id}/status",
    response_model=contract.ModelConfigurationResponse,
)
async def patch_model_configuration_status(
    configuration_id: str,
    payload: ModelConfigurationStatusPatch,
    request: Request,
    admin: Admin = Depends(require_admin_permission("ai_config:publish")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    deployment, provider = await _model_configuration_records(session, configuration_id, lock=True)
    if payload.status == "available":
        test_result = provider.last_test_result
        if (
            not provider.last_tested_at
            or test_result.get("passed") is not True
            or test_result.get("configuration_id") != deployment.id
            or test_result.get("configuration_fingerprint")
            != _model_configuration_fingerprint(provider, deployment)
        ):
            raise ApiError(
                409,
                "MODEL_CONFIGURATION_TEST_REQUIRED",
                "模型配置需要先通过最新连接测试。",
            )
        provider.status = "active"
        deployment.status = "available"
    else:
        deployment.status = "disabled"
        siblings = await session.scalar(
            select(func.count(ModelDeployment.id)).where(
                ModelDeployment.provider_id == provider.id,
                ModelDeployment.id != deployment.id,
                ModelDeployment.status != "disabled",
            )
        )
        if not siblings:
            provider.status = "disabled"
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="model_configuration.status",
        target_type="model_deployment",
        target_id=deployment.id,
        request_id=request.state.request_id,
        details={"status": payload.status},
    )
    await session.commit()
    return _model_configuration_public(provider, deployment)


class RouteCreate(BaseModel):
    purpose: Literal[
        "intent_detection",
        "fast_task",
        "article_planning",
        "article_generation",
        "article_revision",
        "file_extraction",
        "content_check",
        "vision",
        "memory_summary",
        "layout_extraction",
        "embedding",
        "rerank",
    ]
    primary_deployment_id: str
    fallback_deployment_ids: list[str] = Field(default_factory=list)
    policy: dict[str, Any] = Field(default_factory=dict)


def _route_model_types(purpose: str) -> set[str]:
    if purpose == "embedding":
        return {"embedding"}
    if purpose == "rerank":
        return {"rerank"}
    return {"chat", "vision"}


@router.get("/model-routes", response_model=contract.ModelRouteListResponse)
async def list_model_routes(
    purpose: str | None = None,
    admin: Admin = Depends(require_admin_permission("ai_config:read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    del admin
    statement = select(ModelRouteVersion)
    if purpose:
        statement = statement.where(ModelRouteVersion.purpose == purpose)
    rows = list(
        (
            await session.scalars(
                statement.order_by(ModelRouteVersion.purpose, ModelRouteVersion.version_no.desc())
            )
        ).all()
    )
    return {"items": [model_dict(row) for row in rows]}


@router.post("/model-routes", status_code=201, response_model=contract.ModelRouteResource)
async def create_model_route(
    payload: RouteCreate,
    request: Request,
    admin: Admin = Depends(require_admin_permission("ai_config:write")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    deployment_ids = [payload.primary_deployment_id, *payload.fallback_deployment_ids]
    deployments = list(
        (
            await session.scalars(
                select(ModelDeployment).where(ModelDeployment.id.in_(deployment_ids))
            )
        ).all()
    )
    if len({row.id for row in deployments}) != len(set(deployment_ids)):
        raise ApiError(422, "MODEL_DEPLOYMENT_NOT_FOUND", "路由包含不存在的模型部署。")
    expected_types = _route_model_types(payload.purpose)
    if any(row.model_type not in expected_types for row in deployments):
        raise ApiError(422, "MODEL_ROUTE_TYPE_MISMATCH", "路由用途与模型部署类型不匹配。")
    current = await session.scalar(
        select(func.coalesce(func.max(ModelRouteVersion.version_no), 0)).where(
            ModelRouteVersion.purpose == payload.purpose
        )
    )
    route = ModelRouteVersion(
        purpose=payload.purpose,
        version_no=int(current or 0) + 1,
        primary_deployment_id=payload.primary_deployment_id,
        fallback_deployment_ids=payload.fallback_deployment_ids,
        policy=payload.policy,
    )
    session.add(route)
    await session.flush()
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="model_route.create",
        target_type="model_route_version",
        target_id=route.id,
        request_id=request.state.request_id,
        details={"purpose": route.purpose, "version_no": route.version_no},
    )
    await session.commit()
    return model_dict(route)


class PromptBundleCreate(BaseModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,79}$")
    name: str = Field(min_length=1, max_length=120)


class PromptVersionCreate(BaseModel):
    system_template: str = Field(min_length=1, max_length=100_000)
    operation_templates: dict[str, str] = Field(default_factory=dict)
    variable_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)


class PromptVersionPatch(BaseModel):
    system_template: str | None = Field(default=None, min_length=1, max_length=100_000)
    operation_templates: dict[str, str] | None = None
    variable_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None


class ConfigurationTestRequest(BaseModel):
    input: str = Field(
        default="请根据已提供资料生成一段结构清晰、事实可核验的公众号内容。",
        min_length=1,
        max_length=10_000,
    )


def _configuration_schemas_are_valid(*schemas: dict[str, Any]) -> bool:
    """Apply the JSON Schema invariants needed by the runtime without another dependency."""
    return all(
        isinstance(schema, dict)
        and ("type" not in schema or schema["type"] in {"object", "string", "array"})
        and ("properties" not in schema or isinstance(schema["properties"], dict))
        for schema in schemas
    )


async def _run_configuration_model_test(
    *,
    model: ModelProvider,
    safety: ContentSafetyProvider,
    purpose: str,
    prompt: str,
    context: dict[str, Any],
    structural_error: str | None,
) -> dict[str, Any]:
    if structural_error:
        return {
            "passed": False,
            "message": structural_error,
            "provider_request_id": None,
            "input_tokens": None,
            "output_tokens": None,
        }
    try:
        generated = await model.generate(purpose=purpose, prompt=prompt, context=context)
        safe, reason = await safety.check_text(generated.text)
    except ProviderUnavailable:
        return {
            "passed": False,
            "message": "模型或内容安全服务不可用，固定案例未通过。",
            "provider_request_id": None,
            "input_tokens": None,
            "output_tokens": None,
        }
    passed = bool(generated.text.strip()) and safe
    return {
        "passed": passed,
        "message": (
            "固定案例已通过模型生成、非空输出和内容安全检查。"
            if passed
            else f"固定案例未通过内容安全检查：{reason or '模型返回空内容。'}"
        ),
        "provider_request_id": generated.provider_request_id,
        "input_tokens": generated.input_tokens,
        "output_tokens": generated.output_tokens,
    }


@router.get("/prompt-bundles", response_model=contract.PromptBundleListResponse)
async def list_prompt_bundles(
    admin: Admin = Depends(require_admin_permission("prompts:read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    del admin
    rows = list((await session.scalars(select(PromptBundle).order_by(PromptBundle.code))).all())
    return {"items": [model_dict(row) for row in rows]}


@router.post("/prompt-bundles", status_code=201, response_model=contract.PromptBundleResource)
async def create_prompt_bundle(
    payload: PromptBundleCreate,
    request: Request,
    admin: Admin = Depends(require_admin_permission("prompts:write")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    bundle = PromptBundle(code=payload.code, name=payload.name)
    session.add(bundle)
    await session.flush()
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="prompt_bundle.create",
        target_type="prompt_bundle",
        target_id=bundle.id,
        request_id=request.state.request_id,
        details={"code": bundle.code},
    )
    await session.commit()
    return model_dict(bundle)


@router.get("/prompt-bundles/{bundle_id}/versions", response_model=contract.PromptVersionsResponse)
async def list_prompt_versions(
    bundle_id: str,
    admin: Admin = Depends(require_admin_permission("prompts:read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    del admin
    bundle = await session.get(PromptBundle, bundle_id)
    if not bundle:
        raise ApiError(404, "PROMPT_BUNDLE_NOT_FOUND", "提示词集合不存在。")
    versions = list(
        (
            await session.scalars(
                select(PromptVersion)
                .where(PromptVersion.bundle_id == bundle.id)
                .order_by(PromptVersion.version_no.desc())
            )
        ).all()
    )
    return {"bundle": model_dict(bundle), "versions": [model_dict(row) for row in versions]}


@router.post(
    "/prompt-bundles/{bundle_id}/versions",
    status_code=201,
    response_model=contract.PromptVersionResource,
)
async def create_prompt_version(
    bundle_id: str,
    payload: PromptVersionCreate,
    request: Request,
    admin: Admin = Depends(require_admin_permission("prompts:write")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    bundle = await session.get(PromptBundle, bundle_id)
    if not bundle:
        raise ApiError(404, "PROMPT_BUNDLE_NOT_FOUND", "提示词集合不存在。")
    bundle.current_version_no += 1
    checksum = hashlib.sha256(
        json.dumps(payload.model_dump(), sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    version = PromptVersion(
        bundle_id=bundle.id,
        version_no=bundle.current_version_no,
        checksum=checksum,
        **payload.model_dump(),
    )
    session.add(version)
    await session.flush()
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="prompt_version.create",
        target_type="prompt_version",
        target_id=version.id,
        request_id=request.state.request_id,
        details={"bundle_id": bundle.id, "version_no": version.version_no},
    )
    await session.commit()
    return model_dict(version)


@router.patch("/prompt-versions/{version_id}", response_model=contract.PromptVersionResource)
async def patch_prompt_version(
    version_id: str,
    payload: PromptVersionPatch,
    request: Request,
    admin: Admin = Depends(require_admin_permission("prompts:write")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    version = await session.get(PromptVersion, version_id)
    if not version:
        raise ApiError(404, "PROMPT_VERSION_NOT_FOUND", "提示词版本不存在。")
    if version.status not in {"draft", "testing"}:
        raise ApiError(409, "PROMPT_VERSION_IMMUTABLE", "只有草稿或测试版本可以修改。")
    values = payload.model_dump(exclude_unset=True)
    for key, value in values.items():
        setattr(version, key, value)
    checksum_payload = {
        "system_template": version.system_template,
        "operation_templates": version.operation_templates,
        "variable_schema": version.variable_schema,
        "output_schema": version.output_schema,
    }
    version.checksum = hashlib.sha256(
        json.dumps(checksum_payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    version.status = "draft"
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="prompt_version.update",
        target_type="prompt_version",
        target_id=version.id,
        request_id=request.state.request_id,
        details={"fields": sorted(values)},
    )
    await session.commit()
    return model_dict(version)


@router.post("/prompt-versions/{version_id}/test", response_model=contract.ValidationTestResponse)
async def test_prompt_version(
    version_id: str,
    request: Request,
    payload: ConfigurationTestRequest | None = Body(default=None),
    admin: Admin = Depends(require_admin_permission("prompts:test")),
    session: AsyncSession = Depends(get_session),
    model: ModelProvider = Depends(model_provider),
    safety: ContentSafetyProvider = Depends(content_safety_provider),
) -> dict[str, Any]:
    version = await session.get(PromptVersion, version_id)
    if not version:
        raise ApiError(404, "PROMPT_VERSION_NOT_FOUND", "提示词版本不存在。")
    valid_schema = _configuration_schemas_are_valid(version.variable_schema, version.output_schema)
    result = await _run_configuration_model_test(
        model=model,
        safety=safety,
        purpose="prompt_configuration_test",
        prompt=(
            f"{version.system_template}\n\n"
            f"操作模板：{json.dumps(version.operation_templates, ensure_ascii=False)}\n\n"
            f"固定案例输入：{(payload or ConfigurationTestRequest()).input}"
        ),
        context={
            "test_case": "admin_fixed_case",
            "variable_schema": version.variable_schema,
            "output_schema": version.output_schema,
        },
        structural_error=None if valid_schema else "变量或输出 Schema 不是有效对象。",
    )
    version.status = "testing" if result["passed"] else "draft"
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="prompt_version.test",
        target_type="prompt_version",
        target_id=version.id,
        request_id=request.state.request_id,
        details=result,
    )
    await session.commit()
    return result


@router.post("/prompt-versions/{version_id}/publish", response_model=contract.PromptVersionResource)
async def publish_prompt_version(
    version_id: str,
    request: Request,
    admin: Admin = Depends(require_admin_permission("prompts:publish")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    version = await session.get(PromptVersion, version_id)
    if not version:
        raise ApiError(404, "PROMPT_VERSION_NOT_FOUND", "提示词版本不存在。")
    if version.status != "testing":
        raise ApiError(409, "PROMPT_TEST_REQUIRED", "提示词版本需要先通过测试。")
    await session.execute(
        update(PromptVersion)
        .where(
            PromptVersion.bundle_id == version.bundle_id,
            PromptVersion.status == "published",
            PromptVersion.id != version.id,
        )
        .values(status="disabled")
    )
    version.status = "published"
    bundle = await session.get(PromptBundle, version.bundle_id)
    if bundle:
        bundle.status = "published"
        bundle.current_version_no = version.version_no
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="prompt_version.publish",
        target_type="prompt_version",
        target_id=version.id,
        request_id=request.state.request_id,
        details={"version_no": version.version_no},
    )
    await session.commit()
    return model_dict(version)


@router.post("/prompt-versions/{version_id}/disable", response_model=contract.PromptVersionResource)
async def disable_prompt_version(
    version_id: str,
    request: Request,
    admin: Admin = Depends(require_admin_permission("prompts:publish")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    version = await session.get(PromptVersion, version_id)
    if not version:
        raise ApiError(404, "PROMPT_VERSION_NOT_FOUND", "提示词版本不存在。")
    version.status = "disabled"
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="prompt_version.disable",
        target_type="prompt_version",
        target_id=version.id,
        request_id=request.state.request_id,
    )
    await session.commit()
    return model_dict(version)


class OfficialSkillCreate(BaseModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,79}$")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    category: str = Field(default="content", max_length=80)
    sort_order: int = 0


class OfficialSkillVersionCreate(BaseModel):
    instructions: str = Field(min_length=1, max_length=50_000)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    tool_policy: dict[str, Any] = Field(default_factory=dict)


class OfficialSkillVersionPatch(BaseModel):
    instructions: str | None = Field(default=None, min_length=1, max_length=50_000)
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    tool_policy: dict[str, Any] | None = None


class OfficialSkillPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    category: str | None = Field(default=None, max_length=80)
    sort_order: int | None = None


@router.get("/official-skills", response_model=contract.SkillAdminListResponse)
async def list_official_skills(
    admin: Admin = Depends(require_admin_permission("skills:read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    del admin
    rows = list(
        (
            await session.scalars(
                select(Skill)
                .where(Skill.scope == "official", Skill.deleted_at.is_(None))
                .order_by(Skill.sort_order, Skill.created_at)
            )
        ).all()
    )
    return {"items": [model_dict(row) for row in rows]}


@router.patch("/official-skills/{skill_id}", response_model=contract.SkillResource)
async def patch_official_skill(
    skill_id: str,
    payload: OfficialSkillPatch,
    request: Request,
    admin: Admin = Depends(require_admin_permission("skills:write")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    skill = await session.scalar(
        select(Skill).where(Skill.id == skill_id, Skill.scope == "official")
    )
    if not skill:
        raise ApiError(404, "SKILL_NOT_FOUND", "官方技能不存在。")
    values = payload.model_dump(exclude_unset=True)
    for key, value in values.items():
        setattr(skill, key, value)
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="official_skill.update",
        target_type="skill",
        target_id=skill.id,
        request_id=request.state.request_id,
        details={"fields": sorted(values)},
    )
    await session.commit()
    return model_dict(skill)


@router.post("/official-skills", status_code=201, response_model=contract.SkillResource)
async def create_official_skill(
    payload: OfficialSkillCreate,
    request: Request,
    admin: Admin = Depends(require_admin_permission("skills:write")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    skill = Skill(scope="official", owner_id=None, status="draft", **payload.model_dump())
    session.add(skill)
    await session.flush()
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="official_skill.create",
        target_type="skill",
        target_id=skill.id,
        request_id=request.state.request_id,
        details={"code": skill.code},
    )
    await session.commit()
    return model_dict(skill)


@router.get("/jobs", response_model=contract.JobListResponse)
async def list_jobs(
    job_type: str | None = None,
    status: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    admin: Admin = Depends(require_admin_permission("jobs:read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    del admin
    conditions = []
    if job_type:
        conditions.append(JobRecord.job_type == job_type)
    if status:
        conditions.append(JobRecord.status == status)
    rows = list(
        (
            await session.scalars(
                select(JobRecord)
                .where(*conditions)
                .order_by(JobRecord.created_at.desc())
                .limit(limit)
            )
        ).all()
    )
    return {"items": [model_dict(row) for row in rows]}


@router.get("/jobs/{job_id}", response_model=contract.JobResource)
async def get_job(
    job_id: str,
    admin: Admin = Depends(require_admin_permission("jobs:read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    del admin
    job = await session.get(JobRecord, job_id)
    if not job:
        raise ApiError(404, "JOB_NOT_FOUND", "后台任务不存在。")
    return model_dict(job)


class JobActionRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


JOB_RETRY_EVENTS: dict[str, tuple[str, str]] = {
    "ai_generation": ("ai.run.requested", "run_id"),
    "article_revision": ("article.revision.requested", "revision_id"),
    "file_processing": ("document.processing.requested", "document_id"),
    "layout_extraction": ("layout.extraction.requested", "template_id"),
    "wechat_draft": ("wechat.draft.requested", "operation_id"),
    "wechat_publish": ("wechat.publish.requested", "operation_id"),
}


@router.post("/jobs/{job_id}/retry", status_code=202, response_model=contract.JobResource)
async def retry_job(
    job_id: str,
    payload: JobActionRequest,
    request: Request,
    admin: Admin = Depends(require_admin_permission("jobs:retry")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    job = await session.scalar(select(JobRecord).where(JobRecord.id == job_id).with_for_update())
    if not job:
        raise ApiError(404, "JOB_NOT_FOUND", "后台任务不存在。")
    if job.status != "failed":
        raise ApiError(409, "JOB_NOT_RETRYABLE", "只能重试输入已冻结且明确失败的任务。")
    if job.job_type in {"wechat_draft", "wechat_publish"}:
        operation = await session.get(WechatOperation, job.resource_id)
        if operation and operation.status in {"unknown", "reconciling", "submitting"}:
            raise ApiError(
                409,
                "JOB_RECONCILIATION_REQUIRED",
                "微信结果未知，必须先对账，禁止直接重放。",
            )
        if operation:
            operation.status = "queued"
    retry_mapping = JOB_RETRY_EVENTS.get(job.job_type)
    if not retry_mapping:
        raise ApiError(409, "JOB_NOT_RETRYABLE", "该任务类型没有安全的重试路由。")
    job.status = "queued"
    job.stage = "retry_queued"
    job.attempts += 1
    job.error_code = None
    job.error_message = None
    event_type, payload_key = retry_mapping
    frozen_payload = dict(job.frozen_payload)
    frozen_payload.setdefault(payload_key, job.resource_id)
    emit_outbox(
        session,
        event_type=event_type,
        aggregate_type=job.resource_type,
        aggregate_id=job.resource_id,
        payload=frozen_payload,
    )
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="job.retry",
        target_type="job",
        target_id=job.id,
        reason=payload.reason,
        request_id=request.state.request_id,
        details={"attempts": job.attempts, "frozen": True},
    )
    await session.commit()
    return model_dict(job)


@router.post("/jobs/{job_id}/cancel", response_model=contract.JobResource)
async def cancel_job(
    job_id: str,
    payload: JobActionRequest,
    request: Request,
    admin: Admin = Depends(require_admin_permission("jobs:cancel")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    job = await session.scalar(select(JobRecord).where(JobRecord.id == job_id).with_for_update())
    if not job:
        raise ApiError(404, "JOB_NOT_FOUND", "后台任务不存在。")
    if job.status not in {"queued", "retry_queued"}:
        raise ApiError(409, "JOB_NOT_CANCELLABLE", "任务已执行，不能在非安全检查点取消。")
    job.status = "cancelled"
    job.stage = "cancelled"
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="job.cancel",
        target_type="job",
        target_id=job.id,
        reason=payload.reason,
        request_id=request.state.request_id,
    )
    await session.commit()
    return model_dict(job)


@router.post("/jobs/{job_id}/reconcile", status_code=202, response_model=contract.JobResource)
async def reconcile_job(
    job_id: str,
    payload: JobActionRequest,
    request: Request,
    admin: Admin = Depends(require_admin_permission("jobs:reconcile")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    job = await session.scalar(select(JobRecord).where(JobRecord.id == job_id).with_for_update())
    if not job:
        raise ApiError(404, "JOB_NOT_FOUND", "后台任务不存在。")
    if job.status not in {"unknown", "submitting"}:
        raise ApiError(
            409,
            "JOB_RECONCILE_NOT_REQUIRED",
            "只有结果未知或停留在外部提交检查点的任务需要对账。",
        )
    if job.job_type not in {"wechat_draft", "wechat_publish"}:
        raise ApiError(409, "JOB_RECONCILE_UNSUPPORTED", "该任务类型不支持外部结果对账。")
    operation = await session.get(WechatOperation, job.resource_id)
    if not operation:
        raise ApiError(404, "WECHAT_OPERATION_NOT_FOUND", "公众号操作不存在。")
    if not operation.publish_id and not operation.media_id:
        raise ApiError(
            409,
            "WECHAT_RECONCILIATION_ID_MISSING",
            "缺少外部标识，不能安全查询结果，请转人工处理。",
        )
    job.status = "reconciling"
    job.stage = "reconciling"
    operation.status = "reconciling"
    emit_outbox(
        session,
        event_type="wechat.operation.reconcile.requested",
        aggregate_type="wechat_operation",
        aggregate_id=operation.id,
        payload={"operation_id": operation.id},
    )
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="job.reconcile",
        target_type="job",
        target_id=job.id,
        reason=payload.reason,
        request_id=request.state.request_id,
    )
    await session.commit()
    return model_dict(job)


class WechatPlatformConfigUpsert(BaseModel):
    environment: Literal["development", "test", "staging", "production"]
    component_appid: str = Field(min_length=3, max_length=120)
    component_appsecret: SecretStr | None = Field(default=None, min_length=1, max_length=255)
    message_token: SecretStr | None = Field(default=None, min_length=3, max_length=32)
    encoding_aes_key: SecretStr | None = Field(default=None, min_length=43, max_length=43)
    component_secret_ref: str | None = Field(default=None, min_length=5, max_length=255)
    message_token_ref: str | None = Field(default=None, min_length=5, max_length=255)
    encoding_aes_key_ref: str | None = Field(default=None, min_length=5, max_length=255)
    authorization_callback_url: HttpUrl
    ticket_callback_url: HttpUrl
    permission_set: list[str] = Field(default_factory=list)


def _wechat_config_public(config: WechatPlatformConfig) -> dict[str, Any]:
    return {
        "id": config.id,
        "environment": config.environment,
        "component_appid": config.component_appid,
        "component_secret_configured": bool(config.component_secret_ref),
        "message_token_configured": bool(config.message_token_ref),
        "encoding_aes_key_configured": bool(config.encoding_aes_key_ref),
        "authorization_callback_url": config.authorization_callback_url,
        "ticket_callback_url": config.ticket_callback_url,
        "permission_set": config.permission_set,
        "status": config.status,
        "last_ticket_at": config.last_ticket_at,
        "last_token_refresh_at": config.last_token_refresh_at,
        "updated_at": config.updated_at,
    }


@router.get("/wechat-platform-configs", response_model=contract.WechatConfigListResponse)
async def list_wechat_platform_configs(
    admin: Admin = Depends(require_admin_permission("wechat_config:read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    del admin
    rows = list((await session.scalars(select(WechatPlatformConfig))).all())
    return {"items": [_wechat_config_public(row) for row in rows]}


@router.put("/wechat-platform-configs/{environment}", response_model=contract.WechatConfigResponse)
async def upsert_wechat_platform_config(
    environment: str,
    payload: WechatPlatformConfigUpsert,
    request: Request,
    admin: Admin = Depends(require_admin_permission("wechat_config:write")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if payload.environment != environment:
        raise ApiError(422, "ENVIRONMENT_MISMATCH", "配置环境不一致。")
    config = await session.scalar(
        select(WechatPlatformConfig).where(WechatPlatformConfig.environment == environment)
    )
    values = payload.model_dump(
        exclude={"component_appsecret", "message_token", "encoding_aes_key"}
    )
    values["authorization_callback_url"] = str(payload.authorization_callback_url)
    values["ticket_callback_url"] = str(payload.ticket_callback_url)
    incoming_secrets = {
        "component_secret_ref": payload.component_appsecret,
        "message_token_ref": payload.message_token,
        "encoding_aes_key_ref": payload.encoding_aes_key,
    }
    for key, secret in incoming_secrets.items():
        if secret:
            values[key] = request.app.state.secret_provider.protect(secret.get_secret_value())
        elif reference := values.get(key):
            try:
                request.app.state.secret_provider.resolve(reference)
            except ProviderUnavailable as exc:
                raise ApiError(
                    422,
                    "WECHAT_CONFIG_SECRET_UNAVAILABLE",
                    "微信平台密钥引用不可用。",
                ) from exc
    if not config:
        if not all(
            (
                values.get("component_secret_ref"),
                values.get("message_token_ref"),
                values.get("encoding_aes_key_ref"),
            )
        ):
            raise ApiError(
                422,
                "WECHAT_CONFIG_SECRETS_REQUIRED",
                "首次创建配置必须提供全部密钥引用。",
            )
        config = WechatPlatformConfig(**values)
        session.add(config)
    else:
        connection_changed = any(
            value is not None and value != getattr(config, key)
            for key, value in values.items()
            if key
            in {
                "component_appid",
                "component_secret_ref",
                "message_token_ref",
                "encoding_aes_key_ref",
            }
        )
        for key, value in values.items():
            if value is not None:
                setattr(config, key, value)
        if connection_changed:
            config.component_verify_ticket_ref = None
            config.component_access_token_ref = None
            config.component_access_token_expires_at = None
            config.last_ticket_at = None
            config.last_token_refresh_at = None
        config.status = "draft"
    await session.flush()
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="wechat_platform_config.update",
        target_type="wechat_platform_config",
        target_id=config.id,
        request_id=request.state.request_id,
        details={"environment": environment, "secret_values_logged": False},
    )
    await session.commit()
    return _wechat_config_public(config)


@router.post(
    "/wechat-platform-configs/{environment}/test",
    response_model=contract.WechatConfigTestResponse,
)
async def test_wechat_platform_config(
    environment: str,
    request: Request,
    admin: Admin = Depends(require_admin_permission("wechat_config:test")),
    session: AsyncSession = Depends(get_session),
    secrets: SecretProvider = Depends(secret_provider),
) -> dict[str, Any]:
    config = await session.scalar(
        select(WechatPlatformConfig).where(WechatPlatformConfig.environment == environment)
    )
    if not config:
        raise ApiError(404, "WECHAT_CONFIG_NOT_FOUND", "微信平台配置不存在。")
    try:
        for reference in (
            config.component_secret_ref,
            config.message_token_ref,
            config.encoding_aes_key_ref,
        ):
            secrets.resolve(reference)
        if not config.component_verify_ticket_ref:
            raise ProviderUnavailable("component_verify_ticket is missing")
        await component_access_token(
            session,
            config=config,
            secrets=secrets,
            client=WechatOpenPlatformClient(),
        )
        secrets_available = True
        passed = True
        message = "微信票据、平台 Token 和加解密配置验证通过，可以发布。"
    except ProviderUnavailable:
        secrets_available = False
        passed = False
        message = "验证未通过：请检查密钥，并确认微信已向票据回调地址推送 Ticket。"
    result = {
        "passed": passed,
        "secrets_available": secrets_available,
        "message": message,
    }
    config.status = "testing" if passed else "draft"
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="wechat_platform_config.test",
        target_type="wechat_platform_config",
        target_id=config.id,
        request_id=request.state.request_id,
        details=result,
    )
    await session.commit()
    return result


@router.post(
    "/wechat-platform-configs/{environment}/publish",
    response_model=contract.WechatConfigResponse,
)
async def publish_wechat_platform_config(
    environment: str,
    request: Request,
    admin: Admin = Depends(require_admin_permission("wechat_config:publish")),
    session: AsyncSession = Depends(get_session),
    secrets: SecretProvider = Depends(secret_provider),
) -> dict[str, Any]:
    config = await session.scalar(
        select(WechatPlatformConfig).where(WechatPlatformConfig.environment == environment)
    )
    if not config:
        raise ApiError(404, "WECHAT_CONFIG_NOT_FOUND", "微信平台配置不存在。")
    if config.status != "testing" or not config.last_ticket_at:
        raise ApiError(
            409,
            "WECHAT_CONFIG_TEST_REQUIRED",
            "配置必须完成密钥检查并收到真实票据回调后才能发布。",
        )
    try:
        for reference in (
            config.component_secret_ref,
            config.message_token_ref,
            config.encoding_aes_key_ref,
        ):
            secrets.resolve(reference)
    except ProviderUnavailable as exc:
        raise ApiError(409, "WECHAT_CONFIG_SECRET_UNAVAILABLE", "微信平台密钥引用不可用。") from exc
    if environment == "production" and (
        not config.authorization_callback_url.startswith("https://")
        or not config.ticket_callback_url.startswith("https://")
    ):
        raise ApiError(422, "WECHAT_CONFIG_HTTPS_REQUIRED", "生产回调地址必须使用 HTTPS。")
    config.status = "published"
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="wechat_platform_config.publish",
        target_type="wechat_platform_config",
        target_id=config.id,
        request_id=request.state.request_id,
        details={"environment": environment, "last_ticket_at": config.last_ticket_at.isoformat()},
    )
    await session.commit()
    return _wechat_config_public(config)


@router.get("/official-accounts", response_model=contract.AdminOfficialAccountListResponse)
async def admin_list_official_accounts(
    status: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    admin: Admin = Depends(require_admin_permission("wechat_accounts:read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    del admin
    statement = select(OfficialAccount).where(OfficialAccount.deleted_at.is_(None))
    if status:
        statement = statement.where(OfficialAccount.status == status)
    rows = list(
        (
            await session.scalars(
                statement.order_by(OfficialAccount.updated_at.desc()).limit(limit)
            )
        ).all()
    )
    return {
        "items": [
            model_dict(row, exclude={"token_secret_ref", "technical_metadata"}) for row in rows
        ]
    }


@router.post(
    "/official-accounts/{account_id}/refresh",
    response_model=contract.AdminOfficialAccountResource,
)
async def refresh_official_account(
    account_id: str,
    payload: JobActionRequest,
    request: Request,
    admin: Admin = Depends(require_admin_permission("wechat_accounts:write")),
    session: AsyncSession = Depends(get_session),
    provider: WechatProvider = Depends(wechat_provider),
) -> dict[str, Any]:
    account = await session.scalar(
        select(OfficialAccount)
        .where(OfficialAccount.id == account_id, OfficialAccount.deleted_at.is_(None))
        .with_for_update()
    )
    if not account:
        raise ApiError(404, "OFFICIAL_ACCOUNT_NOT_FOUND", "公众号连接不存在。")
    if account.status == "reconnect_required" or not account.token_secret_ref:
        raise ApiError(409, "WECHAT_RECONNECT_REQUIRED", "授权已失效，需要用户重新连接。")
    try:
        result = await provider.refresh_account(account_ref=account.token_secret_ref)
    except ProviderResultUnknown as exc:
        account.status = "limited"
        account.technical_metadata = {
            **account.technical_metadata,
            "last_refresh_state": "unknown",
            "last_refresh_external_id": exc.external_id,
        }
    except ProviderUnavailable as exc:
        raise ApiError(
            503,
            "WECHAT_PROVIDER_UNAVAILABLE",
            "微信平台暂不可用，请稍后重试。",
            retryable=True,
        ) from exc
    else:
        if result.status == "succeeded":
            account.status = "connected"
            account.last_synced_at = utcnow()
            details = result.details or {}
            expires_in = details.get("expires_in_seconds")
            if isinstance(expires_in, int) and expires_in > 0:
                account.token_expires_at = utcnow() + timedelta(seconds=expires_in)
            capabilities = details.get("capability_flags")
            if isinstance(capabilities, list) and all(
                isinstance(item, str) for item in capabilities
            ):
                account.capability_flags = capabilities
            account.technical_metadata = {
                **account.technical_metadata,
                "last_refresh_state": "succeeded",
            }
        else:
            account.status = "limited"
            account.technical_metadata = {
                **account.technical_metadata,
                "last_refresh_state": result.status,
            }
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="official_account.refresh",
        target_type="official_account",
        target_id=account.id,
        reason=payload.reason,
        request_id=request.state.request_id,
        details={"status": account.status},
    )
    await session.commit()
    return model_dict(account, exclude={"token_secret_ref", "technical_metadata"})


@router.post(
    "/official-accounts/{account_id}/mark-reconnect",
    response_model=contract.AdminOfficialAccountResource,
)
async def mark_official_account_reconnect(
    account_id: str,
    payload: JobActionRequest,
    request: Request,
    admin: Admin = Depends(require_admin_permission("wechat_accounts:write")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    account = await session.scalar(
        select(OfficialAccount)
        .where(OfficialAccount.id == account_id, OfficialAccount.deleted_at.is_(None))
        .with_for_update()
    )
    if not account:
        raise ApiError(404, "OFFICIAL_ACCOUNT_NOT_FOUND", "公众号连接不存在。")
    account.status = "reconnect_required"
    account.token_secret_ref = None
    account.token_expires_at = None
    account.capability_flags = []
    account.technical_metadata = {
        **account.technical_metadata,
        "reconnect_marked_at": utcnow().isoformat(),
    }
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="official_account.mark_reconnect",
        target_type="official_account",
        target_id=account.id,
        reason=payload.reason,
        request_id=request.state.request_id,
    )
    await session.commit()
    return model_dict(account, exclude={"token_secret_ref", "technical_metadata"})


SystemSettingsSection = Literal["home", "files", "ai", "articles", "wechat", "features"]
SYSTEM_SETTINGS_SECTION_ORDER: tuple[SystemSettingsSection, ...] = (
    "home",
    "files",
    "ai",
    "articles",
    "wechat",
    "features",
)
SYSTEM_SETTINGS_SECTIONS = set(SYSTEM_SETTINGS_SECTION_ORDER)


class SystemSettingCreate(BaseModel):
    section: SystemSettingsSection
    values: dict[str, Any]


class LexiangTarget(BaseModel):
    type: Literal["team", "space", "kb_entry"]
    id: str = Field(min_length=1, max_length=180)


class ExternalKnowledgeSourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    app_key: str = Field(min_length=3, max_length=255)
    secret_ref: str = Field(min_length=5, max_length=255)
    targets: list[LexiangTarget] = Field(min_length=1, max_length=20)
    owner_staff_ids: dict[str, str] = Field(min_length=1)
    sync_owner_id: str


class ExternalKnowledgeSourcePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    app_key: str | None = Field(default=None, min_length=3, max_length=255)
    secret_ref: str | None = Field(default=None, min_length=5, max_length=255)
    targets: list[LexiangTarget] | None = Field(default=None, min_length=1, max_length=20)
    owner_staff_ids: dict[str, str] | None = Field(default=None, min_length=1)
    sync_owner_id: str | None = None
    status: Literal["active", "disabled"] | None = None
    reason: str = Field(min_length=3, max_length=500)


class WechatArticleApiCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    base_url: HttpUrl
    priority: int = Field(default=100, ge=1, le=999)
    api_key: SecretStr | None = None
    auth_header: str = Field(default="X-Auth-Key", pattern=r"^[A-Za-z0-9-]+$", max_length=80)
    auth_prefix: str = Field(default="", max_length=32)


class WechatArticleApiPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    base_url: HttpUrl | None = None
    priority: int | None = Field(default=None, ge=1, le=999)
    api_key: SecretStr | None = None
    clear_api_key: bool = False
    auth_header: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9-]+$", max_length=80
    )
    auth_prefix: str | None = Field(default=None, max_length=32)
    status: Literal["active", "disabled"] | None = None
    reason: str = Field(min_length=3, max_length=500)


class WechatArticleApiTestRequest(BaseModel):
    source_url: HttpUrl


def _external_source_public(source: ExternalKnowledgeSource) -> dict[str, Any]:
    return {
        "id": source.id,
        "source_type": source.source_type,
        "name": source.name,
        "app_key": source.configuration.get("app_key", ""),
        "secret_configured": bool(source.secret_ref),
        "targets": source.scope.get("targets", []),
        "owner_staff_ids": source.scope.get("owner_staff_ids", {}),
        "sync_owner_id": source.scope.get("sync_owner_id"),
        "status": source.status,
        "last_tested_at": source.last_tested_at,
        "last_test_result": source.last_test_result,
        "last_synced_at": source.last_synced_at,
        "error_code": source.error_code,
        "created_at": source.created_at,
        "updated_at": source.updated_at,
    }


def _wechat_article_api_public(source: ExternalKnowledgeSource) -> dict[str, Any]:
    configuration = source.configuration
    return {
        "id": source.id,
        "name": source.name,
        "base_url": configuration.get("base_url", ""),
        "priority": configuration.get("priority", 100),
        "auth_header": configuration.get("auth_header", "X-Auth-Key"),
        "auth_prefix": configuration.get("auth_prefix", ""),
        "secret_configured": bool(source.secret_ref),
        "status": source.status,
        "is_default": bool(configuration.get("is_default")),
        "last_tested_at": source.last_tested_at,
        "last_test_result": source.last_test_result,
        "error_code": source.error_code,
        "created_at": source.created_at,
        "updated_at": source.updated_at,
    }


@router.get(
    "/external-knowledge-sources",
    response_model=contract.ExternalKnowledgeSourceListResponse,
)
async def list_external_knowledge_sources(
    admin: Admin = Depends(require_admin_permission("settings:read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    del admin
    rows = list(
        (
            await session.scalars(
                select(ExternalKnowledgeSource)
                .where(ExternalKnowledgeSource.source_type == "lexiang")
                .order_by(ExternalKnowledgeSource.created_at)
            )
        ).all()
    )
    return {"items": [_external_source_public(row) for row in rows]}


@router.get(
    "/wechat-article-apis",
    response_model=contract.WechatArticleApiListResponse,
)
async def list_wechat_article_apis(
    admin: Admin = Depends(require_admin_permission("settings:read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    del admin
    rows = list(
        (
            await session.scalars(
                select(ExternalKnowledgeSource)
                .where(ExternalKnowledgeSource.source_type == "wechat_article_api")
                .order_by(ExternalKnowledgeSource.created_at)
            )
        ).all()
    )
    rows.sort(key=lambda item: int(item.configuration.get("priority", 100)))
    return {"items": [_wechat_article_api_public(row) for row in rows]}


@router.post(
    "/wechat-article-apis",
    status_code=201,
    response_model=contract.WechatArticleApiResponse,
)
async def create_wechat_article_api(
    payload: WechatArticleApiCreate,
    request: Request,
    admin: Admin = Depends(require_admin_permission("settings:write")),
    session: AsyncSession = Depends(get_session),
    secrets: SecretProvider = Depends(secret_provider),
) -> dict[str, Any]:
    source = ExternalKnowledgeSource(
        source_type="wechat_article_api",
        name=payload.name.strip(),
        configuration={
            "base_url": str(payload.base_url),
            "priority": payload.priority,
            "auth_header": payload.auth_header,
            "auth_prefix": payload.auth_prefix,
            "is_default": False,
        },
        secret_ref=(
            secrets.protect(payload.api_key.get_secret_value()) if payload.api_key else None
        ),
        scope={},
        status="disabled",
    )
    session.add(source)
    await session.flush()
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="wechat_article_api.create",
        target_type="wechat_article_api",
        target_id=source.id,
        request_id=request.state.request_id,
        details={"base_url": str(payload.base_url), "priority": payload.priority},
    )
    await session.commit()
    return _wechat_article_api_public(source)


@router.patch(
    "/wechat-article-apis/{source_id}",
    response_model=contract.WechatArticleApiResponse,
)
async def patch_wechat_article_api(
    source_id: str,
    payload: WechatArticleApiPatch,
    request: Request,
    admin: Admin = Depends(require_admin_permission("settings:write")),
    session: AsyncSession = Depends(get_session),
    secrets: SecretProvider = Depends(secret_provider),
) -> dict[str, Any]:
    source = await session.get(ExternalKnowledgeSource, source_id)
    if not source or source.source_type != "wechat_article_api":
        raise ApiError(404, "WECHAT_ARTICLE_API_NOT_FOUND", "正文 API 配置不存在。")
    configuration = dict(source.configuration)
    if payload.name is not None:
        source.name = payload.name.strip()
    if payload.base_url is not None:
        configuration["base_url"] = str(payload.base_url)
    if payload.priority is not None:
        configuration["priority"] = payload.priority
    if payload.auth_header is not None:
        configuration["auth_header"] = payload.auth_header
    if payload.auth_prefix is not None:
        configuration["auth_prefix"] = payload.auth_prefix
    if payload.api_key is not None:
        source.secret_ref = secrets.protect(payload.api_key.get_secret_value())
    elif payload.clear_api_key:
        source.secret_ref = None
    if payload.status is not None:
        source.status = payload.status
    source.configuration = configuration
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="wechat_article_api.update",
        target_type="wechat_article_api",
        target_id=source.id,
        reason=payload.reason,
        request_id=request.state.request_id,
        details={
            "status": payload.status,
            "priority": payload.priority,
            "secret_replaced": payload.api_key is not None,
            "secret_cleared": payload.clear_api_key,
        },
    )
    await session.commit()
    return _wechat_article_api_public(source)


@router.post(
    "/wechat-article-apis/{source_id}/test",
    response_model=contract.ValidationTestResponse,
)
async def test_wechat_article_api(
    source_id: str,
    payload: WechatArticleApiTestRequest,
    request: Request,
    admin: Admin = Depends(require_admin_permission("settings:write")),
    session: AsyncSession = Depends(get_session),
    secrets: SecretProvider = Depends(secret_provider),
) -> dict[str, Any]:
    source = await session.get(ExternalKnowledgeSource, source_id)
    if not source or source.source_type != "wechat_article_api":
        raise ApiError(404, "WECHAT_ARTICLE_API_NOT_FOUND", "正文 API 配置不存在。")
    configuration = source.configuration
    try:
        api_key = secrets.resolve(source.secret_ref) if source.secret_ref else None
        result = await WeChatPublicLayoutExtractionProvider(
            article_apis=[
                WeChatArticleApiConfig(
                    name=source.name,
                    base_url=str(configuration.get("base_url", "")),
                    priority=int(configuration.get("priority", 100)),
                    api_key=api_key,
                    auth_header=str(configuration.get("auth_header", "X-Auth-Key")),
                    auth_prefix=str(configuration.get("auth_prefix", "")),
                )
            ],
            direct_fallback=False,
        ).fetch_reference(source_url=str(payload.source_url))
        test_result = {
            "passed": True,
            "message": f"连接成功，已读取《{result.title}》（{len(result.text)} 字）。",
        }
        source.error_code = None
    except ProviderUnavailable:
        test_result = {
            "passed": False,
            "message": "连接失败，请检查接口地址、密钥、额度和文章链接。",
        }
        source.error_code = "WECHAT_ARTICLE_API_TEST_FAILED"
    source.last_tested_at = utcnow()
    source.last_test_result = test_result
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="wechat_article_api.test",
        target_type="wechat_article_api",
        target_id=source.id,
        request_id=request.state.request_id,
        details={"passed": test_result["passed"]},
    )
    await session.commit()
    return test_result


@router.post(
    "/external-knowledge-sources",
    status_code=201,
    response_model=contract.ExternalKnowledgeSourceResponse,
)
async def create_external_knowledge_source(
    payload: ExternalKnowledgeSourceCreate,
    request: Request,
    admin: Admin = Depends(require_admin_permission("settings:write")),
    session: AsyncSession = Depends(get_session),
    secrets: SecretProvider = Depends(secret_provider),
) -> dict[str, Any]:
    try:
        secrets.resolve(payload.secret_ref)
    except ProviderUnavailable as exc:
        raise ApiError(422, "LEXIANG_SECRET_UNAVAILABLE", "乐享 Secret 引用不可用。") from exc
    if payload.sync_owner_id not in payload.owner_staff_ids:
        raise ApiError(
            422,
            "LEXIANG_SYNC_OWNER_INVALID",
            "本地同步所有者必须存在对应的乐享成员帐号映射。",
        )
    source = ExternalKnowledgeSource(
        source_type="lexiang",
        name=payload.name,
        configuration={"app_key": payload.app_key},
        secret_ref=payload.secret_ref,
        scope={
            "targets": [item.model_dump() for item in payload.targets],
            "owner_staff_ids": payload.owner_staff_ids,
            "sync_owner_id": payload.sync_owner_id,
        },
        status="disabled",
    )
    session.add(source)
    await session.flush()
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="external_knowledge_source.create",
        target_type="external_knowledge_source",
        target_id=source.id,
        request_id=request.state.request_id,
        details={"target_count": len(payload.targets), "owner_count": len(payload.owner_staff_ids)},
    )
    await session.commit()
    return _external_source_public(source)


@router.patch(
    "/external-knowledge-sources/{source_id}",
    response_model=contract.ExternalKnowledgeSourceResponse,
)
async def patch_external_knowledge_source(
    source_id: str,
    payload: ExternalKnowledgeSourcePatch,
    request: Request,
    admin: Admin = Depends(require_admin_permission("settings:write")),
    session: AsyncSession = Depends(get_session),
    secrets: SecretProvider = Depends(secret_provider),
) -> dict[str, Any]:
    source = await session.get(ExternalKnowledgeSource, source_id)
    if not source or source.source_type != "lexiang":
        raise ApiError(404, "EXTERNAL_KNOWLEDGE_SOURCE_NOT_FOUND", "外部知识源不存在。")
    if payload.secret_ref:
        try:
            secrets.resolve(payload.secret_ref)
        except ProviderUnavailable as exc:
            raise ApiError(422, "LEXIANG_SECRET_UNAVAILABLE", "乐享 Secret 引用不可用。") from exc
        source.secret_ref = payload.secret_ref
    if payload.name is not None:
        source.name = payload.name
    if payload.app_key is not None:
        source.configuration = {**source.configuration, "app_key": payload.app_key}
    if payload.targets is not None:
        source.scope = {
            **source.scope,
            "targets": [item.model_dump() for item in payload.targets],
        }
    if payload.owner_staff_ids is not None:
        source.scope = {**source.scope, "owner_staff_ids": payload.owner_staff_ids}
    if payload.sync_owner_id is not None:
        owner_staff_ids = payload.owner_staff_ids or source.scope.get("owner_staff_ids", {})
        if payload.sync_owner_id not in owner_staff_ids:
            raise ApiError(
                422,
                "LEXIANG_SYNC_OWNER_INVALID",
                "本地同步所有者必须存在对应的乐享成员帐号映射。",
            )
        source.scope = {**source.scope, "sync_owner_id": payload.sync_owner_id}
    if payload.status is not None:
        if payload.status == "active" and not source.last_test_result.get("passed"):
            raise ApiError(409, "LEXIANG_TEST_REQUIRED", "启用前必须先通过连接测试。")
        source.status = payload.status
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="external_knowledge_source.update",
        target_type="external_knowledge_source",
        target_id=source.id,
        reason=payload.reason,
        request_id=request.state.request_id,
        details={"status": payload.status, "secret_replaced": payload.secret_ref is not None},
    )
    await session.commit()
    return _external_source_public(source)


@router.post(
    "/external-knowledge-sources/{source_id}/test",
    response_model=contract.ValidationTestResponse,
)
async def test_external_knowledge_source(
    source_id: str,
    request: Request,
    admin: Admin = Depends(require_admin_permission("settings:write")),
    session: AsyncSession = Depends(get_session),
    secrets: SecretProvider = Depends(secret_provider),
) -> dict[str, Any]:
    source = await session.get(ExternalKnowledgeSource, source_id)
    app_key = source.configuration.get("app_key") if source else None
    if not source or source.source_type != "lexiang" or not source.secret_ref:
        raise ApiError(404, "EXTERNAL_KNOWLEDGE_SOURCE_NOT_FOUND", "外部知识源不存在。")
    try:
        provider = LexiangKnowledgeProvider(
            app_key=str(app_key), app_secret=secrets.resolve(source.secret_ref)
        )
        await provider.test_connection()
        result = {
            "passed": True,
            "message": "乐享 AppKey、Secret 和 access_token 获取测试通过。",
        }
        source.error_code = None
    except ProviderUnavailable:
        result = {
            "passed": False,
            "message": "乐享连接测试失败，请检查凭据、接口权限和授权范围。",
        }
        source.error_code = "LEXIANG_CONNECTION_FAILED"
    source.last_tested_at = utcnow()
    source.last_test_result = result
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="external_knowledge_source.test",
        target_type="external_knowledge_source",
        target_id=source.id,
        request_id=request.state.request_id,
        details={"passed": result["passed"]},
    )
    await session.commit()
    return result


@router.post(
    "/external-knowledge-sources/{source_id}/sync",
    status_code=202,
    response_model=contract.JobResource,
)
async def request_external_knowledge_sync(
    source_id: str,
    payload: JobActionRequest,
    request: Request,
    admin: Admin = Depends(require_admin_permission("settings:write")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    source = await session.get(ExternalKnowledgeSource, source_id)
    if not source or source.source_type != "lexiang":
        raise ApiError(404, "EXTERNAL_KNOWLEDGE_SOURCE_NOT_FOUND", "外部知识源不存在。")
    if source.status != "active":
        raise ApiError(409, "EXTERNAL_KNOWLEDGE_SOURCE_DISABLED", "请先测试并启用知识源。")
    job = create_job(
        session,
        owner_id=(
            str(source.scope["sync_owner_id"])
            if isinstance(source.scope.get("sync_owner_id"), str)
            else None
        ),
        job_type="external_knowledge_sync",
        resource_type="external_knowledge_source",
        resource_id=source.id,
        queue="sync",
        stage="queued",
        frozen_payload={"source_id": source.id},
    )
    emit_outbox(
        session,
        event_type="external_knowledge.sync.requested",
        aggregate_type="external_knowledge_source",
        aggregate_id=source.id,
        payload={"source_id": source.id},
    )
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="external_knowledge_source.sync_request",
        target_type="external_knowledge_source",
        target_id=source.id,
        reason=payload.reason,
        request_id=request.state.request_id,
    )
    await session.commit()
    return model_dict(job)


class SystemSettingsBundleRequest(BaseModel):
    sections: dict[str, dict[str, Any]]


class SystemSettingsBulkPublishRequest(BaseModel):
    setting_ids: list[str] = Field(min_length=6, max_length=6)
    reason: str = Field(min_length=3, max_length=500)


def _system_setting_checks(sections: Mapping[str, dict[str, Any]]) -> list[str]:
    if set(sections) != SYSTEM_SETTINGS_SECTIONS:
        return ["必须同时提供 home、files、ai、articles、wechat 和 features 六个设置分区。"]
    try:
        ai_run_credit_cost(sections["ai"])
        ai_credit_cost_valid = True
    except ValueError:
        ai_credit_cost_valid = False
    checks: list[tuple[bool, str]] = [
        (bool(str(sections["home"].get("welcome_message", "")).strip()), "首页欢迎语不能为空。"),
        (bool(sections["home"].get("example_prompts")), "首页至少需要一条示例指令。"),
        (bool(sections["files"].get("allowed_extensions")), "至少需要允许一种文件格式。"),
        (
            isinstance(sections["files"].get("max_file_mb"), int)
            and 1 <= sections["files"]["max_file_mb"] <= 2048,
            "单文件大小必须在 1—2048 MB 之间。",
        ),
        (
            isinstance(sections["ai"].get("min_article_length"), int)
            and isinstance(sections["ai"].get("max_article_length"), int)
            and sections["ai"]["min_article_length"] < sections["ai"]["max_article_length"],
            "文章最小长度必须小于最大长度。",
        ),
        (ai_credit_cost_valid, "单次 AI 运行积分必须是 0—10000 之间的整数。"),
        (
            isinstance(sections["articles"].get("autosave_seconds"), int)
            and 5 <= sections["articles"]["autosave_seconds"] <= 300,
            "自动保存间隔必须在 5—300 秒之间。",
        ),
        (
            not sections["wechat"].get("wechat_publish_enabled")
            or bool(sections["wechat"].get("wechat_draft_enabled")),
            "开启正式发布时必须同时开启公众号草稿能力。",
        ),
        (
            isinstance(sections["features"].get("feature_flags"), dict)
            and all(
                isinstance(value, bool)
                for value in sections["features"].get("feature_flags", {}).values()
            ),
            "功能开关必须是布尔值。",
        ),
    ]
    return [message for passed, message in checks if not passed]


@router.get("/system-settings", response_model=contract.SystemSettingListResponse)
async def list_system_settings(
    section: str | None = None,
    admin: Admin = Depends(require_admin_permission("settings:read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    del admin
    statement = select(SystemSetting)
    if section:
        statement = statement.where(SystemSetting.section == section)
    rows = list(
        (
            await session.scalars(
                statement.order_by(SystemSetting.section, SystemSetting.version_no.desc())
            )
        ).all()
    )
    return {"items": [model_dict(row) for row in rows]}


@router.post("/system-settings", status_code=201, response_model=contract.SystemSettingResource)
async def create_system_setting(
    payload: SystemSettingCreate,
    request: Request,
    admin: Admin = Depends(require_admin_permission("settings:write")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if payload.section == "ai":
        try:
            ai_run_credit_cost(payload.values)
        except ValueError as exc:
            raise ApiError(
                422,
                "SYSTEM_SETTINGS_INVALID",
                "系统设置未通过服务端校验。",
                details={"errors": [str(exc)]},
            ) from exc
    current = await session.scalar(
        select(func.coalesce(func.max(SystemSetting.version_no), 0)).where(
            SystemSetting.section == payload.section
        )
    )
    setting = SystemSetting(
        section=payload.section,
        version_no=int(current or 0) + 1,
        values=payload.values,
        created_by_admin_id=admin.id,
    )
    session.add(setting)
    await session.flush()
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="system_setting.create",
        target_type="system_setting",
        target_id=setting.id,
        request_id=request.state.request_id,
        details={"section": setting.section, "version_no": setting.version_no},
    )
    await session.commit()
    return model_dict(setting)


@router.post(
    "/system-settings/validate",
    response_model=contract.SystemSettingsValidationResponse,
)
async def validate_system_settings(
    payload: SystemSettingsBundleRequest,
    admin: Admin = Depends(require_admin_permission("settings:write")),
) -> dict[str, Any]:
    del admin
    errors = _system_setting_checks(payload.sections)
    return {
        "passed": not errors,
        "checks": errors or ["首页、文件、AI、文章、公众号和功能开关的服务端检查全部通过。"],
    }


@router.post(
    "/system-settings/bulk-drafts",
    status_code=201,
    response_model=contract.SystemSettingBundleResponse,
)
async def create_system_setting_bundle(
    payload: SystemSettingsBundleRequest,
    request: Request,
    admin: Admin = Depends(require_admin_permission("settings:write")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    errors = _system_setting_checks(payload.sections)
    if errors:
        raise ApiError(
            422,
            "SYSTEM_SETTINGS_INVALID",
            "系统设置未通过服务端校验。",
            details={"errors": errors},
        )
    created: list[SystemSetting] = []
    for section in SYSTEM_SETTINGS_SECTION_ORDER:
        current = await session.scalar(
            select(func.coalesce(func.max(SystemSetting.version_no), 0)).where(
                SystemSetting.section == section
            )
        )
        setting = SystemSetting(
            section=section,
            version_no=int(current or 0) + 1,
            values=payload.sections[section],
            created_by_admin_id=admin.id,
        )
        session.add(setting)
        created.append(setting)
    await session.flush()
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="system_settings.bundle_create",
        target_type="system_setting_bundle",
        target_id=created[0].id,
        request_id=request.state.request_id,
        details={"setting_ids": [row.id for row in created]},
    )
    await session.commit()
    return {"items": [model_dict(row) for row in created]}


class AdminCreate(BaseModel):
    username: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{2,79}$")
    password: str = Field(min_length=12, max_length=128)
    permissions: list[str] = Field(default_factory=list)


class AdminPatch(BaseModel):
    status: Literal["active", "disabled"] | None = None
    permissions: list[str] | None = None
    reason: str = Field(min_length=3, max_length=500)


@router.get("/admins", response_model=contract.AdminListResponse)
async def list_admins(
    admin: Admin = Depends(require_admin_permission("admins:read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    del admin
    rows = list((await session.scalars(select(Admin).order_by(Admin.created_at))).all())
    return {
        "items": [
            {
                "id": row.id,
                "username": row.username,
                "status": row.status,
                "permissions": row.permissions,
                "last_login_at": row.last_login_at,
                "created_at": row.created_at,
            }
            for row in rows
        ]
    }


@router.post("/admins", status_code=201, response_model=contract.AdminCreatedResponse)
async def create_admin(
    payload: AdminCreate,
    request: Request,
    admin: Admin = Depends(require_admin_permission("admins:write")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    row = Admin(
        username=payload.username,
        password_hash=hash_password(payload.password),
        permissions=payload.permissions,
    )
    session.add(row)
    await session.flush()
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="admin.create",
        target_type="admin",
        target_id=row.id,
        request_id=request.state.request_id,
        details={"username": row.username, "permissions": row.permissions},
    )
    await session.commit()
    return {"id": row.id, "username": row.username, "status": row.status}


@router.patch("/admins/{admin_id}", response_model=contract.AdminPatchedResponse)
async def patch_admin(
    admin_id: str,
    payload: AdminPatch,
    request: Request,
    admin: Admin = Depends(require_admin_permission("admins:write")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    row = await session.get(Admin, admin_id)
    if not row:
        raise ApiError(404, "ADMIN_NOT_FOUND", "管理员不存在。")
    if payload.status == "disabled" and row.id == admin.id:
        raise ApiError(409, "CANNOT_DISABLE_SELF", "不能停用当前登录管理员。")
    if payload.permissions is not None:
        row.permissions = payload.permissions
    if payload.status is not None:
        row.status = payload.status
        if payload.status == "disabled":
            await session.execute(
                update(AdminSession)
                .where(AdminSession.admin_id == row.id, AdminSession.revoked_at.is_(None))
                .values(revoked_at=utcnow())
            )
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="admin.update",
        target_type="admin",
        target_id=row.id,
        reason=payload.reason,
        request_id=request.state.request_id,
        details={
            "status": payload.status,
            "permissions_changed": payload.permissions is not None,
        },
    )
    await session.commit()
    return {
        "id": row.id,
        "username": row.username,
        "status": row.status,
        "permissions": row.permissions,
    }


@router.get("/audit-logs", response_model=contract.AuditLogListResponse)
async def list_audit_logs(
    actor_id: str | None = None,
    action: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    admin: Admin = Depends(require_admin_permission("audit:read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    del admin
    conditions = []
    if actor_id:
        conditions.append(AuditLog.actor_id == actor_id)
    if action:
        conditions.append(AuditLog.action == action)
    rows = list(
        (
            await session.scalars(
                select(AuditLog)
                .where(*conditions)
                .order_by(AuditLog.created_at.desc())
                .limit(limit)
            )
        ).all()
    )
    return {"items": [model_dict(row) for row in rows]}


@router.post(
    "/system-settings/bulk-publish",
    response_model=contract.SystemSettingBundleResponse,
)
async def publish_system_setting_bundle(
    payload: SystemSettingsBulkPublishRequest,
    request: Request,
    admin: Admin = Depends(require_admin_permission("settings:publish")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if len(set(payload.setting_ids)) != 6:
        raise ApiError(422, "SYSTEM_SETTINGS_BUNDLE_INVALID", "设置版本 ID 必须互不重复。")
    rows = list(
        (
            await session.scalars(
                select(SystemSetting)
                .where(SystemSetting.id.in_(payload.setting_ids))
                .with_for_update()
            )
        ).all()
    )
    if len(rows) != 6 or {row.section for row in rows} != SYSTEM_SETTINGS_SECTIONS:
        raise ApiError(
            422,
            "SYSTEM_SETTINGS_BUNDLE_INVALID",
            "必须选择六个完整且互不重复的设置分区版本。",
        )
    errors = _system_setting_checks({row.section: row.values for row in rows})
    if errors:
        raise ApiError(
            422,
            "SYSTEM_SETTINGS_INVALID",
            "系统设置未通过服务端校验。",
            details={"errors": errors},
        )
    published_at = utcnow()
    for row in rows:
        await session.execute(
            update(SystemSetting)
            .where(
                SystemSetting.section == row.section,
                SystemSetting.status == "published",
                SystemSetting.id != row.id,
            )
            .values(status="disabled")
        )
        row.status = "published"
        row.published_at = published_at
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="system_settings.bundle_publish",
        target_type="system_setting_bundle",
        target_id=rows[0].id,
        reason=payload.reason,
        request_id=request.state.request_id,
        details={"setting_ids": payload.setting_ids, "sections": sorted(SYSTEM_SETTINGS_SECTIONS)},
    )
    await session.commit()
    return {"items": [model_dict(row) for row in rows]}


@router.post("/system-settings/{setting_id}/publish", response_model=contract.SystemSettingResource)
async def publish_system_setting(
    setting_id: str,
    request: Request,
    admin: Admin = Depends(require_admin_permission("settings:publish")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    setting = await session.get(SystemSetting, setting_id)
    if not setting:
        raise ApiError(404, "SYSTEM_SETTING_NOT_FOUND", "系统设置版本不存在。")
    await session.execute(
        update(SystemSetting)
        .where(
            SystemSetting.section == setting.section,
            SystemSetting.status == "published",
            SystemSetting.id != setting.id,
        )
        .values(status="disabled")
    )
    setting.status = "published"
    setting.published_at = utcnow()
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="system_setting.publish",
        target_type="system_setting",
        target_id=setting.id,
        request_id=request.state.request_id,
        details={"section": setting.section, "version_no": setting.version_no},
    )
    await session.commit()
    return model_dict(setting)


@router.post(
    "/official-skills/{skill_id}/versions",
    status_code=201,
    response_model=contract.SkillVersionResource,
)
async def create_official_skill_version(
    skill_id: str,
    payload: OfficialSkillVersionCreate,
    request: Request,
    admin: Admin = Depends(require_admin_permission("skills:write")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    skill = await session.scalar(
        select(Skill).where(Skill.id == skill_id, Skill.scope == "official")
    )
    if not skill:
        raise ApiError(404, "SKILL_NOT_FOUND", "官方技能不存在。")
    skill.current_version_no += 1
    checksum = hashlib.sha256(
        json.dumps(payload.model_dump(), sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    version = SkillVersion(
        skill_id=skill.id,
        version_no=skill.current_version_no,
        checksum=checksum,
        status="draft",
        **payload.model_dump(),
    )
    session.add(version)
    await session.flush()
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="official_skill_version.create",
        target_type="skill_version",
        target_id=version.id,
        request_id=request.state.request_id,
        details={"skill_id": skill.id, "version_no": version.version_no},
    )
    await session.commit()
    return model_dict(version)


@router.patch(
    "/skill-versions/{version_id}",
    response_model=contract.SkillVersionResource,
)
async def patch_official_skill_version(
    version_id: str,
    payload: OfficialSkillVersionPatch,
    request: Request,
    admin: Admin = Depends(require_admin_permission("skills:write")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    version = await session.get(SkillVersion, version_id)
    skill = await session.get(Skill, version.skill_id) if version else None
    if not version or not skill or skill.scope != "official":
        raise ApiError(404, "SKILL_VERSION_NOT_FOUND", "官方技能版本不存在。")
    if version.status not in {"draft", "testing"}:
        raise ApiError(409, "SKILL_VERSION_IMMUTABLE", "只有草稿或测试版本可以修改。")
    values = payload.model_dump(exclude_unset=True)
    for key, value in values.items():
        setattr(version, key, value)
    checksum_payload = {
        "instructions": version.instructions,
        "input_schema": version.input_schema,
        "output_schema": version.output_schema,
        "tool_policy": version.tool_policy,
    }
    version.checksum = hashlib.sha256(
        json.dumps(checksum_payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    version.status = "draft"
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="official_skill_version.update",
        target_type="skill_version",
        target_id=version.id,
        request_id=request.state.request_id,
        details={"skill_id": skill.id, "fields": sorted(values)},
    )
    await session.commit()
    return model_dict(version)


@router.get(
    "/official-skills/{skill_id}/versions",
    response_model=contract.SkillVersionListResponse,
)
async def list_official_skill_versions(
    skill_id: str,
    admin: Admin = Depends(require_admin_permission("skills:read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    del admin
    skill = await session.scalar(
        select(Skill).where(Skill.id == skill_id, Skill.scope == "official")
    )
    if not skill:
        raise ApiError(404, "SKILL_NOT_FOUND", "官方技能不存在。")
    versions = list(
        (
            await session.scalars(
                select(SkillVersion)
                .where(SkillVersion.skill_id == skill.id)
                .order_by(SkillVersion.version_no.desc())
            )
        ).all()
    )
    return {"items": [model_dict(version) for version in versions]}


@router.post("/skill-versions/{version_id}/test", response_model=contract.ValidationTestResponse)
async def test_skill_version(
    version_id: str,
    request: Request,
    payload: ConfigurationTestRequest | None = Body(default=None),
    admin: Admin = Depends(require_admin_permission("skills:test")),
    session: AsyncSession = Depends(get_session),
    model: ModelProvider = Depends(model_provider),
    safety: ContentSafetyProvider = Depends(content_safety_provider),
) -> dict[str, Any]:
    version = await session.get(SkillVersion, version_id)
    if not version:
        raise ApiError(404, "SKILL_VERSION_NOT_FOUND", "技能版本不存在。")
    forbidden_publish = bool(version.tool_policy.get("wechat_publish"))
    valid_schema = _configuration_schemas_are_valid(version.input_schema, version.output_schema)
    structural_error = None
    if forbidden_publish:
        structural_error = "技能不能获得直接发布微信的工具权限。"
    elif not version.instructions.strip():
        structural_error = "技能指令不能为空。"
    elif not valid_schema:
        structural_error = "技能输入或输出 Schema 不是有效对象。"
    result = await _run_configuration_model_test(
        model=model,
        safety=safety,
        purpose="skill_configuration_test",
        prompt=(
            f"请严格按照以下技能指令完成固定案例，但不得调用任何外部工具：\n"
            f"{version.instructions}\n\n"
            f"固定案例输入：{(payload or ConfigurationTestRequest()).input}"
        ),
        context={
            "test_case": "admin_fixed_case",
            "input_schema": version.input_schema,
            "output_schema": version.output_schema,
            "tool_policy": version.tool_policy,
        },
        structural_error=structural_error,
    )
    version.status = "testing" if result["passed"] else "draft"
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="official_skill_version.test",
        target_type="skill_version",
        target_id=version.id,
        request_id=request.state.request_id,
        details=result,
    )
    await session.commit()
    return result


@router.post("/skill-versions/{version_id}/publish", response_model=contract.SkillVersionResponse)
async def publish_skill_version(
    version_id: str,
    request: Request,
    admin: Admin = Depends(require_admin_permission("skills:publish")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    version = await session.get(SkillVersion, version_id)
    if not version:
        raise ApiError(404, "SKILL_VERSION_NOT_FOUND", "技能版本不存在。")
    skill = await session.get(Skill, version.skill_id)
    if not skill or skill.scope != "official":
        raise ApiError(404, "SKILL_NOT_FOUND", "官方技能不存在。")
    if version.status != "testing":
        raise ApiError(409, "SKILL_TEST_REQUIRED", "技能版本需要先通过测试。")
    await session.execute(
        update(SkillVersion)
        .where(
            SkillVersion.skill_id == skill.id,
            SkillVersion.status == "published",
            SkillVersion.id != version.id,
        )
        .values(status="disabled")
    )
    version.status = "published"
    skill.status = "published"
    skill.current_version_no = version.version_no
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="official_skill_version.publish",
        target_type="skill_version",
        target_id=version.id,
        request_id=request.state.request_id,
        details={"skill_id": skill.id, "version_no": version.version_no},
    )
    await session.commit()
    return {"skill": model_dict(skill), "version": model_dict(version)}


@router.post("/official-skills/{skill_id}/disable", response_model=contract.SkillResource)
async def disable_official_skill(
    skill_id: str,
    request: Request,
    admin: Admin = Depends(require_admin_permission("skills:publish")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    skill = await session.scalar(
        select(Skill).where(Skill.id == skill_id, Skill.scope == "official")
    )
    if not skill:
        raise ApiError(404, "SKILL_NOT_FOUND", "官方技能不存在。")
    skill.status = "disabled"
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="official_skill.disable",
        target_type="skill",
        target_id=skill.id,
        request_id=request.state.request_id,
    )
    await session.commit()
    return model_dict(skill)


@router.post("/official-skills/{skill_id}/restore", response_model=contract.SkillResource)
async def restore_official_skill(
    skill_id: str,
    request: Request,
    admin: Admin = Depends(require_admin_permission("skills:publish")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    skill = await session.scalar(
        select(Skill).where(Skill.id == skill_id, Skill.scope == "official")
    )
    if not skill:
        raise ApiError(404, "SKILL_NOT_FOUND", "官方技能不存在。")
    current = await session.scalar(
        select(SkillVersion).where(
            SkillVersion.skill_id == skill.id,
            SkillVersion.version_no == skill.current_version_no,
            SkillVersion.status == "published",
        )
    )
    if not current:
        raise ApiError(409, "SKILL_PUBLISHED_VERSION_MISSING", "技能没有可恢复的发布版本。")
    skill.status = "published"
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="official_skill.restore",
        target_type="skill",
        target_id=skill.id,
        request_id=request.state.request_id,
    )
    await session.commit()
    return model_dict(skill)


@router.post("/model-routes/{route_id}/test", response_model=contract.RouteTestResponse)
async def test_model_route(
    route_id: str,
    request: Request,
    admin: Admin = Depends(require_admin_permission("ai_config:test")),
    session: AsyncSession = Depends(get_session),
    config: Settings = Depends(settings),
    model: ModelProvider = Depends(model_provider),
    embedding: EmbeddingProvider = Depends(embedding_provider),
    rerank: RerankProvider = Depends(rerank_provider),
    secrets: SecretProvider = Depends(secret_provider),
) -> dict[str, Any]:
    route = await session.get(ModelRouteVersion, route_id)
    if not route:
        raise ApiError(404, "MODEL_ROUTE_NOT_FOUND", "模型路由不存在。")
    deployment_ids = [route.primary_deployment_id, *route.fallback_deployment_ids]
    passed = False
    provider_request_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    message = "路由固定案例调用失败；请检查部署、凭据和备用链。"
    try:
        snapshot = await freeze_route_snapshot(session, route=route)
        if route.purpose == "embedding":
            embedded = await FrozenEmbeddingRouteProvider(
                snapshot=snapshot,
                fallback=embedding,
                secrets=secrets,
                dimension=config.embedding_dimension,
            ).embed(["管理端固定案例测试"])
            passed = bool(embedded.vectors and embedded.vectors[0])
            provider_request_id = embedded.provider_request_id
            message = "路由固定案例通过，向量接口返回有效结果。"
        elif route.purpose == "rerank":
            ranked = await FrozenRerankRouteProvider(
                snapshot=snapshot,
                fallback=rerank,
                secrets=secrets,
            ).rerank(query="连接测试", documents=["连接测试文档"])
            passed = len(ranked.scores) == 1
            provider_request_id = ranked.provider_request_id
            message = "路由固定案例通过，重排接口返回有效结果。"
        else:
            is_layout_agent = route.purpose == "layout_extraction"
            routed = await generate_with_frozen_route(
                snapshot=snapshot,
                fallback_model=model,
                secrets=secrets,
                purpose=route.purpose,
                prompt=(
                    LAYOUT_AGENT_PROMPT
                    if is_layout_agent
                    else "这是管理端固定案例测试。请只返回简短、无敏感信息的有效文本。"
                ),
                context=(
                    {
                        "test_case": "layout_agent_route_v1",
                        "untrusted_layout_observation": {
                            "title": "管理端脱敏固定案例",
                            "layout_observation": {
                                "schema_version": 1,
                                "samples": [
                                    {
                                        "id": "block-1",
                                        "tag_hint": "p",
                                        "text_excerpt": "这是用于连接测试的正文样本。",
                                        "computed_style": {
                                            "font-size": "16px",
                                            "line-height": "1.8",
                                            "color": "#1f2937",
                                        },
                                    }
                                ],
                            },
                        },
                        "deterministic_baseline_style_tokens": {
                            "body": {
                                "font_size": 16,
                                "line_height": 1.8,
                                "color": "#1f2937",
                            }
                        },
                    }
                    if is_layout_agent
                    else {"test_case": "route_connectivity_v1"}
                ),
                default_timeout_seconds=config.model_timeout_seconds,
                session=session,
                response_schema=(LAYOUT_AGENT_RESPONSE_SCHEMA if is_layout_agent else None),
                result_validator=(validate_layout_agent_model_result if is_layout_agent else None),
            )
            if is_layout_agent:
                tokens = validated_layout_agent_payload(routed.result)["style_tokens"]
                passed = bool(tokens)
            else:
                passed = bool(routed.result.text.strip())
            provider_request_id = routed.result.provider_request_id
            input_tokens = routed.result.input_tokens
            output_tokens = routed.result.output_tokens
            message = (
                (
                    f"排版智能体固定案例通过，共执行 {len(routed.attempts)} 次模型尝试。"
                    if passed
                    else "排版智能体返回了结果，但未通过 StyleToken 结构校验。"
                )
                if is_layout_agent
                else f"路由固定案例通过，共执行 {len(routed.attempts)} 次模型尝试。"
            )
    except ModelRouteExhausted as exc:
        if route.purpose == "layout_extraction" and any(
            attempt.error_code in {"STYLE_TOKEN_INVALID", "LAYOUT_AGENT_OUTPUT_INVALID"}
            for attempt in exc.attempts
        ):
            message = "排版智能体返回了结果，但未通过 StyleToken 结构校验。"
    except (ApiError, ProviderUnavailable):
        pass
    route.status = "testing" if passed else "draft"
    result = {
        "passed": passed,
        "checked_deployments": deployment_ids,
        "message": message,
        "provider_request_id": provider_request_id,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="model_route.test",
        target_type="model_route_version",
        target_id=route.id,
        request_id=request.state.request_id,
        details=result,
    )
    await session.commit()
    return result


@router.post("/model-routes/{route_id}/publish", response_model=contract.ModelRouteResource)
async def publish_model_route(
    route_id: str,
    request: Request,
    admin: Admin = Depends(require_admin_permission("ai_config:publish")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    route = await session.get(ModelRouteVersion, route_id)
    if not route:
        raise ApiError(404, "MODEL_ROUTE_NOT_FOUND", "模型路由不存在。")
    try:
        await freeze_route_snapshot(session, route=route)
    except ApiError as exc:
        raise ApiError(
            409,
            "MODEL_ROUTE_NOT_TESTED",
            "路由中的供应商或模型部署尚未全部可用。",
        ) from exc
    deployment_ids = [route.primary_deployment_id, *route.fallback_deployment_ids]
    deployments = list(
        (
            await session.scalars(
                select(ModelDeployment).where(ModelDeployment.id.in_(deployment_ids))
            )
        ).all()
    )
    if len(deployments) != len(set(deployment_ids)) or any(
        deployment.status != "available" for deployment in deployments
    ):
        raise ApiError(409, "MODEL_ROUTE_NOT_TESTED", "路由中的模型尚未全部可用。")
    await session.execute(
        update(ModelRouteVersion)
        .where(
            ModelRouteVersion.purpose == route.purpose,
            ModelRouteVersion.status == "published",
            ModelRouteVersion.id != route.id,
        )
        .values(status="disabled")
    )
    route.status = "published"
    route.published_at = utcnow()
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="model_route.publish",
        target_type="model_route_version",
        target_id=route.id,
        request_id=request.state.request_id,
        details={"purpose": route.purpose, "version_no": route.version_no},
    )
    await session.commit()
    return model_dict(route)


@router.post("/model-routes/{route_id}/disable", response_model=contract.ModelRouteResource)
async def disable_model_route(
    route_id: str,
    request: Request,
    admin: Admin = Depends(require_admin_permission("ai_config:publish")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    route = await session.get(ModelRouteVersion, route_id)
    if not route:
        raise ApiError(404, "MODEL_ROUTE_NOT_FOUND", "模型路由不存在。")
    route.status = "disabled"
    audit(
        session,
        actor_type="admin",
        actor_id=admin.id,
        action="model_route.disable",
        target_type="model_route_version",
        target_id=route.id,
        request_id=request.state.request_id,
    )
    await session.commit()
    return model_dict(route)

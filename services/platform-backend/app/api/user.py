from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal
from urllib.parse import quote, urlparse

from fastapi import APIRouter, Cookie, Depends, Header, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator
from sqlalchemy import and_, case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database import Database, get_session
from app.dependencies import (
    content_safety_provider,
    current_user,
    document_processing_provider,
    layout_extraction_provider,
    model_provider,
    rate_limiter,
    retrieval_service,
    secret_provider,
    settings,
    storage_provider,
    validate_csrf,
    verification_provider,
    web_reference_provider,
    wechat_provider,
)
from app.domains.account_deletion import schedule_account_deletion
from app.domains.ai import (
    cancel_ai_run,
    create_ai_run,
)
from app.domains.article import (
    create_article,
    current_article_version,
    owned_article,
    restore_article_version,
    save_article_version,
    soft_delete_article,
    upsert_article_library_item,
    upsert_article_preference_candidate,
)
from app.domains.common import (
    begin_idempotency,
    complete_idempotency,
    create_job,
    emit_outbox,
)
from app.domains.files import (
    PART_SIZE,
    complete_upload,
    owned_document,
    register_upload,
    request_reparse,
)
from app.domains.identity import (
    create_verification_challenge,
    login_user,
    login_user_with_code,
    register_user,
    revoke_refresh_token,
    rotate_refresh_token,
    verify_challenge,
)
from app.domains.layout import (
    DEFAULT_STYLE_TOKENS,
    add_template_version,
    create_render,
    owned_template,
    process_layout_extraction,
    validate_source_url,
)
from app.domains.revision import create_article_revision
from app.domains.wechat import (
    confirm_render,
    create_wechat_operation,
    current_wechat_operation,
    owned_official_account,
    owned_render,
)
from app.domains.workspace import delete_project_keep_contents, owned_project, owned_task
from app.errors import ApiError
from app.model_files import MAX_FILE_BYTES
from app.model_gateway import active_route_snapshot
from app.models import (
    AIRun,
    AIRunEvent,
    ArticleRevision,
    ArticleVersion,
    Asset,
    DocumentChunk,
    DocumentSection,
    LayoutTemplate,
    LayoutTemplateVersion,
    LibraryItem,
    Message,
    ModelDeployment,
    ModelProviderRecord,
    OfficialAccount,
    Project,
    QuotaAccount,
    QuotaLedger,
    Skill,
    SkillVersion,
    Task,
    User,
    UserPreference,
    UserSkillSetting,
    WechatAuthorizationState,
    WechatOperation,
    WechatPlatformConfig,
    utcnow,
)
from app.providers import (
    CompletedUploadPart,
    ContentSafetyProvider,
    DocumentProcessingProvider,
    LayoutExtractionProvider,
    ModelProvider,
    ProviderAuthenticationError,
    ProviderReauthorizationRequired,
    ProviderUnavailable,
    SecretProvider,
    StorageProvider,
    VerificationProvider,
    WebReferenceProvider,
    WechatProvider,
)
from app.retrieval import RetrievalService
from app.security import RateLimiter, hash_token, new_opaque_token, new_uuid, verify_password
from app.system_settings import published_setting_section, published_system_settings
from app.wechat_open_platform import (
    WechatOpenPlatformClient,
    component_access_token,
    ensure_authorizer_access_token,
    published_wechat_config,
)

from . import contracts as contract
from .utils import (
    decode_cursor,
    decode_sorted_cursor,
    encode_cursor,
    encode_sorted_cursor,
    model_dict,
    page_response,
)

router = APIRouter(prefix="/api/v1", responses=contract.COMMON_ERROR_RESPONSES)


class VerificationRequest(BaseModel):
    destination: str = Field(min_length=5, max_length=320)
    purpose: Literal["register", "login", "reset_password"]


class VerificationCheck(BaseModel):
    challenge_id: str
    code: str = Field(pattern=r"^\d{6}$")


class RegisterRequest(BaseModel):
    email: EmailStr | None = None
    phone: str | None = Field(default=None, pattern=r"^\+?[0-9]{6,20}$")
    display_name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=128)
    verification_token: str | None = None
    accepted_terms: bool

    @model_validator(mode="after")
    def identifier_required(self) -> RegisterRequest:
        if not self.email and not self.phone:
            raise ValueError("email or phone is required")
        return self


class LoginRequest(BaseModel):
    identifier: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)
    platform: Literal["web", "windows", "ios", "android"] = "web"
    device_name: str | None = Field(default=None, max_length=120)


class CodeLoginRequest(BaseModel):
    identifier: str = Field(min_length=3, max_length=320)
    verification_token: str
    platform: Literal["web", "windows", "ios", "android"] = "web"
    device_name: str | None = Field(default=None, max_length=120)


class RefreshRequest(BaseModel):
    refresh_token: str | None = None


def _set_user_cookies(response: Response, refresh: str, csrf: str, config: Settings) -> None:
    response.set_cookie(
        "ua_session",
        refresh,
        httponly=True,
        secure=config.cookie_secure,
        samesite="lax",
        max_age=config.refresh_token_ttl_seconds,
        path="/api/v1/auth",
    )
    response.set_cookie(
        "ua_csrf",
        csrf,
        httponly=False,
        secure=config.cookie_secure,
        samesite="lax",
        max_age=config.refresh_token_ttl_seconds,
        path="/",
    )


def _clear_user_cookies(response: Response, config: Settings) -> None:
    response.delete_cookie(
        "ua_session", path="/api/v1/auth", secure=config.cookie_secure, samesite="lax"
    )
    response.delete_cookie("ua_csrf", path="/", secure=config.cookie_secure, samesite="lax")


@router.post(
    "/auth/verification-codes",
    status_code=202,
    response_model=contract.VerificationCodeResponse,
)
async def send_verification_code(
    payload: VerificationRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    limiter: RateLimiter = Depends(rate_limiter),
    provider: VerificationProvider = Depends(verification_provider),
    config: Settings = Depends(settings),
) -> dict[str, Any]:
    client = request.client.host if request.client else "unknown"
    await limiter.check(f"verification:{client}:{payload.destination}", 5, 600)
    try:
        challenge, delivery = await create_verification_challenge(
            session,
            destination=payload.destination,
            purpose=payload.purpose,
            provider=provider,
            settings=config,
        )
    except ProviderUnavailable as exc:
        raise ApiError(
            503,
            "VERIFICATION_PROVIDER_UNAVAILABLE",
            "验证码服务暂不可用，请稍后重试。",
            retryable=True,
        ) from exc
    await session.commit()
    result: dict[str, Any] = {
        "challenge_id": challenge.id,
        "expires_at": challenge.expires_at.isoformat(),
        "delivery_status": delivery,
    }
    return result


@router.post("/auth/verification-codes/verify", response_model=contract.VerificationTokenResponse)
async def check_verification_code(
    payload: VerificationCheck,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    token = await verify_challenge(session, challenge_id=payload.challenge_id, code=payload.code)
    await session.commit()
    return {"verification_token": token}


@router.post("/auth/register", status_code=201, response_model=contract.RegisteredUserResponse)
async def register(
    payload: RegisterRequest,
    session: AsyncSession = Depends(get_session),
    config: Settings = Depends(settings),
) -> dict[str, Any]:
    user = await register_user(
        session,
        email=str(payload.email) if payload.email else None,
        phone=payload.phone,
        display_name=payload.display_name,
        password=payload.password,
        verification_token=payload.verification_token,
        accepted_terms=payload.accepted_terms,
        settings=config,
    )
    await session.commit()
    return {"id": user.id, "display_name": user.display_name, "status": user.status}


@router.post(
    "/auth/login",
    response_model=contract.AuthTokenResponse,
    responses={200: {"headers": contract.USER_SESSION_COOKIE_HEADERS}},
)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
    limiter: RateLimiter = Depends(rate_limiter),
    config: Settings = Depends(settings),
) -> dict[str, Any]:
    client = request.client.host if request.client else "unknown"
    await limiter.check(f"user-login:{client}:{payload.identifier.lower()}", 10, 600)
    user, tokens = await login_user(
        session,
        identifier=payload.identifier,
        password=payload.password,
        platform=payload.platform,
        device_name=payload.device_name,
        settings=config,
    )
    await session.commit()
    if payload.platform == "web":
        _set_user_cookies(response, tokens.refresh_token, tokens.csrf_token, config)
    return {
        "access_token": tokens.access_token,
        "token_type": "bearer",
        "expires_in": tokens.access_expires_in,
        "refresh_token": tokens.refresh_token if payload.platform != "web" else None,
        "user": {"id": user.id, "display_name": user.display_name, "status": user.status},
    }


@router.post(
    "/auth/login-code",
    response_model=contract.AuthTokenResponse,
    responses={200: {"headers": contract.USER_SESSION_COOKIE_HEADERS}},
)
async def login_with_verification_code(
    payload: CodeLoginRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
    config: Settings = Depends(settings),
) -> dict[str, Any]:
    user, tokens = await login_user_with_code(
        session,
        identifier=payload.identifier,
        verification_token=payload.verification_token,
        platform=payload.platform,
        device_name=payload.device_name,
        settings=config,
    )
    await session.commit()
    if payload.platform == "web":
        _set_user_cookies(response, tokens.refresh_token, tokens.csrf_token, config)
    return {
        "access_token": tokens.access_token,
        "token_type": "bearer",
        "expires_in": tokens.access_expires_in,
        "refresh_token": tokens.refresh_token if payload.platform != "web" else None,
        "user": {"id": user.id, "display_name": user.display_name},
    }


@router.post(
    "/auth/refresh",
    response_model=contract.AuthTokenResponse,
    responses={200: {"headers": contract.USER_SESSION_COOKIE_HEADERS}},
)
async def refresh(
    payload: RefreshRequest,
    request: Request,
    response: Response,
    csrf_token: Annotated[
        str | None,
        Header(
            alias="X-CSRF-Token",
            description="Required with the ua_session browser cookie; omit for native refresh.",
        ),
    ] = None,
    session_cookie: Annotated[
        str | None,
        Cookie(
            alias="ua_session",
            description="Browser refresh cookie; native clients send refresh_token in the body.",
        ),
    ] = None,
    session: AsyncSession = Depends(get_session),
    config: Settings = Depends(settings),
) -> dict[str, Any]:
    del csrf_token
    raw_refresh = payload.refresh_token or session_cookie
    if not raw_refresh:
        raise ApiError(401, "REFRESH_TOKEN_REQUIRED", "缺少刷新令牌。")
    if not payload.refresh_token:
        validate_csrf(request, "ua_csrf")
    user, tokens = await rotate_refresh_token(session, raw_refresh=raw_refresh, settings=config)
    await session.commit()
    if not payload.refresh_token:
        _set_user_cookies(response, tokens.refresh_token, tokens.csrf_token, config)
    return {
        "access_token": tokens.access_token,
        "token_type": "bearer",
        "expires_in": tokens.access_expires_in,
        "refresh_token": tokens.refresh_token if payload.refresh_token else None,
        "user": {"id": user.id, "display_name": user.display_name},
    }


@router.post(
    "/auth/logout",
    status_code=204,
    responses={204: {"headers": contract.USER_SESSION_COOKIE_HEADERS}},
)
async def logout(
    request: Request,
    response: Response,
    payload: RefreshRequest | None = None,
    csrf_token: Annotated[
        str | None,
        Header(
            alias="X-CSRF-Token",
            description="Required when ua_session is present; native bearer logout omits it.",
        ),
    ] = None,
    session_cookie: Annotated[
        str | None, Cookie(alias="ua_session", description="Optional browser session cookie.")
    ] = None,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    config: Settings = Depends(settings),
) -> Response:
    del csrf_token
    raw_refresh = payload.refresh_token if payload and payload.refresh_token else session_cookie
    if session_cookie and not (payload and payload.refresh_token):
        validate_csrf(request, "ua_csrf")
    await revoke_refresh_token(
        session,
        raw_refresh=raw_refresh,
        user_id=user.id,
        all_sessions=False,
        family_id=getattr(request.state, "user_session_family", None),
    )
    await session.commit()
    _clear_user_cookies(response, config)
    response.status_code = 204
    return response


@router.post(
    "/auth/logout-all",
    status_code=204,
    responses={204: {"headers": contract.USER_SESSION_COOKIE_HEADERS}},
)
async def logout_all(
    response: Response,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    config: Settings = Depends(settings),
) -> Response:
    await revoke_refresh_token(session, raw_refresh=None, user_id=user.id, all_sessions=True)
    await session.commit()
    _clear_user_cookies(response, config)
    response.status_code = 204
    return response


@router.get("/me", response_model=contract.MeResponse)
async def me(
    user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    quota = await session.scalar(select(QuotaAccount).where(QuotaAccount.owner_id == user.id))
    return {
        "id": user.id,
        "email": user.email,
        "phone": user.phone,
        "display_name": user.display_name,
        "theme_preference": user.theme_preference,
        "quota_balance": quota.balance if quota else 0,
    }


class MePatch(BaseModel):
    theme_preference: Literal["system", "light", "dark"]


@router.patch("/me", response_model=contract.MePatchResponse)
async def patch_me(
    payload: MePatch,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user.theme_preference = payload.theme_preference
    await session.commit()
    return {"id": user.id, "theme_preference": user.theme_preference}


@router.get("/model-options", response_model=contract.ModelOptionListResponse)
async def list_model_options(
    user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    del user
    rows = (
        await session.execute(
            select(ModelDeployment, ModelProviderRecord)
            .join(ModelProviderRecord, ModelProviderRecord.id == ModelDeployment.provider_id)
            .where(
                ModelDeployment.status == "available",
                ModelDeployment.model_type.in_(("chat", "vision")),
                ModelProviderRecord.status == "active",
            )
            .order_by(
                case((ModelProviderRecord.adapter == "manus_v2", 1), else_=0),
                ModelDeployment.alias,
                ModelDeployment.created_at,
            )
        )
    ).all()
    return {
        "items": [
            {
                "id": deployment.id,
                "name": deployment.alias,
                "provider_name": provider.name,
                "model_id": deployment.model_id,
                "model_type": deployment.model_type,
                "context_window": deployment.context_window,
                "max_output_tokens": deployment.max_output_tokens,
            }
            for deployment, provider in rows
        ]
    }


class AccountDeletionCreate(BaseModel):
    password: str = Field(min_length=1, max_length=128)
    confirmation: Literal["注销账号"]


@router.delete(
    "/me",
    status_code=202,
    response_model=contract.AccountDeletionResponse,
    responses={202: {"headers": contract.USER_SESSION_COOKIE_HEADERS}},
)
async def delete_me(
    payload: AccountDeletionCreate,
    request: Request,
    response: Response,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    config: Settings = Depends(settings),
) -> dict[str, Any]:
    if not verify_password(user.password_hash, payload.password):
        raise ApiError(403, "ACCOUNT_DELETION_PASSWORD_INVALID", "当前密码不正确。")
    deletion = await schedule_account_deletion(
        session,
        user=user,
        request_id=request.state.request_id,
    )
    await session.commit()
    _clear_user_cookies(response, config)
    return {
        "deletion_request_id": deletion.id,
        "status": "scheduled",
        "requested_at": deletion.requested_at,
        "purge_after": deletion.purge_after,
    }


@router.get("/quota", response_model=contract.QuotaResponse)
async def quota(
    user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    account = await session.scalar(select(QuotaAccount).where(QuotaAccount.owner_id == user.id))
    if not account:
        raise ApiError(500, "QUOTA_ACCOUNT_MISSING", "额度账户不存在。")
    ledger = list(
        (
            await session.scalars(
                select(QuotaLedger)
                .where(QuotaLedger.account_id == account.id)
                .order_by(QuotaLedger.created_at.desc())
                .limit(50)
            )
        ).all()
    )
    return {
        "balance": account.balance,
        "version": account.version,
        "ledger": [model_dict(x) for x in ledger],
    }


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    writing_requirements: str | None = Field(default=None, max_length=10_000)


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    writing_requirements: str | None = Field(default=None, max_length=10_000)
    sort_order: int | None = None


@router.post("/projects", status_code=201, response_model=contract.ProjectResource)
async def create_project(
    payload: ProjectCreate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    project = Project(owner_id=user.id, **payload.model_dump())
    session.add(project)
    await session.commit()
    return model_dict(project)


@router.get("/projects", response_model=contract.ProjectListResponse)
async def list_projects(
    cursor: str | None = None,
    limit: int = Query(30, ge=1, le=100),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    conditions = [Project.owner_id == user.id, Project.deleted_at.is_(None)]
    decoded = decode_sorted_cursor(cursor)
    if decoded:
        sort_order, timestamp, identifier = decoded
        conditions.append(
            or_(
                Project.sort_order > sort_order,
                and_(Project.sort_order == sort_order, Project.created_at > timestamp),
                and_(
                    Project.sort_order == sort_order,
                    Project.created_at == timestamp,
                    Project.id > identifier,
                ),
            )
        )
    rows = list(
        (
            await session.scalars(
                select(Project)
                .where(*conditions)
                .order_by(Project.sort_order, Project.created_at, Project.id)
                .limit(limit + 1)
            )
        ).all()
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = (
        encode_sorted_cursor(rows[-1].sort_order, rows[-1].created_at, rows[-1].id)
        if has_more and rows
        else None
    )
    return page_response([model_dict(row) for row in rows], next_cursor)


@router.patch("/projects/{project_id}", response_model=contract.ProjectResource)
async def patch_project(
    project_id: str,
    payload: ProjectPatch,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    project = await owned_project(session, owner_id=user.id, project_id=project_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, key, value)
    await session.commit()
    return model_dict(project)


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await delete_project_keep_contents(session, owner_id=user.id, project_id=project_id)
    await session.commit()
    return Response(status_code=204)


class MessageAttachment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=180)
    name: str = Field(min_length=1, max_length=255)
    kind: Literal["file", "image", "link"]
    size: int | None = Field(default=None, ge=0)
    url: str | None = Field(default=None, max_length=2000)
    status: str = Field(default="ready", max_length=40)
    save_to_library: bool = False
    asset_id: str | None = None
    document_id: str | None = None


class MessageContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_ids: list[str] = Field(default_factory=list, max_length=20)
    links: list[str] = Field(default_factory=list, max_length=20)
    attachments: list[MessageAttachment] = Field(default_factory=list, max_length=20)
    source: str | None = Field(default=None, max_length=80)


class MessageCreate(BaseModel):
    text: str = Field(min_length=1, max_length=100_000)
    content: MessageContent = Field(default_factory=MessageContent)
    client_message_id: str = Field(min_length=1, max_length=100)
    model_deployment_id: str | None = None


class TaskCreate(BaseModel):
    project_id: str | None = None
    title: str | None = Field(default=None, max_length=160)
    current_skill_id: str | None = None
    use_preferences: bool | None = None
    model_deployment_id: str | None = None
    first_message: MessageCreate


class TaskPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    project_id: str | None = None
    current_skill_id: str | None = None
    use_preferences: bool | None = None
    status: Literal["active", "archived"] | None = None


def _run_response(task: Task, message: Message, run: AIRun) -> dict[str, Any]:
    return {
        "task": model_dict(task),
        "message": model_dict(message),
        "ai_run": model_dict(run),
    }


@router.post("/tasks", status_code=202, response_model=contract.RunCreationResponse)
async def create_task(
    payload: TaskCreate,
    request: Request,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    config: Settings = Depends(settings),
    model: ModelProvider = Depends(model_provider),
    safety: ContentSafetyProvider = Depends(content_safety_provider),
    retrieval: RetrievalService = Depends(retrieval_service),
    secrets: SecretProvider = Depends(secret_provider),
    web_references: WebReferenceProvider = Depends(web_reference_provider),
    storage: StorageProvider = Depends(storage_provider),
) -> dict[str, Any]:
    attempt = await begin_idempotency(
        session,
        actor_type="user",
        actor_id=user.id,
        scope="tasks.create",
        key=idempotency_key,
        payload=payload.model_dump(mode="json"),
    )
    if attempt.cached_body:
        return attempt.cached_body
    if payload.project_id:
        await owned_project(session, owner_id=user.id, project_id=payload.project_id)
    ai_settings = await published_setting_section(session, "ai")
    preference_default = ai_settings.get("preference_enabled_by_default", True)
    task = Task(
        owner_id=user.id,
        project_id=payload.project_id,
        title=payload.title or payload.first_message.text.strip().splitlines()[0][:80],
        current_skill_id=payload.current_skill_id,
        use_preferences=(
            payload.use_preferences
            if payload.use_preferences is not None
            else preference_default is not False
        ),
    )
    session.add(task)
    await session.flush()
    created = await create_ai_run(
        session,
        owner_id=user.id,
        task_id=task.id,
        text=payload.first_message.text,
        content=payload.first_message.content.model_dump(mode="json", exclude_none=True),
        client_message_id=payload.first_message.client_message_id,
        idempotency_key=idempotency_key or "",
        settings=config,
        retrieval=retrieval,
        secrets=secrets,
        web_references=web_references,
        storage=storage,
        model_deployment_id=payload.model_deployment_id
        or payload.first_message.model_deployment_id,
    )
    body = _run_response(task, created.message, created.run)
    complete_idempotency(attempt, body, 202)
    await session.commit()
    return body


@router.get("/tasks", response_model=contract.TaskPageResponse)
async def list_tasks(
    project_id: str | None = None,
    cursor: str | None = None,
    limit: int = Query(30, ge=1, le=100),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    decoded = decode_cursor(cursor)
    conditions = [Task.owner_id == user.id, Task.deleted_at.is_(None)]
    if project_id == "unclassified":
        conditions.append(Task.project_id.is_(None))
    elif project_id:
        conditions.append(Task.project_id == project_id)
    if decoded:
        timestamp, identifier = decoded
        conditions.append(
            or_(
                Task.last_message_at < timestamp,
                and_(Task.last_message_at == timestamp, Task.id < identifier),
            )
        )
    rows = list(
        (
            await session.scalars(
                select(Task)
                .where(*conditions)
                .order_by(Task.last_message_at.desc(), Task.id.desc())
                .limit(limit + 1)
            )
        ).all()
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = (
        encode_cursor(rows[-1].last_message_at, rows[-1].id) if has_more and rows else None
    )
    return page_response([model_dict(row) for row in rows], next_cursor)


@router.get("/tasks/{task_id}", response_model=contract.TaskDetailResponse)
async def get_task(
    task_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    task = await owned_task(session, owner_id=user.id, task_id=task_id)
    messages, next_cursor = await _message_page(
        session,
        task_id=task.id,
        cursor=None,
        limit=30,
    )
    latest_run = await session.scalar(
        select(AIRun)
        .where(AIRun.task_id == task.id, AIRun.owner_id == user.id)
        .order_by(AIRun.created_at.desc(), AIRun.id.desc())
        .limit(1)
    )
    return {
        **model_dict(task),
        "messages": [model_dict(item) for item in messages],
        "messages_next_cursor": next_cursor,
        "latest_ai_run": (
            {
                "id": latest_run.id,
                "status": latest_run.status,
                "run_type": latest_run.run_type,
                "error_code": latest_run.error_code,
                "error_message": latest_run.error_message,
                "created_at": latest_run.created_at,
                "completed_at": latest_run.completed_at,
            }
            if latest_run
            else None
        ),
    }


async def _message_page(
    session: AsyncSession,
    *,
    task_id: str,
    cursor: str | None,
    limit: int,
) -> tuple[list[Message], str | None]:
    conditions = [Message.task_id == task_id]
    decoded = decode_cursor(cursor)
    if decoded:
        timestamp, identifier = decoded
        conditions.append(
            or_(
                Message.created_at < timestamp,
                and_(Message.created_at == timestamp, Message.id < identifier),
            )
        )
    newest_first = list(
        (
            await session.scalars(
                select(Message)
                .where(*conditions)
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(limit + 1)
            )
        ).all()
    )
    has_more = len(newest_first) > limit
    newest_first = newest_first[:limit]
    next_cursor = (
        encode_cursor(newest_first[-1].created_at, newest_first[-1].id)
        if has_more and newest_first
        else None
    )
    newest_first.reverse()
    return newest_first, next_cursor


@router.patch("/tasks/{task_id}", response_model=contract.TaskResource)
async def patch_task(
    task_id: str,
    payload: TaskPatch,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    task = await owned_task(session, owner_id=user.id, task_id=task_id)
    values = payload.model_dump(exclude_unset=True)
    if "project_id" in values and values["project_id"]:
        await owned_project(session, owner_id=user.id, project_id=values["project_id"])
    for key, value in values.items():
        setattr(task, key, value)
    await session.commit()
    return model_dict(task)


@router.delete("/tasks/{task_id}", status_code=204)
async def delete_task(
    task_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    task = await owned_task(session, owner_id=user.id, task_id=task_id)
    task.status = "deleted"
    task.deleted_at = utcnow()
    await session.commit()
    return Response(status_code=204)


@router.post(
    "/tasks/{task_id}/messages", status_code=202, response_model=contract.RunCreationResponse
)
async def send_message(
    task_id: str,
    payload: MessageCreate,
    request: Request,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    config: Settings = Depends(settings),
    model: ModelProvider = Depends(model_provider),
    safety: ContentSafetyProvider = Depends(content_safety_provider),
    retrieval: RetrievalService = Depends(retrieval_service),
    secrets: SecretProvider = Depends(secret_provider),
    web_references: WebReferenceProvider = Depends(web_reference_provider),
    storage: StorageProvider = Depends(storage_provider),
) -> dict[str, Any]:
    attempt = await begin_idempotency(
        session,
        actor_type="user",
        actor_id=user.id,
        scope=f"tasks.{task_id}.messages",
        key=idempotency_key,
        payload=payload.model_dump(mode="json"),
    )
    if attempt.cached_body:
        return attempt.cached_body
    task = await owned_task(session, owner_id=user.id, task_id=task_id)
    created = await create_ai_run(
        session,
        owner_id=user.id,
        task_id=task.id,
        text=payload.text,
        content=payload.content.model_dump(mode="json", exclude_none=True),
        client_message_id=payload.client_message_id,
        idempotency_key=idempotency_key or "",
        settings=config,
        retrieval=retrieval,
        secrets=secrets,
        web_references=web_references,
        storage=storage,
        model_deployment_id=payload.model_deployment_id,
    )
    body = _run_response(task, created.message, created.run)
    complete_idempotency(attempt, body, 202)
    await session.commit()
    return body


@router.get("/tasks/{task_id}/messages", response_model=contract.MessagePageResponse)
async def list_task_messages(
    task_id: str,
    cursor: str | None = None,
    limit: int = Query(30, ge=1, le=100),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    task = await owned_task(session, owner_id=user.id, task_id=task_id)
    messages, next_cursor = await _message_page(
        session,
        task_id=task.id,
        cursor=cursor,
        limit=limit,
    )
    return page_response([model_dict(item) for item in messages], next_cursor)


@router.post("/ai-runs/{run_id}/cancel", response_model=contract.AIRunResource)
async def cancel_run(
    run_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    run = await cancel_ai_run(session, owner_id=user.id, run_id=run_id)
    await session.commit()
    return model_dict(run)


@router.get("/ai-runs/{run_id}", response_model=contract.AIRunResource)
async def get_run(
    run_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    run = await session.scalar(select(AIRun).where(AIRun.id == run_id, AIRun.owner_id == user.id))
    if not run:
        raise ApiError(404, "AI_RUN_NOT_FOUND", "AI 任务不存在。")
    return model_dict(run)


@router.get(
    "/ai-runs/{run_id}/events",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "Resumable AI run event stream.",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        }
    },
)
async def stream_run_events(
    run_id: str,
    request: Request,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    run = await session.scalar(select(AIRun).where(AIRun.id == run_id, AIRun.owner_id == user.id))
    if not run:
        raise ApiError(404, "AI_RUN_NOT_FOUND", "AI 任务不存在。")
    try:
        start_seq = int(last_event_id or 0)
    except ValueError as exc:
        raise ApiError(422, "LAST_EVENT_ID_INVALID", "事件序号无效。") from exc
    database: Database = request.app.state.database

    async def events() -> Any:
        cursor = start_seq
        idle_rounds = 0
        while not await request.is_disconnected():
            async with database.session_maker() as event_session:
                rows = list(
                    (
                        await event_session.scalars(
                            select(AIRunEvent)
                            .where(AIRunEvent.run_id == run_id, AIRunEvent.seq > cursor)
                            .order_by(AIRunEvent.seq)
                        )
                    ).all()
                )
                current_run = await event_session.get(AIRun, run_id)
            if rows:
                idle_rounds = 0
                for event in rows:
                    cursor = event.seq
                    data = json.dumps(event.payload, ensure_ascii=False, separators=(",", ":"))
                    yield f"id: {event.seq}\nevent: {event.event_type}\ndata: {data}\n\n"
            else:
                idle_rounds += 1
                if idle_rounds % 40 == 0:
                    yield ": keep-alive\n\n"
            if (
                current_run
                and current_run.status in {"completed", "failed", "cancelled"}
                and not rows
            ):
                break
            await asyncio.sleep(0.25)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class UploadCreate(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=3, max_length=150)
    size_bytes: int = Field(gt=0)
    sha256: str = Field(min_length=64, max_length=64)
    project_id: str | None = None
    task_id: str | None = None


class UploadPartCompletion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    part_number: int = Field(ge=1, le=10_000)
    etag: str = Field(min_length=1, max_length=1024)

    @model_validator(mode="after")
    def validate_etag(self) -> UploadPartCompletion:
        if (
            self.etag != self.etag.strip()
            or not self.etag.isascii()
            or any(ord(character) < 32 for character in self.etag)
        ):
            raise ValueError("etag must be a non-empty printable ASCII value")
        return self


class UploadComplete(BaseModel):
    size_bytes: int = Field(gt=0)
    sha256: str = Field(min_length=64, max_length=64)
    completed_parts: list[UploadPartCompletion] = Field(min_length=1, max_length=10_000)
    save_to_library: bool = True


@router.post("/uploads", status_code=201, response_model=contract.UploadCreateResponse)
async def create_upload(
    payload: UploadCreate,
    request: Request,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageProvider = Depends(storage_provider),
) -> dict[str, Any]:
    attempt = await begin_idempotency(
        session,
        actor_type="user",
        actor_id=user.id,
        scope="uploads.create",
        key=idempotency_key,
        payload=payload.model_dump(mode="json"),
    )
    if attempt.cached_body:
        return attempt.cached_body
    if payload.project_id:
        await owned_project(session, owner_id=user.id, project_id=payload.project_id)
    if payload.task_id:
        await owned_task(session, owner_id=user.id, task_id=payload.task_id)
    file_settings = await published_setting_section(session, "files")
    feature_settings = await published_setting_section(session, "features")
    feature_flags = feature_settings.get("feature_flags", {})
    if (
        payload.mime_type.startswith("image/")
        and isinstance(feature_flags, dict)
        and feature_flags.get("visual_understanding") is False
    ):
        raise ApiError(403, "VISUAL_UNDERSTANDING_DISABLED", "图片理解功能当前已停用。")
    allowed_extensions = {
        str(value).lower().lstrip(".")
        for value in file_settings.get("allowed_extensions", [])
        if isinstance(value, str)
    }
    max_file_mb = file_settings.get("max_file_mb", 200)
    try:
        asset, upload, part_urls = await register_upload(
            session,
            owner_id=user.id,
            filename=payload.filename,
            mime_type=payload.mime_type,
            size_bytes=payload.size_bytes,
            sha256=payload.sha256,
            project_id=payload.project_id,
            task_id=payload.task_id,
            idempotency_key=idempotency_key,
            storage=storage,
            allowed_extensions=allowed_extensions,
            platform_max_file_bytes=(
                int(max_file_mb) * 1024 * 1024 if isinstance(max_file_mb, int) else None
            ),
        )
    except ProviderUnavailable as exc:
        raise ApiError(
            503,
            "STORAGE_PROVIDER_UNAVAILABLE",
            "文件存储服务暂不可用，请稍后重试。",
            retryable=True,
        ) from exc
    body = {
        "upload": model_dict(upload),
        "asset": model_dict(asset),
        "part_urls": part_urls,
        "part_size_bytes": PART_SIZE,
    }
    complete_idempotency(attempt, body, 201)
    await session.commit()
    return body


@router.post("/uploads/{upload_id}/complete", response_model=contract.UploadCompleteResponse)
async def finish_upload(
    upload_id: str,
    payload: UploadComplete,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageProvider = Depends(storage_provider),
    processor: DocumentProcessingProvider = Depends(document_processing_provider),
    config: Settings = Depends(settings),
    retrieval: RetrievalService = Depends(retrieval_service),
) -> dict[str, Any]:
    attempt = await begin_idempotency(
        session,
        actor_type="user",
        actor_id=user.id,
        scope=f"uploads.{upload_id}.complete",
        key=idempotency_key,
        payload=payload.model_dump(mode="json"),
    )
    if attempt.cached_body:
        return attempt.cached_body
    try:
        asset, document, library_item = await complete_upload(
            session,
            owner_id=user.id,
            upload_id=upload_id,
            size_bytes=payload.size_bytes,
            sha256=payload.sha256,
            completed_parts=[
                CompletedUploadPart(part_number=part.part_number, etag=part.etag)
                for part in payload.completed_parts
            ],
            save_to_library=payload.save_to_library,
            storage=storage,
        )
    except ProviderUnavailable as exc:
        raise ApiError(
            503,
            "STORAGE_PROVIDER_UNAVAILABLE",
            "文件存储服务暂不可用，请稍后重试。",
            retryable=True,
        ) from exc
    await session.flush()
    body = {
        "asset": model_dict(asset),
        "document": model_dict(document),
        "library_item": model_dict(library_item) if library_item else None,
    }
    complete_idempotency(attempt, body)
    await session.commit()
    return body


@router.get("/documents/{document_id}", response_model=contract.DocumentDetailResponse)
async def get_document(
    document_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    document = await owned_document(session, owner_id=user.id, document_id=document_id)
    section_limit = 500
    chunk_limit = 500
    sections = list(
        (
            await session.scalars(
                select(DocumentSection)
                .where(DocumentSection.document_id == document.id)
                .order_by(DocumentSection.sort_order)
                .limit(section_limit + 1)
            )
        ).all()
    )
    chunks = list(
        (
            await session.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == document.id)
                .order_by(DocumentChunk.chunk_no)
                .limit(chunk_limit + 1)
            )
        ).all()
    )
    return {
        **model_dict(document),
        "sections": [model_dict(row) for row in sections[:section_limit]],
        "chunks": [model_dict(row) for row in chunks[:chunk_limit]],
        "sections_truncated": len(sections) > section_limit,
        "chunks_truncated": len(chunks) > chunk_limit,
    }


@router.get(
    "/documents/{document_id}/content",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
async def get_document_content(
    document_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageProvider = Depends(storage_provider),
) -> Response:
    document = await owned_document(session, owner_id=user.id, document_id=document_id)
    asset = await session.get(Asset, document.asset_id)
    if not asset or asset.deleted_at:
        raise ApiError(404, "DOCUMENT_ASSET_MISSING", "原文件不存在或已被删除。")
    content = await storage.read_bytes(object_key=asset.object_key, max_bytes=MAX_FILE_BYTES)
    return Response(
        content=content,
        media_type=asset.mime_type,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(asset.filename)}",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post(
    "/documents/{document_id}/reparse",
    status_code=202,
    response_model=contract.DocumentResource,
)
async def reparse_document(
    document_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    processor: DocumentProcessingProvider = Depends(document_processing_provider),
    config: Settings = Depends(settings),
    retrieval: RetrievalService = Depends(retrieval_service),
) -> dict[str, Any]:
    document = await request_reparse(session, owner_id=user.id, document_id=document_id)
    await session.commit()
    return model_dict(document)


class ArticleCreate(BaseModel):
    project_id: str | None = None
    task_id: str | None = None
    title: str = Field(min_length=1, max_length=255)
    summary: str | None = Field(default=None, max_length=2000)
    content: contract.TiptapDocument


class ArticleContentUpdate(BaseModel):
    base_version_no: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=255)
    summary: str | None = Field(default=None, max_length=2000)
    content: contract.TiptapDocument
    source: Literal["manual", "autosave", "ai"] = "manual"


class RestoreVersionRequest(BaseModel):
    version_no: int = Field(ge=1)
    base_version_no: int = Field(ge=1)


class ArticleRevisionCreate(BaseModel):
    base_version_no: int = Field(ge=1)
    selected_text: str = Field(min_length=1, max_length=50_000)
    instruction: str = Field(min_length=1, max_length=10_000)
    selection_from: int | None = Field(default=None, ge=0)
    selection_to: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_selection(self) -> ArticleRevisionCreate:
        if (self.selection_from is None) != (self.selection_to is None):
            raise ValueError("selection_from and selection_to must be provided together")
        if (
            self.selection_from is not None
            and self.selection_to is not None
            and self.selection_from >= self.selection_to
        ):
            raise ValueError("selection_from must be less than selection_to")
        return self


@router.post("/articles", status_code=201, response_model=contract.ArticleWithVersionResponse)
async def create_article_endpoint(
    payload: ArticleCreate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if payload.project_id:
        await owned_project(session, owner_id=user.id, project_id=payload.project_id)
    if payload.task_id:
        await owned_task(session, owner_id=user.id, task_id=payload.task_id)
    article, version = await create_article(
        session,
        owner_id=user.id,
        project_id=payload.project_id,
        task_id=payload.task_id,
        title=payload.title,
        summary=payload.summary,
        content=payload.content.model_dump(exclude_none=True),
        source="manual",
        created_by_type="user",
        created_by_id=user.id,
    )
    await session.commit()
    return {"article": model_dict(article), "version": model_dict(version)}


@router.get("/articles/{article_id}", response_model=contract.ArticleWithVersionResponse)
async def get_article(
    article_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    article = await owned_article(session, owner_id=user.id, article_id=article_id)
    version = await current_article_version(session, article=article)
    return {"article": model_dict(article), "version": model_dict(version)}


@router.post(
    "/articles/{article_id}/revisions",
    status_code=202,
    response_model=contract.ArticleRevisionResource,
)
async def create_article_revision_endpoint(
    article_id: str,
    payload: ArticleRevisionCreate,
    request: Request,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    config: Settings = Depends(settings),
    model: ModelProvider = Depends(model_provider),
    safety: ContentSafetyProvider = Depends(content_safety_provider),
    secrets: SecretProvider = Depends(secret_provider),
) -> dict[str, Any]:
    attempt = await begin_idempotency(
        session,
        actor_type="user",
        actor_id=user.id,
        scope=f"articles.{article_id}.revisions",
        key=idempotency_key,
        payload=payload.model_dump(mode="json"),
    )
    if attempt.cached_body:
        return attempt.cached_body
    revision = await create_article_revision(
        session,
        owner_id=user.id,
        article_id=article_id,
        idempotency_key=idempotency_key,
        settings=config,
        **payload.model_dump(),
    )
    body = model_dict(revision)
    complete_idempotency(attempt, body, 202)
    await session.commit()
    return body


@router.get("/article-revisions/{revision_id}", response_model=contract.ArticleRevisionResource)
async def get_article_revision(
    revision_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    revision = await session.scalar(
        select(ArticleRevision).where(
            ArticleRevision.id == revision_id, ArticleRevision.owner_id == user.id
        )
    )
    if not revision:
        raise ApiError(404, "ARTICLE_REVISION_NOT_FOUND", "文章修改任务不存在。")
    return model_dict(revision)


@router.get(
    "/articles/{article_id}/versions",
    response_model=contract.ArticleVersionListResponse,
)
async def list_article_versions(
    article_id: str,
    cursor: str | None = None,
    limit: int = Query(30, ge=1, le=100),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    article = await owned_article(session, owner_id=user.id, article_id=article_id)
    article_settings = await published_setting_section(session, "articles")
    history_versions = article_settings.get("history_versions", 50)
    effective_limit = min(limit, history_versions if isinstance(history_versions, int) else 50)
    conditions = [ArticleVersion.article_id == article.id]
    decoded = decode_cursor(cursor)
    if decoded:
        timestamp, identifier = decoded
        conditions.append(
            or_(
                ArticleVersion.created_at < timestamp,
                and_(ArticleVersion.created_at == timestamp, ArticleVersion.id < identifier),
            )
        )
    versions = list(
        (
            await session.scalars(
                select(ArticleVersion)
                .where(*conditions)
                .order_by(ArticleVersion.created_at.desc(), ArticleVersion.id.desc())
                .limit(effective_limit + 1)
            )
        ).all()
    )
    has_more = len(versions) > effective_limit
    versions = versions[:effective_limit]
    next_cursor = (
        encode_cursor(versions[-1].created_at, versions[-1].id) if has_more and versions else None
    )
    return page_response([model_dict(version) for version in versions], next_cursor)


@router.put("/articles/{article_id}/content", response_model=contract.ArticleWithVersionResponse)
async def update_article_content(
    article_id: str,
    payload: ArticleContentUpdate,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    attempt = await begin_idempotency(
        session,
        actor_type="user",
        actor_id=user.id,
        scope=f"articles.{article_id}.content",
        key=idempotency_key,
        payload=payload.model_dump(mode="json"),
    )
    if attempt.cached_body:
        return attempt.cached_body
    article, version = await save_article_version(
        session,
        owner_id=user.id,
        article_id=article_id,
        base_version_no=payload.base_version_no,
        title=payload.title,
        summary=payload.summary,
        content=payload.content.model_dump(exclude_none=True),
        source=payload.source,
        created_by_type="user",
        created_by_id=user.id,
    )
    body = {"article": model_dict(article), "version": model_dict(version)}
    complete_idempotency(attempt, body)
    await session.commit()
    return body


@router.post(
    "/articles/{article_id}/versions/restore",
    response_model=contract.ArticleWithVersionResponse,
)
async def restore_version(
    article_id: str,
    payload: RestoreVersionRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    attempt = await begin_idempotency(
        session,
        actor_type="user",
        actor_id=user.id,
        scope=f"articles.{article_id}.restore",
        key=idempotency_key,
        payload=payload.model_dump(),
    )
    if attempt.cached_body:
        return attempt.cached_body
    article, version = await restore_article_version(
        session,
        owner_id=user.id,
        article_id=article_id,
        version_no=payload.version_no,
        base_version_no=payload.base_version_no,
    )
    body = {"article": model_dict(article), "version": model_dict(version)}
    complete_idempotency(attempt, body)
    await session.commit()
    return body


@router.post("/articles/{article_id}/save-local", response_model=contract.SavedArticleResponse)
async def save_local_draft(
    article_id: str,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    attempt = await begin_idempotency(
        session,
        actor_type="user",
        actor_id=user.id,
        scope=f"articles.{article_id}.save_local",
        key=idempotency_key,
        payload={"article_id": article_id},
    )
    if attempt.cached_body:
        return attempt.cached_body
    article = await owned_article(session, owner_id=user.id, article_id=article_id, for_update=True)
    version = await current_article_version(session, article=article)
    article.status = "local_draft"
    item = await upsert_article_library_item(
        session, article=article, version=version, status="local_draft"
    )
    await upsert_article_preference_candidate(
        session,
        article=article,
        version=version,
        source_type="saved_local_article",
        confidence=Decimal("0.3000"),
    )
    create_job(
        session,
        owner_id=user.id,
        job_type="article_indexing",
        resource_type="article",
        resource_id=article.id,
        queue="embedding",
        stage="queued",
        frozen_payload={"article_id": article.id, "version_id": version.id},
    )
    emit_outbox(
        session,
        event_type="article.index.requested",
        aggregate_type="article",
        aggregate_id=article.id,
        payload={"article_id": article.id, "version_id": version.id},
    )
    await session.flush()
    body = {"article": model_dict(article), "library_item": model_dict(item)}
    complete_idempotency(attempt, body)
    await session.commit()
    return body


@router.delete("/articles/{article_id}", status_code=204)
async def delete_article(
    article_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await soft_delete_article(session, owner_id=user.id, article_id=article_id)
    await session.commit()
    return Response(status_code=204)


@router.get("/library-items", response_model=contract.LibraryItemPageResponse)
async def list_library_items(
    query: str | None = Query(default=None, max_length=200),
    project_id: str | None = None,
    item_type: Literal["article", "document"] | None = None,
    status: str | None = Query(default=None, max_length=40),
    cursor: str | None = None,
    limit: int = Query(30, ge=1, le=100),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    conditions = [LibraryItem.owner_id == user.id, LibraryItem.deleted_at.is_(None)]
    if query:
        conditions.append(LibraryItem.search_text.ilike(f"%{query.strip()}%"))
    if project_id == "unclassified":
        conditions.append(LibraryItem.project_id.is_(None))
    elif project_id:
        conditions.append(LibraryItem.project_id == project_id)
    if item_type:
        conditions.append(LibraryItem.item_type == item_type)
    if status:
        conditions.append(LibraryItem.display_status == status)
    decoded = decode_cursor(cursor)
    if decoded:
        timestamp, identifier = decoded
        conditions.append(
            or_(
                LibraryItem.updated_at < timestamp,
                and_(LibraryItem.updated_at == timestamp, LibraryItem.id < identifier),
            )
        )
    rows = list(
        (
            await session.scalars(
                select(LibraryItem)
                .where(*conditions)
                .order_by(LibraryItem.updated_at.desc(), LibraryItem.id.desc())
                .limit(limit + 1)
            )
        ).all()
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = encode_cursor(rows[-1].updated_at, rows[-1].id) if has_more and rows else None
    return page_response([model_dict(row) for row in rows], next_cursor)


@router.get("/library-items/{item_id}", response_model=contract.LibraryItemDetailResponse)
async def get_library_item(
    item_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    item = await session.scalar(
        select(LibraryItem).where(
            LibraryItem.id == item_id,
            LibraryItem.owner_id == user.id,
            LibraryItem.deleted_at.is_(None),
        )
    )
    if not item:
        raise ApiError(404, "LIBRARY_ITEM_NOT_FOUND", "文章库内容不存在。")
    source: dict[str, Any] | None = None
    if item.item_type == "article":
        article = await owned_article(session, owner_id=user.id, article_id=item.source_id)
        version = await current_article_version(session, article=article)
        source = {"article": model_dict(article), "version": model_dict(version)}
    elif item.item_type == "document":
        document = await owned_document(session, owner_id=user.id, document_id=item.source_id)
        source = {"document": model_dict(document)}
    return {"item": model_dict(item), "source": source}


class LibraryItemPatch(BaseModel):
    title: str = Field(min_length=1, max_length=255)


@router.patch("/library-items/{item_id}", response_model=contract.LibraryItemResource)
async def patch_library_item(
    item_id: str,
    payload: LibraryItemPatch,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    item = await session.scalar(
        select(LibraryItem)
        .where(
            LibraryItem.id == item_id,
            LibraryItem.owner_id == user.id,
            LibraryItem.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if not item:
        raise ApiError(404, "LIBRARY_ITEM_NOT_FOUND", "文章库内容不存在。")
    title = payload.title.strip()
    if not title:
        raise ApiError(422, "LIBRARY_TITLE_INVALID", "标题不能为空。")
    item.title = title
    if item.item_type == "article":
        article = await owned_article(session, owner_id=user.id, article_id=item.source_id)
        article.title = title
    elif item.item_type == "document":
        document = await owned_document(session, owner_id=user.id, document_id=item.source_id)
        document.title = title
    await session.commit()
    return model_dict(item)


@router.delete("/library-items/{item_id}", status_code=204)
async def delete_library_item(
    item_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    item = await session.scalar(
        select(LibraryItem).where(
            LibraryItem.id == item_id,
            LibraryItem.owner_id == user.id,
            LibraryItem.deleted_at.is_(None),
        )
    )
    if not item:
        raise ApiError(404, "LIBRARY_ITEM_NOT_FOUND", "文章库内容不存在。")
    item.deleted_at = utcnow()
    if item.item_type == "article":
        await soft_delete_article(session, owner_id=user.id, article_id=item.source_id)
    elif item.item_type == "document":
        document = await owned_document(session, owner_id=user.id, document_id=item.source_id)
        document.status = "deleted"
    await session.commit()
    return Response(status_code=204)


class PersonalSkillCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    category: str = Field(default="content", max_length=80)
    scenario: str = Field(min_length=1, max_length=2000)
    instructions: str = Field(min_length=1, max_length=20_000)
    example_article: str | None = Field(default=None, max_length=50_000)


class PersonalSkillPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    category: str | None = Field(default=None, max_length=80)
    scenario: str | None = Field(default=None, min_length=1, max_length=2000)
    instructions: str | None = Field(default=None, min_length=1, max_length=20_000)
    example_article: str | None = Field(default=None, max_length=50_000)


class SkillSettingPatch(BaseModel):
    enabled: bool


async def ensure_personal_skills_enabled(session: AsyncSession) -> None:
    feature_settings = await published_setting_section(session, "features")
    flags = feature_settings.get("feature_flags", {})
    if isinstance(flags, dict) and flags.get("personal_skills") is False:
        raise ApiError(403, "PERSONAL_SKILLS_DISABLED", "个人技能功能当前已停用。")


@router.get("/skills", response_model=contract.SkillListResponse)
async def list_skills(
    query: str | None = Query(default=None, max_length=100),
    enabled_only: bool = False,
    cursor: str | None = None,
    limit: int = Query(30, ge=1, le=100),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    conditions = [
        Skill.deleted_at.is_(None),
        or_(
            and_(Skill.scope == "official", Skill.status == "published"),
            and_(Skill.scope == "personal", Skill.owner_id == user.id),
        ),
    ]
    if query:
        conditions.append(
            or_(Skill.name.ilike(f"%{query}%"), Skill.description.ilike(f"%{query}%"))
        )
    if enabled_only:
        conditions.append(
            or_(
                UserSkillSetting.enabled.is_(True),
                and_(UserSkillSetting.id.is_(None), Skill.scope == "personal"),
            )
        )
    decoded = decode_sorted_cursor(cursor)
    if decoded:
        sort_order, timestamp, identifier = decoded
        conditions.append(
            or_(
                Skill.sort_order > sort_order,
                and_(Skill.sort_order == sort_order, Skill.created_at > timestamp),
                and_(
                    Skill.sort_order == sort_order,
                    Skill.created_at == timestamp,
                    Skill.id > identifier,
                ),
            )
        )
    skills = list(
        (
            await session.scalars(
                select(Skill)
                .outerjoin(
                    UserSkillSetting,
                    and_(
                        UserSkillSetting.skill_id == Skill.id,
                        UserSkillSetting.user_id == user.id,
                    ),
                )
                .where(*conditions)
                .order_by(Skill.sort_order, Skill.created_at, Skill.id)
                .limit(limit + 1)
            )
        ).all()
    )
    has_more = len(skills) > limit
    skills = skills[:limit]
    skill_ids = [skill.id for skill in skills]
    settings_rows = list(
        (
            await session.scalars(
                select(UserSkillSetting).where(
                    UserSkillSetting.user_id == user.id,
                    UserSkillSetting.skill_id.in_(skill_ids),
                )
            )
        ).all()
    )
    enabled_map = {row.skill_id: row.enabled for row in settings_rows}
    versions = list(
        (
            await session.scalars(
                select(SkillVersion).where(
                    SkillVersion.skill_id.in_(skill_ids),
                    SkillVersion.status == "published",
                )
            )
        ).all()
    )
    current_versions = {skill.id: skill.current_version_no for skill in skills}
    version_map = {
        version.skill_id: version
        for version in versions
        if current_versions.get(version.skill_id) == version.version_no
    }
    items = [
        {
            **model_dict(skill),
            "enabled": enabled_map.get(skill.id, skill.scope == "personal"),
            "version": model_dict(version_map[skill.id]) if skill.id in version_map else None,
        }
        for skill in skills
    ]
    next_cursor = (
        encode_sorted_cursor(skills[-1].sort_order, skills[-1].created_at, skills[-1].id)
        if has_more and skills
        else None
    )
    return page_response(items, next_cursor)


@router.post("/skills", status_code=201, response_model=contract.SkillDetailResponse)
async def create_personal_skill(
    payload: PersonalSkillCreate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ensure_personal_skills_enabled(session)
    code = f"user-{user.id[:8]}-{new_uuid()[:8]}"
    skill = Skill(
        scope="personal",
        owner_id=user.id,
        code=code,
        name=payload.name,
        description=payload.description,
        category=payload.category,
        status="published",
        current_version_no=1,
    )
    session.add(skill)
    await session.flush()
    version_payload: dict[str, Any] = {
        "instructions": payload.instructions,
        "input_schema": {
            "scenario": payload.scenario,
            "example_article": payload.example_article,
        },
        "output_schema": {"type": "article"},
        "tool_policy": {"wechat_publish": False},
    }
    version = SkillVersion(
        skill_id=skill.id,
        version_no=1,
        status="published",
        checksum=hashlib.sha256(
            json.dumps(version_payload, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest(),
        **version_payload,
    )
    session.add(version)
    session.add(UserSkillSetting(user_id=user.id, skill_id=skill.id, enabled=True))
    await session.commit()
    return {"skill": model_dict(skill), "version": model_dict(version), "enabled": True}


@router.get("/skills/{skill_id}", response_model=contract.SkillDetailResponse)
async def get_skill(
    skill_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    skill = await session.scalar(
        select(Skill).where(
            Skill.id == skill_id,
            Skill.deleted_at.is_(None),
            or_(
                and_(Skill.scope == "official", Skill.status == "published"),
                and_(Skill.scope == "personal", Skill.owner_id == user.id),
            ),
        )
    )
    if not skill:
        raise ApiError(404, "SKILL_NOT_FOUND", "技能不存在。")
    version = await session.scalar(
        select(SkillVersion).where(
            SkillVersion.skill_id == skill.id,
            SkillVersion.version_no == skill.current_version_no,
        )
    )
    setting = await session.scalar(
        select(UserSkillSetting).where(
            UserSkillSetting.user_id == user.id, UserSkillSetting.skill_id == skill.id
        )
    )
    return {
        "skill": model_dict(skill),
        "version": model_dict(version) if version else None,
        "enabled": setting.enabled if setting else skill.scope == "personal",
    }


@router.patch("/skills/{skill_id}", response_model=contract.SkillVersionResponse)
async def patch_personal_skill(
    skill_id: str,
    payload: PersonalSkillPatch,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ensure_personal_skills_enabled(session)
    skill = await session.scalar(
        select(Skill)
        .where(
            Skill.id == skill_id,
            Skill.scope == "personal",
            Skill.owner_id == user.id,
            Skill.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if not skill:
        raise ApiError(404, "SKILL_NOT_FOUND", "个人技能不存在。")
    fields = payload.model_fields_set
    required_when_present = {"name", "description", "category", "scenario", "instructions"}
    if any(getattr(payload, field) is None for field in fields & required_when_present):
        raise ApiError(422, "SKILL_FIELD_INVALID", "技能字段不能设置为空值。")
    for field in {"name", "description", "category"} & fields:
        setattr(skill, field, getattr(payload, field))
    version_fields = {"scenario", "instructions", "example_article"}
    version: SkillVersion | None = None
    if fields & version_fields:
        current = await session.scalar(
            select(SkillVersion).where(
                SkillVersion.skill_id == skill.id,
                SkillVersion.version_no == skill.current_version_no,
            )
        )
        if not current:
            raise ApiError(409, "SKILL_VERSION_UNAVAILABLE", "个人技能当前版本不存在。")
        input_schema = dict(current.input_schema)
        if "scenario" in fields:
            input_schema["scenario"] = payload.scenario
        if "example_article" in fields:
            input_schema["example_article"] = payload.example_article
        version_payload: dict[str, Any] = {
            "instructions": payload.instructions
            if "instructions" in fields
            else current.instructions,
            "input_schema": input_schema,
            "output_schema": current.output_schema,
            "tool_policy": current.tool_policy,
        }
        skill.current_version_no += 1
        version = SkillVersion(
            skill_id=skill.id,
            version_no=skill.current_version_no,
            status="published",
            checksum=hashlib.sha256(
                json.dumps(version_payload, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest(),
            **version_payload,
        )
        session.add(version)
    await session.commit()
    return {
        "skill": model_dict(skill),
        "version": model_dict(version) if version else None,
    }


@router.patch("/skills/{skill_id}/setting", response_model=contract.UserSkillSettingResource)
async def patch_skill_setting(
    skill_id: str,
    payload: SkillSettingPatch,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    skill = await session.scalar(
        select(Skill).where(
            Skill.id == skill_id,
            Skill.deleted_at.is_(None),
            or_(
                Skill.owner_id == user.id,
                and_(Skill.scope == "official", Skill.status == "published"),
            ),
        )
    )
    if not skill:
        raise ApiError(404, "SKILL_NOT_FOUND", "技能不存在。")
    setting_row = await session.scalar(
        select(UserSkillSetting).where(
            UserSkillSetting.user_id == user.id, UserSkillSetting.skill_id == skill.id
        )
    )
    if not setting_row:
        setting_row = UserSkillSetting(user_id=user.id, skill_id=skill.id, enabled=payload.enabled)
        session.add(setting_row)
    else:
        setting_row.enabled = payload.enabled
    await session.commit()
    return model_dict(setting_row)


@router.delete("/skills/{skill_id}", status_code=204)
async def delete_personal_skill(
    skill_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await ensure_personal_skills_enabled(session)
    skill = await session.scalar(
        select(Skill).where(
            Skill.id == skill_id,
            Skill.scope == "personal",
            Skill.owner_id == user.id,
            Skill.deleted_at.is_(None),
        )
    )
    if not skill:
        raise ApiError(404, "SKILL_NOT_FOUND", "个人技能不存在。")
    skill.deleted_at = utcnow()
    await session.commit()
    return Response(status_code=204)


class PreferenceCreate(BaseModel):
    preference_type: str = Field(min_length=1, max_length=64)
    value: str = Field(min_length=1, max_length=2000)
    scope: Literal["personal", "project"] = "personal"
    project_id: str | None = None
    confidence: float = Field(default=1, ge=0, le=1)


class PreferencePatch(BaseModel):
    value: str | None = Field(default=None, min_length=1, max_length=2000)
    status: Literal["candidate", "confirmed", "revoked"] | None = None


@router.get("/preferences", response_model=contract.PreferenceListResponse)
async def list_preferences(
    project_id: str | None = None,
    cursor: str | None = None,
    limit: int = Query(30, ge=1, le=100),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    conditions = [UserPreference.user_id == user.id, UserPreference.status != "revoked"]
    if project_id:
        conditions.append(UserPreference.project_id == project_id)
    decoded = decode_cursor(cursor)
    if decoded:
        timestamp, identifier = decoded
        conditions.append(
            or_(
                UserPreference.updated_at < timestamp,
                and_(UserPreference.updated_at == timestamp, UserPreference.id < identifier),
            )
        )
    rows = list(
        (
            await session.scalars(
                select(UserPreference)
                .where(*conditions)
                .order_by(UserPreference.updated_at.desc(), UserPreference.id.desc())
                .limit(limit + 1)
            )
        ).all()
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = encode_cursor(rows[-1].updated_at, rows[-1].id) if has_more and rows else None
    return page_response([model_dict(row) for row in rows], next_cursor)


@router.post("/preferences", status_code=201, response_model=contract.UserPreferenceResource)
async def create_preference(
    payload: PreferenceCreate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if payload.scope == "project" and not payload.project_id:
        raise ApiError(422, "PROJECT_REQUIRED", "项目偏好需要指定项目。")
    if payload.scope == "personal" and payload.project_id:
        raise ApiError(422, "PREFERENCE_SCOPE_INVALID", "个人偏好不能绑定项目。")
    if payload.project_id:
        await owned_project(session, owner_id=user.id, project_id=payload.project_id)
    from app.domains.conversation_actions import create_preference as save_preference

    preference = await save_preference(session, user.id, payload.model_dump())
    await session.commit()
    return model_dict(preference)


@router.patch("/preferences/{preference_id}", response_model=contract.UserPreferenceResource)
async def patch_preference(
    preference_id: str,
    payload: PreferencePatch,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    from app.domains.conversation_actions import owned_preference, update_preference

    preference = await owned_preference(session, user.id, preference_id)
    update_preference(session, preference, payload.model_dump(exclude_unset=True))
    await session.commit()
    return model_dict(preference)


@router.delete("/preferences/{preference_id}", status_code=204)
async def delete_preference(
    preference_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    from app.domains.conversation_actions import owned_preference, update_preference

    preference = await owned_preference(session, user.id, preference_id)
    update_preference(session, preference, {"status": "revoked"})
    await session.commit()
    return Response(status_code=204)


@router.get("/public-settings", response_model=contract.PublicSettingsResponse)
async def public_settings(
    user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    del user
    return await published_system_settings(session)


class LayoutTemplateCreate(BaseModel):
    official_account_id: str | None = None
    name: str = Field(min_length=1, max_length=120)
    enabled: bool = False
    style_tokens: contract.StyleTokenPayload = Field(
        default_factory=lambda: contract.StyleTokenPayload.model_validate(DEFAULT_STYLE_TOKENS)
    )


class LayoutTemplatePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    enabled: bool | None = None
    style_tokens: contract.StyleTokenPayload | None = None


class LayoutExtractRequest(BaseModel):
    source_url: str = Field(min_length=12, max_length=1000)
    official_account_id: str | None = None
    name: str = Field(default="待提取模板", min_length=1, max_length=120)
    save_template: bool = True


@router.get(
    "/layout-templates",
    response_model=contract.LayoutTemplateListResponse,
)
async def list_layout_templates(
    official_account_id: str | None = None,
    enabled_only: bool = False,
    cursor: str | None = None,
    limit: int = Query(30, ge=1, le=100),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    conditions = [
        LayoutTemplate.owner_id == user.id,
        LayoutTemplate.deleted_at.is_(None),
        or_(LayoutTemplate.extraction_status != "failed", LayoutTemplate.current_version_no > 0),
    ]
    if official_account_id:
        conditions.append(LayoutTemplate.official_account_id == official_account_id)
    if enabled_only:
        conditions.append(LayoutTemplate.enabled.is_(True))
    decoded = decode_cursor(cursor)
    if decoded:
        timestamp, identifier = decoded
        conditions.append(
            or_(
                LayoutTemplate.updated_at < timestamp,
                and_(
                    LayoutTemplate.updated_at == timestamp,
                    LayoutTemplate.id < identifier,
                ),
            )
        )
    templates = list(
        (
            await session.scalars(
                select(LayoutTemplate)
                .where(*conditions)
                .order_by(LayoutTemplate.updated_at.desc(), LayoutTemplate.id.desc())
                .limit(limit + 1)
            )
        ).all()
    )
    has_more = len(templates) > limit
    templates = templates[:limit]
    versions = list(
        (
            await session.scalars(
                select(LayoutTemplateVersion).where(
                    LayoutTemplateVersion.template_id.in_([item.id for item in templates])
                )
            )
        ).all()
    )
    current_versions = {item.id: item.current_version_no for item in templates}
    version_map = {
        version.template_id: version
        for version in versions
        if current_versions.get(version.template_id) == version.version_no
    }
    items = [
        {
            **model_dict(item),
            "version": model_dict(version_map[item.id]) if item.id in version_map else None,
        }
        for item in templates
    ]
    next_cursor = (
        encode_cursor(templates[-1].updated_at, templates[-1].id)
        if has_more and templates
        else None
    )
    return page_response(items, next_cursor)


@router.post(
    "/layout-templates",
    status_code=201,
    response_model=contract.LayoutTemplateVersionResponse,
)
async def create_layout_template(
    payload: LayoutTemplateCreate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if payload.official_account_id:
        await owned_official_account(
            session, owner_id=user.id, account_id=payload.official_account_id
        )
    template = LayoutTemplate(
        owner_id=user.id,
        official_account_id=payload.official_account_id,
        name=payload.name,
        enabled=payload.enabled,
        extraction_status="manual",
    )
    session.add(template)
    await session.flush()
    version = await add_template_version(
        session,
        template=template,
        style_tokens=payload.style_tokens.model_dump(exclude_none=True),
    )
    await session.commit()
    return {"template": model_dict(template), "version": model_dict(version)}


@router.post(
    "/layout-templates/extract",
    status_code=202,
    response_model=contract.LayoutExtractionResponse,
)
async def extract_layout_template(
    payload: LayoutExtractRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    provider: LayoutExtractionProvider = Depends(layout_extraction_provider),
    model: ModelProvider = Depends(model_provider),
    secrets: SecretProvider = Depends(secret_provider),
    config: Settings = Depends(settings),
) -> dict[str, Any]:
    feature_settings = await published_setting_section(session, "features")
    flags = feature_settings.get("feature_flags", {})
    if isinstance(flags, dict) and flags.get("template_extraction") is False:
        raise ApiError(403, "TEMPLATE_EXTRACTION_DISABLED", "公众号模板提取当前已停用。")
    source_url = validate_source_url(payload.source_url)
    route_snapshot = await active_route_snapshot(
        session,
        purpose="layout_extraction",
        settings=config,
    )
    if payload.official_account_id:
        await owned_official_account(
            session, owner_id=user.id, account_id=payload.official_account_id
        )
    template = LayoutTemplate(
        owner_id=user.id,
        official_account_id=payload.official_account_id,
        name=payload.name,
        enabled=False,
        source_url=source_url,
        extraction_status="queued",
    )
    session.add(template)
    await session.flush()
    create_job(
        session,
        owner_id=user.id,
        job_type="layout_extraction",
        resource_type="layout_template",
        resource_id=template.id,
        queue="files",
        stage="queued",
        frozen_payload={
            "template_id": template.id,
            "source_url": source_url,
            "save_template": payload.save_template,
            "model_route": route_snapshot,
        },
    )
    emit_outbox(
        session,
        event_type="layout.extraction.requested",
        aggregate_type="layout_template",
        aggregate_id=template.id,
        payload={"template_id": template.id},
    )
    await session.flush()
    try:
        template = await process_layout_extraction(
            session,
            template_id=template.id,
            provider=provider,
            route_snapshot=route_snapshot,
            model=model,
            secrets=secrets,
            settings=config,
        )
    except ProviderUnavailable as exc:
        await session.rollback()
        raise ApiError(422, "LAYOUT_PROVIDER_FAILED", str(exc)) from exc
    version = await session.scalar(
        select(LayoutTemplateVersion).where(
            LayoutTemplateVersion.template_id == template.id,
            LayoutTemplateVersion.version_no == template.current_version_no,
        )
    )
    model_assist = (
        version.source_snapshot.get("model_assist", {})
        if version and isinstance(version.source_snapshot, dict)
        else {}
    )
    used_layout_agent = isinstance(model_assist, dict) and model_assist.get("status") == "completed"
    await session.commit()
    return {
        "template": model_dict(template),
        "version": model_dict(version) if version else None,
        "provider_status": template.extraction_status,
        "message": (
            (
                "排版智能体已结合真实公众号文章完成模板学习。"
                if used_layout_agent
                else "模板已使用真实公众号文章的基础样式完成提取，可继续手动调整。"
            )
            if template.extraction_status == "completed"
            else "模板提取已排队；抓取失败时会记录原因，不会生成模拟模板。"
        ),
    }


@router.get("/layout-templates/{template_id}", response_model=contract.LayoutTemplateDetailResponse)
async def get_layout_template(
    template_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    template = await owned_template(session, owner_id=user.id, template_id=template_id)
    versions = list(
        (
            await session.scalars(
                select(LayoutTemplateVersion)
                .where(LayoutTemplateVersion.template_id == template.id)
                .order_by(LayoutTemplateVersion.version_no.desc())
            )
        ).all()
    )
    return {
        "template": model_dict(template),
        "versions": [model_dict(v) for v in versions],
    }


@router.patch(
    "/layout-templates/{template_id}", response_model=contract.LayoutTemplateVersionResponse
)
async def patch_layout_template(
    template_id: str,
    payload: LayoutTemplatePatch,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    template = await owned_template(session, owner_id=user.id, template_id=template_id)
    if payload.name is not None:
        template.name = payload.name
    if payload.enabled is not None:
        template.enabled = payload.enabled
    version = None
    if payload.style_tokens is not None:
        version = await add_template_version(
            session,
            template=template,
            style_tokens=payload.style_tokens.model_dump(exclude_none=True),
        )
    await session.commit()
    return {
        "template": model_dict(template),
        "version": model_dict(version) if version else None,
    }


@router.delete("/layout-templates/{template_id}", status_code=204)
async def delete_layout_template(
    template_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    template = await owned_template(session, owner_id=user.id, template_id=template_id)
    template.deleted_at = utcnow()
    template.enabled = False
    await session.commit()
    return Response(status_code=204)


class RenderCreate(BaseModel):
    article_id: str
    article_version_no: int | None = Field(default=None, ge=1)
    template_id: str | None = None
    official_account_id: str | None = None
    cover_asset_id: str | None = None


class RenderConfirmRequest(BaseModel):
    action: Literal["draft", "publish"]


@router.post("/article-renders", status_code=201, response_model=contract.ArticleRenderResource)
async def create_article_render(
    payload: RenderCreate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    config: Settings = Depends(settings),
    storage: StorageProvider = Depends(storage_provider),
) -> dict[str, Any]:
    if payload.official_account_id:
        await owned_official_account(
            session, owner_id=user.id, account_id=payload.official_account_id
        )
    if payload.cover_asset_id:
        cover = await session.scalar(
            select(Asset).where(
                Asset.id == payload.cover_asset_id,
                Asset.owner_id == user.id,
                Asset.deleted_at.is_(None),
            )
        )
        if not cover:
            raise ApiError(404, "COVER_ASSET_NOT_FOUND", "封面图片不存在。")
        if not cover.mime_type.startswith("image/"):
            raise ApiError(422, "COVER_ASSET_TYPE_INVALID", "封面必须是图片文件。")
        ready_states = {"clean", "completed", "ready"}
        if cover.scan_status not in ready_states:
            raise ApiError(
                409,
                "COVER_ASSET_NOT_READY",
                "封面图片尚未完成安全扫描。",
                retryable=True,
            )
        try:
            readable = await storage.verify_object(
                object_key=cover.object_key,
                size_bytes=cover.size_bytes,
                sha256=cover.sha256,
            )
        except ProviderUnavailable as exc:
            raise ApiError(
                503,
                "COVER_STORAGE_UNAVAILABLE",
                "封面存储服务暂不可用，请稍后重试。",
                retryable=True,
            ) from exc
        if not readable:
            raise ApiError(
                409,
                "COVER_ASSET_NOT_READY",
                "封面对象当前不可读取，请重新上传或稍后重试。",
                retryable=True,
            )
    render = await create_render(
        session,
        owner_id=user.id,
        article_id=payload.article_id,
        article_version_no=payload.article_version_no,
        template_id=payload.template_id,
        official_account_id=payload.official_account_id,
        cover_asset_id=payload.cover_asset_id,
        max_article_images=(
            int(max_images)
            if isinstance(
                max_images := (await published_setting_section(session, "wechat")).get(
                    "max_article_images"
                ),
                int,
            )
            else None
        ),
    )
    await session.commit()
    return model_dict(render)


@router.get(
    "/article-renders/{render_id}/download",
    response_class=Response,
    responses={
        200: {
            "content": {
                mime: {"schema": {"type": "string", "format": "binary"}}
                for mime in [
                    "application/pdf",
                    "text/markdown",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ]
            }
        }
    },
)
async def download_article_render(
    render_id: str,
    format: Literal["md", "pdf", "docx"],
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    from starlette.concurrency import run_in_threadpool

    from app.article_export import MIME, export_article

    render = await owned_render(session, owner_id=user.id, render_id=render_id)
    article = await owned_article(session, owner_id=user.id, article_id=render.article_id)
    content = await run_in_threadpool(export_article, render.html, article.title, format)
    return Response(
        content,
        media_type=MIME[format],
        headers={
            "Content-Disposition": f'attachment; filename="article.{format}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/article-renders/{render_id}", response_model=contract.ArticleRenderResource)
async def get_article_render(
    render_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    render = await owned_render(session, owner_id=user.id, render_id=render_id)
    return model_dict(render)


@router.post(
    "/article-renders/{render_id}/confirm",
    response_model=contract.ArticleConfirmationResource,
)
async def confirm_article_render(
    render_id: str,
    payload: RenderConfirmRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    confirmation = await confirm_render(
        session, owner_id=user.id, render_id=render_id, action=payload.action
    )
    await session.commit()
    return model_dict(confirmation)


class AuthorizationUrlRequest(BaseModel):
    redirect_uri: str = Field(min_length=8, max_length=1000)


@router.post("/official-accounts/authorize-url", response_model=contract.AuthorizationUrlResponse)
async def create_authorization_url(
    payload: AuthorizationUrlRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    provider: WechatProvider = Depends(wechat_provider),
    config: Settings = Depends(settings),
    secrets: SecretProvider = Depends(secret_provider),
    limiter: RateLimiter = Depends(rate_limiter),
) -> dict[str, Any]:
    parsed_redirect = urlparse(payload.redirect_uri)
    try:
        redirect_origin = (
            parsed_redirect.scheme.lower(),
            (parsed_redirect.hostname or "").lower(),
            parsed_redirect.port,
        )
        allowed = {
            (
                parsed.scheme.lower(),
                (parsed.hostname or "").lower(),
                parsed.port,
            )
            for parsed in map(urlparse, config.allowed_origins)
        }
    except ValueError as exc:
        raise ApiError(422, "REDIRECT_URI_INVALID", "授权回跳地址不在允许范围内。") from exc
    if (
        redirect_origin not in allowed
        or parsed_redirect.username
        or parsed_redirect.password
        or parsed_redirect.scheme not in {"http", "https"}
    ):
        raise ApiError(422, "REDIRECT_URI_INVALID", "授权回跳地址不在允许范围内。")
    await limiter.check(f"wechat-authorize:{user.id}", 10, 300)
    state = new_opaque_token()
    platform_config: WechatPlatformConfig | None = None
    expires_in = 300
    if config.wechat_provider_mode == "direct":
        platform_config = await published_wechat_config(session, environment=config.environment)
        if not platform_config:
            raise ApiError(
                503,
                "WECHAT_PLATFORM_NOT_CONFIGURED",
                "微信第三方平台配置尚未发布，暂时无法生成授权二维码。",
            )
        client = WechatOpenPlatformClient()
        try:
            token = await component_access_token(
                session,
                config=platform_config,
                secrets=secrets,
                client=client,
            )
            authorization = await client.pre_authorization(
                component_appid=platform_config.component_appid,
                component_access_token=token,
                callback_url=platform_config.authorization_callback_url,
                state=state,
                mobile=True,
            )
            url = authorization.url
            expires_in = authorization.expires_in
        except ProviderUnavailable as exc:
            raise ApiError(
                503,
                "WECHAT_PLATFORM_NOT_READY",
                "微信第三方平台尚未收到有效票据或凭据验证失败，请联系管理员检查配置。",
                retryable=True,
            ) from exc
    else:
        try:
            url = await provider.authorization_url(state=state, redirect_uri=payload.redirect_uri)
        except ProviderUnavailable as exc:
            raise ApiError(
                503,
                "WECHAT_PLATFORM_NOT_CONFIGURED",
                "微信第三方平台尚未配置，暂时无法生成授权二维码。",
            ) from exc
    session.add(
        WechatAuthorizationState(
            owner_id=user.id,
            platform_config_id=platform_config.id if platform_config else None,
            state_hash=hash_token(state),
            redirect_uri=payload.redirect_uri,
            expires_at=utcnow() + timedelta(seconds=expires_in),
        )
    )
    await session.commit()
    return {"authorization_url": url, "expires_in": expires_in}


@router.get("/official-accounts", response_model=contract.OfficialAccountListResponse)
async def list_official_accounts(
    cursor: str | None = None,
    limit: int = Query(30, ge=1, le=100),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    conditions = [
        OfficialAccount.owner_id == user.id,
        OfficialAccount.deleted_at.is_(None),
    ]
    decoded = decode_cursor(cursor)
    if decoded:
        timestamp, identifier = decoded
        conditions.append(
            or_(
                OfficialAccount.updated_at < timestamp,
                and_(OfficialAccount.updated_at == timestamp, OfficialAccount.id < identifier),
            )
        )
    accounts = list(
        (
            await session.scalars(
                select(OfficialAccount)
                .where(*conditions)
                .order_by(OfficialAccount.updated_at.desc(), OfficialAccount.id.desc())
                .limit(limit + 1)
            )
        ).all()
    )
    has_more = len(accounts) > limit
    accounts = accounts[:limit]
    next_cursor = (
        encode_cursor(accounts[-1].updated_at, accounts[-1].id) if has_more and accounts else None
    )
    return page_response([_official_account_public(account) for account in accounts], next_cursor)


def _official_account_public(account: OfficialAccount) -> dict[str, Any]:
    if account.status == "reconnect_required":
        ui_status = "reconnect_required"
    elif not set(account.capability_flags) & {"draft", "publish"}:
        ui_status = "unsupported"
    else:
        ui_status = "connected"
    return {
        "id": account.id,
        "name": account.name,
        "avatar_url": account.avatar_url,
        "status": account.status,
        "ui_status": ui_status,
        "capabilities": account.capability_flags,
        "authorized_at": account.authorized_at,
        "last_synced_at": account.last_synced_at,
        "created_at": account.created_at,
        "updated_at": account.updated_at,
    }


@router.get("/official-accounts/{account_id}", response_model=contract.OfficialAccountResponse)
async def get_official_account(
    account_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    account = await owned_official_account(session, owner_id=user.id, account_id=account_id)
    return _official_account_public(account)


@router.delete("/official-accounts/{account_id}", status_code=204)
async def delete_official_account(
    account_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    account = await owned_official_account(session, owner_id=user.id, account_id=account_id)
    account.status = "revoked"
    account.deleted_at = utcnow()
    await session.commit()
    return Response(status_code=204)


class WechatOperationRequest(BaseModel):
    render_id: str


async def _create_wechat_endpoint(
    *,
    operation_type: Literal["draft", "publish"],
    payload: WechatOperationRequest,
    request: Request,
    idempotency_key: str | None,
    user: User,
    session: AsyncSession,
    provider: WechatProvider,
    config: Settings,
    secrets: SecretProvider,
) -> dict[str, Any]:
    if config.wechat_provider_mode == "direct":
        render = await owned_render(session, owner_id=user.id, render_id=payload.render_id)
        if render.official_account_id:
            try:
                await ensure_authorizer_access_token(
                    session,
                    account_id=render.official_account_id,
                    environment=config.environment,
                    secrets=secrets,
                    client=WechatOpenPlatformClient(),
                )
            except ProviderReauthorizationRequired as exc:
                raise ApiError(
                    403,
                    "reauth_required",
                    "公众号授权已解除，请管理员重新扫码绑定。",
                ) from exc
            except ProviderAuthenticationError as exc:
                raise ApiError(
                    503,
                    "WECHAT_TOKEN_REFRESH_FAILED",
                    "公众号接口令牌自动续期暂时失败，请稍后重试，无需重新扫码。",
                    retryable=True,
                ) from exc
            except ProviderUnavailable as exc:
                raise ApiError(
                    503,
                    "WECHAT_PLATFORM_NOT_READY",
                    "微信平台暂时不可用，请稍后重试。",
                    retryable=True,
                ) from exc
    scope = "wechat.drafts" if operation_type == "draft" else "wechat.publishes"
    attempt = await begin_idempotency(
        session,
        actor_type="user",
        actor_id=user.id,
        scope=scope,
        key=idempotency_key,
        payload=payload.model_dump(),
    )
    if attempt.cached_body:
        return attempt.cached_body
    operation = await create_wechat_operation(
        session,
        owner_id=user.id,
        render_id=payload.render_id,
        operation_type=operation_type,
        idempotency_key=idempotency_key or "",
    )
    body = model_dict(operation)
    complete_idempotency(attempt, body, 202)
    await session.commit()
    return body


@router.post("/wechat-drafts", status_code=202, response_model=contract.WechatOperationResource)
async def create_wechat_draft(
    payload: WechatOperationRequest,
    request: Request,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    provider: WechatProvider = Depends(wechat_provider),
    config: Settings = Depends(settings),
    secrets: SecretProvider = Depends(secret_provider),
) -> dict[str, Any]:
    return await _create_wechat_endpoint(
        operation_type="draft",
        payload=payload,
        request=request,
        idempotency_key=idempotency_key,
        user=user,
        session=session,
        provider=provider,
        config=config,
        secrets=secrets,
    )


@router.post("/wechat-publishes", status_code=202, response_model=contract.WechatOperationResource)
async def create_wechat_publish(
    payload: WechatOperationRequest,
    request: Request,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    provider: WechatProvider = Depends(wechat_provider),
    config: Settings = Depends(settings),
    secrets: SecretProvider = Depends(secret_provider),
) -> dict[str, Any]:
    return await _create_wechat_endpoint(
        operation_type="publish",
        payload=payload,
        request=request,
        idempotency_key=idempotency_key,
        user=user,
        session=session,
        provider=provider,
        config=config,
        secrets=secrets,
    )


@router.get(
    "/articles/{article_id}/wechat-operation",
    response_model=contract.CurrentWechatOperationResponse,
)
async def get_current_article_wechat_operation(
    article_id: str,
    operation_type: Literal["draft", "publish"] | None = None,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    operation = await current_wechat_operation(
        session,
        owner_id=user.id,
        article_id=article_id,
        operation_type=operation_type,
    )
    return {"operation": model_dict(operation) if operation else None}


@router.get("/wechat-operations/{operation_id}", response_model=contract.WechatOperationResource)
async def get_wechat_operation(
    operation_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    operation = await session.scalar(
        select(WechatOperation).where(
            WechatOperation.id == operation_id, WechatOperation.owner_id == user.id
        )
    )
    if not operation:
        raise ApiError(404, "WECHAT_OPERATION_NOT_FOUND", "公众号操作不存在。")
    return model_dict(operation)

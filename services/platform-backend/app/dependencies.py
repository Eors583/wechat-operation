from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database import get_session
from app.errors import ApiError
from app.models import Admin, AdminSession, ExternalKnowledgeSource, RefreshToken, User, utcnow
from app.providers import (
    ContentSafetyProvider,
    DocumentProcessingProvider,
    EmbeddingProvider,
    LayoutExtractionProvider,
    ModelProvider,
    ProviderUnavailable,
    RerankProvider,
    SecretProvider,
    StorageProvider,
    VerificationProvider,
    WebReferenceProvider,
    WechatProvider,
)
from app.retrieval import RetrievalService
from app.security import RateLimiter, decode_access_token

bearer = HTTPBearer(auto_error=False)


def settings(request: Request) -> Settings:
    return request.app.state.settings


def rate_limiter(request: Request) -> RateLimiter:
    return request.app.state.rate_limiter


def verification_provider(request: Request) -> VerificationProvider:
    return request.app.state.verification_provider


def storage_provider(request: Request) -> StorageProvider:
    return request.app.state.storage_provider


def document_processing_provider(request: Request) -> DocumentProcessingProvider:
    return request.app.state.document_processing_provider


async def _wechat_article_api_configs(
    session: AsyncSession, secrets: SecretProvider
) -> list[Any]:
    rows = list(
        (
            await session.scalars(
                select(ExternalKnowledgeSource)
                .where(ExternalKnowledgeSource.source_type == "wechat_article_api")
                .order_by(ExternalKnowledgeSource.created_at)
            )
        ).all()
    )
    if not rows:
        from app.wechat_public_layout import DEFAULT_MPTEXT_CONFIG

        return [DEFAULT_MPTEXT_CONFIG]
    from app.wechat_public_layout import WeChatArticleApiConfig

    configs: list[WeChatArticleApiConfig] = []
    for row in rows:
        if row.status != "active":
            continue
        configuration = row.configuration
        try:
            api_key = secrets.resolve(row.secret_ref) if row.secret_ref else None
        except ProviderUnavailable:
            continue
        configs.append(
            WeChatArticleApiConfig(
                name=row.name,
                base_url=str(configuration.get("base_url", "")),
                priority=int(configuration.get("priority", 100)),
                api_key=api_key,
                auth_header=str(configuration.get("auth_header", "X-Auth-Key")),
                auth_prefix=str(configuration.get("auth_prefix", "")),
            )
        )
    return configs


async def layout_extraction_provider(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> LayoutExtractionProvider:
    provider = request.app.state.layout_extraction_provider
    from app.wechat_public_layout import WeChatPublicLayoutExtractionProvider

    if isinstance(provider, WeChatPublicLayoutExtractionProvider):
        if provider._transport is not None:  # Preserve explicit test/custom transports.
            return provider
        return WeChatPublicLayoutExtractionProvider(
            timeout_seconds=request.app.state.settings.model_timeout_seconds,
            article_apis=await _wechat_article_api_configs(
                session, request.app.state.secret_provider
            ),
        )
    return provider


def model_provider(request: Request) -> ModelProvider:
    return request.app.state.model_provider


def embedding_provider(request: Request) -> EmbeddingProvider:
    return request.app.state.embedding_provider


def rerank_provider(request: Request) -> RerankProvider:
    return request.app.state.rerank_provider


def content_safety_provider(request: Request) -> ContentSafetyProvider:
    return request.app.state.content_safety_provider


def wechat_provider(request: Request) -> WechatProvider:
    return request.app.state.wechat_provider


async def web_reference_provider(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> WebReferenceProvider:
    from app.web_references import SafeHttpWebReferenceProvider

    configured = request.app.state.web_reference_provider
    if not isinstance(configured, SafeHttpWebReferenceProvider):
        return configured
    if configured._transport is not None:  # Preserve explicit test/custom transports.
        return configured
    return SafeHttpWebReferenceProvider(
        article_apis=await _wechat_article_api_configs(
            session, request.app.state.secret_provider
        )
    )


def secret_provider(request: Request) -> SecretProvider:
    return request.app.state.secret_provider


def retrieval_service(request: Request) -> RetrievalService:
    return request.app.state.retrieval


async def current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: AsyncSession = Depends(get_session),
) -> User:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise ApiError(401, "AUTHENTICATION_REQUIRED", "请先登录。")
    app_settings: Settings = request.app.state.settings
    claims = decode_access_token(credentials.credentials, app_settings.token_secret, "user_access")
    user = await session.get(User, str(claims["sub"]))
    active_family = await session.scalar(
        select(
            exists().where(
                RefreshToken.user_id == str(claims["sub"]),
                RefreshToken.family_id == str(claims["sid"]),
                RefreshToken.revoked_at.is_(None),
                RefreshToken.expires_at > utcnow(),
            )
        )
    )
    if not user or user.status != "active" or user.deleted_at or not active_family:
        raise ApiError(401, "INVALID_SESSION", "登录状态无效或已撤销。")
    request.state.user_session_family = str(claims["sid"])
    return user


async def current_admin(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: AsyncSession = Depends(get_session),
) -> Admin:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise ApiError(401, "ADMIN_AUTHENTICATION_REQUIRED", "请先登录管理端。")
    app_settings: Settings = request.app.state.settings
    claims = decode_access_token(credentials.credentials, app_settings.token_secret, "admin_access")
    admin = await session.get(Admin, str(claims["sub"]))
    admin_session = await session.scalar(
        select(AdminSession).where(
            AdminSession.id == str(claims["sid"]),
            AdminSession.admin_id == str(claims["sub"]),
            AdminSession.revoked_at.is_(None),
            AdminSession.expires_at > utcnow(),
        )
    )
    if not admin or admin.status != "active" or not admin_session:
        raise ApiError(401, "INVALID_ADMIN_SESSION", "管理端登录状态无效或已撤销。")
    request.state.admin_session_id = admin_session.id
    return admin


def require_admin_permission(
    permission: str,
) -> Callable[..., Coroutine[Any, Any, Admin]]:
    async def dependency(admin: Admin = Depends(current_admin)) -> Admin:
        if "*" not in admin.permissions and permission not in admin.permissions:
            raise ApiError(403, "ADMIN_PERMISSION_DENIED", "当前管理员没有此操作权限。")
        return admin

    return dependency


def validate_csrf(request: Request, cookie_name: str) -> None:
    cookie = request.cookies.get(cookie_name)
    header = request.headers.get("X-CSRF-Token")
    if not cookie or not header or cookie != header:
        raise ApiError(403, "CSRF_VALIDATION_FAILED", "安全校验失败，请刷新页面后重试。")

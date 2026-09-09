from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timedelta
from html import escape
from typing import Any, Literal
from urllib.parse import urlencode, urljoin, urlsplit

from fastapi import APIRouter, Depends, Header, Path, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.dependencies import rate_limiter, secret_provider
from app.domains.identity import is_expired
from app.domains.wechat import sync_article_operation_status
from app.errors import ApiError
from app.models import (
    JobRecord,
    OfficialAccount,
    WechatAuthorizationState,
    WechatCallback,
    WechatOperation,
    WechatPlatformConfig,
    utcnow,
)
from app.providers import ProviderUnavailable, SecretProvider
from app.security import RateLimiter, hash_token
from app.wechat_open_platform import (
    WechatOpenPlatformClient,
    add_query_parameters,
    capability_flags,
    component_access_token,
    decrypt_callback,
    decrypt_callback_message,
    parse_encrypted_callback,
)

from . import contracts as contract

router = APIRouter(prefix="/callbacks/v1", responses=contract.COMMON_ERROR_RESPONSES)


class NormalizedWechatEvent(BaseModel):
    event_key: str = Field(min_length=8, max_length=180)
    event_type: str = Field(min_length=1, max_length=80)
    encrypted_payload: str = Field(min_length=1, max_length=1_000_000)
    operation_id: str | None = None
    status: Literal["processing", "succeeded", "failed", "unknown"] | None = None
    stage: Literal["draft", "publish"] | None = None
    media_id: str | None = Field(default=None, max_length=180)
    publish_id: str | None = Field(default=None, max_length=180)
    result: dict[str, Any] = Field(default_factory=dict)


def _verify_normalized_signature(body: bytes, signature: str | None) -> None:
    secret = os.getenv("WECHAT_CALLBACK_HMAC_SECRET")
    if not secret:
        raise ApiError(
            503,
            "CALLBACK_VERIFIER_NOT_CONFIGURED",
            "微信回调验证器尚未配置。",
        )
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not signature or not hmac.compare_digest(signature, expected):
        raise ApiError(401, "CALLBACK_SIGNATURE_INVALID", "回调签名无效。")


@router.post("/wechat/operations", response_model=contract.CallbackAckResponse)
async def normalized_wechat_operation_callback(
    request: Request,
    signature: str | None = Header(default=None, alias="X-Callback-Signature"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    body = await request.body()
    _verify_normalized_signature(body, signature)
    try:
        payload = NormalizedWechatEvent.model_validate_json(body)
    except ValueError as exc:
        raise ApiError(422, "CALLBACK_PAYLOAD_INVALID", "回调内容无效。") from exc
    existing = await session.scalar(
        select(WechatCallback).where(WechatCallback.event_key == payload.event_key)
    )
    if existing:
        return {"accepted": True, "duplicate": True}
    callback = WechatCallback(
        event_key=payload.event_key,
        event_type=payload.event_type,
        encrypted_payload=payload.encrypted_payload,
    )
    session.add(callback)
    if payload.operation_id and payload.status:
        operation = await session.scalar(
            select(WechatOperation)
            .where(WechatOperation.id == payload.operation_id)
            .with_for_update()
        )
        if operation:
            terminal = {"succeeded", "failed", "cancelled"}
            if operation.status not in terminal:
                operation.status = (
                    "submitting" if payload.status == "processing" else payload.status
                )
                if (
                    operation.status == "succeeded"
                    and operation.operation_type == "publish"
                    and payload.stage == "draft"
                ):
                    operation.status = "failed"
                    operation.error_code = "DRAFT_RECONCILED_PUBLISH_PENDING"
                operation.media_id = payload.media_id or operation.media_id
                operation.publish_id = payload.publish_id or operation.publish_id
                operation.result = dict(payload.result)
                if payload.stage:
                    operation.result["external_stage"] = payload.stage
                    if operation.status == "unknown":
                        operation.result["unknown_stage"] = payload.stage
                if operation.status == "succeeded":
                    operation.error_code = None
                elif operation.status == "failed":
                    operation.error_code = (
                        operation.error_code or "WECHAT_CALLBACK_REPORTED_FAILURE"
                    )
                elif operation.status == "unknown":
                    operation.error_code = (
                        operation.error_code or "WECHAT_CALLBACK_REPORTED_UNKNOWN"
                    )
                await sync_article_operation_status(session, operation=operation)
                job = await session.scalar(
                    select(JobRecord).where(
                        JobRecord.resource_type == "wechat_operation",
                        JobRecord.resource_id == operation.id,
                    )
                )
                if job:
                    job.status = operation.status
                    job.stage = "callback"
                    job.progress = 100 if operation.status == "succeeded" else job.progress
                    job.error_code = operation.error_code
    callback.processed_at = utcnow()
    await session.commit()
    return {"accepted": True, "duplicate": False}


class NormalizedTicketEvent(BaseModel):
    event_key: str = Field(min_length=8, max_length=180)
    environment: str = Field(min_length=1, max_length=32)
    encrypted_payload: str = Field(min_length=1, max_length=1_000_000)


class NormalizedAuthorizationEvent(BaseModel):
    event_key: str = Field(min_length=8, max_length=180)
    state: str = Field(min_length=32, max_length=200)
    encrypted_payload: str = Field(min_length=1, max_length=1_000_000)
    authorizer_appid: str = Field(min_length=3, max_length=100)
    name: str = Field(min_length=1, max_length=160)
    avatar_url: str | None = Field(default=None, max_length=1000)
    capability_flags: list[str] = Field(default_factory=list)
    token_secret_ref: str = Field(min_length=5, max_length=4096)
    token_expires_at: datetime | None = None


@router.get("/wechat/tickets", response_model=None)
async def verify_wechat_ticket_callback(
    request: Request,
    echostr: str = Query(min_length=1, max_length=1_000_000),
    timestamp: str = Query(min_length=1, max_length=32),
    nonce: str = Query(min_length=1, max_length=128),
    signature: str | None = Query(default=None, min_length=1, max_length=128),
    msg_signature: str | None = Query(default=None, min_length=1, max_length=128),
    appid: str | None = Query(default=None, min_length=3, max_length=120),
    session: AsyncSession = Depends(get_session),
    secrets: SecretProvider = Depends(secret_provider),
    limiter: RateLimiter = Depends(rate_limiter),
) -> PlainTextResponse:
    client_host = request.client.host if request.client else "unknown"
    await limiter.check(f"wechat-ticket-verification:{client_host}", 30, 60)
    statement = select(WechatPlatformConfig)
    if appid:
        statement = statement.where(WechatPlatformConfig.component_appid == appid)
    config = await session.scalar(
        statement.order_by(WechatPlatformConfig.updated_at.desc()).limit(1)
    )
    if not config:
        raise ApiError(404, "WECHAT_CONFIG_NOT_FOUND", "微信平台配置不存在。")
    try:
        token = secrets.resolve(config.message_token_ref)
        if msg_signature:
            echo = decrypt_callback_message(
                encrypted=echostr,
                message_token=token,
                encoding_aes_key=secrets.resolve(config.encoding_aes_key_ref),
                msg_signature=msg_signature,
                timestamp=timestamp,
                nonce=nonce,
                expected_appid=config.component_appid,
            ).decode()
        else:
            expected = hashlib.sha1("".join(sorted((token, timestamp, nonce))).encode()).hexdigest()
            if not signature or not hmac.compare_digest(signature, expected):
                raise ValueError
            echo = echostr
    except (ProviderUnavailable, UnicodeDecodeError, ValueError) as exc:
        raise ApiError(401, "CALLBACK_SIGNATURE_INVALID", "微信回调校验失败。") from exc
    return PlainTextResponse(echo, headers={"Cache-Control": "no-store"})


@router.post(
    "/wechat/authorizations",
    response_model=contract.AuthorizationCallbackAckResponse,
    response_model_exclude_none=True,
)
async def normalized_wechat_authorization_callback(
    request: Request,
    signature: str | None = Header(default=None, alias="X-Callback-Signature"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    body = await request.body()
    _verify_normalized_signature(body, signature)
    try:
        payload = NormalizedAuthorizationEvent.model_validate_json(body)
    except ValueError as exc:
        raise ApiError(422, "CALLBACK_PAYLOAD_INVALID", "回调内容无效。") from exc
    duplicate = await session.scalar(
        select(WechatCallback).where(WechatCallback.event_key == payload.event_key)
    )
    if duplicate:
        return {"accepted": True, "duplicate": True}
    state = await session.scalar(
        select(WechatAuthorizationState)
        .where(WechatAuthorizationState.state_hash == hash_token(payload.state))
        .with_for_update()
    )
    if not state or state.consumed_at or is_expired(state.expires_at):
        raise ApiError(400, "WECHAT_AUTHORIZATION_STATE_INVALID", "公众号授权状态无效或已过期。")
    account = await session.scalar(
        select(OfficialAccount).where(
            OfficialAccount.owner_id == state.owner_id,
            OfficialAccount.authorizer_appid == payload.authorizer_appid,
        )
    )
    if not account:
        account = OfficialAccount(
            owner_id=state.owner_id,
            authorizer_appid=payload.authorizer_appid,
            name=payload.name,
        )
        session.add(account)
    account.name = payload.name
    account.avatar_url = payload.avatar_url
    account.status = "connected"
    account.capability_flags = payload.capability_flags
    account.token_secret_ref = payload.token_secret_ref
    account.token_expires_at = payload.token_expires_at
    account.authorized_at = utcnow()
    account.last_synced_at = utcnow()
    account.deleted_at = None
    state.consumed_at = utcnow()
    session.add(
        WechatCallback(
            event_key=payload.event_key,
            event_type="authorization_succeeded",
            encrypted_payload=payload.encrypted_payload,
            processed_at=utcnow(),
        )
    )
    await session.flush()
    await session.commit()
    return {"accepted": True, "duplicate": False, "official_account_id": account.id}


@router.post("/wechat/tickets", response_model=None)
async def wechat_ticket_callback(
    request: Request,
    msg_signature: str | None = Query(default=None),
    timestamp: str | None = Query(default=None),
    nonce: str | None = Query(default=None),
    appid: str | None = Query(default=None),
    signature: str | None = Header(default=None, alias="X-Callback-Signature"),
    session: AsyncSession = Depends(get_session),
    secrets: SecretProvider = Depends(secret_provider),
    limiter: RateLimiter = Depends(rate_limiter),
) -> dict[str, Any] | PlainTextResponse:
    body = await request.body()
    if msg_signature is not None:
        client_host = request.client.host if request.client else "unknown"
        await limiter.check(f"wechat-ticket-callback:{client_host}", 120, 60)
        try:
            outer_appid, encrypted = parse_encrypted_callback(body)
        except ValueError as exc:
            raise ApiError(422, "CALLBACK_PAYLOAD_INVALID", "微信回调内容无效。") from exc
        component_appid = outer_appid or appid or ""
        config = await session.scalar(
            select(WechatPlatformConfig)
            .where(WechatPlatformConfig.component_appid == component_appid)
            .with_for_update()
        )
        if not config:
            raise ApiError(404, "WECHAT_CONFIG_NOT_FOUND", "微信平台配置不存在。")
        try:
            direct_payload = decrypt_callback(
                encrypted=encrypted,
                message_token=secrets.resolve(config.message_token_ref),
                encoding_aes_key=secrets.resolve(config.encoding_aes_key_ref),
                msg_signature=msg_signature,
                timestamp=timestamp or "",
                nonce=nonce or "",
                expected_appid=config.component_appid,
            )
        except (ProviderUnavailable, ValueError) as exc:
            raise ApiError(401, "CALLBACK_SIGNATURE_INVALID", "微信回调验签或解密失败。") from exc
        event_type = (direct_payload.findtext("InfoType") or "unknown").strip()
        event_key = hashlib.sha256(encrypted.encode()).hexdigest()
        existing = await session.scalar(
            select(WechatCallback).where(WechatCallback.event_key == event_key)
        )
        if existing:
            return PlainTextResponse("success")
        session.add(
            WechatCallback(
                event_key=event_key,
                event_type=event_type[:80],
                encrypted_payload=encrypted,
                processed_at=utcnow(),
            )
        )
        if event_type == "component_verify_ticket":
            ticket = (direct_payload.findtext("ComponentVerifyTicket") or "").strip()
            if not ticket:
                raise ApiError(422, "WECHAT_TICKET_MISSING", "微信票据回调缺少 Ticket。")
            config.component_verify_ticket_ref = secrets.protect(ticket)
            config.component_access_token_ref = None
            config.component_access_token_expires_at = None
            config.last_ticket_at = utcnow()
        elif event_type == "unauthorized":
            authorizer_appid = (direct_payload.findtext("AuthorizerAppid") or "").strip()
            if authorizer_appid:
                accounts = list(
                    (
                        await session.scalars(
                            select(OfficialAccount).where(
                                OfficialAccount.authorizer_appid == authorizer_appid,
                                OfficialAccount.deleted_at.is_(None),
                            )
                        )
                    ).all()
                )
                for account in accounts:
                    account.status = "reconnect_required"
                    account.token_secret_ref = None
                    account.token_expires_at = None
                    account.technical_metadata = {
                        key: value
                        for key, value in account.technical_metadata.items()
                        if key != "authorizer_refresh_token_ref"
                    }
        await session.commit()
        return PlainTextResponse("success")

    _verify_normalized_signature(body, signature)
    try:
        normalized_payload = NormalizedTicketEvent.model_validate_json(body)
    except ValueError as exc:
        raise ApiError(422, "CALLBACK_PAYLOAD_INVALID", "回调内容无效。") from exc
    existing = await session.scalar(
        select(WechatCallback).where(WechatCallback.event_key == normalized_payload.event_key)
    )
    if existing:
        return {"accepted": True, "duplicate": True}
    config = await session.scalar(
        select(WechatPlatformConfig).where(
            WechatPlatformConfig.environment == normalized_payload.environment
        )
    )
    if not config:
        raise ApiError(404, "WECHAT_CONFIG_NOT_FOUND", "微信平台环境配置不存在。")
    callback = WechatCallback(
        event_key=normalized_payload.event_key,
        event_type="component_verify_ticket",
        encrypted_payload=normalized_payload.encrypted_payload,
        processed_at=utcnow(),
    )
    session.add(callback)
    config.last_ticket_at = utcnow()
    await session.commit()
    return {"accepted": True, "duplicate": False}


@router.post("/wechat/messages/{authorizer_appid}", response_model=None)
async def wechat_authorizer_message_callback(
    request: Request,
    authorizer_appid: str = Path(min_length=3, max_length=120),
    msg_signature: str = Query(min_length=1, max_length=128),
    timestamp: str = Query(min_length=1, max_length=32),
    nonce: str = Query(min_length=1, max_length=128),
    session: AsyncSession = Depends(get_session),
    secrets: SecretProvider = Depends(secret_provider),
    limiter: RateLimiter = Depends(rate_limiter),
) -> PlainTextResponse:
    client_host = request.client.host if request.client else "unknown"
    await limiter.check(f"wechat-message-callback:{client_host}", 300, 60)
    account = await session.scalar(
        select(OfficialAccount)
        .where(
            OfficialAccount.authorizer_appid == authorizer_appid,
            OfficialAccount.deleted_at.is_(None),
        )
        .order_by(OfficialAccount.updated_at.desc())
        .limit(1)
    )
    platform_config_id = account.technical_metadata.get("platform_config_id") if account else None
    if not account or not isinstance(platform_config_id, str):
        raise ApiError(404, "WECHAT_ACCOUNT_NOT_FOUND", "授权公众号不存在。")
    config = await session.scalar(
        select(WechatPlatformConfig).where(WechatPlatformConfig.id == platform_config_id)
    )
    if not config:
        raise ApiError(404, "WECHAT_CONFIG_NOT_FOUND", "微信平台配置不存在。")
    body = await request.body()
    try:
        _, encrypted = parse_encrypted_callback(body)
        payload = decrypt_callback(
            encrypted=encrypted,
            message_token=secrets.resolve(config.message_token_ref),
            encoding_aes_key=secrets.resolve(config.encoding_aes_key_ref),
            msg_signature=msg_signature,
            timestamp=timestamp,
            nonce=nonce,
            expected_appid=config.component_appid,
        )
    except (ProviderUnavailable, ValueError) as exc:
        raise ApiError(401, "CALLBACK_SIGNATURE_INVALID", "微信消息验签或解密失败。") from exc
    expected_username = account.technical_metadata.get("user_name")
    if (
        isinstance(expected_username, str)
        and expected_username != (payload.findtext("ToUserName") or "").strip()
    ):
        raise ApiError(401, "CALLBACK_ACCOUNT_MISMATCH", "微信消息与授权公众号不匹配。")
    message_type = (payload.findtext("MsgType") or "unknown").strip()
    event = (payload.findtext("Event") or "").strip()
    event_key = hashlib.sha256(f"{authorizer_appid}:{encrypted}".encode()).hexdigest()
    if not await session.scalar(
        select(WechatCallback).where(WechatCallback.event_key == event_key)
    ):
        session.add(
            WechatCallback(
                event_key=event_key,
                event_type=f"{message_type}:{event}"[:80] if event else message_type[:80],
                encrypted_payload=encrypted,
                processed_at=utcnow(),
            )
        )
        await session.commit()
    return PlainTextResponse("success")


@router.get(
    "/wechat/entry",
    response_class=Response,
    response_model=None,
    responses={200: {"content": {"text/html": {"schema": {"type": "string"}}}}},
)
async def direct_wechat_authorization_entry(
    request: Request,
    state: str = Query(min_length=32, max_length=200),
    session: AsyncSession = Depends(get_session),
    secrets: SecretProvider = Depends(secret_provider),
    limiter: RateLimiter = Depends(rate_limiter),
) -> HTMLResponse | RedirectResponse:
    client_host = request.client.host if request.client else "unknown"
    await limiter.check(f"wechat-authorization-entry:{client_host}", 60, 60)
    state_hash = hash_token(state)
    authorization_state = await session.scalar(
        select(WechatAuthorizationState).where(WechatAuthorizationState.state_hash == state_hash)
    )
    if (
        not authorization_state
        or authorization_state.consumed_at
        or is_expired(authorization_state.expires_at)
        or not authorization_state.platform_config_id
    ):
        raise ApiError(
            400, "WECHAT_AUTHORIZATION_STATE_INVALID", "授权已失效，请在电脑端重新生成二维码。"
        )
    config = await session.get(WechatPlatformConfig, authorization_state.platform_config_id)
    if not config or config.status != "published":
        raise ApiError(409, "WECHAT_CONFIG_CHANGED", "微信平台配置已变化，请重新扫码授权。")
    canonical_url = urljoin(config.authorization_callback_url, "/callbacks/v1/wechat/entry")
    if urlsplit(str(request.url)).netloc != urlsplit(canonical_url).netloc:
        return RedirectResponse(
            canonical_url + "?" + urlencode({"state": state}),
            status_code=303,
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )
    await limiter.check(f"wechat-authorization-entry-state:{state_hash}", 10, 300)
    client = WechatOpenPlatformClient()
    try:
        token = await component_access_token(session, config=config, secrets=secrets, client=client)
        authorization = await client.pre_authorization(
            component_appid=config.component_appid,
            component_access_token=token,
            callback_url=config.authorization_callback_url,
            state=state,
            mobile="micromessenger" in request.headers.get("user-agent", "").lower(),
        )
    except ProviderUnavailable as exc:
        raise ApiError(
            503, "WECHAT_PLATFORM_NOT_READY", "微信授权暂时不可用，请稍后重新扫码。"
        ) from exc
    await session.commit()
    # A real same-tab link sends only our origin, never the bearer state in the URL.
    return HTMLResponse(
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="referrer" content="origin"><title>公众号授权</title>'
        "<style>:root{color-scheme:light dark;--space:1.5rem;--measure:32rem}"
        "*{box-sizing:border-box}body{margin:0;padding:var(--space);"
        "font:1rem/1.6 system-ui,sans-serif;overflow-wrap:anywhere}"
        "main{min-width:0;max-width:var(--measure);margin:auto}"
        "h1{font-size:1.5rem}a{display:inline-block;padding:1rem 0;min-height:44px}"
        "</style></head><body><main><h1>公众号授权</h1>"
        "<p>请确认这是你本人在电脑端发起的操作。继续后，请使用公众号管理员微信完成授权。</p>"
        f'<a referrerpolicy="origin" href="{escape(authorization.url, quote=True)}">'
        "继续微信授权</a>"
        "<p>完成后返回电脑端查看结果。二维码过期时，请在电脑端重新生成。</p>"
        "</main></body></html>",
        headers={
            "Referrer-Policy": "origin",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": (
                "default-src 'none'; style-src 'unsafe-inline'; "
                "base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
            ),
        },
    )


@router.get("/wechat/authorize", response_model=None)
async def direct_wechat_authorization_callback(
    request: Request,
    state: str = Query(min_length=32, max_length=200),
    component_appid: str | None = Query(default=None, min_length=3, max_length=120),
    auth_code: str | None = Query(default=None, min_length=3, max_length=1000),
    authorization_code: str | None = Query(default=None, min_length=3, max_length=1000),
    session: AsyncSession = Depends(get_session),
    secrets: SecretProvider = Depends(secret_provider),
    limiter: RateLimiter = Depends(rate_limiter),
) -> RedirectResponse | HTMLResponse:
    client_host = request.client.host if request.client else "unknown"
    await limiter.check(f"wechat-authorization-callback:{client_host}", 120, 60)
    code = auth_code or authorization_code
    if not code:
        raise ApiError(422, "WECHAT_AUTHORIZATION_CODE_MISSING", "微信授权回调缺少授权码。")
    authorization_state = await session.scalar(
        select(WechatAuthorizationState)
        .where(WechatAuthorizationState.state_hash == hash_token(state))
        .with_for_update()
    )
    if (
        not authorization_state
        or authorization_state.consumed_at
        or is_expired(authorization_state.expires_at)
    ):
        raise ApiError(400, "WECHAT_AUTHORIZATION_STATE_INVALID", "公众号授权状态无效或已过期。")
    if not authorization_state.platform_config_id:
        raise ApiError(400, "WECHAT_AUTHORIZATION_STATE_INVALID", "公众号授权状态缺少平台配置。")
    config = await session.scalar(
        select(WechatPlatformConfig)
        .where(WechatPlatformConfig.id == authorization_state.platform_config_id)
        .with_for_update()
    )
    if (
        not config
        or config.status != "published"
        or (component_appid is not None and config.component_appid != component_appid)
    ):
        raise ApiError(409, "WECHAT_CONFIG_CHANGED", "微信平台配置已变化，请重新扫码授权。")
    client = WechatOpenPlatformClient()
    try:
        platform_token = await component_access_token(
            session, config=config, secrets=secrets, client=client
        )
        details = await client.exchange_authorization(
            component_appid=config.component_appid,
            component_access_token=platform_token,
            authorization_code=code,
        )
    except ProviderUnavailable as exc:
        raise ApiError(
            502,
            "WECHAT_AUTHORIZATION_EXCHANGE_FAILED",
            "微信授权结果处理失败，请重新扫码。",
            retryable=True,
        ) from exc
    account = await session.scalar(
        select(OfficialAccount).where(
            OfficialAccount.owner_id == authorization_state.owner_id,
            OfficialAccount.authorizer_appid == details.authorizer_appid,
        )
    )
    if not account:
        account = OfficialAccount(
            owner_id=authorization_state.owner_id,
            authorizer_appid=details.authorizer_appid,
            name=details.name,
        )
        session.add(account)
    account.name = details.name
    account.avatar_url = details.avatar_url
    account.status = "connected"
    account.capability_flags = capability_flags(details.scope_ids)
    account.token_secret_ref = secrets.protect(details.access_token)
    account.token_expires_at = utcnow() + timedelta(seconds=max(60, details.expires_in))
    account.authorized_at = utcnow()
    account.last_synced_at = utcnow()
    account.deleted_at = None
    account.technical_metadata = {
        **details.metadata,
        "authorizer_refresh_token_ref": secrets.protect(details.refresh_token),
        "platform_config_id": config.id,
    }
    authorization_state.consumed_at = utcnow()
    session.add(
        WechatCallback(
            event_key=hashlib.sha256(f"authorization:{code}".encode()).hexdigest(),
            event_type="authorization_succeeded",
            encrypted_payload="authorization-code-consumed",
            processed_at=utcnow(),
        )
    )
    await session.flush()
    await session.commit()
    redirect_uri = add_query_parameters(
        authorization_state.redirect_uri,
        wechat_authorization="success",
        official_account_id=account.id,
    )
    redirect_target = urlsplit(redirect_uri)
    if redirect_target.scheme in {"http", "https"} and redirect_target.hostname in {
        "localhost",
        "127.0.0.1",
    }:
        return HTMLResponse(
            "<!doctype html><html lang='zh-CN'><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>公众号授权完成</title><body style='font-family:system-ui;padding:40px;"
            "text-align:center'><h1>公众号授权已完成</h1>"
            "<p>绑定成功，授权长期有效，接口令牌将由系统自动续期。"
            "可以关闭此页面。</p></body></html>",
            headers={"Cache-Control": "no-store"},
        )
    return RedirectResponse(
        redirect_uri,
        status_code=303,
    )

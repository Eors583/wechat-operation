from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import struct
import time
from dataclasses import dataclass
from datetime import UTC, timedelta
from typing import Any, cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from xml.etree import ElementTree

import httpx
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import OfficialAccount, WechatPlatformConfig, utcnow
from app.providers import (
    ProviderAuthenticationError,
    ProviderRateLimited,
    ProviderReauthorizationRequired,
    ProviderResultUnknown,
    ProviderTransientError,
    ProviderUnavailable,
    SecretProvider,
    WechatCover,
    WechatResult,
)

WECHAT_API_BASE = "https://api.weixin.qq.com"
WECHAT_AUTHORIZATION_PAGE = "https://mp.weixin.qq.com/cgi-bin/componentloginpage"
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PreAuthorization:
    url: str
    expires_in: int


@dataclass(frozen=True, slots=True)
class AuthorizationDetails:
    authorizer_appid: str
    access_token: str
    refresh_token: str
    expires_in: int
    scope_ids: list[int]
    name: str
    avatar_url: str | None
    metadata: dict[str, Any]


def _xml_text(root: ElementTree.Element, name: str) -> str:
    return (root.findtext(name) or "").strip()


def parse_encrypted_callback(body: bytes) -> tuple[str, str]:
    if len(body) > 1_000_000:
        raise ValueError("callback body is too large")
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        raise ValueError("callback XML is invalid") from exc
    appid = _xml_text(root, "AppId")
    encrypted = _xml_text(root, "Encrypt")
    if not encrypted:
        raise ValueError("callback XML does not contain Encrypt")
    return appid, encrypted


def _remove_wechat_padding(value: bytes) -> bytes:
    if not value:
        raise ValueError("callback plaintext is empty")
    padding_length = value[-1]
    if (
        padding_length < 1
        or padding_length > 32
        or value[-padding_length:] != bytes((padding_length,)) * padding_length
    ):
        raise ValueError("callback padding is invalid")
    return value[:-padding_length]


def decrypt_callback_message(
    *,
    encrypted: str,
    message_token: str,
    encoding_aes_key: str,
    msg_signature: str,
    timestamp: str,
    nonce: str,
    expected_appid: str,
) -> bytes:
    expected_signature = hashlib.sha1(
        "".join(sorted((message_token, timestamp, nonce, encrypted))).encode()
    ).hexdigest()
    if not msg_signature or not hmac.compare_digest(expected_signature, msg_signature):
        raise ValueError("callback signature is invalid")
    try:
        aes_key = base64.b64decode(encoding_aes_key + "=", validate=True)
        ciphertext = base64.b64decode(encrypted, validate=True)
        if len(aes_key) != 32 or not ciphertext or len(ciphertext) % 16:
            raise ValueError
        decryptor = Cipher(algorithms.AES(aes_key), modes.CBC(aes_key[:16])).decryptor()
        padded = decryptor.update(ciphertext) + decryptor.finalize()
        plaintext = _remove_wechat_padding(padded)
        if len(plaintext) < 21:
            raise ValueError
        message_length = struct.unpack(">I", plaintext[16:20])[0]
        message_end = 20 + message_length
        if message_end > len(plaintext):
            raise ValueError
        xml = plaintext[20:message_end]
        receiver = plaintext[message_end:].decode()
        if receiver != expected_appid:
            raise ValueError("callback receiver does not match component AppID")
        return xml
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("callback encryption payload is invalid") from exc


def decrypt_callback(
    *,
    encrypted: str,
    message_token: str,
    encoding_aes_key: str,
    msg_signature: str,
    timestamp: str,
    nonce: str,
    expected_appid: str,
) -> ElementTree.Element:
    try:
        return ElementTree.fromstring(
            decrypt_callback_message(
                encrypted=encrypted,
                message_token=message_token,
                encoding_aes_key=encoding_aes_key,
                msg_signature=msg_signature,
                timestamp=timestamp,
                nonce=nonce,
                expected_appid=expected_appid,
            )
        )
    except ElementTree.ParseError as exc:
        raise ValueError("callback XML payload is invalid") from exc


def add_query_parameters(url: str, **parameters: str) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(parameters)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


class WechatOpenPlatformClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def _post(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        access_token: str | None = None,
        token_parameter: str = "component_access_token",
    ) -> dict[str, Any]:
        params = {token_parameter: access_token} if access_token else None
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(base_url=WECHAT_API_BASE, timeout=10.0)
        try:
            response = await client.post(path, params=params, json=payload)
            response.raise_for_status()
            result = response.json()
        except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
            raise ProviderTransientError("WeChat Open Platform request failed") from exc
        except ValueError as exc:
            raise ProviderUnavailable("WeChat Open Platform returned invalid JSON") from exc
        finally:
            if owns_client:
                await client.aclose()
        if not isinstance(result, dict):
            raise ProviderUnavailable("WeChat Open Platform returned an invalid response")
        code = result.get("errcode", 0)
        if isinstance(code, int) and code != 0:
            if code in {-1, 45009}:
                error = f"WeChat Open Platform rejected the request ({code})"
                if code == 45009:
                    raise ProviderRateLimited(error)
                raise ProviderTransientError(error)
            if code in {40001, 40013, 40014, 42001, 61004}:
                raise ProviderAuthenticationError(
                    f"WeChat Open Platform rejected the configured credentials ({code})",
                    code=code,
                )
            raise ProviderUnavailable(f"WeChat Open Platform returned error {code}")
        return cast(dict[str, Any], result)

    async def upload_permanent_image(self, *, access_token: str, cover: WechatCover) -> str:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(base_url=WECHAT_API_BASE, timeout=20.0)
        try:
            response = await client.post(
                "/cgi-bin/material/add_material",
                params={"access_token": access_token, "type": "image"},
                files={"media": (cover.filename, cover.content, cover.mime_type)},
            )
            response.raise_for_status()
            result = response.json()
        except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
            raise ProviderTransientError("WeChat cover upload failed") from exc
        except ValueError as exc:
            raise ProviderUnavailable("WeChat cover upload returned invalid JSON") from exc
        finally:
            if owns_client:
                await client.aclose()
        if not isinstance(result, dict):
            raise ProviderUnavailable("WeChat cover upload returned an invalid response")
        code = result.get("errcode", 0)
        if isinstance(code, int) and code != 0:
            if code in {-1, 45009}:
                if code == 45009:
                    raise ProviderRateLimited("WeChat cover upload was rate limited")
                raise ProviderTransientError("WeChat cover upload failed temporarily")
            if code in {40001, 40013, 40014, 42001, 61004}:
                raise ProviderAuthenticationError(
                    f"WeChat cover upload rejected the access token ({code})", code=code
                )
            raise ProviderUnavailable(f"WeChat cover upload returned error {code}")
        media_id = result.get("media_id")
        if not isinstance(media_id, str) or not media_id:
            raise ProviderUnavailable("WeChat cover upload did not return a media ID")
        return media_id

    async def add_draft(
        self,
        *,
        access_token: str,
        title: str,
        digest: str,
        html: str,
        thumb_media_id: str,
    ) -> str:
        result = await self._post(
            "/cgi-bin/draft/add",
            {
                "articles": [
                    {
                        "title": title[:64],
                        "author": "",
                        "digest": digest[:120],
                        "content": html,
                        "content_source_url": "",
                        "thumb_media_id": thumb_media_id,
                        "need_open_comment": 0,
                        "only_fans_can_comment": 0,
                    }
                ]
            },
            access_token=access_token,
            token_parameter="access_token",
        )
        media_id = result.get("media_id")
        if not isinstance(media_id, str) or not media_id:
            raise ProviderUnavailable("WeChat draft creation did not return a media ID")
        return media_id

    async def submit_publish(self, *, access_token: str, media_id: str) -> str:
        result = await self._post(
            "/cgi-bin/freepublish/submit",
            {"media_id": media_id},
            access_token=access_token,
            token_parameter="access_token",
        )
        publish_id = result.get("publish_id")
        if not isinstance(publish_id, str) or not publish_id:
            raise ProviderUnavailable("WeChat publish submission did not return a publish ID")
        return publish_id

    async def get_draft(self, *, access_token: str, media_id: str) -> bool:
        result = await self._post(
            "/cgi-bin/draft/get",
            {"media_id": media_id},
            access_token=access_token,
            token_parameter="access_token",
        )
        return isinstance(result.get("news_item"), list)

    async def get_publish_status(self, *, access_token: str, publish_id: str) -> int:
        result = await self._post(
            "/cgi-bin/freepublish/get",
            {"publish_id": publish_id},
            access_token=access_token,
            token_parameter="access_token",
        )
        status = result.get("publish_status")
        if not isinstance(status, int):
            raise ProviderUnavailable("WeChat publish query returned an invalid status")
        return status

    async def component_access_token(
        self, *, component_appid: str, component_appsecret: str, verify_ticket: str
    ) -> tuple[str, int]:
        result = await self._post(
            "/cgi-bin/component/api_component_token",
            {
                "component_appid": component_appid,
                "component_appsecret": component_appsecret,
                "component_verify_ticket": verify_ticket,
            },
        )
        token = result.get("component_access_token")
        expires_in = result.get("expires_in")
        if not isinstance(token, str) or not token or not isinstance(expires_in, int):
            raise ProviderUnavailable("WeChat component token response is incomplete")
        return token, expires_in

    async def start_ticket_push(self, *, component_appid: str, component_appsecret: str) -> None:
        await self._post(
            "/cgi-bin/component/api_start_push_ticket",
            {
                "component_appid": component_appid,
                "component_secret": component_appsecret,
            },
        )

    async def pre_authorization(
        self,
        *,
        component_appid: str,
        component_access_token: str,
        callback_url: str,
        state: str,
        mobile: bool = False,
    ) -> PreAuthorization:
        result = await self._post(
            "/cgi-bin/component/api_create_preauthcode",
            {"component_appid": component_appid},
            access_token=component_access_token,
        )
        code = result.get("pre_auth_code")
        expires_in = result.get("expires_in")
        if not isinstance(code, str) or not code or not isinstance(expires_in, int):
            raise ProviderUnavailable("WeChat pre-authorization response is incomplete")
        redirect_uri = add_query_parameters(
            callback_url, state=state, component_appid=component_appid
        )
        parameters = {
            "component_appid": component_appid,
            "pre_auth_code": code,
            "redirect_uri": redirect_uri,
            "auth_type": "1",
        }
        page = WECHAT_AUTHORIZATION_PAGE
        if mobile:
            page = "https://mp.weixin.qq.com/safe/bindcomponent"
            parameters.update(action="bindcomponent", no_scan="1")
        query = urlencode(parameters)
        return PreAuthorization(
            url=f"{page}?{query}" + ("#wechat_redirect" if mobile else ""),
            expires_in=expires_in,
        )

    async def exchange_authorization(
        self,
        *,
        component_appid: str,
        component_access_token: str,
        authorization_code: str,
    ) -> AuthorizationDetails:
        result = await self._post(
            "/cgi-bin/component/api_query_auth",
            {
                "component_appid": component_appid,
                "authorization_code": authorization_code,
            },
            access_token=component_access_token,
        )
        authorization = result.get("authorization_info")
        if not isinstance(authorization, dict):
            raise ProviderUnavailable("WeChat authorization response is incomplete")
        authorizer_appid = authorization.get("authorizer_appid")
        access_token = authorization.get("authorizer_access_token")
        refresh_token = authorization.get("authorizer_refresh_token")
        expires_in = authorization.get("expires_in")
        if (
            not isinstance(authorizer_appid, str)
            or not authorizer_appid
            or not isinstance(access_token, str)
            or not access_token
            or not isinstance(refresh_token, str)
            or not refresh_token
            or not isinstance(expires_in, int)
        ):
            raise ProviderUnavailable("WeChat authorization credentials are incomplete")
        scope_ids = sorted(
            {
                scope_id
                for item in authorization.get("func_info", [])
                if isinstance(item, dict)
                and isinstance(item.get("funcscope_category"), dict)
                and isinstance(
                    scope_id := item["funcscope_category"].get("id"),
                    int,
                )
            }
        )
        account_result = await self._post(
            "/cgi-bin/component/api_get_authorizer_info",
            {
                "component_appid": component_appid,
                "authorizer_appid": authorizer_appid,
            },
            access_token=component_access_token,
        )
        info = account_result.get("authorizer_info")
        info = info if isinstance(info, dict) else {}
        name = info.get("nick_name")
        avatar_url = info.get("head_img")
        metadata = {
            key: info[key]
            for key in (
                "user_name",
                "principal_name",
                "alias",
                "service_type_info",
                "verify_type_info",
            )
            if key in info
        }
        metadata["funcscope_ids"] = scope_ids
        return AuthorizationDetails(
            authorizer_appid=authorizer_appid,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
            scope_ids=scope_ids,
            name=name if isinstance(name, str) and name else authorizer_appid,
            avatar_url=avatar_url if isinstance(avatar_url, str) else None,
            metadata=metadata,
        )

    async def refresh_authorization(
        self,
        *,
        component_appid: str,
        component_access_token: str,
        authorizer_appid: str,
        authorizer_refresh_token: str,
    ) -> tuple[str, str, int]:
        result = await self._post(
            "/cgi-bin/component/api_authorizer_token",
            {
                "component_appid": component_appid,
                "authorizer_appid": authorizer_appid,
                "authorizer_refresh_token": authorizer_refresh_token,
            },
            access_token=component_access_token,
        )
        access_token = result.get("authorizer_access_token")
        refresh_token = result.get("authorizer_refresh_token") or authorizer_refresh_token
        expires_in = result.get("expires_in")
        if (
            not isinstance(access_token, str)
            or not access_token
            or not isinstance(refresh_token, str)
            or not refresh_token
            or not isinstance(expires_in, int)
        ):
            raise ProviderUnavailable("WeChat authorizer token response is incomplete")
        return access_token, refresh_token, expires_in


class DirectWechatProvider:
    def __init__(
        self, secrets: SecretProvider, client: WechatOpenPlatformClient | None = None
    ) -> None:
        self._secrets = secrets
        self._client = client or WechatOpenPlatformClient()

    async def authorization_url(self, *, state: str, redirect_uri: str) -> str:
        raise ProviderUnavailable(
            "Direct WeChat authorization requires the persisted platform config"
        )

    async def create_or_update_draft(
        self,
        *,
        account_ref: str,
        html: str,
        title: str,
        digest: str,
        cover: WechatCover | None,
    ) -> WechatResult:
        if not cover:
            return WechatResult(
                status="failed",
                details={"message": "请先设置文章封面，再存入公众号草稿箱。"},
            )
        access_token = self._secrets.resolve(account_ref)
        try:
            thumb_media_id = await self._client.upload_permanent_image(
                access_token=access_token, cover=cover
            )
            media_id = await self._client.add_draft(
                access_token=access_token,
                title=title,
                digest=digest,
                html=html,
                thumb_media_id=thumb_media_id,
            )
        except ProviderAuthenticationError:
            raise
        except ProviderTransientError as exc:
            raise ProviderResultUnknown("WeChat draft response was not received") from exc
        except ProviderUnavailable:
            return WechatResult(
                status="failed",
                details={"message": "微信拒绝创建草稿，请检查封面、标题和公众号授权权限。"},
            )
        return WechatResult(
            status="succeeded",
            media_id=media_id,
            external_action_performed=True,
        )

    async def publish(self, *, account_ref: str, media_id: str) -> WechatResult:
        try:
            publish_id = await self._client.submit_publish(
                access_token=self._secrets.resolve(account_ref), media_id=media_id
            )
        except ProviderAuthenticationError:
            raise
        except ProviderTransientError as exc:
            raise ProviderResultUnknown("WeChat publish response was not received") from exc
        except ProviderUnavailable:
            return WechatResult(
                status="failed",
                media_id=media_id,
                details={"message": "微信拒绝发布文章，请检查公众号授权和发布权限。"},
            )
        return WechatResult(
            status="unknown",
            media_id=media_id,
            publish_id=publish_id,
            external_action_performed=True,
        )

    async def reconcile(
        self, *, operation_type: str, external_id: str, account_ref: str
    ) -> WechatResult:
        access_token = self._secrets.resolve(account_ref)
        try:
            if operation_type == "draft":
                exists = await self._client.get_draft(
                    access_token=access_token, media_id=external_id
                )
                return WechatResult(
                    status="succeeded" if exists else "failed", media_id=external_id
                )
            status = await self._client.get_publish_status(
                access_token=access_token, publish_id=external_id
            )
        except ProviderUnavailable:
            return WechatResult(status="unknown")
        if status == 0:
            return WechatResult(status="succeeded", publish_id=external_id)
        if status == 1:
            return WechatResult(status="unknown", publish_id=external_id)
        return WechatResult(status="failed", publish_id=external_id)

    async def refresh_account(self, *, account_ref: str) -> WechatResult:
        return WechatResult(
            status="failed", details={"message": "公众号令牌由系统自动续期，无需重新扫码。"}
        )


async def component_access_token(
    session: AsyncSession,
    *,
    config: WechatPlatformConfig,
    secrets: SecretProvider,
    client: WechatOpenPlatformClient,
) -> str:
    expires_at = config.component_access_token_expires_at
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if (
        config.component_access_token_ref
        and expires_at
        and expires_at > utcnow() + timedelta(seconds=60)
    ):
        return secrets.resolve(config.component_access_token_ref)
    if not config.component_verify_ticket_ref:
        await client.start_ticket_push(
            component_appid=config.component_appid,
            component_appsecret=secrets.resolve(config.component_secret_ref),
        )
        raise ProviderUnavailable("Requested component_verify_ticket push")
    token, expires_in = await client.component_access_token(
        component_appid=config.component_appid,
        component_appsecret=secrets.resolve(config.component_secret_ref),
        verify_ticket=secrets.resolve(config.component_verify_ticket_ref),
    )
    config.component_access_token_ref = secrets.protect(token)
    config.component_access_token_expires_at = utcnow() + timedelta(
        seconds=max(60, expires_in - 120)
    )
    config.last_token_refresh_at = utcnow()
    await session.flush()
    return token


async def ensure_authorizer_access_token(
    session: AsyncSession,
    *,
    account_id: str,
    environment: str,
    secrets: SecretProvider,
    client: WechatOpenPlatformClient,
    force: bool = False,
) -> OfficialAccount:
    account = await session.scalar(
        select(OfficialAccount).where(OfficialAccount.id == account_id).with_for_update()
    )
    if not account:
        raise ProviderUnavailable("WeChat account is unavailable")
    if account.status == "reconnect_required":
        raise ProviderReauthorizationRequired("WeChat authorization was revoked")
    expires_at = account.token_expires_at
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if not force and account.token_secret_ref and (
        not expires_at or expires_at > utcnow() + timedelta(seconds=300)
    ):
        return account
    metadata = account.technical_metadata if isinstance(account.technical_metadata, dict) else {}
    refresh_ref = metadata.get("authorizer_refresh_token_ref")
    config_id = metadata.get("platform_config_id")
    config = None
    if isinstance(config_id, str) and config_id:
        config = await session.scalar(
            select(WechatPlatformConfig)
            .where(
                WechatPlatformConfig.id == config_id,
                WechatPlatformConfig.status == "published",
            )
            .with_for_update()
        )
    if not config:
        config = await published_wechat_config(session, environment=environment)
    if not config or not isinstance(refresh_ref, str) or not refresh_ref:
        raise ProviderUnavailable("WeChat refresh credential is unavailable")
    started_at = time.monotonic()
    last_error: ProviderUnavailable | None = None
    for attempt in range(3):
        try:
            platform_token = await component_access_token(
                session, config=config, secrets=secrets, client=client
            )
            access_token, refresh_token, expires_in = await client.refresh_authorization(
                component_appid=config.component_appid,
                component_access_token=platform_token,
                authorizer_appid=account.authorizer_appid,
                authorizer_refresh_token=secrets.resolve(refresh_ref),
            )
            break
        except ProviderAuthenticationError as exc:
            last_error = exc
            if exc.code in {40001, 40014, 42001} and attempt == 0:
                config.component_access_token_ref = None
                config.component_access_token_expires_at = None
                await session.flush()
                continue
            logger.warning(
                "wechat_authorizer_token_refresh_failed appid=%s duration_ms=%d errcode=%s",
                account.authorizer_appid,
                round((time.monotonic() - started_at) * 1000),
                exc.code,
            )
            account.technical_metadata = {
                **metadata,
                "last_refresh_error": f"errcode:{exc.code or 'credential_rejected'}",
            }
            await session.flush()
            raise ProviderUnavailable("WeChat token refresh was rejected") from exc
        except ProviderUnavailable as exc:
            last_error = exc
            if attempt == 2:
                logger.warning(
                    "wechat_authorizer_token_refresh_failed appid=%s duration_ms=%d error=%s",
                    account.authorizer_appid,
                    round((time.monotonic() - started_at) * 1000),
                    type(exc).__name__,
                )
                account.technical_metadata = {
                    **metadata,
                    "last_refresh_error": type(exc).__name__,
                }
                await session.flush()
                raise
            await asyncio.sleep(2**attempt)
    else:  # pragma: no cover - the loop either succeeds or raises
        raise ProviderUnavailable("WeChat token refresh failed") from last_error
    account.token_secret_ref = secrets.protect(access_token)
    account.token_expires_at = utcnow() + timedelta(seconds=max(60, expires_in))
    account.last_synced_at = utcnow()
    account.technical_metadata = {
        **{key: value for key, value in metadata.items() if key != "last_refresh_error"},
        "authorizer_refresh_token_ref": secrets.protect(refresh_token),
        "platform_config_id": config.id,
    }
    await session.flush()
    logger.info(
        "wechat_authorizer_token_refreshed appid=%s duration_ms=%d",
        account.authorizer_appid,
        round((time.monotonic() - started_at) * 1000),
    )
    return account


async def published_wechat_config(
    session: AsyncSession, *, environment: str
) -> WechatPlatformConfig | None:
    config = await session.scalar(
        select(WechatPlatformConfig)
        .where(
            WechatPlatformConfig.environment == environment,
            WechatPlatformConfig.status == "published",
        )
        .with_for_update()
    )
    if config:
        return config
    return await session.scalar(
        select(WechatPlatformConfig)
        .where(WechatPlatformConfig.status == "published")
        .order_by(WechatPlatformConfig.updated_at.desc())
        .limit(1)
        .with_for_update()
    )


def capability_flags(scope_ids: list[int]) -> list[str]:
    scopes = set(scope_ids)
    capabilities: list[str] = []
    if 11 in scopes:
        capabilities.extend(("assets", "draft"))
    if 7 in scopes:
        capabilities.append("publish")
    return capabilities


async def seed_wechat_config_from_environment(session: AsyncSession, *, settings: Settings) -> None:
    values = (
        settings.wechat_component_app_id,
        settings.wechat_component_app_secret,
        settings.wechat_message_token,
        settings.wechat_encoding_aes_key,
        settings.wechat_authorization_callback_url,
        settings.wechat_ticket_callback_url,
    )
    if settings.wechat_provider_mode != "direct" or not all(values):
        return
    existing = await session.scalar(
        select(WechatPlatformConfig).where(WechatPlatformConfig.environment == settings.environment)
    )
    if existing:
        component_changed = existing.component_appid != settings.wechat_component_app_id
        existing.component_appid = settings.wechat_component_app_id
        existing.component_secret_ref = "env:WECHAT_COMPONENT_APP_SECRET"
        existing.message_token_ref = "env:WECHAT_MESSAGE_TOKEN"
        existing.encoding_aes_key_ref = "env:WECHAT_ENCODING_AES_KEY"
        existing.authorization_callback_url = settings.wechat_authorization_callback_url
        existing.ticket_callback_url = settings.wechat_ticket_callback_url
        existing.permission_set = ["draft", "publish"]
        existing.status = "published"
        if component_changed:
            existing.component_verify_ticket_ref = None
            existing.component_access_token_ref = None
            existing.component_access_token_expires_at = None
            existing.last_ticket_at = None
            existing.last_token_refresh_at = None
        await session.commit()
        return
    session.add(
        WechatPlatformConfig(
            environment=settings.environment,
            component_appid=settings.wechat_component_app_id,
            component_secret_ref="env:WECHAT_COMPONENT_APP_SECRET",
            message_token_ref="env:WECHAT_MESSAGE_TOKEN",
            encoding_aes_key_ref="env:WECHAT_ENCODING_AES_KEY",
            authorization_callback_url=settings.wechat_authorization_callback_url,
            ticket_callback_url=settings.wechat_ticket_callback_url,
            permission_set=["draft", "publish"],
            status="published",
        )
    )
    await session.commit()

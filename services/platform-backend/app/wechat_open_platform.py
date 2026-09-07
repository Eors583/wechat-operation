from __future__ import annotations

import base64
import hashlib
import hmac
import struct
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
from app.models import WechatPlatformConfig, utcnow
from app.providers import (
    ProviderAuthenticationError,
    ProviderRateLimited,
    ProviderTransientError,
    ProviderUnavailable,
    SecretProvider,
)

WECHAT_API_BASE = "https://api.weixin.qq.com"
WECHAT_AUTHORIZATION_PAGE = "https://mp.weixin.qq.com/cgi-bin/componentloginpage"


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
        self, path: str, payload: dict[str, Any], *, access_token: str | None = None
    ) -> dict[str, Any]:
        params = {"component_access_token": access_token} if access_token else None
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
                    f"WeChat Open Platform rejected the configured credentials ({code})"
                )
            raise ProviderUnavailable(f"WeChat Open Platform returned error {code}")
        return cast(dict[str, Any], result)

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

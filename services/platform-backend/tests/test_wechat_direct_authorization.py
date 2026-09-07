from __future__ import annotations

import base64
import hashlib
import json
import struct
from dataclasses import replace
from datetime import timedelta
from html import unescape
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, MockTransport, Request, Response
from sqlalchemy import select

from app.config import Settings
from app.main import create_app
from app.models import OfficialAccount, WechatAuthorizationState, WechatPlatformConfig, utcnow
from app.security import hash_token
from app.wechat_open_platform import (
    AuthorizationDetails,
    PreAuthorization,
    WechatOpenPlatformClient,
    decrypt_callback,
    decrypt_callback_message,
    parse_encrypted_callback,
)

from .conftest import bearer, register_and_login


def _encrypted_callback(
    *, xml: str, appid: str, token: str, aes_key_text: str, timestamp: str, nonce: str
) -> tuple[bytes, str]:
    aes_key = base64.b64decode(aes_key_text + "=")
    plaintext = (
        b"0123456789abcdef" + struct.pack(">I", len(xml.encode())) + xml.encode() + appid.encode()
    )
    padding_length = 32 - len(plaintext) % 32
    padded = plaintext + bytes((padding_length,)) * padding_length
    encryptor = Cipher(algorithms.AES(aes_key), modes.CBC(aes_key[:16])).encryptor()
    encrypted = base64.b64encode(encryptor.update(padded) + encryptor.finalize()).decode()
    signature = hashlib.sha1(
        "".join(sorted((token, timestamp, nonce, encrypted))).encode()
    ).hexdigest()
    body = f"<xml><AppId>{appid}</AppId><Encrypt>{encrypted}</Encrypt></xml>".encode()
    return body, signature


def test_official_callback_signature_and_encryption_are_verified() -> None:
    appid = "wx-component-appid"
    token = "callback-token"
    aes_key = base64.b64encode(bytes(range(32))).decode().rstrip("=")
    xml = (
        "<xml><InfoType>component_verify_ticket</InfoType>"
        "<ComponentVerifyTicket>ticket-value-0123456789abcdef</ComponentVerifyTicket></xml>"
    )
    body, signature = _encrypted_callback(
        xml=xml,
        appid=appid,
        token=token,
        aes_key_text=aes_key,
        timestamp="1700000000",
        nonce="nonce-value",
    )
    outer_appid, encrypted = parse_encrypted_callback(body)
    decrypted = decrypt_callback(
        encrypted=encrypted,
        message_token=token,
        encoding_aes_key=aes_key,
        msg_signature=signature,
        timestamp="1700000000",
        nonce="nonce-value",
        expected_appid=appid,
    )
    assert outer_appid == appid
    assert decrypted.findtext("ComponentVerifyTicket") == "ticket-value-0123456789abcdef"
    with pytest.raises(ValueError):
        decrypt_callback(
            encrypted=encrypted,
            message_token=token,
            encoding_aes_key=aes_key,
            msg_signature="invalid",
            timestamp="1700000000",
            nonce="nonce-value",
            expected_appid=appid,
        )


def test_public_tunnel_origin_derives_local_callback_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WECHAT_PROVIDER_MODE", "direct")
    monkeypatch.setenv("WECHAT_COMPONENT_APP_ID", "wx-component")
    monkeypatch.setenv("WECHAT_COMPONENT_APP_SECRET", "component-secret")
    monkeypatch.setenv("WECHAT_MESSAGE_TOKEN", "message-token")
    monkeypatch.setenv("WECHAT_ENCODING_AES_KEY", base64.b64encode(bytes(range(32))).decode()[:43])
    monkeypatch.setenv("WECHAT_PUBLIC_BASE_URL", "https://fixed-tunnel.example/")
    monkeypatch.setenv("WECHAT_AUTHORIZATION_CALLBACK_URL", "")
    monkeypatch.setenv("WECHAT_TICKET_CALLBACK_URL", "")

    settings = Settings.from_env()

    assert settings.wechat_authorization_callback_url == (
        "https://fixed-tunnel.example/callbacks/v1/wechat/authorize"
    )
    assert settings.wechat_ticket_callback_url == (
        "https://fixed-tunnel.example/callbacks/v1/wechat/tickets"
    )
    assert "http://127.0.0.1:9000" in settings.allowed_origins
    assert "https://fixed-tunnel.example" in settings.allowed_origins


async def test_domain_verification_file_is_served_from_public_root(tmp_path: Path) -> None:
    application = create_app(
        Settings(
            environment="test",
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'domain-verification.db'}",
            token_secret="test-token-secret-with-at-least-thirty-two-characters",
            auto_create_schema=True,
            wechat_domain_verification_filename="MP_verify_localtest.txt",
            wechat_domain_verification_content="local-domain-proof",
        )
    )
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://testserver"
        ) as local_client:
            response = await local_client.get("/MP_verify_localtest.txt")
            missing = await local_client.get("/MP_verify_wrong.txt")

    assert response.status_code == 200
    assert response.text == "local-domain-proof"
    assert response.headers["referrer-policy"] == "same-origin"
    assert missing.status_code == 404


async def test_open_platform_client_uses_official_authorization_endpoints() -> None:
    requested_paths: list[str] = []

    def handler(request: Request) -> Response:
        requested_paths.append(request.url.path)
        if request.url.path.endswith("api_start_push_ticket"):
            assert json.loads(request.content)["component_secret"] == "secret"
            return Response(200, json={"errcode": 0, "errmsg": "ok"})
        if request.url.path.endswith("api_component_token"):
            return Response(
                200, json={"component_access_token": "component-token", "expires_in": 7200}
            )
        if request.url.path.endswith("api_create_preauthcode"):
            return Response(200, json={"pre_auth_code": "pre-auth-code", "expires_in": 600})
        if request.url.path.endswith("api_query_auth"):
            return Response(
                200,
                json={
                    "authorization_info": {
                        "authorizer_appid": "wx-authorizer",
                        "authorizer_access_token": "access-token",
                        "authorizer_refresh_token": "refresh-token",
                        "expires_in": 7200,
                        "func_info": [
                            {"funcscope_category": {"id": 7}},
                            {"funcscope_category": {"id": 11}},
                        ],
                    }
                },
            )
        return Response(
            200,
            json={
                "authorizer_info": {
                    "nick_name": "公众号名称",
                    "head_img": "https://example.com/avatar.png",
                }
            },
        )

    async with AsyncClient(
        transport=MockTransport(handler), base_url="https://api.weixin.qq.com"
    ) as http_client:
        wechat = WechatOpenPlatformClient(http_client)
        await wechat.start_ticket_push(component_appid="wx-component", component_appsecret="secret")
        token, expires_in = await wechat.component_access_token(
            component_appid="wx-component",
            component_appsecret="secret",
            verify_ticket="ticket",
        )
        pre_auth = await wechat.pre_authorization(
            component_appid="wx-component",
            component_access_token=token,
            callback_url="https://app.example.com/callbacks/v1/wechat/authorize",
            state="state-value",
        )
        mobile_auth = await wechat.pre_authorization(
            component_appid="wx-component",
            component_access_token=token,
            callback_url="https://app.example.com/callbacks/v1/wechat/authorize",
            state="state-value",
            mobile=True,
        )
        authorization = await wechat.exchange_authorization(
            component_appid="wx-component",
            component_access_token=token,
            authorization_code="authorization-code",
        )

    assert expires_in == 7200
    assert "pre_auth_code=pre-auth-code" in pre_auth.url
    assert "auth_type=1" in pre_auth.url
    assert urlparse(mobile_auth.url).path == "/safe/bindcomponent"
    assert parse_qs(urlparse(mobile_auth.url).query)["no_scan"] == ["1"]
    assert urlparse(mobile_auth.url).fragment == "wechat_redirect"
    assert authorization.scope_ids == [7, 11]
    assert requested_paths == [
        "/cgi-bin/component/api_start_push_ticket",
        "/cgi-bin/component/api_component_token",
        "/cgi-bin/component/api_create_preauthcode",
        "/cgi-bin/component/api_create_preauthcode",
        "/cgi-bin/component/api_query_auth",
        "/cgi-bin/component/api_get_authorizer_info",
    ]


class FakeWechatOpenPlatformClient:
    async def component_access_token(self, **_: str) -> tuple[str, int]:
        return "component-access-token", 7200

    async def pre_authorization(self, *, mobile: bool = False, **values: str) -> PreAuthorization:
        callback = values["callback_url"]
        redirect = f"{callback}?state={values['state']}&component_appid={values['component_appid']}"
        query = urlencode(
            {
                "component_appid": values["component_appid"],
                "pre_auth_code": "pre-auth-code",
                "redirect_uri": redirect,
            }
        )
        path = "/safe/bindcomponent" if mobile else "/cgi-bin/componentloginpage"
        return PreAuthorization(
            url=f"https://mp.weixin.qq.com{path}?{query}",
            expires_in=600,
        )

    async def exchange_authorization(self, **_: str) -> AuthorizationDetails:
        return AuthorizationDetails(
            authorizer_appid="wx-authorized-account",
            access_token="authorizer-access-token",
            refresh_token="authorizer-refresh-token",
            expires_in=7200,
            scope_ids=[7, 11],
            name="授权测试公众号",
            avatar_url="https://example.com/avatar.png",
            metadata={"funcscope_ids": [7, 11], "user_name": "gh_authorized"},
        )


async def test_direct_scan_authorization_binds_account_to_authenticated_owner(
    app: FastAPI,
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    login = await register_and_login(client, "direct-wechat@example.com")
    app.state.settings = replace(app.state.settings, wechat_provider_mode="direct")
    secrets = app.state.secret_provider
    message_token = "message-token"
    aes_key = base64.b64encode(bytes(range(32))).decode().rstrip("=")
    async with app.state.database.session_maker() as session:
        config = WechatPlatformConfig(
            environment="test",
            component_appid="wx-component-appid",
            component_secret_ref=secrets.protect("component-secret"),
            message_token_ref=secrets.protect(message_token),
            encoding_aes_key_ref=secrets.protect(aes_key),
            authorization_callback_url="http://testserver/callbacks/v1/wechat/authorize",
            ticket_callback_url="http://testserver/callbacks/v1/wechat/tickets",
            permission_set=["draft", "publish"],
            status="published",
        )
        session.add(config)
        await session.commit()

    plain_echo = "wechat-callback-ready"
    plain_signature = hashlib.sha1(
        "".join(sorted((message_token, "1690000000", "plain-nonce"))).encode()
    ).hexdigest()
    plain_verification = await client.get(
        "/callbacks/v1/wechat/tickets",
        params={
            "appid": "wx-component-appid",
            "signature": plain_signature,
            "timestamp": "1690000000",
            "nonce": "plain-nonce",
            "echostr": plain_echo,
        },
    )
    assert plain_verification.status_code == 200
    assert plain_verification.text == plain_echo

    encrypted_echo_body, encrypted_echo_signature = _encrypted_callback(
        xml="encrypted-echo-ready",
        appid="wx-component-appid",
        token=message_token,
        aes_key_text=aes_key,
        timestamp="1690000001",
        nonce="encrypted-nonce",
    )
    _, encrypted_echo = parse_encrypted_callback(encrypted_echo_body)
    encrypted_verification = await client.get(
        "/callbacks/v1/wechat/tickets",
        params={
            "appid": "wx-component-appid",
            "msg_signature": encrypted_echo_signature,
            "timestamp": "1690000001",
            "nonce": "encrypted-nonce",
            "echostr": encrypted_echo,
        },
    )
    assert encrypted_verification.status_code == 200
    assert encrypted_verification.text == "encrypted-echo-ready"
    assert (
        decrypt_callback_message(
            encrypted=encrypted_echo,
            message_token=message_token,
            encoding_aes_key=aes_key,
            msg_signature=encrypted_echo_signature,
            timestamp="1690000001",
            nonce="encrypted-nonce",
            expected_appid="wx-component-appid",
        )
        == b"encrypted-echo-ready"
    )

    ticket_xml = (
        "<xml><InfoType>component_verify_ticket</InfoType>"
        "<ComponentVerifyTicket>verify-ticket</ComponentVerifyTicket></xml>"
    )
    ticket_body, ticket_signature = _encrypted_callback(
        xml=ticket_xml,
        appid="wx-component-appid",
        token=message_token,
        aes_key_text=aes_key,
        timestamp="1700000000",
        nonce="ticket-nonce",
    )
    ticket_callback = await client.post(
        "/callbacks/v1/wechat/tickets",
        params={
            "msg_signature": ticket_signature,
            "timestamp": "1700000000",
            "nonce": "ticket-nonce",
        },
        content=ticket_body,
        headers={"Content-Type": "application/xml"},
    )
    assert ticket_callback.status_code == 200, ticket_callback.text
    assert ticket_callback.text == "success"

    monkeypatch.setattr("app.api.user.WechatOpenPlatformClient", FakeWechatOpenPlatformClient)
    monkeypatch.setattr("app.api.callbacks.WechatOpenPlatformClient", FakeWechatOpenPlatformClient)
    authorization = await client.post(
        "/api/v1/official-accounts/authorize-url",
        headers=bearer(login["access_token"]),
        json={"redirect_uri": "http://localhost:9000/official-accounts"},
    )
    assert authorization.status_code == 200, authorization.text
    authorization_url = authorization.json()["authorization_url"]
    assert authorization_url.startswith("http://testserver/callbacks/v1/wechat/entry?")
    assert "pre_auth_code" not in authorization_url
    state = parse_qs(urlparse(authorization_url).query)["state"][0]
    entry = await client.get(authorization_url)
    assert entry.status_code == 200, entry.text
    assert entry.headers["referrer-policy"] == "origin"
    assert entry.headers["cache-control"] == "no-store"
    assert 'referrerpolicy="origin"' in entry.text
    wechat_url = unescape(entry.text.split('href="')[1].split('"')[0])
    callback_url = parse_qs(urlparse(wechat_url).query)["redirect_uri"][0]
    assert parse_qs(urlparse(callback_url).query)["state"] == [state]
    assert urlparse(wechat_url).path == "/cgi-bin/componentloginpage"
    mobile = await client.get(authorization_url, headers={"User-Agent": "MicroMessenger/8.0"})
    assert "/safe/bindcomponent?" in mobile.text
    wrong_host = await client.get(authorization_url.replace("testserver", "untrusted.example"))
    assert wrong_host.status_code == 303
    assert wrong_host.headers["location"] == authorization_url
    invalid = await client.get("/callbacks/v1/wechat/entry", params={"state": "x" * 43})
    assert invalid.status_code == 400
    async with app.state.database.session_maker() as session:
        stored = await session.scalar(
            select(WechatAuthorizationState).where(
                WechatAuthorizationState.state_hash == hash_token(state)
            )
        )
        assert stored is not None
        stored.expires_at = utcnow() - timedelta(seconds=1)
        await session.commit()
    expired = await client.get(authorization_url)
    assert expired.status_code == 400
    async with app.state.database.session_maker() as session:
        stored = await session.scalar(
            select(WechatAuthorizationState).where(
                WechatAuthorizationState.state_hash == hash_token(state)
            )
        )
        assert stored is not None
        stored.expires_at = utcnow() + timedelta(seconds=600)
        await session.commit()

    callback = await client.get(
        "/callbacks/v1/wechat/authorize",
        params={
            "state": state,
            "component_appid": "wx-component-appid",
            "auth_code": "one-time-authorization-code",
        },
    )
    assert callback.status_code == 200, callback.text
    assert "公众号授权已完成" in callback.text
    consumed = await client.get(authorization_url)
    assert consumed.status_code == 400

    message_xml = (
        "<xml><ToUserName>gh_authorized</ToUserName><FromUserName>openid</FromUserName>"
        "<CreateTime>1700000001</CreateTime><MsgType>event</MsgType>"
        "<Event>subscribe</Event></xml>"
    )
    message_body, message_signature = _encrypted_callback(
        xml=message_xml,
        appid="wx-component-appid",
        token=message_token,
        aes_key_text=aes_key,
        timestamp="1700000001",
        nonce="message-nonce",
    )
    message_callback = await client.post(
        "/callbacks/v1/wechat/messages/wx-authorized-account",
        params={
            "msg_signature": message_signature,
            "timestamp": "1700000001",
            "nonce": "message-nonce",
        },
        content=message_body,
        headers={"Content-Type": "application/xml"},
    )
    assert message_callback.status_code == 200, message_callback.text
    assert message_callback.text == "success"

    async with app.state.database.session_maker() as session:
        account = await session.scalar(
            select(OfficialAccount).where(
                OfficialAccount.owner_id == login["registered_user"]["id"]
            )
        )
        assert account is not None
        assert account.name == "授权测试公众号"
        assert account.capability_flags == ["assets", "draft", "publish"]
        assert account.token_secret_ref is not None
        assert secrets.resolve(account.token_secret_ref) == "authorizer-access-token"
        assert "authorizer-refresh-token" not in str(account.technical_metadata)

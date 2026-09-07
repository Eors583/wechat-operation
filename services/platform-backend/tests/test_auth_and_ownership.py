from __future__ import annotations

from datetime import timedelta

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select

from app.domains.account_deletion import purge_account
from app.models import (
    AccountDeletionRequest,
    Admin,
    Message,
    ModelDeployment,
    ModelProviderRecord,
    Project,
    Task,
    User,
    utcnow,
)
from app.security import hash_password

from .conftest import bearer, register_and_login


async def test_unified_error_and_owner_isolation(client: AsyncClient) -> None:
    unauthenticated = await client.get("/api/v1/me")
    assert unauthenticated.status_code == 401
    assert set(unauthenticated.json()) == {
        "code",
        "message",
        "request_id",
        "retryable",
        "details",
    }
    assert unauthenticated.headers["x-request-id"].startswith("req_")

    alice = await register_and_login(client, "alice@example.com", display_name="Alice")
    bob = await register_and_login(client, "bob@example.com", display_name="Bob")
    alice_headers = bearer(alice["access_token"])
    bob_headers = bearer(bob["access_token"])

    themed = await client.patch(
        "/api/v1/me",
        headers=alice_headers,
        json={"theme_preference": "dark"},
    )
    assert themed.status_code == 200
    assert (await client.get("/api/v1/me", headers=alice_headers)).json()[
        "theme_preference"
    ] == "dark"

    project = await client.post(
        "/api/v1/projects",
        headers=bob_headers,
        json={"name": "Bob 的项目", "description": "private"},
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    hidden = await client.patch(
        f"/api/v1/projects/{project_id}",
        headers=alice_headers,
        json={"name": "越权修改"},
    )
    assert hidden.status_code == 404
    assert hidden.json()["code"] == "PROJECT_NOT_FOUND"

    bob_projects = await client.get("/api/v1/projects", headers=bob_headers)
    alice_projects = await client.get("/api/v1/projects", headers=alice_headers)
    assert [item["id"] for item in bob_projects.json()["items"]] == [project_id]
    assert alice_projects.json()["items"] == []


async def test_user_model_options_only_expose_available_admin_chat_models(
    app: FastAPI, client: AsyncClient
) -> None:
    login = await register_and_login(client, "models@example.com")
    async with app.state.database.session_maker() as session:
        provider = ModelProviderRecord(
            code="model-options-provider",
            name="模型供应商",
            adapter="openai_responses",
            base_url="https://models.example/v1",
            secret_ref="env:MODEL_API_KEY",
            status="active",
        )
        disabled_provider = ModelProviderRecord(
            code="disabled-model-options-provider",
            name="禁用供应商",
            adapter="openai_responses",
            base_url="https://disabled.example/v1",
            secret_ref="env:DISABLED_MODEL_API_KEY",
            status="disabled",
        )
        manus_provider = ModelProviderRecord(
            code="manus-model-options-provider",
            name="Manus",
            adapter="manus_v2",
            base_url="https://api.manus.example",
            secret_ref="env:MANUS_API_KEY",
            status="active",
        )
        session.add_all([provider, disabled_provider, manus_provider])
        await session.flush()
        visible = ModelDeployment(
            provider_id=provider.id,
            model_id="chat-visible",
            alias="可用对话模型",
            model_type="chat",
            status="available",
        )
        hidden_embedding = ModelDeployment(
            provider_id=provider.id,
            model_id="embedding-hidden",
            alias="向量模型",
            model_type="embedding",
            status="available",
        )
        hidden_draft = ModelDeployment(
            provider_id=provider.id,
            model_id="chat-draft",
            alias="草稿模型",
            model_type="chat",
            status="draft",
        )
        hidden_provider = ModelDeployment(
            provider_id=disabled_provider.id,
            model_id="chat-disabled-provider",
            alias="供应商禁用模型",
            model_type="chat",
            status="available",
        )
        deep_model = ModelDeployment(
            provider_id=manus_provider.id,
            model_id="lite",
            alias="A Manus 深度模型",
            model_type="chat",
            status="available",
        )
        session.add_all([visible, hidden_embedding, hidden_draft, hidden_provider, deep_model])
        await session.commit()

    response = await client.get("/api/v1/model-options", headers=bearer(login["access_token"]))

    assert response.status_code == 200
    assert response.json()["items"] == [
        {
            "id": visible.id,
            "name": "可用对话模型",
            "provider_name": "模型供应商",
            "model_id": "chat-visible",
            "model_type": "chat",
            "context_window": 0,
            "max_output_tokens": 0,
        },
        {
            "id": deep_model.id,
            "name": "A Manus 深度模型",
            "provider_name": "Manus",
            "model_id": "lite",
            "model_type": "chat",
            "context_window": 0,
            "max_output_tokens": 0,
        },
    ]


async def test_user_and_admin_authentication_boundaries(
    app: FastAPI, client: AsyncClient, monkeypatch: object
) -> None:
    user = await register_and_login(client, "boundary@example.com")
    user_headers = bearer(user["access_token"])

    try:
        async with app.state.database.session_maker() as session:
            session.add(
                Admin(
                    username="root-admin",
                    password_hash=hash_password("admin-password-is-long"),
                    permissions=["*"],
                )
            )
            await session.commit()

        admin_login = await client.post(
            "/admin-api/v1/auth/login",
            json={
                "username": "root-admin",
                "password": "admin-password-is-long",
                "device_name": "pytest",
            },
        )
        assert admin_login.status_code == 200, admin_login.text
        admin_headers = bearer(admin_login.json()["access_token"])

        assert (await client.get("/admin-api/v1/me", headers=user_headers)).status_code == 401
        assert (await client.get("/api/v1/me", headers=admin_headers)).status_code == 401
        assert (
            await client.get("/admin-api/v1/dashboard", headers=admin_headers)
        ).status_code == 200

        adjusted = await client.post(
            f"/admin-api/v1/users/{user['registered_user']['id']}/quota-adjustments",
            headers={**admin_headers, "Idempotency-Key": "admin-credit-1"},
            json={"direction": "credit", "amount": 25, "reason": "pytest 额度补偿"},
        )
        assert adjusted.status_code == 200, adjusted.text
        assert adjusted.json()["balance"] == 525
        replay = await client.post(
            f"/admin-api/v1/users/{user['registered_user']['id']}/quota-adjustments",
            headers={**admin_headers, "Idempotency-Key": "admin-credit-1"},
            json={"direction": "credit", "amount": 25, "reason": "pytest 额度补偿"},
        )
        assert replay.json() == adjusted.json()

        audits = await client.get("/admin-api/v1/audit-logs", headers=admin_headers)
        assert audits.status_code == 200
        assert any(item["action"] == "quota.adjust" for item in audits.json()["items"])
    finally:
        pass


async def test_refresh_rotation_detects_replay_and_revokes_family(client: AsyncClient) -> None:
    login = await register_and_login(client, "refresh@example.com", platform="windows")
    first_refresh = login["refresh_token"]
    assert first_refresh

    rotated = await client.post("/api/v1/auth/refresh", json={"refresh_token": first_refresh})
    assert rotated.status_code == 200, rotated.text
    second_refresh = rotated.json()["refresh_token"]

    replay = await client.post("/api/v1/auth/refresh", json={"refresh_token": first_refresh})
    assert replay.status_code == 401
    assert replay.json()["code"] == "REFRESH_TOKEN_REPLAY"

    family_revoked = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": second_refresh}
    )
    assert family_revoked.status_code == 401
    assert family_revoked.json()["code"] == "REFRESH_TOKEN_REPLAY"


async def test_verification_failures_persist_and_lock_the_challenge(client: AsyncClient) -> None:
    challenge = await client.post(
        "/api/v1/auth/verification-codes",
        json={"destination": "+8613800000000", "purpose": "register"},
    )
    assert challenge.status_code == 202
    challenge_id = challenge.json()["challenge_id"]
    wrong_code = "000000" if challenge.json()["debug_code"] != "000000" else "000001"
    for _ in range(5):
        rejected = await client.post(
            "/api/v1/auth/verification-codes/verify",
            json={"challenge_id": challenge_id, "code": wrong_code},
        )
        assert rejected.status_code == 400
        assert rejected.json()["code"] == "VERIFICATION_INVALID"
    locked = await client.post(
        "/api/v1/auth/verification-codes/verify",
        json={"challenge_id": challenge_id, "code": challenge.json()["debug_code"]},
    )
    assert locked.status_code == 429
    assert locked.json()["code"] == "VERIFICATION_LOCKED"


async def test_native_logout_revokes_the_access_token_family_without_cookies(
    client: AsyncClient,
) -> None:
    login = await register_and_login(client, "native-logout@example.com", platform="ios")
    access_token = login["access_token"]
    refresh_token = login["refresh_token"]
    assert not client.cookies.get("ua_session")
    assert not client.cookies.get("ua_csrf")

    # A stale browser cookie must not force CSRF on the explicit native-token branch.
    client.cookies.set("ua_session", "stale-browser-cookie", path="/api/v1/auth")
    logged_out = await client.post(
        "/api/v1/auth/logout",
        headers=bearer(access_token),
        json={"refresh_token": refresh_token},
    )
    assert logged_out.status_code == 204
    assert (await client.get("/api/v1/me", headers=bearer(access_token))).status_code == 401
    replay = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert replay.status_code == 401
    assert replay.json()["code"] == "REFRESH_TOKEN_REPLAY"


async def test_account_deletion_revokes_sessions_and_purges_personal_content(
    app: FastAPI, client: AsyncClient
) -> None:
    login = await register_and_login(client, "delete-me@example.com", display_name="待注销用户")
    headers = bearer(login["access_token"])
    user_id = login["registered_user"]["id"]

    wrong_password = await client.request(
        "DELETE",
        "/api/v1/me",
        headers=headers,
        json={"password": "wrong-password", "confirmation": "注销账号"},
    )
    assert wrong_password.status_code == 403
    assert wrong_password.json()["code"] == "ACCOUNT_DELETION_PASSWORD_INVALID"
    assert (await client.get("/api/v1/me", headers=headers)).status_code == 200

    async with app.state.database.session_maker() as session:
        project = Project(owner_id=user_id, name="含个人信息的项目", description="敏感描述")
        session.add(project)
        await session.flush()
        task = Task(owner_id=user_id, project_id=project.id, title="含个人信息的任务")
        session.add(task)
        await session.flush()
        task_id = task.id
        session.add(
            Message(
                task_id=task.id,
                role="user",
                content_json={"private": "content"},
                plain_text="需要在清理时擦除的正文",
            )
        )
        await session.commit()

    deleted = await client.request(
        "DELETE",
        "/api/v1/me",
        headers=headers,
        json={
            "password": "correct-horse-battery-staple",
            "confirmation": "注销账号",
        },
    )
    assert deleted.status_code == 202, deleted.text
    assert deleted.json()["status"] == "scheduled"
    assert deleted.json()["purge_after"] > deleted.json()["requested_at"]
    assert (await client.get("/api/v1/me", headers=headers)).status_code == 401
    refresh = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]}
    )
    assert refresh.status_code == 401

    async with app.state.database.session_maker() as session:
        deletion = await session.scalar(
            select(AccountDeletionRequest).where(AccountDeletionRequest.user_id == user_id)
        )
        assert deletion is not None
        assert deletion.status == "scheduled"
        deletion.purge_after = utcnow() - timedelta(seconds=1)
        await session.commit()
        await purge_account(session, deletion=deletion, storage=app.state.storage_provider)
        await session.commit()

    async with app.state.database.session_maker() as session:
        user = await session.get(User, user_id)
        assert user is not None
        assert user.status == "disabled"
        assert user.email is None
        assert user.display_name == "已注销用户"
        message = await session.scalar(select(Message).where(Message.task_id == task_id))
        assert message is not None
        assert message.plain_text == ""
        assert message.content_json == {}

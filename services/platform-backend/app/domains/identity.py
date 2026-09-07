from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import false, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import ApiError
from app.models import (
    Admin,
    AdminSession,
    RefreshToken,
    User,
    VerificationChallenge,
    utcnow,
)
from app.providers import VerificationProvider
from app.security import (
    hash_password,
    hash_token,
    issue_access_token,
    new_opaque_token,
    new_uuid,
    verify_password,
)

from .quota import provision_quota


@dataclass(slots=True)
class SessionTokens:
    access_token: str
    refresh_token: str
    csrf_token: str
    access_expires_in: int


@dataclass(slots=True)
class AdminTokens:
    access_token: str
    session_token: str
    csrf_token: str
    access_expires_in: int


def is_expired(value: datetime) -> bool:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value <= utcnow()


async def create_verification_challenge(
    session: AsyncSession,
    *,
    destination: str,
    purpose: str,
    provider: VerificationProvider,
    settings: Settings,
) -> tuple[VerificationChallenge, str | None, str]:
    code = f"{secrets.randbelow(1_000_000):06d}"
    challenge_id = new_uuid()
    challenge = VerificationChallenge(
        id=challenge_id,
        destination=destination.lower().strip(),
        purpose=purpose,
        code_hash=hash_token(f"{challenge_id}:{code}"),
        expires_at=utcnow() + timedelta(seconds=settings.verification_code_ttl_seconds),
    )
    session.add(challenge)
    delivery_status = await provider.send(challenge.destination, code)
    debug_code = code if settings.environment in {"development", "test"} else None
    return challenge, debug_code, delivery_status


async def verify_challenge(session: AsyncSession, *, challenge_id: str, code: str) -> str:
    challenge = await session.scalar(
        select(VerificationChallenge)
        .where(VerificationChallenge.id == challenge_id)
        .with_for_update()
    )
    if not challenge or challenge.consumed_at or is_expired(challenge.expires_at):
        raise ApiError(400, "VERIFICATION_EXPIRED", "验证码已过期，请重新获取。")
    challenge.attempts += 1
    if challenge.attempts > 5:
        await session.commit()
        raise ApiError(429, "VERIFICATION_LOCKED", "验证码尝试次数过多，请重新获取。")
    if hash_token(f"{challenge.id}:{code}") != challenge.code_hash:
        await session.commit()
        raise ApiError(400, "VERIFICATION_INVALID", "验证码不正确。")
    token = new_opaque_token()
    challenge.verified_at = utcnow()
    challenge.verification_token_hash = hash_token(token)
    return token


async def _consume_verification(
    session: AsyncSession,
    *,
    destination: str,
    purpose: str,
    verification_token: str | None,
) -> None:
    if not verification_token:
        raise ApiError(400, "VERIFICATION_REQUIRED", "手机号注册需要先完成验证码校验。")
    challenge = await session.scalar(
        select(VerificationChallenge)
        .where(
            VerificationChallenge.destination == destination,
            VerificationChallenge.purpose == purpose,
            VerificationChallenge.verification_token_hash == hash_token(verification_token),
            VerificationChallenge.verified_at.is_not(None),
            VerificationChallenge.consumed_at.is_(None),
        )
        .with_for_update()
    )
    if not challenge or is_expired(challenge.expires_at):
        raise ApiError(400, "VERIFICATION_REQUIRED", "验证码校验无效或已过期。")
    challenge.consumed_at = utcnow()


async def register_user(
    session: AsyncSession,
    *,
    email: str | None,
    phone: str | None,
    display_name: str,
    password: str,
    verification_token: str | None,
    accepted_terms: bool,
    settings: Settings,
) -> User:
    normalized_email = email.lower().strip() if email else None
    normalized_phone = phone.strip() if phone else None
    if not normalized_email and not normalized_phone:
        raise ApiError(422, "IDENTIFIER_REQUIRED", "请输入手机号或邮箱。")
    if not accepted_terms:
        raise ApiError(422, "TERMS_REQUIRED", "请先阅读并同意用户协议和隐私政策。")
    if normalized_phone:
        await _consume_verification(
            session,
            destination=normalized_phone,
            purpose="register",
            verification_token=verification_token,
        )
    duplicate = await session.scalar(
        select(User.id).where(
            or_(
                User.email == normalized_email if normalized_email else false(),
                User.phone == normalized_phone if normalized_phone else false(),
            )
        )
    )
    if duplicate:
        raise ApiError(409, "ACCOUNT_EXISTS", "该手机号或邮箱已注册。")
    user = User(
        email=normalized_email,
        phone=normalized_phone,
        display_name=display_name.strip(),
        password_hash=hash_password(password),
    )
    session.add(user)
    await session.flush()
    await provision_quota(session, user_id=user.id, initial_balance=settings.default_quota_balance)
    return user


async def login_user(
    session: AsyncSession,
    *,
    identifier: str,
    password: str,
    platform: str,
    device_name: str | None,
    settings: Settings,
) -> tuple[User, SessionTokens]:
    normalized = identifier.lower().strip()
    user = await session.scalar(
        select(User).where(or_(User.email == normalized, User.phone == normalized))
    )
    if not user or not verify_password(user.password_hash, password):
        raise ApiError(401, "INVALID_CREDENTIALS", "账号或密码不正确。")
    if user.status != "active" or user.deleted_at:
        raise ApiError(403, "ACCOUNT_DISABLED", "账号当前不可用。")
    user.last_login_at = utcnow()
    tokens = await create_user_session(
        session,
        user=user,
        platform=platform,
        device_name=device_name,
        settings=settings,
    )
    return user, tokens


async def login_user_with_code(
    session: AsyncSession,
    *,
    identifier: str,
    verification_token: str,
    platform: str,
    device_name: str | None,
    settings: Settings,
) -> tuple[User, SessionTokens]:
    normalized = identifier.lower().strip()
    await _consume_verification(
        session,
        destination=normalized,
        purpose="login",
        verification_token=verification_token,
    )
    user = await session.scalar(
        select(User).where(or_(User.email == normalized, User.phone == normalized))
    )
    if not user or user.status != "active" or user.deleted_at:
        raise ApiError(403, "ACCOUNT_DISABLED", "账号当前不可用。")
    user.last_login_at = utcnow()
    tokens = await create_user_session(
        session,
        user=user,
        platform=platform,
        device_name=device_name,
        settings=settings,
    )
    return user, tokens


async def create_user_session(
    session: AsyncSession,
    *,
    user: User,
    platform: str,
    device_name: str | None,
    settings: Settings,
    family_id: str | None = None,
) -> SessionTokens:
    raw_refresh = new_opaque_token()
    family = family_id or new_uuid()
    session_record = RefreshToken(
        user_id=user.id,
        token_hash=hash_token(raw_refresh),
        family_id=family,
        platform=platform,
        device_name=device_name,
        expires_at=utcnow() + timedelta(seconds=settings.refresh_token_ttl_seconds),
    )
    session.add(session_record)
    await session.flush()
    return SessionTokens(
        access_token=issue_access_token(
            subject=user.id,
            session_id=family,
            kind="user_access",
            secret=settings.token_secret,
            ttl_seconds=settings.access_token_ttl_seconds,
        ),
        refresh_token=raw_refresh,
        csrf_token=new_opaque_token(),
        access_expires_in=settings.access_token_ttl_seconds,
    )


async def rotate_refresh_token(
    session: AsyncSession, *, raw_refresh: str, settings: Settings
) -> tuple[User, SessionTokens]:
    token = await session.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_hash == hash_token(raw_refresh))
        .with_for_update()
    )
    if not token:
        raise ApiError(401, "INVALID_REFRESH_TOKEN", "刷新令牌无效。")
    if token.revoked_at:
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == token.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=utcnow())
        )
        await session.commit()
        raise ApiError(401, "REFRESH_TOKEN_REPLAY", "检测到会话令牌重放，已退出该设备。")
    if is_expired(token.expires_at):
        token.revoked_at = utcnow()
        await session.commit()
        raise ApiError(401, "REFRESH_TOKEN_EXPIRED", "登录已过期，请重新登录。")
    user = await session.get(User, token.user_id)
    if not user or user.status != "active" or user.deleted_at:
        raise ApiError(403, "ACCOUNT_DISABLED", "账号当前不可用。")
    replacement = await create_user_session(
        session,
        user=user,
        platform=token.platform,
        device_name=token.device_name,
        family_id=token.family_id,
        settings=settings,
    )
    new_record = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(replacement.refresh_token))
    )
    token.revoked_at = utcnow()
    token.replaced_by_id = new_record.id if new_record else None
    return user, replacement


async def revoke_refresh_token(
    session: AsyncSession,
    *,
    raw_refresh: str | None,
    user_id: str,
    all_sessions: bool,
    family_id: str | None = None,
) -> None:
    if all_sessions:
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=utcnow())
        )
        return
    if family_id:
        await session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.family_id == family_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=utcnow())
        )
        return
    if raw_refresh:
        await session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.token_hash == hash_token(raw_refresh),
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=utcnow())
        )


async def login_admin(
    session: AsyncSession,
    *,
    username: str,
    password: str,
    device_name: str | None,
    settings: Settings,
) -> tuple[Admin, AdminTokens]:
    admin = await session.scalar(select(Admin).where(Admin.username == username.strip()))
    if not admin or not verify_password(admin.password_hash, password):
        raise ApiError(401, "INVALID_ADMIN_CREDENTIALS", "管理员账号或密码不正确。")
    if admin.status != "active":
        raise ApiError(403, "ADMIN_DISABLED", "管理员账号已停用。")
    raw_session = new_opaque_token()
    record = AdminSession(
        admin_id=admin.id,
        token_hash=hash_token(raw_session),
        device_name=device_name,
        expires_at=utcnow() + timedelta(seconds=settings.admin_session_ttl_seconds),
    )
    session.add(record)
    await session.flush()
    admin.last_login_at = utcnow()
    return admin, AdminTokens(
        access_token=issue_access_token(
            subject=admin.id,
            session_id=record.id,
            kind="admin_access",
            secret=settings.token_secret,
            ttl_seconds=settings.admin_access_token_ttl_seconds,
        ),
        session_token=raw_session,
        csrf_token=new_opaque_token(),
        access_expires_in=settings.admin_access_token_ttl_seconds,
    )


async def revoke_admin_session(
    session: AsyncSession, *, admin_id: str, session_id: str | None = None
) -> None:
    statement = update(AdminSession).where(
        AdminSession.admin_id == admin_id, AdminSession.revoked_at.is_(None)
    )
    if session_id:
        statement = statement.where(AdminSession.id == session_id)
    await session.execute(statement.values(revoked_at=utcnow()))

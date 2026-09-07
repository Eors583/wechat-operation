from __future__ import annotations

from datetime import UTC
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError
from app.models import (
    Article,
    ArticleConfirmation,
    ArticleRender,
    ArticleVersion,
    JobRecord,
    OfficialAccount,
    ResourceLimit,
    WechatOperation,
    utcnow,
)
from app.providers import ProviderResultUnknown, ProviderUnavailable, WechatProvider
from app.system_settings import published_setting_section

from .article import (
    current_article_version,
    owned_article,
    upsert_article_library_item,
    upsert_article_preference_candidate,
)
from .common import create_job, emit_outbox

BLOCKING_WECHAT_OPERATION_STATUSES = frozenset({"queued", "submitting", "reconciling", "unknown"})


def _article_operation_status(operation: WechatOperation) -> str:
    if operation.status == "succeeded":
        return "wechat_draft" if operation.operation_type == "draft" else "published"
    prefix = "wechat_draft" if operation.operation_type == "draft" else "publish"
    return f"{prefix}_{operation.status}"


async def sync_article_operation_status(
    session: AsyncSession, *, operation: WechatOperation, article: Article | None = None
) -> None:
    target = article or await session.get(Article, operation.article_id)
    version = await session.get(ArticleVersion, operation.article_version_id)
    if not target or not version:
        return
    aggregate_status = _article_operation_status(operation)
    target.status = aggregate_status
    await upsert_article_library_item(
        session,
        article=target,
        version=version,
        status=aggregate_status,
    )


async def owned_official_account(
    session: AsyncSession, *, owner_id: str, account_id: str
) -> OfficialAccount:
    account = await session.scalar(
        select(OfficialAccount).where(
            OfficialAccount.id == account_id,
            OfficialAccount.owner_id == owner_id,
            OfficialAccount.deleted_at.is_(None),
        )
    )
    if not account:
        raise ApiError(404, "OFFICIAL_ACCOUNT_NOT_FOUND", "公众号不存在。")
    return account


async def owned_render(session: AsyncSession, *, owner_id: str, render_id: str) -> ArticleRender:
    render = await session.scalar(
        select(ArticleRender).where(
            ArticleRender.id == render_id, ArticleRender.owner_id == owner_id
        )
    )
    if not render:
        raise ApiError(404, "ARTICLE_RENDER_NOT_FOUND", "排版预览不存在。")
    return render


async def confirm_render(
    session: AsyncSession, *, owner_id: str, render_id: str, action: str
) -> ArticleConfirmation:
    if action not in {"draft", "publish"}:
        raise ApiError(422, "CONFIRMATION_ACTION_INVALID", "确认操作无效。")
    render = await owned_render(session, owner_id=owner_id, render_id=render_id)
    if render.stale_at or render.compatibility_status != "passed":
        raise ApiError(409, "ARTICLE_RENDER_STALE", "排版已变化，请重新预览并确认。")
    article = await owned_article(session, owner_id=owner_id, article_id=render.article_id)
    current = await current_article_version(session, article=article)
    if current.id != render.article_version_id:
        raise ApiError(409, "ARTICLE_RENDER_STALE", "文章已变化，请重新生成最终预览。")
    existing = await session.scalar(
        select(ArticleConfirmation).where(
            ArticleConfirmation.render_id == render.id,
            ArticleConfirmation.user_id == owner_id,
            ArticleConfirmation.action == action,
            ArticleConfirmation.invalidated_at.is_(None),
        )
    )
    if existing:
        return existing
    confirmation = ArticleConfirmation(
        render_id=render.id,
        user_id=owner_id,
        action=action,
        checksum=render.checksum,
    )
    session.add(confirmation)
    await upsert_article_preference_candidate(
        session,
        article=article,
        version=current,
        source_type="confirmed_article",
        confidence=Decimal("0.4500"),
    )
    await session.flush()
    return confirmation


def _account_token_expired(account: OfficialAccount) -> bool:
    if not account.token_expires_at:
        return False
    expires = account.token_expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    return expires <= utcnow()


async def create_wechat_operation(
    session: AsyncSession,
    *,
    owner_id: str,
    render_id: str,
    operation_type: str,
    idempotency_key: str,
) -> WechatOperation:
    if operation_type not in {"draft", "publish"}:
        raise ApiError(422, "WECHAT_OPERATION_INVALID", "公众号操作无效。")
    wechat_settings = await published_setting_section(session, "wechat")
    enabled_key = "wechat_draft_enabled" if operation_type == "draft" else "wechat_publish_enabled"
    if wechat_settings.get(enabled_key) is False:
        raise ApiError(403, "WECHAT_OPERATION_DISABLED", "当前公众号操作已由管理员停用。")
    limits = await session.scalar(select(ResourceLimit).where(ResourceLimit.owner_id == owner_id))
    if not limits or not limits.wechat_enabled:
        raise ApiError(403, "WECHAT_CAPABILITY_DISABLED", "当前账号暂不能使用公众号发送功能。")
    render = await owned_render(session, owner_id=owner_id, render_id=render_id)
    if not render.official_account_id:
        raise ApiError(422, "OFFICIAL_ACCOUNT_REQUIRED", "请选择目标公众号。")
    account = await owned_official_account(
        session, owner_id=owner_id, account_id=render.official_account_id
    )
    if account.status != "connected" or _account_token_expired(account):
        raise ApiError(
            409, "OFFICIAL_ACCOUNT_REAUTH_REQUIRED", "公众号连接已失效，请重新扫码连接。"
        )
    required_capabilities = {"draft"}
    if operation_type == "publish":
        required_capabilities.add("publish")
    missing_capabilities = required_capabilities - set(account.capability_flags)
    if missing_capabilities:
        raise ApiError(
            403,
            "WECHAT_CAPABILITY_UNAVAILABLE",
            "当前公众号授权不包含所需操作权限，请重新授权。",
            details={"missing_capabilities": sorted(missing_capabilities)},
        )
    if render.stale_at or render.compatibility_status != "passed":
        raise ApiError(409, "ARTICLE_RENDER_STALE", "排版已变化，请重新预览并确认。")
    confirmation = await session.scalar(
        select(ArticleConfirmation).where(
            ArticleConfirmation.render_id == render.id,
            ArticleConfirmation.user_id == owner_id,
            ArticleConfirmation.action == operation_type,
            ArticleConfirmation.checksum == render.checksum,
            ArticleConfirmation.invalidated_at.is_(None),
        )
    )
    if not confirmation:
        raise ApiError(409, "FINAL_PREVIEW_CONFIRMATION_REQUIRED", "请先查看最终预览并确认。")
    version = await session.get(ArticleVersion, render.article_version_id)
    # Serialize operation creation per article. The status lookup below then remains
    # authoritative across processes, devices and idempotency keys.
    article = await owned_article(
        session,
        owner_id=owner_id,
        article_id=render.article_id,
        for_update=True,
    )
    if not version or article.current_version_no != version.version_no:
        raise ApiError(409, "ARTICLE_RENDER_STALE", "文章已变化，请重新生成最终预览。")
    existing = await session.scalar(
        select(WechatOperation).where(
            WechatOperation.owner_id == owner_id,
            WechatOperation.idempotency_key == idempotency_key,
        )
    )
    if existing:
        return existing
    blocking = await session.scalar(
        select(WechatOperation)
        .where(
            WechatOperation.owner_id == owner_id,
            WechatOperation.article_id == article.id,
            WechatOperation.article_version_id == version.id,
            WechatOperation.operation_type == operation_type,
            WechatOperation.status.in_(BLOCKING_WECHAT_OPERATION_STATUSES),
        )
        .order_by(WechatOperation.created_at.desc(), WechatOperation.id.desc())
        .limit(1)
    )
    if blocking:
        raise ApiError(
            409,
            "WECHAT_OPERATION_ALREADY_PENDING",
            "该文章版本已有未完成的公众号操作，请先恢复并确认其结果。",
            details={
                "operation_id": blocking.id,
                "status": blocking.status,
                "operation_type": blocking.operation_type,
            },
        )
    operation = WechatOperation(
        owner_id=owner_id,
        official_account_id=account.id,
        article_id=article.id,
        article_version_id=version.id,
        render_id=render.id,
        operation_type=operation_type,
        status="queued",
        idempotency_key=idempotency_key,
        render_checksum=render.checksum,
    )
    session.add(operation)
    await session.flush()
    await sync_article_operation_status(session, operation=operation, article=article)
    create_job(
        session,
        owner_id=owner_id,
        job_type=f"wechat_{operation_type}",
        resource_type="wechat_operation",
        resource_id=operation.id,
        queue="wechat",
        stage="queued",
        frozen_payload={"operation_id": operation.id, "render_checksum": render.checksum},
    )
    emit_outbox(
        session,
        event_type=f"wechat.{operation_type}.requested",
        aggregate_type="wechat_operation",
        aggregate_id=operation.id,
        payload={"operation_id": operation.id},
    )
    return operation


async def current_wechat_operation(
    session: AsyncSession,
    *,
    owner_id: str,
    article_id: str,
    operation_type: str | None = None,
) -> WechatOperation | None:
    await owned_article(session, owner_id=owner_id, article_id=article_id)
    conditions = [
        WechatOperation.owner_id == owner_id,
        WechatOperation.article_id == article_id,
        WechatOperation.status.in_(BLOCKING_WECHAT_OPERATION_STATUSES),
    ]
    if operation_type:
        conditions.append(WechatOperation.operation_type == operation_type)
    return await session.scalar(
        select(WechatOperation)
        .where(*conditions)
        .order_by(WechatOperation.created_at.desc(), WechatOperation.id.desc())
        .limit(1)
    )


async def process_wechat_operation(
    session: AsyncSession, *, operation_id: str, provider: WechatProvider
) -> WechatOperation:
    operation = await session.scalar(
        select(WechatOperation).where(WechatOperation.id == operation_id).with_for_update()
    )
    if not operation:
        raise ApiError(404, "WECHAT_OPERATION_NOT_FOUND", "公众号操作不存在。")
    if operation.status in {
        "succeeded",
        "cancelled",
        "unknown",
        "reconciling",
        "submitting",
    }:
        await sync_article_operation_status(session, operation=operation)
        return operation
    render = await session.get(ArticleRender, operation.render_id)
    account = await session.get(OfficialAccount, operation.official_account_id)
    article = await owned_article(
        session, owner_id=operation.owner_id, article_id=operation.article_id
    )
    if not render or not account or render.checksum != operation.render_checksum:
        operation.status = "failed"
        operation.error_code = "FROZEN_INPUT_MISMATCH"
        await sync_article_operation_status(session, operation=operation, article=article)
        return operation
    job = await session.scalar(
        select(JobRecord).where(
            JobRecord.resource_type == "wechat_operation",
            JobRecord.resource_id == operation.id,
        )
    )
    operation.status = "submitting"
    operation.error_code = None
    operation.result = {
        **operation.result,
        "external_stage": (
            "publish" if operation.operation_type == "publish" and operation.media_id else "draft"
        ),
    }
    await sync_article_operation_status(session, operation=operation, article=article)
    if job:
        job.status = "submitting"
        job.stage = "submitting"
        job.error_code = None
    # Persist the no-replay checkpoint before the external side effect. A crashed worker
    # leaves `submitting`, which must be reconciled rather than submitted again.
    await session.commit()
    external_stage = (
        "publish" if operation.operation_type == "publish" and operation.media_id else "draft"
    )
    try:
        if operation.operation_type == "publish" and operation.media_id:
            media_id = operation.media_id
        else:
            draft_result = await provider.create_or_update_draft(
                account_ref=account.token_secret_ref or account.id,
                html=render.html,
                title=article.title,
                cover_ref=render.cover_asset_id,
            )
            operation.result = draft_result.details or {}
            if draft_result.status == "failed":
                operation.status = "failed"
                operation.error_code = "WECHAT_DRAFT_FAILED"
                media_id = None
            elif draft_result.status != "succeeded":
                operation.status = "unknown"
                operation.error_code = "WECHAT_DRAFT_RESULT_UNKNOWN"
                operation.media_id = draft_result.media_id
                operation.result = {**operation.result, "unknown_stage": "draft"}
                media_id = None
            elif not draft_result.media_id:
                operation.status = "unknown"
                operation.error_code = "WECHAT_DRAFT_RESULT_UNKNOWN"
                operation.result = {**operation.result, "unknown_stage": "draft"}
                media_id = None
            else:
                operation.media_id = draft_result.media_id
                media_id = draft_result.media_id
        if media_id and operation.operation_type == "draft":
            operation.status = "succeeded"
        elif media_id and operation.operation_type == "publish":
            external_stage = "publish"
            operation.result = {**operation.result, "external_stage": external_stage}
            if job:
                job.stage = "publish_submitting"
            # Freeze the draft identifier before publishing. If the worker dies after
            # this point, reconciliation can query the publish stage without recreating
            # the draft.
            await session.commit()
            publish_result = await provider.publish(
                account_ref=account.token_secret_ref or account.id,
                media_id=media_id,
            )
            operation.publish_id = publish_result.publish_id
            operation.result = publish_result.details or {}
            operation.status = publish_result.status
            if publish_result.status == "succeeded":
                operation.error_code = None
            elif publish_result.status == "failed":
                operation.error_code = "DRAFT_CREATED_PUBLISH_FAILED"
            else:
                operation.status = "unknown"
                operation.error_code = "WECHAT_PUBLISH_RESULT_UNKNOWN"
                operation.result = {**operation.result, "unknown_stage": "publish"}
    except ProviderResultUnknown as exc:
        operation.status = "unknown"
        operation.error_code = "WECHAT_RESULT_UNKNOWN"
        operation.result = {**operation.result, "unknown_stage": external_stage}
        if external_stage == "publish":
            operation.publish_id = exc.external_id or operation.publish_id
        else:
            operation.media_id = exc.external_id or operation.media_id
    except ProviderUnavailable:
        operation.status = "failed"
        operation.error_code = (
            "DRAFT_CREATED_PUBLISH_FAILED"
            if operation.operation_type == "publish" and operation.media_id
            else "WECHAT_PROVIDER_UNAVAILABLE"
        )
    except Exception:
        operation.status = "unknown"
        operation.error_code = "WECHAT_RESULT_UNKNOWN"
        operation.result = {**operation.result, "unknown_stage": external_stage}
    await sync_article_operation_status(session, operation=operation, article=article)
    if job:
        job.status = operation.status
        job.stage = operation.status
        job.progress = 100 if operation.status == "succeeded" else job.progress
        job.error_code = operation.error_code
    return operation


async def reconcile_wechat_operation(
    session: AsyncSession, *, operation_id: str, provider: WechatProvider
) -> WechatOperation:
    operation = await session.scalar(
        select(WechatOperation).where(WechatOperation.id == operation_id).with_for_update()
    )
    if not operation:
        raise ApiError(404, "WECHAT_OPERATION_NOT_FOUND", "公众号操作不存在。")
    if operation.status in {"succeeded", "failed", "cancelled"}:
        await sync_article_operation_status(session, operation=operation)
        return operation
    if operation.status not in {"unknown", "reconciling", "submitting"}:
        raise ApiError(409, "WECHAT_RECONCILE_NOT_REQUIRED", "当前公众号操作不需要对账。")
    result_metadata = operation.result if isinstance(operation.result, dict) else {}
    reconcile_stage = result_metadata.get("unknown_stage") or result_metadata.get("external_stage")
    if reconcile_stage not in {"draft", "publish"}:
        reconcile_stage = "publish" if operation.operation_type == "publish" else "draft"
    if reconcile_stage == "publish":
        external_id = operation.publish_id or operation.media_id
    else:
        external_id = operation.media_id
    job = await session.scalar(
        select(JobRecord).where(
            JobRecord.resource_type == "wechat_operation",
            JobRecord.resource_id == operation.id,
        )
    )
    if not external_id:
        operation.status = "unknown"
        operation.error_code = "WECHAT_RECONCILIATION_ID_MISSING"
        if job:
            job.status = "unknown"
            job.stage = "manual_review"
            job.error_code = operation.error_code
            job.error_message = "No external identifier is available for a safe status query."
        await sync_article_operation_status(session, operation=operation)
        return operation
    operation.status = "reconciling"
    try:
        result = await provider.reconcile(
            operation_type=reconcile_stage,
            external_id=external_id,
        )
    except ProviderUnavailable:
        operation.status = "unknown"
        operation.error_code = "WECHAT_RECONCILE_PROVIDER_UNAVAILABLE"
        if job:
            job.status = "unknown"
            job.stage = "reconcile_provider_unavailable"
            job.error_code = operation.error_code
        await sync_article_operation_status(session, operation=operation)
        return operation
    operation.media_id = result.media_id or operation.media_id
    operation.publish_id = result.publish_id or operation.publish_id
    operation.result = {
        **(result.details or {}),
        "reconciled_stage": reconcile_stage,
    }
    if (
        result.status == "succeeded"
        and operation.operation_type == "publish"
        and reconcile_stage == "draft"
    ):
        # The draft is known to exist, but publishing has not been confirmed. Marking
        # this as failed makes an admin retry safe: it reuses media_id and only publishes.
        operation.status = "failed"
        operation.error_code = "DRAFT_RECONCILED_PUBLISH_PENDING"
    elif result.status == "succeeded":
        operation.status = result.status
        operation.error_code = None
    elif result.status == "failed":
        operation.status = "failed"
        operation.error_code = "WECHAT_RECONCILIATION_FAILED"
    else:
        operation.status = "unknown"
        operation.error_code = "WECHAT_RECONCILIATION_RESULT_UNKNOWN"
    await sync_article_operation_status(session, operation=operation)
    if job:
        job.status = operation.status
        job.stage = (
            "reconciled" if operation.status == "succeeded" else operation.status
        )
        job.progress = 100 if operation.status == "succeeded" else job.progress
        job.error_code = operation.error_code
    return operation

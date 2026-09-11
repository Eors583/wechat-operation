from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.common import audit
from app.errors import ApiError
from app.models import (
    AccountDeletionRequest,
    AIRun,
    AIRunEvent,
    Article,
    ArticleRender,
    ArticleRevision,
    ArticleVersion,
    Asset,
    AuthIdentity,
    Document,
    DocumentChunk,
    DocumentSection,
    LayoutTemplate,
    LayoutTemplateVersion,
    LibraryItem,
    Message,
    OfficialAccount,
    PreferenceProposal,
    Project,
    RefreshToken,
    Skill,
    SkillVersion,
    Task,
    TaskMemorySummary,
    User,
    UserMemoryEntry,
    UserPreference,
    UserPreferenceMemory,
    WechatAuthorizationState,
    WechatOperation,
    utcnow,
)
from app.providers import StorageProvider
from app.security import hash_password, new_opaque_token

RETENTION_DAYS = 30


async def schedule_account_deletion(
    session: AsyncSession,
    *,
    user: User,
    request_id: str | None,
) -> AccountDeletionRequest:
    existing = await session.scalar(
        select(AccountDeletionRequest).where(AccountDeletionRequest.user_id == user.id)
    )
    if existing:
        return existing
    now = utcnow()
    deletion = AccountDeletionRequest(
        user_id=user.id,
        status="scheduled",
        requested_at=now,
        purge_after=now + timedelta(days=RETENTION_DAYS),
    )
    session.add(deletion)
    await session.flush()
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    await session.execute(
        update(OfficialAccount)
        .where(OfficialAccount.owner_id == user.id, OfficialAccount.deleted_at.is_(None))
        .values(status="disconnected", token_secret_ref=None, token_expires_at=None)
    )
    user.status = "pending"
    user.deleted_at = now
    audit(
        session,
        actor_type="user",
        actor_id=user.id,
        action="account.deletion.schedule",
        target_type="user",
        target_id=user.id,
        request_id=request_id,
        details={
            "deletion_request_id": deletion.id,
            "purge_after": deletion.purge_after.isoformat(),
        },
    )
    return deletion


async def purge_account(
    session: AsyncSession,
    *,
    deletion: AccountDeletionRequest,
    storage: StorageProvider,
) -> None:
    user = await session.get(User, deletion.user_id)
    if not user:
        deletion.status = "completed"
        deletion.completed_at = utcnow()
        return
    if deletion.status == "completed":
        return
    if deletion.purge_after > utcnow():
        raise ApiError(409, "ACCOUNT_DELETION_NOT_DUE", "账号数据尚未到清理时间。")

    deletion.status = "processing"
    deletion.attempts += 1
    deletion.last_error = None
    await session.flush()

    assets = list((await session.scalars(select(Asset).where(Asset.owner_id == user.id))).all())
    for asset in assets:
        await storage.delete_object(object_key=asset.object_key)

    task_ids = select(Task.id).where(Task.owner_id == user.id)
    article_ids = select(Article.id).where(Article.owner_id == user.id)
    document_ids = select(Document.id).where(Document.owner_id == user.id)
    template_ids = select(LayoutTemplate.id).where(LayoutTemplate.owner_id == user.id)
    skill_ids = select(Skill.id).where(Skill.owner_id == user.id)
    run_ids = select(AIRun.id).where(AIRun.owner_id == user.id)

    await session.execute(delete(PreferenceProposal).where(PreferenceProposal.user_id == user.id))
    await session.execute(delete(UserMemoryEntry).where(UserMemoryEntry.user_id == user.id))

    await session.execute(
        update(AuthIdentity)
        .where(AuthIdentity.user_id == user.id)
        .values(provider_subject=f"deleted:{user.id}")
    )
    await session.execute(
        update(Project)
        .where(Project.owner_id == user.id)
        .values(
            name="已删除项目",
            description=None,
            writing_requirements=None,
            deleted_at=utcnow(),
        )
    )
    await session.execute(
        update(Task)
        .where(Task.owner_id == user.id)
        .values(
            title="已删除任务",
            status="deleted",
            current_article_id=None,
            current_skill_id=None,
            deleted_at=utcnow(),
        )
    )
    await session.execute(
        update(Message)
        .where(Message.task_id.in_(task_ids))
        .values(content_json={}, plain_text="", client_message_id=None)
    )
    await session.execute(
        update(TaskMemorySummary)
        .where(TaskMemorySummary.task_id.in_(task_ids))
        .values(summary="", facts={})
    )
    await session.execute(
        update(AIRun)
        .where(AIRun.owner_id == user.id)
        .values(context_snapshot={}, error_message=None)
    )
    await session.execute(
        update(AIRunEvent).where(AIRunEvent.run_id.in_(run_ids)).values(payload={})
    )
    await session.execute(
        update(Asset)
        .where(Asset.owner_id == user.id)
        .values(filename="已删除文件", deleted_at=utcnow(), scan_status="deleted")
    )
    await session.execute(
        update(Document)
        .where(Document.owner_id == user.id)
        .values(title="已删除资料", extracted_text=None, status="deleted")
    )
    await session.execute(
        update(DocumentSection)
        .where(DocumentSection.document_id.in_(document_ids))
        .values(title=None, text=None, data={})
    )
    await session.execute(
        update(DocumentChunk)
        .where(DocumentChunk.owner_id == user.id)
        .values(text="", indexing_status="deleted")
    )
    await session.execute(
        update(LibraryItem)
        .where(LibraryItem.owner_id == user.id)
        .values(
            title="已删除内容",
            summary=None,
            search_text="",
            display_status="deleted",
            deleted_at=utcnow(),
        )
    )
    await session.execute(
        update(Article)
        .where(Article.owner_id == user.id)
        .values(title="已删除文章", summary=None, status="deleted", deleted_at=utcnow())
    )
    await session.execute(
        update(ArticleVersion)
        .where(ArticleVersion.article_id.in_(article_ids))
        .values(content_json={"type": "doc", "content": []}, plain_text="", content_hash="deleted")
    )
    await session.execute(
        update(ArticleRevision)
        .where(ArticleRevision.owner_id == user.id)
        .values(selected_text="", instruction="", replacement_text=None, error_message=None)
    )
    await session.execute(
        update(LayoutTemplate)
        .where(LayoutTemplate.owner_id == user.id)
        .values(
            name="已删除模板",
            source_url=None,
            enabled=False,
            extraction_status="deleted",
            deleted_at=utcnow(),
        )
    )
    await session.execute(
        update(LayoutTemplateVersion)
        .where(LayoutTemplateVersion.template_id.in_(template_ids))
        .values(style_tokens={}, source_snapshot={})
    )
    await session.execute(
        update(ArticleRender)
        .where(ArticleRender.owner_id == user.id)
        .values(html="", structure={}, html_object_key=None)
    )
    accounts = list(
        (
            await session.scalars(
                select(OfficialAccount).where(OfficialAccount.owner_id == user.id)
            )
        ).all()
    )
    for account in accounts:
        account.authorizer_appid = f"deleted:{account.id}"
        account.name = "已断开公众号"
        account.avatar_url = None
        account.status = "deleted"
        account.capability_flags = []
        account.token_secret_ref = None
        account.technical_metadata = {}
        account.deleted_at = utcnow()
    await session.execute(
        update(WechatAuthorizationState)
        .where(WechatAuthorizationState.owner_id == user.id)
        .values(redirect_uri="https://invalid.local/deleted", consumed_at=utcnow())
    )
    await session.execute(
        update(WechatOperation).where(WechatOperation.owner_id == user.id).values(result={})
    )
    await session.execute(
        update(Skill)
        .where(Skill.owner_id == user.id)
        .values(name="已删除技能", description="", status="deleted", deleted_at=utcnow())
    )
    await session.execute(
        update(SkillVersion)
        .where(SkillVersion.skill_id.in_(skill_ids))
        .values(instructions="", input_schema={}, output_schema={}, tool_policy={})
    )
    await session.execute(
        update(UserPreference)
        .where(UserPreference.user_id == user.id)
        .values(value="", status="revoked", revoked_at=utcnow())
    )
    await session.execute(
        update(UserPreferenceMemory).where(UserPreferenceMemory.user_id == user.id).values(items=[])
    )
    user.email = None
    user.phone = None
    user.display_name = "已注销用户"
    user.password_hash = hash_password(new_opaque_token())
    user.status = "disabled"
    user.theme_preference = "system"
    deletion.status = "completed"
    deletion.completed_at = utcnow()
    audit(
        session,
        actor_type="system",
        actor_id="account-purge",
        action="account.deletion.complete",
        target_type="user",
        target_id=user.id,
        request_id=None,
        details={"deletion_request_id": deletion.id},
    )

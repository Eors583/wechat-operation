from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select, text

from app.celery_app import celery
from app.config import Settings
from app.database import Database
from app.dependencies import _wechat_article_api_configs
from app.domains.account_deletion import purge_account
from app.domains.ai import (
    fail_ai_run,
    persist_live_run_event,
    prepare_ai_run,
    process_ai_run,
    process_ai_run_memory,
)
from app.domains.common import emit_outbox, processed_inbox_message, remember_inbox_message
from app.domains.external_knowledge import enqueue_due_lexiang_syncs, sync_lexiang_source
from app.domains.files import process_document
from app.domains.layout import process_layout_extraction
from app.domains.quota import apply_quota_change
from app.domains.revision import process_article_revision
from app.domains.user_preference_memory import summarize_preferences
from app.domains.wechat import process_wechat_operation, reconcile_wechat_operation
from app.external_knowledge import LexiangKnowledgeProvider
from app.model_gateway import ModelRouteExhausted
from app.models import (
    AccountDeletionRequest,
    AIRun,
    Article,
    ArticleRevision,
    ArticleVersion,
    Asset,
    Document,
    DocumentChunk,
    ExternalKnowledgeSource,
    JobRecord,
    LayoutTemplate,
    LibraryItem,
    OfficialAccount,
    OutboxEvent,
    utcnow,
)
from app.provider_factory import build_providers
from app.providers import EnvironmentSecretProvider, ProviderUnavailable
from app.retrieval_routing import build_route_aware_retrieval_service
from app.web_references import SafeHttpWebReferenceProvider
from app.wechat_open_platform import WechatOpenPlatformClient, ensure_authorizer_access_token


def _run(coroutine: Any) -> Any:
    return asyncio.run(coroutine)


def _configured_secrets(config: Settings) -> EnvironmentSecretProvider:
    return EnvironmentSecretProvider(config.model_secret_master_key or config.token_secret)


@celery.task(name="app.worker_tasks.process_ai_run_task")
def process_ai_run_task(run_id: str, message_id: str | None = None) -> dict[str, Any]:
    return _run(_process_ai(run_id, message_id))


async def _process_ai(run_id: str, message_id: str | None = None) -> dict[str, Any]:
    config = Settings.from_env()
    database = Database(config)
    secrets = _configured_secrets(config)
    providers = build_providers(config, secrets)
    try:
        async with database.session_maker() as session:
            consumer = "process_ai_run"
            processed = await processed_inbox_message(
                session, consumer=consumer, message_id=message_id
            )
            if processed:
                return processed.result
            try:

                async def live_event(event_type: str, payload: dict[str, Any]) -> None:
                    await persist_live_run_event(
                        database.session_maker,
                        run_id=run_id,
                        event_type=event_type,
                        payload=payload,
                    )

                if session.get_bind().dialect.name == "postgresql":
                    await session.execute(
                        text("SELECT pg_advisory_xact_lock(hashtext(:run_id))"),
                        {"run_id": run_id},
                    )
                pending = await session.get(AIRun, run_id, populate_existing=True)
                if pending and pending.status not in {"completed", "failed", "cancelled"}:
                    if pending.context_snapshot.get("preparation_pending"):
                        await live_event("stage.changed", {"stage": "retrieving"})
                    retrieval = build_route_aware_retrieval_service(
                        database=database,
                        settings=config,
                        secrets=secrets,
                        embedding=providers.embedding,
                        rerank=providers.rerank,
                    )
                    web_references = providers.web_reference
                    if (
                        isinstance(web_references, SafeHttpWebReferenceProvider)
                        and web_references._transport is None
                    ):
                        web_references = SafeHttpWebReferenceProvider(
                            article_apis=await _wechat_article_api_configs(session, secrets)
                        )
                    await prepare_ai_run(
                        session,
                        run=pending,
                        settings=config,
                        retrieval=retrieval,
                        secrets=secrets,
                        web_references=web_references,
                        storage=providers.storage,
                        model=providers.model,
                    )
                    await session.commit()
                run = await process_ai_run(
                    session,
                    run_id=run_id,
                    model=providers.model,
                    safety=providers.content_safety,
                    secrets=secrets,
                    model_timeout_seconds=config.model_timeout_seconds,
                    live_event_sink=live_event,
                )
                result: dict[str, Any] = {"run_id": run.id, "status": run.status}
            except Exception as exc:
                await session.rollback()
                failed_run = await fail_ai_run(session, run_id=run_id, error=exc)
                result = {
                    "run_id": failed_run.id,
                    "status": failed_run.status,
                    "error_code": failed_run.error_code,
                }
            remember_inbox_message(session, consumer=consumer, message_id=message_id, result=result)
            await session.commit()
            return result
    finally:
        await database.dispose()


@celery.task(name="app.worker_tasks.process_ai_run_memory_task")
def process_ai_run_memory_task(run_id: str, message_id: str | None = None) -> dict[str, Any]:
    return _run(_process_ai_memory(run_id, message_id))


async def _process_ai_memory(run_id: str, message_id: str | None = None) -> dict[str, Any]:
    config = Settings.from_env()
    database = Database(config)
    secrets = _configured_secrets(config)
    providers = build_providers(config, secrets)
    try:
        async with database.session_maker() as session:
            consumer = "process_ai_run_memory"
            processed = await processed_inbox_message(
                session, consumer=consumer, message_id=message_id
            )
            if processed:
                return processed.result
            summary = await process_ai_run_memory(
                session,
                run_id=run_id,
                model=providers.model,
                secrets=secrets,
                model_timeout_seconds=config.model_timeout_seconds,
            )
            result = {
                "run_id": run_id,
                "status": "updated" if summary else "skipped",
            }
            remember_inbox_message(session, consumer=consumer, message_id=message_id, result=result)
            await session.commit()
            return result
    finally:
        await database.dispose()


@celery.task(
    name="app.worker_tasks.process_user_preferences_task",
    autoretry_for=(ProviderUnavailable, ModelRouteExhausted),
    retry_backoff=True,
    max_retries=3,
)
def process_user_preferences_task(task_id: str, message_id: str) -> dict[str, Any]:
    return _run(_process_user_preferences(task_id, message_id))


async def _process_user_preferences(task_id: str, message_id: str) -> dict[str, Any]:
    config = Settings.from_env()
    database = Database(config)
    secrets = _configured_secrets(config)
    providers = build_providers(config, secrets)
    try:
        async with database.session_maker() as session:
            event = await session.scalar(
                select(OutboxEvent).where(OutboxEvent.id == message_id).with_for_update()
            )
            if (
                not event
                or event.event_type != "user.preferences.summarize"
                or event.payload.get("task_id") != task_id
            ):
                return {"status": "skipped"}
            consumer = "process_user_preferences"
            processed = await processed_inbox_message(
                session, consumer=consumer, message_id=message_id
            )
            if processed:
                return processed.result
            await summarize_preferences(
                session, event=event, model=providers.model, secrets=secrets, settings=config
            )
            result = {"status": "completed"}
            remember_inbox_message(session, consumer=consumer, message_id=message_id, result=result)
            await session.commit()
            return result
    finally:
        await database.dispose()


@celery.task(name="app.worker_tasks.process_article_revision_task")
def process_article_revision_task(
    revision_id: str, message_id: str | None = None
) -> dict[str, Any]:
    return _run(_process_article_revision(revision_id, message_id))


async def _process_article_revision(
    revision_id: str, message_id: str | None = None
) -> dict[str, Any]:
    config = Settings.from_env()
    database = Database(config)
    secrets = _configured_secrets(config)
    providers = build_providers(config, secrets)
    try:
        async with database.session_maker() as session:
            consumer = "process_article_revision"
            processed = await processed_inbox_message(
                session, consumer=consumer, message_id=message_id
            )
            if processed:
                return processed.result
            try:
                revision = await process_article_revision(
                    session,
                    revision_id=revision_id,
                    model=providers.model,
                    safety=providers.content_safety,
                    secrets=secrets,
                    model_timeout_seconds=config.model_timeout_seconds,
                )
                result: dict[str, Any] = {
                    "revision_id": revision.id,
                    "status": revision.status,
                }
            except Exception as exc:
                await session.rollback()
                failed_revision = await session.scalar(
                    select(ArticleRevision)
                    .where(ArticleRevision.id == revision_id)
                    .with_for_update()
                )
                if not failed_revision:
                    raise
                if failed_revision.status not in {"completed", "failed", "cancelled"}:
                    failed_revision.status = "failed"
                    failed_revision.error_code = type(exc).__name__[:80]
                    failed_revision.error_message = str(exc)[:1000]
                    failed_revision.completed_at = utcnow()
                    if failed_revision.quota_reserved:
                        await apply_quota_change(
                            session,
                            user_id=failed_revision.owner_id,
                            direction="credit",
                            amount=failed_revision.quota_reserved,
                            reason="文章局部修改失败释放",
                            business_type="article_revision_release",
                            business_id=failed_revision.id,
                        )
                        failed_revision.quota_reserved = 0
                    job = await session.scalar(
                        select(JobRecord).where(
                            JobRecord.resource_type == "article_revision",
                            JobRecord.resource_id == failed_revision.id,
                        )
                    )
                    if job:
                        job.status = "failed"
                        job.stage = "failed"
                        job.error_code = failed_revision.error_code
                        job.error_message = failed_revision.error_message
                result = {
                    "revision_id": failed_revision.id,
                    "status": failed_revision.status,
                    "error_code": failed_revision.error_code,
                }
            remember_inbox_message(session, consumer=consumer, message_id=message_id, result=result)
            await session.commit()
            return result
    finally:
        await database.dispose()


@celery.task(name="app.worker_tasks.process_wechat_operation_task")
def process_wechat_operation_task(
    operation_id: str, message_id: str | None = None
) -> dict[str, Any]:
    return _run(_process_wechat(operation_id, message_id))


async def _process_wechat(operation_id: str, message_id: str | None = None) -> dict[str, Any]:
    config = Settings.from_env()
    database = Database(config)
    secrets = _configured_secrets(config)
    providers = build_providers(config, secrets)
    try:
        async with database.session_maker() as session:
            consumer = "process_wechat_operation"
            processed = await processed_inbox_message(
                session, consumer=consumer, message_id=message_id
            )
            if processed:
                return processed.result

            async def ensure_account_token(
                account: OfficialAccount, force: bool = False
            ) -> OfficialAccount:
                return await ensure_authorizer_access_token(
                    session,
                    account_id=account.id,
                    environment=config.environment,
                    secrets=secrets,
                    client=WechatOpenPlatformClient(),
                    force=force,
                )

            operation = await process_wechat_operation(
                session,
                operation_id=operation_id,
                provider=providers.wechat,
                storage=providers.storage,
                ensure_account_token=(
                    ensure_account_token if config.wechat_provider_mode == "direct" else None
                ),
            )
            result = {"operation_id": operation.id, "status": operation.status}
            remember_inbox_message(session, consumer=consumer, message_id=message_id, result=result)
            await session.commit()
            return result
    finally:
        await database.dispose()


@celery.task(name="app.worker_tasks.reconcile_wechat_operation_task")
def reconcile_wechat_operation_task(
    operation_id: str, message_id: str | None = None
) -> dict[str, Any]:
    return _run(_reconcile_wechat(operation_id, message_id))


async def _reconcile_wechat(operation_id: str, message_id: str | None = None) -> dict[str, Any]:
    config = Settings.from_env()
    database = Database(config)
    secrets = _configured_secrets(config)
    provider = build_providers(config, secrets).wechat
    try:
        async with database.session_maker() as session:
            consumer = "reconcile_wechat_operation"
            processed = await processed_inbox_message(
                session, consumer=consumer, message_id=message_id
            )
            if processed:
                return processed.result

            async def ensure_account_token(
                account: OfficialAccount, force: bool = False
            ) -> OfficialAccount:
                return await ensure_authorizer_access_token(
                    session,
                    account_id=account.id,
                    environment=config.environment,
                    secrets=secrets,
                    client=WechatOpenPlatformClient(),
                    force=force,
                )

            operation = await reconcile_wechat_operation(
                session,
                operation_id=operation_id,
                provider=provider,
                ensure_account_token=(
                    ensure_account_token if config.wechat_provider_mode == "direct" else None
                ),
            )
            result = {"operation_id": operation.id, "status": operation.status}
            remember_inbox_message(session, consumer=consumer, message_id=message_id, result=result)
            await session.commit()
            return result
    finally:
        await database.dispose()


@celery.task(name="app.worker_tasks.process_document_task")
def process_document_task(document_id: str, message_id: str | None = None) -> dict[str, Any]:
    return _run(_process_document(document_id, message_id))


async def _process_document(document_id: str, message_id: str | None = None) -> dict[str, Any]:
    config = Settings.from_env()
    database = Database(config)
    processor = build_providers(config).document_processing
    try:
        async with database.session_maker() as session:
            consumer = "process_document"
            processed = await processed_inbox_message(
                session, consumer=consumer, message_id=message_id
            )
            if processed:
                return processed.result
            document = await session.scalar(
                select(Document).where(Document.id == document_id).with_for_update()
            )
            if not document:
                result = {"document_id": document_id, "status": "missing"}
                remember_inbox_message(
                    session, consumer=consumer, message_id=message_id, result=result
                )
                await session.commit()
                return result
            try:
                document = await process_document(
                    session,
                    owner_id=document.owner_id,
                    document_id=document.id,
                    processor=processor,
                    chunk_target_characters=config.chunk_target_characters,
                    chunk_overlap_characters=config.chunk_overlap_characters,
                    chunking_version=config.chunking_version,
                    retrieval_required=bool(config.retrieval_database_url),
                )
                if config.retrieval_database_url:
                    emit_outbox(
                        session,
                        event_type="document.index.requested",
                        aggregate_type="document",
                        aggregate_id=document.id,
                        payload={"document_id": document.id},
                    )
            except ProviderUnavailable:
                asset = await session.get(Asset, document.asset_id)
                document.status = "blocked_external"
                document.error_code = "DOCUMENT_INDEX_PROVIDER_UNAVAILABLE"
                if asset:
                    asset.scan_status = "blocked_external"
                library_item = await session.scalar(
                    select(LibraryItem).where(
                        LibraryItem.item_type == "document",
                        LibraryItem.source_id == document.id,
                    )
                )
                if library_item:
                    library_item.display_status = "failed"
                job = await session.scalar(
                    select(JobRecord).where(
                        JobRecord.resource_type == "document",
                        JobRecord.resource_id == document.id,
                    )
                )
                if job:
                    job.status = "failed"
                    job.stage = "provider_required"
                    job.error_code = "DOCUMENT_INDEX_PROVIDER_UNAVAILABLE"
                    job.error_message = "Document processing or retrieval indexing failed."
            result = {"document_id": document.id, "status": document.status}
            remember_inbox_message(session, consumer=consumer, message_id=message_id, result=result)
            await session.commit()
            return result
    finally:
        await database.dispose()


@celery.task(name="app.worker_tasks.process_document_index_task")
def process_document_index_task(document_id: str, message_id: str | None = None) -> dict[str, Any]:
    return _run(_process_document_index(document_id, message_id))


async def _process_document_index(
    document_id: str, message_id: str | None = None
) -> dict[str, Any]:
    config = Settings.from_env()
    database = Database(config)
    secrets = _configured_secrets(config)
    providers = build_providers(config, secrets)
    retrieval = build_route_aware_retrieval_service(
        database=database,
        settings=config,
        secrets=secrets,
        embedding=providers.embedding,
        rerank=providers.rerank,
    )
    try:
        async with database.session_maker() as session:
            consumer = "process_document_index"
            processed = await processed_inbox_message(
                session, consumer=consumer, message_id=message_id
            )
            if processed:
                return processed.result
            document = await session.scalar(
                select(Document).where(Document.id == document_id).with_for_update()
            )
            if not document:
                result = {"document_id": document_id, "status": "missing"}
            else:
                chunks = list(
                    (
                        await session.scalars(
                            select(DocumentChunk)
                            .where(DocumentChunk.document_id == document.id)
                            .order_by(DocumentChunk.chunk_no)
                        )
                    ).all()
                )
                try:
                    embedding_model = await retrieval.index_document(
                        document=document, chunks=chunks
                    )
                    for chunk in chunks:
                        chunk.indexing_status = "indexed"
                        chunk.embedding_model = embedding_model
                    document.status = "completed"
                    document.error_code = None
                    library_item = await session.scalar(
                        select(LibraryItem).where(
                            LibraryItem.item_type == "document",
                            LibraryItem.source_id == document.id,
                        )
                    )
                    if library_item:
                        library_item.display_status = "ready"
                    job = await session.scalar(
                        select(JobRecord).where(
                            JobRecord.resource_type == "document",
                            JobRecord.resource_id == document.id,
                        )
                    )
                    if job:
                        job.status = "completed"
                        job.stage = "indexed"
                        job.progress = 100
                        job.error_code = None
                        job.error_message = None
                except ProviderUnavailable:
                    document.status = "blocked_external"
                    document.error_code = "RETRIEVAL_INDEX_PROVIDER_UNAVAILABLE"
                    job = await session.scalar(
                        select(JobRecord).where(
                            JobRecord.resource_type == "document",
                            JobRecord.resource_id == document.id,
                        )
                    )
                    if job:
                        job.status = "failed"
                        job.stage = "embedding_provider_required"
                        job.error_code = document.error_code
                result = {"document_id": document.id, "status": document.status}
            remember_inbox_message(session, consumer=consumer, message_id=message_id, result=result)
            await session.commit()
            return result
    finally:
        await retrieval.backend.dispose()
        await database.dispose()


@celery.task(name="app.worker_tasks.process_layout_extraction_task")
def process_layout_extraction_task(
    template_id: str, message_id: str | None = None
) -> dict[str, Any]:
    return _run(_process_layout_extraction(template_id, message_id))


async def _process_layout_extraction(
    template_id: str, message_id: str | None = None
) -> dict[str, Any]:
    config = Settings.from_env()
    database = Database(config)
    secrets = _configured_secrets(config)
    providers = build_providers(config, secrets)
    try:
        async with database.session_maker() as session:
            consumer = "process_layout_extraction"
            processed = await processed_inbox_message(
                session, consumer=consumer, message_id=message_id
            )
            if processed:
                return processed.result
            template = await session.scalar(
                select(LayoutTemplate).where(LayoutTemplate.id == template_id).with_for_update()
            )
            if not template:
                result = {"template_id": template_id, "status": "missing"}
                remember_inbox_message(
                    session, consumer=consumer, message_id=message_id, result=result
                )
                await session.commit()
                return result
            try:
                job = await session.scalar(
                    select(JobRecord)
                    .where(
                        JobRecord.resource_type == "layout_template",
                        JobRecord.resource_id == template.id,
                    )
                    .order_by(JobRecord.created_at.desc())
                    .limit(1)
                )
                route_snapshot = (
                    job.frozen_payload.get("model_route", {})
                    if job and isinstance(job.frozen_payload, dict)
                    else {}
                )
                template = await process_layout_extraction(
                    session,
                    template_id=template.id,
                    provider=providers.layout_extraction,
                    route_snapshot=(route_snapshot if isinstance(route_snapshot, dict) else {}),
                    model=providers.model,
                    secrets=secrets,
                    settings=config,
                )
            except ProviderUnavailable as exc:
                template.extraction_status = "failed"
                job = await session.scalar(
                    select(JobRecord).where(
                        JobRecord.resource_type == "layout_template",
                        JobRecord.resource_id == template.id,
                        JobRecord.status == "queued",
                    )
                )
                if job:
                    job.status = "failed"
                    job.stage = "provider_required"
                    job.error_code = "LAYOUT_PROVIDER_FAILED"
                    job.error_message = str(exc)
            result = {"template_id": template.id, "status": template.extraction_status}
            remember_inbox_message(session, consumer=consumer, message_id=message_id, result=result)
            await session.commit()
            return result
    finally:
        await database.dispose()


@celery.task(name="app.worker_tasks.process_article_index_task")
def process_article_index_task(article_id: str, message_id: str | None = None) -> dict[str, Any]:
    return _run(_process_article_index(article_id, message_id))


async def _process_article_index(article_id: str, message_id: str | None = None) -> dict[str, Any]:
    config = Settings.from_env()
    database = Database(config)
    secrets = _configured_secrets(config)
    providers = build_providers(config, secrets)
    retrieval = build_route_aware_retrieval_service(
        database=database,
        settings=config,
        secrets=secrets,
        embedding=providers.embedding,
        rerank=providers.rerank,
    )
    try:
        async with database.session_maker() as session:
            consumer = "process_article_index"
            processed = await processed_inbox_message(
                session, consumer=consumer, message_id=message_id
            )
            if processed:
                return processed.result
            article = await session.scalar(
                select(Article).where(Article.id == article_id).with_for_update()
            )
            result: dict[str, Any]
            if not article or article.deleted_at:
                result = {"article_id": article_id, "status": "missing"}
            else:
                version = await session.scalar(
                    select(ArticleVersion).where(
                        ArticleVersion.article_id == article.id,
                        ArticleVersion.version_no == article.current_version_no,
                    )
                )
                if not version:
                    result = {"article_id": article.id, "status": "missing_version"}
                else:
                    try:
                        embedding_model = await retrieval.index_article(
                            article=article,
                            version=version,
                            target_characters=config.chunk_target_characters,
                            overlap_characters=config.chunk_overlap_characters,
                            chunking_version=config.chunking_version,
                        )
                        result = {
                            "article_id": article.id,
                            "version_id": version.id,
                            "status": "indexed" if embedding_model else "index_disabled",
                            "embedding_model": embedding_model,
                        }
                        job_status = "completed"
                        job_error = None
                    except ProviderUnavailable:
                        result = {
                            "article_id": article.id,
                            "version_id": version.id,
                            "status": "blocked_external",
                            "error_code": "RETRIEVAL_INDEX_PROVIDER_UNAVAILABLE",
                        }
                        job_status = "failed"
                        job_error = result["error_code"]
                    job = await session.scalar(
                        select(JobRecord)
                        .where(
                            JobRecord.resource_type == "article",
                            JobRecord.resource_id == article.id,
                            JobRecord.status.in_(["queued", "processing"]),
                        )
                        .order_by(JobRecord.created_at.desc())
                    )
                    if job:
                        job.status = job_status
                        job.stage = result["status"]
                        job.progress = 100
                        job.error_code = job_error
                        job.error_message = (
                            "Article retrieval indexing provider is unavailable."
                            if job_error
                            else None
                        )
            remember_inbox_message(session, consumer=consumer, message_id=message_id, result=result)
            await session.commit()
            return result
    finally:
        await retrieval.backend.dispose()
        await database.dispose()


@celery.task(name="app.worker_tasks.process_external_knowledge_sync_task")
def process_external_knowledge_sync_task(
    source_id: str, message_id: str | None = None
) -> dict[str, Any]:
    return _run(_process_external_knowledge_sync(source_id, message_id))


async def _process_external_knowledge_sync(
    source_id: str, message_id: str | None = None
) -> dict[str, Any]:
    config = Settings.from_env()
    database = Database(config)
    secret_store = _configured_secrets(config)
    try:
        async with database.session_maker() as session:
            consumer = "process_external_knowledge_sync"
            processed = await processed_inbox_message(
                session, consumer=consumer, message_id=message_id
            )
            if processed:
                return processed.result
            source = await session.scalar(
                select(ExternalKnowledgeSource)
                .where(ExternalKnowledgeSource.id == source_id)
                .with_for_update()
            )
            if not source or source.source_type != "lexiang":
                result: dict[str, Any] = {"source_id": source_id, "status": "missing"}
            elif source.status != "active" or not source.secret_ref:
                result = {"source_id": source.id, "status": "disabled"}
            else:
                try:
                    app_key = str(source.configuration.get("app_key", ""))
                    provider = LexiangKnowledgeProvider(
                        app_key=app_key,
                        app_secret=secret_store.resolve(source.secret_ref),
                    )
                    result = await sync_lexiang_source(
                        session,
                        source=source,
                        provider=provider,
                        chunk_target_characters=config.chunk_target_characters,
                        chunk_overlap_characters=config.chunk_overlap_characters,
                        chunking_version=config.chunking_version,
                        retrieval_required=bool(config.retrieval_database_url),
                    )
                except (ProviderUnavailable, ValueError):
                    source.error_code = "LEXIANG_SYNC_PROVIDER_UNAVAILABLE"
                    result = {
                        "source_id": source.id,
                        "status": "blocked_external",
                        "error_code": source.error_code,
                    }
                    job = await session.scalar(
                        select(JobRecord)
                        .where(
                            JobRecord.resource_type == "external_knowledge_source",
                            JobRecord.resource_id == source.id,
                            JobRecord.status.in_(["queued", "processing"]),
                        )
                        .order_by(JobRecord.created_at.desc())
                    )
                    if job:
                        job.status = "failed"
                        job.stage = "provider_unavailable"
                        job.progress = 100
                        job.error_code = source.error_code
                        job.error_message = "Lexiang synchronization provider is unavailable."
            remember_inbox_message(session, consumer=consumer, message_id=message_id, result=result)
            await session.commit()
            return result
    finally:
        await database.dispose()


@celery.task(name="app.worker_tasks.enqueue_due_external_knowledge_syncs_task")
def enqueue_due_external_knowledge_syncs_task() -> dict[str, Any]:
    return _run(_enqueue_due_external_knowledge_syncs())


async def _enqueue_due_external_knowledge_syncs() -> dict[str, Any]:
    config = Settings.from_env()
    database = Database(config)
    enqueued = 0
    acquired = True
    try:
        async with database.session_maker() as session:
            connection = await session.connection()
            if connection.dialect.name == "postgresql":
                acquired = bool(
                    await session.scalar(
                        text("SELECT pg_try_advisory_xact_lock(:lock_key)"),
                        {"lock_key": 8_218_954_013},
                    )
                )
            if acquired:
                enqueued = await enqueue_due_lexiang_syncs(
                    session,
                    interval_seconds=config.external_knowledge_sync_interval_seconds,
                )
            await session.commit()
    finally:
        await database.dispose()
    return {"acquired": acquired, "enqueued": enqueued}


EVENT_TASKS: dict[str, tuple[str, str]] = {
    "user.preferences.summarize": ("app.worker_tasks.process_user_preferences_task", "task_id"),
    "ai.run.requested": ("app.worker_tasks.process_ai_run_task", "run_id"),
    "ai.run.memory.requested": ("app.worker_tasks.process_ai_run_memory_task", "run_id"),
    "article.revision.requested": (
        "app.worker_tasks.process_article_revision_task",
        "revision_id",
    ),
    "document.processing.requested": ("app.worker_tasks.process_document_task", "document_id"),
    "document.index.requested": (
        "app.worker_tasks.process_document_index_task",
        "document_id",
    ),
    "layout.extraction.requested": (
        "app.worker_tasks.process_layout_extraction_task",
        "template_id",
    ),
    "article.index.requested": ("app.worker_tasks.process_article_index_task", "article_id"),
    "external_knowledge.sync.requested": (
        "app.worker_tasks.process_external_knowledge_sync_task",
        "source_id",
    ),
    "wechat.draft.requested": (
        "app.worker_tasks.process_wechat_operation_task",
        "operation_id",
    ),
    "wechat.publish.requested": (
        "app.worker_tasks.process_wechat_operation_task",
        "operation_id",
    ),
    "wechat.operation.reconcile.requested": (
        "app.worker_tasks.reconcile_wechat_operation_task",
        "operation_id",
    ),
}


@celery.task(name="app.worker_tasks.relay_outbox_task")
def relay_outbox_task() -> dict[str, Any]:
    return _run(_relay_outbox())


async def _relay_outbox() -> dict[str, Any]:
    config = Settings.from_env()
    database = Database(config)
    published = 0
    try:
        async with database.session_maker() as session:
            events = list(
                (
                    await session.scalars(
                        select(OutboxEvent)
                        .where(
                            OutboxEvent.status == "pending",
                            OutboxEvent.available_at <= utcnow(),
                        )
                        .order_by(OutboxEvent.created_at)
                        .limit(100)
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            for event in events:
                mapping = EVENT_TASKS.get(event.event_type)
                if not mapping:
                    event.status = "ignored"
                    event.last_error = "No worker route is registered for this event type"
                    continue
                task_name, payload_key = mapping
                celery.send_task(
                    task_name,
                    args=[event.payload[payload_key], event.id],
                    task_id=event.id,
                )
                event.status = "published"
                event.published_at = utcnow()
                event.attempts += 1
                published += 1
            await session.commit()
    finally:
        await database.dispose()
    return {"published": published}


@celery.task(name="app.worker_tasks.purge_due_accounts_task")
def purge_due_accounts_task() -> dict[str, Any]:
    return _run(_purge_due_accounts())


async def _purge_due_accounts() -> dict[str, Any]:
    config = Settings.from_env()
    database = Database(config)
    secrets = _configured_secrets(config)
    providers = build_providers(config, secrets)
    storage = providers.storage
    retrieval = build_route_aware_retrieval_service(
        database=database,
        settings=config,
        secrets=secrets,
        embedding=providers.embedding,
        rerank=providers.rerank,
    )
    completed = 0
    failed = 0
    try:
        async with database.session_maker() as session:
            request_ids = list(
                (
                    await session.scalars(
                        select(AccountDeletionRequest.id)
                        .where(
                            AccountDeletionRequest.status.in_(("scheduled", "failed")),
                            AccountDeletionRequest.purge_after <= utcnow(),
                        )
                        .order_by(AccountDeletionRequest.purge_after)
                        .limit(50)
                    )
                ).all()
            )
        for request_id in request_ids:
            async with database.session_maker() as session:
                deletion = await session.scalar(
                    select(AccountDeletionRequest)
                    .where(AccountDeletionRequest.id == request_id)
                    .with_for_update()
                )
                if not deletion or deletion.status == "completed":
                    continue
                try:
                    owner_id = deletion.user_id
                    await purge_account(session, deletion=deletion, storage=storage)
                    await retrieval.backend.delete_owner(owner_id)
                    await session.commit()
                    completed += 1
                except Exception as exc:
                    await session.rollback()
                    failed_deletion = await session.get(AccountDeletionRequest, request_id)
                    if failed_deletion:
                        failed_deletion.status = "failed"
                        failed_deletion.attempts += 1
                        failed_deletion.last_error = str(exc)[:1000]
                        await session.commit()
                    failed += 1
    finally:
        await retrieval.backend.dispose()
        await database.dispose()
    return {"completed": completed, "failed": failed}

from __future__ import annotations

import hashlib
from collections import deque
from datetime import timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.external_knowledge import LexiangEntry, LexiangKnowledgeProvider
from app.models import (
    Asset,
    Document,
    ExternalKnowledgeMapping,
    ExternalKnowledgeSource,
    JobRecord,
    LibraryItem,
    utcnow,
)
from app.providers import DocumentProcessingResult, DocumentSectionResult, ProviderUnavailable

from .common import create_job, emit_outbox
from .files import persist_document_processing_result


async def enqueue_due_lexiang_syncs(
    session: AsyncSession,
    *,
    interval_seconds: int,
    limit: int = 50,
) -> int:
    """Create one durable sync request for each due active source.

    The scheduler invokes this inside one transaction. Existing queued or processing jobs
    suppress another request, so a slow provider does not cause an unbounded queue backlog.
    """
    cutoff = utcnow() - timedelta(seconds=interval_seconds)
    active_source_ids = set(
        (
            await session.scalars(
                select(JobRecord.resource_id).where(
                    JobRecord.job_type == "external_knowledge_sync",
                    JobRecord.status.in_(("queued", "processing")),
                )
            )
        ).all()
    )
    sources = list(
        (
            await session.scalars(
                select(ExternalKnowledgeSource)
                .where(
                    ExternalKnowledgeSource.source_type == "lexiang",
                    ExternalKnowledgeSource.status == "active",
                    or_(
                        ExternalKnowledgeSource.last_synced_at.is_(None),
                        ExternalKnowledgeSource.last_synced_at <= cutoff,
                    ),
                )
                .order_by(ExternalKnowledgeSource.last_synced_at, ExternalKnowledgeSource.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    enqueued = 0
    for source in sources:
        if source.id in active_source_ids:
            continue
        owner_id = source.scope.get("sync_owner_id")
        create_job(
            session,
            owner_id=owner_id if isinstance(owner_id, str) else None,
            job_type="external_knowledge_sync",
            resource_type="external_knowledge_source",
            resource_id=source.id,
            queue="sync",
            stage="queued",
            frozen_payload={"source_id": source.id, "trigger": "scheduled"},
        )
        emit_outbox(
            session,
            event_type="external_knowledge.sync.requested",
            aggregate_type="external_knowledge_source",
            aggregate_id=source.id,
            payload={"source_id": source.id},
        )
        active_source_ids.add(source.id)
        enqueued += 1
    await session.flush()
    return enqueued


async def sync_lexiang_source(
    session: AsyncSession,
    *,
    source: ExternalKnowledgeSource,
    provider: LexiangKnowledgeProvider,
    chunk_target_characters: int,
    chunk_overlap_characters: int,
    chunking_version: str,
    retrieval_required: bool,
    max_nodes: int = 1000,
) -> dict[str, Any]:
    owner_id = source.scope.get("sync_owner_id")
    if not isinstance(owner_id, str):
        raise ValueError("Lexiang source requires a sync_owner_id")
    targets = source.scope.get("targets", [])
    space_ids = [
        str(target["id"])
        for target in targets
        if isinstance(target, dict)
        and target.get("type") == "space"
        and isinstance(target.get("id"), str)
    ]
    if not space_ids:
        raise ValueError("Lexiang synchronization requires at least one space target")

    pending: deque[tuple[str, str | None]] = deque((space_id, None) for space_id in space_ids)
    discovered: list[LexiangEntry] = []
    while pending and len(discovered) < max_nodes:
        space_id, parent_id = pending.popleft()
        page_token: str | None = None
        while len(discovered) < max_nodes:
            page = await provider.list_entries(
                space_id=space_id,
                parent_id=parent_id,
                page_token=page_token,
            )
            for entry in page.entries:
                discovered.append(entry)
                if entry.has_children or entry.entry_type == "folder":
                    pending.append((space_id, entry.id))
                if len(discovered) >= max_nodes:
                    break
            page_token = page.next_page_token
            if not page_token:
                break

    synced = 0
    unchanged = 0
    remote_only = 0
    failed = 0
    for entry in discovered:
        mapping = await session.scalar(
            select(ExternalKnowledgeMapping).where(
                ExternalKnowledgeMapping.source_id == source.id,
                ExternalKnowledgeMapping.external_node_id == entry.id,
            )
        )
        if entry.entry_type != "page":
            if not mapping:
                mapping = ExternalKnowledgeMapping(
                    source_id=source.id,
                    external_node_id=entry.id,
                    external_version=entry.version,
                    sync_status="remote_only",
                )
                session.add(mapping)
            else:
                mapping.external_version = entry.version
                mapping.sync_status = "remote_only"
            remote_only += 1
            continue
        if (
            mapping
            and mapping.document_id
            and mapping.external_version == entry.version
            and mapping.sync_status == "synced"
        ):
            unchanged += 1
            continue
        try:
            content = await provider.page_content(entry.id)
            if not content.strip():
                raise ValueError("Lexiang page was empty")
            document = await session.get(Document, mapping.document_id) if mapping else None
            asset = await session.get(Asset, document.asset_id) if document else None
            digest = hashlib.sha256(content.encode()).hexdigest()
            if not document or not asset:
                asset = Asset(
                    owner_id=owner_id,
                    filename=f"{entry.name}.html"[:255],
                    mime_type="text/html",
                    size_bytes=len(content.encode()),
                    sha256=digest,
                    object_key=f"external/lexiang/{source.id}/{entry.id}",
                    scan_status="clean",
                )
                session.add(asset)
                await session.flush()
                document = Document(
                    owner_id=owner_id,
                    asset_id=asset.id,
                    source_type="lexiang",
                    external_source_id=entry.id,
                    title=entry.name,
                    status="indexing" if retrieval_required else "completed",
                )
                session.add(document)
                await session.flush()
                session.add(
                    LibraryItem(
                        owner_id=owner_id,
                        item_type="document",
                        source_id=document.id,
                        title=entry.name,
                        display_status="indexing" if retrieval_required else "ready",
                        search_text=entry.name,
                    )
                )
                if not mapping:
                    mapping = ExternalKnowledgeMapping(
                        source_id=source.id,
                        external_node_id=entry.id,
                        document_id=document.id,
                        sync_status="syncing",
                    )
                    session.add(mapping)
                else:
                    mapping.document_id = document.id
            asset.filename = f"{entry.name}.html"[:255]
            asset.size_bytes = len(content.encode())
            asset.sha256 = digest
            document.title = entry.name
            result = DocumentProcessingResult(
                extracted_text=content,
                parser_version="lexiang-html-v1",
                page_count=None,
                sections=(
                    DocumentSectionResult(
                        section_type="lexiang_page",
                        title=entry.name,
                        text=content,
                    ),
                ),
            )
            await persist_document_processing_result(
                session,
                owner_id=owner_id,
                document=document,
                asset=asset,
                result=result,
                chunk_target_characters=chunk_target_characters,
                chunk_overlap_characters=chunk_overlap_characters,
                chunking_version=chunking_version,
                retrieval_required=retrieval_required,
            )
            assert mapping is not None
            mapping.external_version = entry.version
            mapping.sync_status = "synced"
            if retrieval_required:
                emit_outbox(
                    session,
                    event_type="document.index.requested",
                    aggregate_type="document",
                    aggregate_id=document.id,
                    payload={"document_id": document.id},
                )
            synced += 1
        except (ProviderUnavailable, ValueError):
            failed += 1
            if mapping:
                mapping.sync_status = "failed"

    source.last_synced_at = utcnow()
    source.sync_cursor = {
        "discovered": len(discovered),
        "truncated": len(discovered) >= max_nodes,
    }
    source.error_code = "LEXIANG_SYNC_PARTIAL" if failed else None
    job = await session.scalar(
        select(JobRecord)
        .where(
            JobRecord.resource_type == "external_knowledge_source",
            JobRecord.resource_id == source.id,
            JobRecord.status.in_(["queued", "processing"]),
        )
        .order_by(JobRecord.created_at.desc())
    )
    result_summary: dict[str, Any] = {
        "source_id": source.id,
        "status": "partial" if failed else "completed",
        "discovered": len(discovered),
        "synced": synced,
        "unchanged": unchanged,
        "remote_only": remote_only,
        "failed": failed,
    }
    if job:
        job.status = "failed" if failed else "completed"
        job.stage = result_summary["status"]
        job.progress = 100
        job.error_code = source.error_code
        job.error_message = "Some Lexiang nodes could not be synchronized." if failed else None
    await session.flush()
    return result_summary

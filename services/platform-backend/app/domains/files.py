from __future__ import annotations

import math
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError
from app.models import (
    Asset,
    Document,
    DocumentChunk,
    DocumentSection,
    JobRecord,
    LibraryItem,
    ResourceLimit,
    UploadSession,
    utcnow,
)
from app.providers import (
    CompletedUploadPart,
    DocumentProcessingProvider,
    DocumentProcessingResult,
    DocumentSectionResult,
    InvalidMultipartUpload,
    ProviderResultUnknown,
    StorageProvider,
)
from app.security import request_hash
from app.text_chunking import iter_text_chunks

from .common import audit, create_job, emit_outbox

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/plain",
    "text/markdown",
    "text/csv",
    "text/html",
    "image/jpeg",
    "image/png",
    "audio/mpeg",
    "audio/mp4",
    "video/mp4",
}
PART_SIZE = 8 * 1024 * 1024


async def uploaded_library_item(
    session: AsyncSession, *, asset: Asset, document: Document
) -> LibraryItem:
    # Serialize per-owner library insertion, including concurrent distinct uploads.
    await session.scalar(
        select(ResourceLimit).where(ResourceLimit.owner_id == asset.owner_id).with_for_update()
    )
    matches = list(
        await session.scalars(
            select(LibraryItem)
            .join(Document, Document.id == LibraryItem.source_id)
            .join(Asset, Asset.id == Document.asset_id)
            .where(
                LibraryItem.owner_id == asset.owner_id,
                Document.owner_id == asset.owner_id,
                Asset.owner_id == asset.owner_id,
                LibraryItem.item_type == "document",
                LibraryItem.project_id == asset.project_id,
                LibraryItem.deleted_at.is_(None),
                Asset.deleted_at.is_(None),
                Asset.sha256 == asset.sha256,
                Asset.size_bytes == asset.size_bytes,
                Asset.mime_type == asset.mime_type,
                Document.source_type == "upload",
            )
            .order_by(LibraryItem.created_at, LibraryItem.id)
        )
    )
    if matches:
        item = next((row for row in matches if row.display_status == "ready"), matches[0])
        for duplicate in matches:
            if duplicate.id != item.id:
                duplicate.deleted_at = utcnow()
                audit(
                    session,
                    actor_type="system",
                    actor_id="upload-library-dedup",
                    action="library.document.deduplicated",
                    target_type="library_item",
                    target_id=duplicate.id,
                    request_id=None,
                    details={"retained_item_id": item.id, "source_id": duplicate.source_id},
                )
        return item
    item = LibraryItem(
        owner_id=asset.owner_id,
        item_type="document",
        source_id=document.id,
        project_id=asset.project_id,
        title=asset.filename,
        display_status="processing",
        search_text=asset.filename,
    )
    session.add(item)
    await session.flush()
    return item


async def register_upload(
    session: AsyncSession,
    *,
    owner_id: str,
    filename: str,
    mime_type: str,
    size_bytes: int,
    sha256: str,
    project_id: str | None,
    task_id: str | None,
    idempotency_key: str,
    storage: StorageProvider,
    allowed_extensions: set[str] | None = None,
    platform_max_file_bytes: int | None = None,
) -> tuple[Asset, UploadSession, list[str], bool]:
    clean_name = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if (
        not clean_name
        or len(clean_name) > 255
        or any(ord(character) < 32 for character in clean_name)
    ):
        raise ApiError(422, "FILE_NAME_INVALID", "文件名无效。")
    if mime_type not in ALLOWED_MIME_TYPES:
        raise ApiError(422, "FILE_TYPE_NOT_ALLOWED", "暂不支持这种文件格式。")
    extension = clean_name.rsplit(".", 1)[-1].lower() if "." in clean_name else ""
    if allowed_extensions is not None and extension not in allowed_extensions:
        raise ApiError(422, "FILE_TYPE_NOT_ALLOWED", "当前系统设置不允许这种文件格式。")
    if len(sha256) != 64 or any(char not in "0123456789abcdefABCDEF" for char in sha256):
        raise ApiError(422, "FILE_HASH_INVALID", "文件校验值无效。")
    limits = await session.scalar(select(ResourceLimit).where(ResourceLimit.owner_id == owner_id))
    if not limits:
        raise ApiError(500, "RESOURCE_LIMIT_MISSING", "资源额度配置不存在。")
    effective_limit = limits.single_file_bytes
    if platform_max_file_bytes is not None:
        effective_limit = min(effective_limit, platform_max_file_bytes)
    if size_bytes <= 0 or size_bytes > effective_limit:
        raise ApiError(
            413,
            "FILE_TOO_LARGE",
            "文件超过单文件大小限制。",
            details={"max_bytes": effective_limit},
        )
    used_storage = await session.scalar(
        select(func.coalesce(func.sum(Asset.size_bytes), 0)).where(
            Asset.owner_id == owner_id, Asset.deleted_at.is_(None)
        )
    )
    if int(used_storage or 0) + size_bytes > limits.storage_bytes:
        raise ApiError(413, "STORAGE_QUOTA_EXCEEDED", "存储空间不足。")
    creation_token = request_hash(
        {
            "owner_id": owner_id,
            "idempotency_key": idempotency_key,
            "filename": clean_name,
            "mime_type": mime_type,
            "size_bytes": size_bytes,
            "sha256": sha256.lower(),
            "project_id": project_id,
            "task_id": task_id,
        }
    )
    object_key = f"quarantine/{owner_id}/{creation_token}"
    part_count = math.ceil(size_bytes / PART_SIZE)
    descriptor = await storage.create_multipart_upload(
        object_key=object_key,
        part_count=part_count,
        mime_type=mime_type,
        sha256=sha256.lower(),
        request_token=creation_token,
    )
    asset = Asset(
        owner_id=owner_id,
        project_id=project_id,
        task_id=task_id,
        filename=clean_name,
        mime_type=mime_type,
        size_bytes=size_bytes,
        sha256=sha256.lower(),
        object_key=object_key,
    )
    session.add(asset)
    await session.flush()
    upload = UploadSession(
        asset_id=asset.id,
        provider_upload_id=descriptor.provider_upload_id,
        part_count=part_count,
        expires_at=utcnow() + timedelta(hours=24),
    )
    session.add(upload)
    await session.flush()
    return asset, upload, descriptor.part_urls, descriptor.simulated


async def complete_upload(
    session: AsyncSession,
    *,
    owner_id: str,
    upload_id: str,
    size_bytes: int,
    sha256: str,
    completed_parts: list[CompletedUploadPart],
    save_to_library: bool,
    storage: StorageProvider,
) -> tuple[Asset, Document, LibraryItem | None]:
    upload = await session.scalar(
        select(UploadSession)
        .join(Asset, Asset.id == UploadSession.asset_id)
        .where(UploadSession.id == upload_id, Asset.owner_id == owner_id)
        .with_for_update()
    )
    if not upload:
        raise ApiError(404, "UPLOAD_NOT_FOUND", "上传任务不存在。")
    asset = await session.get(Asset, upload.asset_id)
    if not asset:
        raise ApiError(404, "UPLOAD_NOT_FOUND", "上传文件不存在。")
    if size_bytes != asset.size_bytes or sha256.lower() != asset.sha256:
        raise ApiError(422, "UPLOAD_INTEGRITY_FAILED", "文件大小或校验值不一致。")
    normalized_parts = sorted(completed_parts, key=lambda part: part.part_number)
    expected_part_numbers = list(range(1, upload.part_count + 1))
    if (
        len(normalized_parts) != upload.part_count
        or [part.part_number for part in normalized_parts] != expected_part_numbers
    ):
        raise ApiError(
            422,
            "UPLOAD_PARTS_INCOMPLETE",
            "上传分片必须完整、连续且不能重复。",
            details={"expected_part_count": upload.part_count},
        )
    if upload.status == "completed":
        document = await session.scalar(select(Document).where(Document.asset_id == asset.id))
        if not document:
            raise ApiError(500, "DOCUMENT_MISSING", "上传记录不完整。")
        existing_library_item = await session.scalar(
            select(LibraryItem).where(
                LibraryItem.owner_id == owner_id,
                LibraryItem.item_type == "document",
                LibraryItem.source_id == document.id,
            )
        )
        return asset, document, existing_library_item
    if upload.expires_at < utcnow().replace(tzinfo=upload.expires_at.tzinfo):
        raise ApiError(410, "UPLOAD_EXPIRED", "上传任务已过期，请重新上传。")
    finalization_unknown = False
    try:
        await storage.complete_multipart_upload(
            provider_upload_id=upload.provider_upload_id,
            object_key=asset.object_key,
            parts=normalized_parts,
        )
    except InvalidMultipartUpload as exc:
        raise ApiError(422, "UPLOAD_PARTS_INVALID", "上传分片凭据无效。") from exc
    except ProviderResultUnknown:
        # The adapter's request token and provider upload id make retry safe. A HEAD/hash
        # verification also resolves the common "response lost after completion" case.
        finalization_unknown = True
    verified = await storage.verify_object(
        object_key=asset.object_key, size_bytes=size_bytes, sha256=sha256.lower()
    )
    if not verified:
        if finalization_unknown:
            raise ApiError(
                409,
                "UPLOAD_FINALIZATION_UNKNOWN",
                "对象存储完成结果未知，请使用相同幂等键稍后重试。",
                retryable=True,
            )
        raise ApiError(422, "UPLOAD_INTEGRITY_FAILED", "对象存储校验失败。")
    upload.status = "completed"
    upload.completed_at = utcnow()
    asset.scan_status = "queued"
    document = Document(
        asset_id=asset.id,
        owner_id=owner_id,
        project_id=asset.project_id,
        title=asset.filename,
        status="queued",
    )
    session.add(document)
    await session.flush()
    library_item: LibraryItem | None = None
    if save_to_library:
        library_item = await uploaded_library_item(session, asset=asset, document=document)
    create_job(
        session,
        owner_id=owner_id,
        job_type="file_processing",
        resource_type="document",
        resource_id=document.id,
        queue="files",
        stage="virus_scan",
        frozen_payload={"document_id": document.id, "asset_id": asset.id},
    )
    emit_outbox(
        session,
        event_type="document.processing.requested",
        aggregate_type="document",
        aggregate_id=document.id,
        payload={"document_id": document.id, "asset_id": asset.id},
    )
    await session.flush()
    return asset, document, library_item


async def owned_document(session: AsyncSession, *, owner_id: str, document_id: str) -> Document:
    document = await session.scalar(
        select(Document).where(Document.id == document_id, Document.owner_id == owner_id)
    )
    if not document:
        raise ApiError(404, "DOCUMENT_NOT_FOUND", "参考资料不存在。")
    return document


async def process_document(
    session: AsyncSession,
    *,
    owner_id: str,
    document_id: str,
    processor: DocumentProcessingProvider,
    chunk_target_characters: int = 800,
    chunk_overlap_characters: int = 120,
    chunking_version: str = "zh-char-v1",
    retrieval_required: bool = False,
) -> Document:
    document = await owned_document(session, owner_id=owner_id, document_id=document_id)
    if document.status == "completed":
        return document
    asset = await session.get(Asset, document.asset_id)
    if not asset:
        raise ApiError(500, "DOCUMENT_ASSET_MISSING", "参考资料的文件记录不存在。")
    result = await processor.process(
        object_key=asset.object_key,
        filename=asset.filename,
        mime_type=asset.mime_type,
        size_bytes=asset.size_bytes,
        sha256=asset.sha256,
    )
    return await persist_document_processing_result(
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


async def persist_document_processing_result(
    session: AsyncSession,
    *,
    owner_id: str,
    document: Document,
    asset: Asset,
    result: DocumentProcessingResult,
    chunk_target_characters: int = 800,
    chunk_overlap_characters: int = 120,
    chunking_version: str = "zh-char-v1",
    retrieval_required: bool = False,
) -> Document:
    document.parser_version = result.parser_version
    document.page_count = result.page_count
    document.extracted_text = result.extracted_text
    document.normalized_object_key = result.normalized_object_key
    document.error_code = None
    document.status = "indexing" if retrieval_required else "completed"
    asset.scan_status = "mocked_clean" if result.simulated else "clean"
    await session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document.id))
    await session.execute(delete(DocumentSection).where(DocumentSection.document_id == document.id))
    parsed_sections = list(result.sections)
    if not parsed_sections:
        parsed_sections = [
            DocumentSectionResult(section_type="document", text=result.extracted_text)
        ]
    section_rows: list[DocumentSection] = []
    for sort_order, parsed in enumerate(parsed_sections, start=1):
        section_data = dict(parsed.data)
        if parsed.start_ms is not None:
            section_data["start_ms"] = parsed.start_ms
        if parsed.end_ms is not None:
            section_data["end_ms"] = parsed.end_ms
        row = DocumentSection(
            document_id=document.id,
            section_type=parsed.section_type,
            title=parsed.title,
            text=parsed.text or None,
            data=section_data,
            page_no=parsed.page_no,
            sort_order=sort_order,
        )
        session.add(row)
        section_rows.append(row)
    await session.flush()
    for index, parsed in enumerate(parsed_sections):
        if parsed.parent_index is not None:
            section_rows[index].parent_id = section_rows[parsed.parent_index].id

    chunk_no = 0
    for parsed, section_row in zip(parsed_sections, section_rows, strict=True):
        for text in iter_text_chunks(
            parsed.text,
            target_characters=chunk_target_characters,
            overlap_characters=chunk_overlap_characters,
        ):
            chunk_no += 1
            session.add(
                DocumentChunk(
                    owner_id=owner_id,
                    document_id=document.id,
                    section_id=section_row.id,
                    section_title=section_row.title,
                    project_id=document.project_id,
                    page_no=parsed.page_no,
                    start_ms=parsed.start_ms,
                    end_ms=parsed.end_ms,
                    chunk_no=chunk_no,
                    text=text,
                    token_count=max(1, len(text) // 4),
                    chunking_version=chunking_version,
                    indexing_status="pending" if retrieval_required else "ready",
                )
            )
    library_item = await session.scalar(
        select(LibraryItem).where(
            LibraryItem.owner_id == owner_id,
            LibraryItem.item_type == "document",
            LibraryItem.source_id == document.id,
        )
    )
    if library_item:
        library_item.display_status = "indexing" if retrieval_required else "ready"
        library_item.search_text = f"{library_item.title} {document.extracted_text}"
    job = await session.scalar(
        select(JobRecord)
        .where(
            JobRecord.owner_id == owner_id,
            JobRecord.resource_type == "document",
            JobRecord.resource_id == document.id,
        )
        .order_by(JobRecord.created_at.desc())
        .limit(1)
    )
    if job:
        job.status = "processing" if retrieval_required else "completed"
        job.stage = (
            "embedding"
            if retrieval_required
            else ("completed_mock" if result.simulated else "completed")
        )
        job.progress = 80 if retrieval_required else 100
        job.error_code = None
        job.error_message = None
    await session.flush()
    return document


async def request_reparse(session: AsyncSession, *, owner_id: str, document_id: str) -> Document:
    document = await owned_document(session, owner_id=owner_id, document_id=document_id)
    if document.status not in {"failed", "blocked_external", "completed"}:
        raise ApiError(409, "DOCUMENT_BUSY", "文件仍在处理中。")
    document.status = "queued"
    document.error_code = None
    create_job(
        session,
        owner_id=owner_id,
        job_type="file_processing",
        resource_type="document",
        resource_id=document.id,
        queue="files",
        stage="virus_scan",
        frozen_payload={"document_id": document.id, "asset_id": document.asset_id},
    )
    emit_outbox(
        session,
        event_type="document.processing.requested",
        aggregate_type="document",
        aggregate_id=document.id,
        payload={"document_id": document.id, "asset_id": document.asset_id},
    )
    await session.flush()
    return document

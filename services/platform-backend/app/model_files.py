"""Original-file delivery to a verified model service, never a local parser substitute."""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError
from app.models import AIRun, Asset, Document, Message
from app.providers import ProviderUnavailable, SecretProvider, StorageProvider

TEXT_FILES = {
    ".pdf",
    ".txt",
    ".md",
    ".csv",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".html",
    ".dot",
    ".epub",
    ".json",
    ".mobi",
    ".log",
    ".go",
    ".h",
    ".c",
    ".cpp",
    ".cxx",
    ".cc",
    ".cs",
    ".java",
    ".js",
    ".css",
    ".jsp",
    ".php",
    ".py",
    ".py3",
    ".asp",
    ".yaml",
    ".yml",
    ".ini",
    ".conf",
    ".ts",
    ".tsx",
    ".bmp",
    ".svg",
    ".svgz",
    ".ico",
    ".xbm",
    ".dib",
    ".pjp",
    ".tif",
    ".pjpeg",
    ".avif",
    ".apng",
    ".tiff",
    ".jfif",
}
IMAGE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/jpg",
    "image/gif",
    "image/webp",
}
VIDEO_TYPES = {
    "video/mp4",
    "video/mpeg",
    "video/quicktime",
    "video/x-msvideo",
    "video/x-flv",
    "video/mpg",
    "video/webm",
    "video/x-ms-wmv",
    "video/3gpp",
}
IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
}
VIDEO_EXTENSIONS = {
    ".mp4",
    ".mpeg",
    ".mov",
    ".avi",
    ".flv",
    ".mpg",
    ".webm",
    ".wmv",
    ".3gpp",
}
MOONSHOT_FILE_PURPOSES = {
    "file-extract",
    "image",
    "video",
}
MAX_FILE_BYTES = 100 * 1024 * 1024


def _file_transfer_http_error(service: str, error: httpx.HTTPStatusError) -> ApiError:
    status = error.response.status_code
    if status == 429:
        return ApiError(
            429,
            "MODEL_FILE_PROVIDER_LIMITED",
            f"{service} 文件服务的额度、预算或调用频率已受限，请检查服务商账户后重试。",
            retryable=True,
            details={"provider_status": status},
        )
    if status in {401, 403}:
        return ApiError(
            422,
            "MODEL_FILE_PROVIDER_FORBIDDEN",
            f"{service} 文件服务拒绝访问，请检查 API 密钥及文件权限。",
            details={"provider_status": status},
        )
    return ApiError(
        502,
        "MODEL_FILE_TRANSFER_FAILED",
        f"原文件传递至 {service} 未成功，未开始生成；附件已保留，请稍后重试。",
        retryable=status >= 500,
        details={"provider_status": status},
    )


def _moonshot_file_purpose(filename: str, mime_type: str) -> str:
    """Route uploaded files to the Kimi-compatible Kimi file mode.

    * `file-extract`: text类资料（PDF/Word/表格/纯文本）先提取文本供模型使用
    * `image`: 图片类走官方图片理解接口
    * `video`: 视频类走官方视频理解接口
    """
    extension = Path(filename).suffix.lower()
    if mime_type in IMAGE_TYPES or extension in IMAGE_EXTENSIONS:
        return "image"
    if mime_type in VIDEO_TYPES or extension in VIDEO_EXTENSIONS:
        return "video"
    if extension in TEXT_FILES or mime_type in {
        "application/pdf",
        "text/plain",
        "text/markdown",
        "text/csv",
        "text/html",
        "application/json",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.ms-excel",
        "application/vnd.ms-powerpoint",
        "application/msword",
        "text/javascript",
        "text/x-python",
        "text/x-java-source",
        "text/x-c",
        "text/x-c++src",
        "text/x-yaml",
    }:
        return "file-extract"
    if mime_type.startswith("text/"):
        return "file-extract"
    raise ApiError(
        422,
        "MODEL_FILE_FORMAT_UNSUPPORTED",
        "当前统一文件入口支持 pdf、文本、Office、图片和常见音视频；请更换模型渠道或重新选择文件。",
    )


def file_input_route(config: dict[str, Any]) -> tuple[str, str]:
    """Resolve verified protocols, not model display names or guessed compatibility."""
    base = str(config.get("base_url", "")).rstrip("/")
    url = urlsplit(base)
    if config.get("adapter") == "manus_v2" and base == "https://api.manus.ai":
        return "manus_files_api", base
    if url.hostname in {"dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com"}:
        raise ApiError(
            422,
            "MODEL_FILE_INPUT_UNSUPPORTED",
            "当前所选模型未接通原文件输入协议。请切换到管理端已配置且支持原文件输入的模型；"
            "原附件会保留，无需重新上传。",
        )
    return "moonshot_files_api", moonshot_file_endpoint(config)


async def upload_manus_file(
    client: httpx.AsyncClient,
    *,
    api_base: str,
    headers: dict[str, str],
    filename: str,
    mime_type: str,
    content: bytes,
) -> str:
    response = await client.post(
        f"{api_base.rstrip('/')}/v2/file.upload",
        headers=headers,
        json={"filename": filename},
    )
    response.raise_for_status()
    body = response.json()
    file_id = body.get("file", {}).get("id")
    upload_url = body.get("upload_url", "")
    url = urlsplit(upload_url)
    # Only official S3 presigned storage; never forward API credentials to storage.
    if (
        not isinstance(file_id, str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", file_id)
        or url.scheme != "https"
        or not (url.hostname or "").endswith(".amazonaws.com")
        or url.username
        or url.fragment
        or url.port not in {None, 443}
    ):
        raise ProviderUnavailable("Manus returned an invalid file upload destination")
    uploaded = await client.put(
        upload_url,
        content=content,
        headers={"Content-Type": mime_type},
        follow_redirects=False,
    )
    uploaded.raise_for_status()
    for attempt in range(120):
        detail = await client.get(
            f"{api_base.rstrip('/')}/v2/file.detail",
            headers=headers,
            params={"file_id": file_id},
        )
        detail.raise_for_status()
        status = detail.json().get("file", {}).get("status")
        if status == "uploaded":
            return file_id
        if status != "pending":
            break
        if attempt < 119:
            await asyncio.sleep(1)
    raise ProviderUnavailable("Manus did not confirm original file upload")


def moonshot_file_endpoint(config: dict[str, Any]) -> str:
    base = str(config.get("base_url", "")).rstrip("/")
    url = urlsplit(base)
    if (
        config.get("adapter") != "openai_chat_completions"
        or url.scheme != "https"
        or url.hostname not in {"api.moonshot.cn", "api.moonshot.ai"}
        or url.path != "/v1"
        or url.query
        or url.fragment
        or url.username
        or url.port not in {None, 443}
    ):
        raise ApiError(
            422,
            "MODEL_FILE_INPUT_UNSUPPORTED",
            "当前所选模型未接通原文件输入协议。请切换到管理端已配置且支持原文件输入的模型；"
            "原附件会保留，不会用本地解析或文件名替代。",
        )
    return base


def selected_document_ids(content: dict[str, Any]) -> list[str]:
    raw = content.get("document_ids", [])
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        raise ApiError(422, "DOCUMENT_IDS_INVALID", "参考资料 ID 格式无效。")
    attachments = content.get("attachments", [])
    ids = (
        [
            *raw,
            *[
                item["document_id"]
                for item in attachments
                if isinstance(item, dict) and isinstance(item.get("document_id"), str)
            ],
        ]
        if isinstance(attachments, list)
        else raw
    )
    return list(dict.fromkeys(ids))


async def conversation_file_ids(
    session: AsyncSession, *, task_id: str, content: dict[str, Any]
) -> list[str]:
    ids = selected_document_ids(content)
    if not ids:
        # Carry the last explicit file selection, not arbitrary documents from another task.
        messages = (
            await session.scalars(
                select(Message)
                .where(Message.task_id == task_id, Message.role == "user")
                .order_by(Message.created_at.desc())
            )
        ).all()
        for message in messages:
            ids = selected_document_ids(message.content_json)
            if ids:
                break
    if len(ids) > 20:
        raise ApiError(422, "DOCUMENT_LIMIT_EXCEEDED", "单次最多引用 20 个文件。")
    return ids


async def upload_moonshot_file(
    *,
    base: str,
    key: str,
    filename: str,
    mime_type: str,
    content: bytes,
    purpose: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[str, str]:
    headers = {"Authorization": f"Bearer {key}"}
    if purpose not in MOONSHOT_FILE_PURPOSES:
        raise ApiError(
            422,
            "MODEL_FILE_PURPOSE_INVALID",
            "文件用途仅支持 file-extract、image、video。",
        )
    try:
        async with httpx.AsyncClient(
            timeout=120, transport=transport, follow_redirects=False
        ) as client:
            response = await client.post(
                f"{base}/files",
                headers=headers,
                data={"purpose": purpose},
                files={"file": (filename, content, mime_type)},
            )
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict):
                raise ApiError(
                    422,
                    "MODEL_FILE_TRANSFER_FAILED",
                    "模型服务返回了非预期文件上传响应。",
                )
            file_id = body.get("id") or (body.get("file") or {}).get("id")
            if not isinstance(file_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", file_id):
                raise ValueError("Invalid provider file id")
            if purpose == "file-extract":
                async with client.stream(
                    "GET", f"{base}/files/{file_id}/content", headers=headers
                ) as result:
                    result.raise_for_status()
                    extracted_buffer = bytearray()
                    async for chunk in result.aiter_bytes():
                        extracted_buffer.extend(chunk)
                        if len(extracted_buffer) > 4_000_000:
                            raise ApiError(
                                422,
                                "MODEL_FILE_CONTENT_TOO_LARGE",
                                "官方返回的文件正文过长，请拆分文件；不会静默截断。",
                            )
                    extracted = extracted_buffer.decode("utf-8").strip()
                if not extracted:
                    raise ApiError(
                        422,
                        "MODEL_FILE_CONTENT_EMPTY",
                        "模型服务没有从文件中返回有效内容，未开始写作。",
                    )
                return file_id, extracted
            return file_id, ""
    except ApiError:
        raise
    except (AttributeError, UnicodeDecodeError, KeyError) as exc:
        raise ApiError(
            422,
            "MODEL_FILE_CONTENT_EMPTY",
            "模型服务没有从文件中返回有效可解析文本。",
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise _file_transfer_http_error("Kimi", exc) from exc
    except (httpx.RequestError, ValueError) as exc:
        raise ApiError(
            502,
            "MODEL_FILE_TRANSFER_FAILED",
            "原文件上传到模型服务或获取官方文件内容失败，未开始写作。请检查模型文件权限、格式和大小后重试。",
            retryable=isinstance(exc, httpx.RequestError),
        ) from exc


async def prepare_model_files(
    session: AsyncSession,
    *,
    owner_id: str,
    task_id: str,
    document_ids: list[str],
    config: dict[str, Any],
    storage: StorageProvider,
    secrets: SecretProvider,
    max_characters: int,
) -> list[dict[str, Any]]:
    if not document_ids:
        return []
    delivery, base = file_input_route(config)
    credential_fingerprint = (
        hashlib.sha256(str(config["secret_ref"]).encode()).hexdigest()
        if config.get("secret_ref")
        else None
    )
    records = (
        await session.execute(
            select(Document, Asset)
            .join(Asset, Asset.id == Document.asset_id)
            .where(
                Document.id.in_(document_ids),
                Document.owner_id == owner_id,
                Asset.owner_id == owner_id,
                Asset.deleted_at.is_(None),
            )
        )
    ).all()
    by_id = {document.id: (document, asset) for document, asset in records}
    if any(identifier not in by_id for identifier in document_ids):
        raise ApiError(404, "DOCUMENT_NOT_FOUND", "参考文件不存在或无权访问。")
    for _, asset in records:
        if asset.scan_status != "clean":
            raise ApiError(409, "FILE_NOT_SAFE", "文件尚未完成安全检查，不能发送给模型。")
        if not 0 < asset.size_bytes <= MAX_FILE_BYTES:
            raise ApiError(413, "MODEL_FILE_SIZE_EXCEEDED", "单文件最大仅支持100MB。")
        if delivery == "moonshot_files_api":
            asset_purpose = _moonshot_file_purpose(asset.filename, asset.mime_type)
            if asset_purpose not in MOONSHOT_FILE_PURPOSES:
                raise ApiError(
                    422,
                    "MODEL_FILE_FORMAT_UNSUPPORTED",
                    "当前统一文件入口支持不超过 100MB 的 PDF、Office、文本、图片和音视频；"
                    "更多类型请改用支持该文件类型的模型渠道。",
                )
    previous = (
        await session.scalars(
            select(AIRun)
            .where(AIRun.owner_id == owner_id, AIRun.task_id == task_id)
            .order_by(AIRun.created_at.desc())
            .limit(30)
        )
    ).all()
    cache: dict[str, dict[str, Any]] = {}
    for run in previous:
        for item in run.context_snapshot.get("untrusted_model_files", []):
            if (
                isinstance(item, dict)
                and item.get("provider_id") == config.get("provider_id")
                and item.get("base_url") == base
                and item.get("delivery") == delivery
                and item.get("credential_fingerprint") == credential_fingerprint
                and delivery == "moonshot_files_api"
            ):
                cache.setdefault(str(item.get("document_id")), item)
    results: list[dict[str, Any]] = []
    used = 0
    for identifier in document_ids:
        _, asset = by_id[identifier]
        asset_purpose = _moonshot_file_purpose(asset.filename, asset.mime_type)
        cached = cache.get(identifier)
        cached_purpose = cached.get("provider_file_purpose") if isinstance(cached, dict) else None
        if (
            isinstance(cached, dict)
            and cached.get("sha256") == asset.sha256
            and (
                cached_purpose == asset_purpose
                or (cached_purpose is None and cached.get("content"))
            )
        ):
            item = dict(cached)
            if not item.get("provider_file_purpose"):
                item["provider_file_purpose"] = asset_purpose
        else:
            try:
                raw = await storage.read_bytes(
                    object_key=asset.object_key, max_bytes=MAX_FILE_BYTES
                )
            except ProviderUnavailable as exc:
                raise ApiError(
                    422,
                    "ORIGINAL_FILE_UNAVAILABLE",
                    "原文件已不可读取（旧版内存存储可能在重启后丢失），请重新上传；不会用文件名替代。",
                ) from exc
            if len(raw) != asset.size_bytes or hashlib.sha256(raw).hexdigest() != asset.sha256:
                raise ApiError(
                    422, "ORIGINAL_FILE_INTEGRITY_FAILED", "原文件校验失败，请重新上传。"
                )
            key = secrets.resolve(str(config["secret_ref"]))
            extracted = ""
            if delivery == "moonshot_files_api":
                file_id, extracted = await upload_moonshot_file(
                    base=base,
                    key=key,
                    filename=asset.filename,
                    mime_type=asset.mime_type,
                    content=raw,
                    purpose=asset_purpose,
                )
            else:
                try:
                    async with httpx.AsyncClient(timeout=120, follow_redirects=False) as client:
                        file_id = await upload_manus_file(
                            client,
                            api_base=base,
                            headers={"x-manus-api-key": key},
                            filename=asset.filename,
                            mime_type=asset.mime_type,
                            content=raw,
                        )
                except httpx.HTTPStatusError as exc:
                    raise _file_transfer_http_error("Manus", exc) from exc
                except (httpx.RequestError, ValueError, AttributeError, ProviderUnavailable) as exc:
                    raise ApiError(
                        502,
                        "MODEL_FILE_TRANSFER_FAILED",
                        "原文件传递至 Manus 未成功，未开始生成；附件已保留，请稍后重试。",
                        retryable=isinstance(exc, httpx.RequestError),
                    ) from exc
            item = {
                "document_id": identifier,
                "filename": asset.filename,
                "sha256": asset.sha256,
                "provider_id": config.get("provider_id"),
                "base_url": base,
                "provider_file_id": file_id,
                "delivery": delivery,
                "credential_fingerprint": credential_fingerprint,
                "content": extracted,
                "provider_file_purpose": asset_purpose,
                "uploaded_at": time.time(),
            }
        used += len(str(item.get("content", "")))
        if used > 2_000_000:
            raise ApiError(
                422,
                "MODEL_FILE_CONTEXT_LIMIT",
                "文件文字总量超过200万字符的分段处理上限，请分批处理；不会静默截断。",
            )
        results.append(item)
    return results

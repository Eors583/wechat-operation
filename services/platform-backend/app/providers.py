from __future__ import annotations

import hashlib
import io
import os
import posixpath
import secrets
import zipfile
from base64 import urlsafe_b64encode
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from xml.etree import ElementTree

from cryptography.fernet import Fernet, InvalidToken


class ProviderUnavailable(RuntimeError):
    pass


class ModelContractViolation(ProviderUnavailable):
    def __init__(self, message: str, *, code: str = "MODEL_OUTPUT_INVALID") -> None:
        super().__init__(message)
        self.code = code


class ProviderAuthenticationError(ProviderUnavailable):
    """The configured external credential was rejected and should be disabled."""


class ProviderTransientError(ProviderUnavailable):
    """A connection or server failure may succeed on a bounded retry."""


class ProviderTimeoutError(ProviderTransientError):
    """The provider did not finish within the configured request timeout."""


class ProviderRateLimited(ProviderTransientError):
    def __init__(self, message: str, *, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class ProviderResultUnknown(RuntimeError):
    """The request may have reached an external service and must be reconciled."""

    def __init__(self, message: str, *, external_id: str | None = None) -> None:
        super().__init__(message)
        self.external_id = external_id


class SecretProvider(Protocol):
    def resolve(self, reference: str) -> str: ...

    def protect(self, value: str) -> str: ...


class EnvironmentSecretProvider:
    _PREFIX = "encrypted:v1:"

    def __init__(self, encryption_key: str | None = None) -> None:
        key = encryption_key or os.getenv("MODEL_SECRET_MASTER_KEY") or os.getenv("TOKEN_SECRET")
        self._cipher = (
            Fernet(urlsafe_b64encode(hashlib.sha256(key.encode()).digest())) if key else None
        )

    def protect(self, value: str) -> str:
        if not value or self._cipher is None:
            raise ProviderUnavailable("Model secret encryption is not configured")
        return self._PREFIX + self._cipher.encrypt(value.encode()).decode()

    def resolve(self, reference: str) -> str:
        if reference.startswith("env:"):
            value = os.getenv(reference.removeprefix("env:"))
            if not value:
                raise ProviderUnavailable("Referenced secret is not available")
            return value
        if reference.startswith(self._PREFIX) and self._cipher is not None:
            try:
                return self._cipher.decrypt(reference.removeprefix(self._PREFIX).encode()).decode()
            except (InvalidToken, UnicodeDecodeError) as exc:
                raise ProviderUnavailable("Encrypted model secret is invalid") from exc
        raise ProviderUnavailable("Secret reference is not supported")


@dataclass(frozen=True, slots=True)
class ModelResult:
    text: str
    structured: dict[str, Any]
    input_tokens: int
    output_tokens: int
    provider_request_id: str
    simulated: bool


class ModelProvider(Protocol):
    async def generate(
        self, *, purpose: str, prompt: str, context: dict[str, Any]
    ) -> ModelResult: ...


@dataclass(frozen=True, slots=True)
class WebReferenceContent:
    requested_url: str
    final_url: str
    title: str
    text: str
    content_type: str


class WebReferenceProvider(Protocol):
    async def fetch(self, url: str) -> WebReferenceContent: ...


class MockWebReferenceProvider:
    async def fetch(self, url: str) -> WebReferenceContent:
        return WebReferenceContent(
            requested_url=url,
            final_url=url,
            title="模拟网页参考资料",
            text=f"这是从 {url} 抓取的模拟网页正文。",
            content_type="text/html",
        )


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    vectors: list[list[float]]
    model: str
    provider_request_id: str
    simulated: bool


class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str]) -> EmbeddingResult: ...


class MockEmbeddingProvider:
    def __init__(self, dimension: int = 16) -> None:
        self._dimension = dimension

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        vectors: list[list[float]] = []
        for text in texts:
            digest = hashlib.sha256(text.encode()).digest()
            vectors.append(
                [
                    ((digest[index % len(digest)] / 255.0) * 2) - 1
                    for index in range(self._dimension)
                ]
            )
        return EmbeddingResult(vectors, "mock-hash-v1", "mock-embedding", True)


@dataclass(frozen=True, slots=True)
class RerankResult:
    scores: list[float]
    provider_request_id: str
    simulated: bool


class RerankProvider(Protocol):
    async def rerank(self, *, query: str, documents: list[str]) -> RerankResult: ...


class MockRerankProvider:
    async def rerank(self, *, query: str, documents: list[str]) -> RerankResult:
        query_terms = set(query.lower().split())
        scores = [
            float(len(query_terms.intersection(document.lower().split()))) for document in documents
        ]
        return RerankResult(scores, "mock-rerank", True)


class MockModelProvider:
    async def generate(self, *, purpose: str, prompt: str, context: dict[str, Any]) -> ModelResult:
        raise ProviderUnavailable("真实模型服务未配置，不能生成模拟内容。")


class UnconfiguredModelProvider:
    async def generate(self, *, purpose: str, prompt: str, context: dict[str, Any]) -> ModelResult:
        raise ProviderUnavailable("No production model adapter is configured")


class ContentSafetyProvider(Protocol):
    async def check_text(self, text: str) -> tuple[bool, str | None]: ...


class MockContentSafetyProvider:
    async def check_text(self, text: str) -> tuple[bool, str | None]:
        return True, None


class UnconfiguredContentSafetyProvider:
    async def check_text(self, text: str) -> tuple[bool, str | None]:
        raise ProviderUnavailable("No production content-safety adapter is configured")


class VerificationProvider(Protocol):
    async def send(self, destination: str, code: str) -> str: ...


class MockVerificationProvider:
    async def send(self, destination: str, code: str) -> str:
        return "mocked"


class UnconfiguredVerificationProvider:
    async def send(self, destination: str, code: str) -> str:
        raise ProviderUnavailable("No production verification provider is configured")


@dataclass(frozen=True, slots=True)
class UploadDescriptor:
    provider_upload_id: str
    part_urls: list[str]
    simulated: bool


@dataclass(frozen=True, slots=True)
class CompletedUploadPart:
    part_number: int
    etag: str


class InvalidMultipartUpload(RuntimeError):
    pass


class StorageProvider(Protocol):
    async def read_bytes(self, *, object_key: str, max_bytes: int) -> bytes: ...

    async def put_bytes(
        self, *, object_key: str, content: bytes, mime_type: str, sha256: str
    ) -> None: ...

    async def create_multipart_upload(
        self,
        *,
        object_key: str,
        part_count: int,
        mime_type: str,
        sha256: str,
        request_token: str,
    ) -> UploadDescriptor: ...

    async def complete_multipart_upload(
        self,
        *,
        provider_upload_id: str,
        object_key: str,
        parts: list[CompletedUploadPart],
    ) -> None: ...

    async def verify_object(self, *, object_key: str, size_bytes: int, sha256: str) -> bool: ...

    async def delete_object(self, *, object_key: str) -> None: ...


class MockStorageProvider:
    async def read_bytes(self, *, object_key: str, max_bytes: int) -> bytes:
        content = self.object_bytes(object_key)
        if content is None:
            raise ProviderUnavailable("Original file is no longer available; upload it again")
        if len(content) > max_bytes:
            raise ProviderUnavailable("Original file exceeds upload limit")
        return content

    def __init__(self, *, persistence_dir: Path | None = None) -> None:
        self._persistence_dir = persistence_dir
        self._uploads: dict[str, dict[str, Any]] = {}
        self._direct_objects: dict[str, bytes] = {}
        self._object_tokens: dict[str, str] = {}
        self._request_tokens: dict[str, str] = {}

    async def put_bytes(
        self, *, object_key: str, content: bytes, mime_type: str, sha256: str
    ) -> None:
        del mime_type
        if hashlib.sha256(content).hexdigest() != sha256:
            raise ProviderUnavailable("Object content hash does not match metadata")
        self._direct_objects[object_key] = bytes(content)
        self._persist(object_key, content)

    def _persist(self, object_key: str, content: bytes) -> None:
        if self._persistence_dir is None:
            return
        self._persistence_dir.mkdir(parents=True, exist_ok=True)
        target = self._persistence_dir / hashlib.sha256(object_key.encode()).hexdigest()
        temporary = target.with_suffix(f".{secrets.token_hex(8)}.tmp")
        temporary.write_bytes(content)
        temporary.replace(target)

    async def create_multipart_upload(
        self,
        *,
        object_key: str,
        part_count: int,
        mime_type: str,
        sha256: str,
        request_token: str,
    ) -> UploadDescriptor:
        token = self._request_tokens.get(request_token)
        if token:
            upload = self._uploads[token]
            if (
                upload["object_key"] != object_key
                or upload["part_count"] != part_count
                or upload["mime_type"] != mime_type
                or upload["sha256"] != sha256
            ):
                raise InvalidMultipartUpload("request token was reused for a different upload")
            return self._descriptor(token, part_count)
        token = secrets.token_urlsafe(48)
        self._uploads[token] = {
            "object_key": object_key,
            "part_count": part_count,
            "mime_type": mime_type,
            "sha256": sha256,
            "parts": {},
            "etags": {},
            "completed": False,
        }
        self._object_tokens[object_key] = token
        self._request_tokens[request_token] = token
        return self._descriptor(token, part_count)

    @staticmethod
    def _descriptor(token: str, part_count: int) -> UploadDescriptor:
        return UploadDescriptor(
            provider_upload_id=f"mock:{token}",
            part_urls=[
                f"/api/v1/mock-storage/{token}/parts/{part}" for part in range(1, part_count + 1)
            ],
            simulated=True,
        )

    async def complete_multipart_upload(
        self,
        *,
        provider_upload_id: str,
        object_key: str,
        parts: list[CompletedUploadPart],
    ) -> None:
        if not provider_upload_id.startswith("mock:"):
            raise InvalidMultipartUpload("mock upload identifier is invalid")
        token = provider_upload_id.removeprefix("mock:")
        upload = self._uploads.get(token)
        if not upload or upload["object_key"] != object_key:
            raise InvalidMultipartUpload("multipart upload does not exist")
        part_count = int(upload["part_count"])
        expected_numbers = list(range(1, part_count + 1))
        if [part.part_number for part in parts] != expected_numbers:
            raise InvalidMultipartUpload("multipart upload is incomplete")
        etags = upload["etags"]
        if not isinstance(etags, dict) or any(
            etags.get(part.part_number) != part.etag for part in parts
        ):
            raise InvalidMultipartUpload("multipart ETag does not match the uploaded part")
        upload["completed"] = True
        completed = self.object_bytes(object_key)
        if completed is not None:
            self._persist(object_key, completed)

    async def verify_object(self, *, object_key: str, size_bytes: int, sha256: str) -> bool:
        content = self.object_bytes(object_key)
        return bool(
            content is not None
            and len(content) == size_bytes
            and hashlib.sha256(content).hexdigest() == sha256
        )

    async def delete_object(self, *, object_key: str) -> None:
        if self._persistence_dir is not None:
            (self._persistence_dir / hashlib.sha256(object_key.encode()).hexdigest()).unlink(
                missing_ok=True
            )
        self._direct_objects.pop(object_key, None)
        token = self._object_tokens.pop(object_key, None)
        if token:
            self._uploads.pop(token, None)
            stale_requests = [key for key, value in self._request_tokens.items() if value == token]
            for key in stale_requests:
                self._request_tokens.pop(key, None)

    def put_part(self, *, token: str, part_number: int, content: bytes) -> str:
        upload = self._uploads.get(token)
        if not upload:
            raise KeyError(token)
        if upload["completed"]:
            raise ValueError("multipart upload is already completed")
        if part_number < 1 or part_number > int(upload["part_count"]):
            raise ValueError("part number is outside the multipart upload")
        parts = upload["parts"]
        etags = upload["etags"]
        if not isinstance(parts, dict) or not isinstance(etags, dict):
            raise ValueError("mock upload state is invalid")
        parts[part_number] = content
        etag = f"mock-{hashlib.sha256(content).hexdigest()}"
        etags[part_number] = etag
        return etag

    def object_bytes(self, object_key: str) -> bytes | None:
        if self._persistence_dir is not None:
            path = self._persistence_dir / hashlib.sha256(object_key.encode()).hexdigest()
            if path.is_file():
                return path.read_bytes()
        direct = self._direct_objects.get(object_key)
        if direct is not None:
            return direct
        token = self._object_tokens.get(object_key)
        upload = self._uploads.get(token or "")
        if not upload or not upload["completed"]:
            return None
        part_count = int(upload["part_count"])
        parts = upload["parts"]
        if not isinstance(parts, dict) or set(parts) != set(range(1, part_count + 1)):
            return None
        return b"".join(parts[index] for index in range(1, part_count + 1))


class UnconfiguredStorageProvider:
    async def read_bytes(self, *, object_key: str, max_bytes: int) -> bytes:
        raise ProviderUnavailable("No object-storage provider is configured")

    async def put_bytes(
        self, *, object_key: str, content: bytes, mime_type: str, sha256: str
    ) -> None:
        raise ProviderUnavailable("No production object-storage provider is configured")

    async def create_multipart_upload(
        self,
        *,
        object_key: str,
        part_count: int,
        mime_type: str,
        sha256: str,
        request_token: str,
    ) -> UploadDescriptor:
        raise ProviderUnavailable("No production object-storage provider is configured")

    async def complete_multipart_upload(
        self,
        *,
        provider_upload_id: str,
        object_key: str,
        parts: list[CompletedUploadPart],
    ) -> None:
        raise ProviderUnavailable("No production object-storage provider is configured")

    async def verify_object(self, *, object_key: str, size_bytes: int, sha256: str) -> bool:
        raise ProviderUnavailable("No production object-storage provider is configured")

    async def delete_object(self, *, object_key: str) -> None:
        raise ProviderUnavailable("No production object-storage provider is configured")


@dataclass(frozen=True, slots=True)
class DocumentSectionResult:
    section_type: str
    text: str
    title: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    page_no: int | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    parent_index: int | None = None


@dataclass(frozen=True, slots=True)
class DocumentProcessingResult:
    extracted_text: str
    parser_version: str
    page_count: int | None
    simulated: bool
    sections: tuple[DocumentSectionResult, ...] = ()
    normalized_object_key: str | None = None


class DocumentProcessingProvider(Protocol):
    async def process(
        self,
        *,
        object_key: str,
        filename: str,
        mime_type: str,
        size_bytes: int,
        sha256: str,
    ) -> DocumentProcessingResult: ...


class MockDocumentProcessingProvider:
    def __init__(self, storage: MockStorageProvider | None = None) -> None:
        self._storage = storage

    async def process(
        self,
        *,
        object_key: str,
        filename: str,
        mime_type: str,
        size_bytes: int,
        sha256: str,
    ) -> DocumentProcessingResult:
        del sha256
        content = self._storage.object_bytes(object_key) if self._storage else None
        text_types = {"text/plain", "text/markdown", "text/csv", "text/html"}
        if content is not None and mime_type in text_types:
            extracted = content[:2_000_000].decode("utf-8", errors="replace")
            if len(content) > 2_000_000:
                extracted += "\n[SIMULATED MOCK CONTENT TRUNCATED AT 2,000,000 BYTES]"
            return DocumentProcessingResult(
                extracted_text=extracted,
                parser_version="mock-text-bytes-v1",
                page_count=1,
                simulated=True,
                sections=(
                    DocumentSectionResult(
                        section_type="page",
                        title="第 1 页",
                        text=extracted,
                        page_no=1,
                    ),
                ),
            )
        if (
            content is not None
            and mime_type
            == "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        ):
            return self._process_pptx(content)
        return DocumentProcessingResult(
            extracted_text=(
                "[SIMULATED MOCK CONTENT: file bytes were not parsed] "
                f"filename={filename}; mime_type={mime_type}; size_bytes={size_bytes}"
            ),
            parser_version="mock-metadata-v1",
            page_count=0,
            simulated=True,
            sections=(
                DocumentSectionResult(
                    section_type="metadata",
                    title=filename,
                    text=(
                        "[SIMULATED MOCK CONTENT: file bytes were not parsed] "
                        f"filename={filename}; mime_type={mime_type}; size_bytes={size_bytes}"
                    ),
                ),
            ),
        )

    @staticmethod
    def _process_pptx(content: bytes) -> DocumentProcessingResult:
        drawing_namespace = "http://schemas.openxmlformats.org/drawingml/2006/main"
        relationships_namespace = "http://schemas.openxmlformats.org/package/2006/relationships"
        document_relationships_namespace = (
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        )
        max_slide_xml_bytes = 5_000_000
        max_total_slide_xml_bytes = 50_000_000
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                presentation_info = archive.getinfo("ppt/presentation.xml")
                relationships_info = archive.getinfo("ppt/_rels/presentation.xml.rels")
                if (
                    presentation_info.file_size > 2_000_000
                    or relationships_info.file_size > 2_000_000
                ):
                    raise ProviderUnavailable("PPTX 演示文稿结构过大，无法安全解析。")
                presentation = ElementTree.fromstring(archive.read(presentation_info))
                relationships = ElementTree.fromstring(archive.read(relationships_info))
                slide_targets = {
                    relationship.attrib["Id"]: posixpath.normpath(
                        posixpath.join("ppt", relationship.attrib["Target"])
                    )
                    for relationship in relationships.iter(
                        f"{{{relationships_namespace}}}Relationship"
                    )
                    if relationship.attrib.get("Type", "").endswith("/slide")
                }
                slide_paths = [
                    slide_targets[slide.attrib[f"{{{document_relationships_namespace}}}id"]]
                    for slide in presentation.iter(
                        "{http://schemas.openxmlformats.org/presentationml/2006/main}sldId"
                    )
                ]
                if not slide_paths:
                    raise ProviderUnavailable("PPTX 文件中没有可读取的幻灯片。")
                slides = [archive.getinfo(path) for path in slide_paths]
                if (
                    any(entry.file_size > max_slide_xml_bytes for entry in slides)
                    or sum(entry.file_size for entry in slides) > max_total_slide_xml_bytes
                ):
                    raise ProviderUnavailable("PPTX 幻灯片文本结构过大，无法安全解析。")

                sections: list[DocumentSectionResult] = []
                for page_no, entry in enumerate(slides, start=1):
                    root = ElementTree.fromstring(archive.read(entry))
                    paragraphs: list[str] = []
                    for paragraph in root.iter(f"{{{drawing_namespace}}}p"):
                        text = "".join(
                            node.text or "" for node in paragraph.iter(f"{{{drawing_namespace}}}t")
                        ).strip()
                        if text:
                            paragraphs.append(text)
                    sections.append(
                        DocumentSectionResult(
                            section_type="page",
                            title=f"第 {page_no} 页",
                            text="\n".join(paragraphs),
                            page_no=page_no,
                        )
                    )
        except (
            KeyError,
            zipfile.BadZipFile,
            ElementTree.ParseError,
            OSError,
            RuntimeError,
        ) as exc:
            raise ProviderUnavailable("PPTX 文件结构无效或无法读取。") from exc

        extracted = "\n\n".join(
            f"{section.title}\n{section.text}" for section in sections if section.text
        )
        if not extracted:
            raise ProviderUnavailable("PPTX 中没有可提取的文字。")
        return DocumentProcessingResult(
            extracted_text=extracted,
            parser_version="local-pptx-xml-v1",
            page_count=len(sections),
            simulated=True,
            sections=tuple(sections),
        )


class UnconfiguredDocumentProcessingProvider:
    async def process(
        self,
        *,
        object_key: str,
        filename: str,
        mime_type: str,
        size_bytes: int,
        sha256: str,
    ) -> DocumentProcessingResult:
        raise ProviderUnavailable("No production file scan/parser provider is configured")


@dataclass(frozen=True, slots=True)
class LayoutExtractionResult:
    style_tokens: dict[str, Any]
    source_snapshot: dict[str, Any]
    extractor_version: str
    simulated: bool


class LayoutExtractionProvider(Protocol):
    async def extract(self, *, source_url: str) -> LayoutExtractionResult: ...


class UnconfiguredLayoutExtractionProvider:
    async def extract(self, *, source_url: str) -> LayoutExtractionResult:
        raise ProviderUnavailable("No production-safe WeChat article fetcher is configured")


@dataclass(frozen=True, slots=True)
class WechatResult:
    status: str
    media_id: str | None = None
    publish_id: str | None = None
    external_action_performed: bool = False
    details: dict[str, Any] | None = None


class WechatProvider(Protocol):
    async def authorization_url(self, *, state: str, redirect_uri: str) -> str: ...

    async def create_or_update_draft(
        self, *, account_ref: str, html: str, title: str, cover_ref: str | None
    ) -> WechatResult: ...

    async def publish(self, *, account_ref: str, media_id: str) -> WechatResult: ...

    async def reconcile(self, *, operation_type: str, external_id: str) -> WechatResult: ...

    async def refresh_account(self, *, account_ref: str) -> WechatResult: ...


class UnconfiguredWechatProvider:
    async def authorization_url(self, *, state: str, redirect_uri: str) -> str:
        raise ProviderUnavailable("WeChat third-party platform is not configured")

    async def create_or_update_draft(
        self, *, account_ref: str, html: str, title: str, cover_ref: str | None
    ) -> WechatResult:
        raise ProviderUnavailable("WeChat third-party platform is not configured")

    async def publish(self, *, account_ref: str, media_id: str) -> WechatResult:
        raise ProviderUnavailable("WeChat third-party platform is not configured")

    async def reconcile(self, *, operation_type: str, external_id: str) -> WechatResult:
        raise ProviderUnavailable("WeChat third-party platform is not configured")

    async def refresh_account(self, *, account_ref: str) -> WechatResult:
        raise ProviderUnavailable("WeChat third-party platform is not configured")


class MockWechatProvider(UnconfiguredWechatProvider):
    async def authorization_url(self, *, state: str, redirect_uri: str) -> str:
        raise ProviderUnavailable("Mock mode cannot authorize a real official account")

    async def create_or_update_draft(
        self, *, account_ref: str, html: str, title: str, cover_ref: str | None
    ) -> WechatResult:
        return WechatResult(
            status="mocked",
            external_action_performed=False,
            details={
                "provider_mode": "mock",
                "external_action_performed": False,
                "message": "No WeChat request was sent",
            },
        )

    async def publish(self, *, account_ref: str, media_id: str) -> WechatResult:
        return WechatResult(
            status="mocked",
            external_action_performed=False,
            details={
                "provider_mode": "mock",
                "external_action_performed": False,
                "message": "No WeChat request was sent",
            },
        )

    async def reconcile(self, *, operation_type: str, external_id: str) -> WechatResult:
        return WechatResult(
            status="mocked",
            external_action_performed=False,
            details={
                "provider_mode": "mock",
                "external_action_performed": False,
                "message": "No external result exists",
            },
        )

    async def refresh_account(self, *, account_ref: str) -> WechatResult:
        del account_ref
        return WechatResult(
            status="mocked",
            external_action_performed=False,
            details={"provider_mode": "mock", "message": "No token refresh was sent"},
        )

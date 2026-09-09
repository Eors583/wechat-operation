from __future__ import annotations

import hashlib
import os
from base64 import urlsafe_b64encode
from dataclasses import dataclass, field
from typing import Any, Protocol

from cryptography.fernet import Fernet, InvalidToken


class ProviderUnavailable(RuntimeError):
    pass


class ModelContractViolation(ProviderUnavailable):
    def __init__(self, message: str, *, code: str = "MODEL_OUTPUT_INVALID") -> None:
        super().__init__(message)
        self.code = code


class ProviderAuthenticationError(ProviderUnavailable):
    """The configured external credential was rejected and should be disabled."""

    def __init__(self, message: str, *, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class ProviderReauthorizationRequired(ProviderAuthenticationError):
    """The provider confirmed that the user must authorize the account again."""


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


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    vectors: list[list[float]]
    model: str
    provider_request_id: str


class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str]) -> EmbeddingResult: ...


class UnconfiguredEmbeddingProvider:
    async def embed(self, texts: list[str]) -> EmbeddingResult:
        raise ProviderUnavailable("No production embedding adapter is configured")


@dataclass(frozen=True, slots=True)
class RerankResult:
    scores: list[float]
    provider_request_id: str


class RerankProvider(Protocol):
    async def rerank(self, *, query: str, documents: list[str]) -> RerankResult: ...


class UnconfiguredRerankProvider:
    async def rerank(self, *, query: str, documents: list[str]) -> RerankResult:
        raise ProviderUnavailable("No production rerank adapter is configured")


class UnconfiguredModelProvider:
    async def generate(self, *, purpose: str, prompt: str, context: dict[str, Any]) -> ModelResult:
        raise ProviderUnavailable("No production model adapter is configured")


class ContentSafetyProvider(Protocol):
    async def check_text(self, text: str) -> tuple[bool, str | None]: ...


class UnconfiguredContentSafetyProvider:
    async def check_text(self, text: str) -> tuple[bool, str | None]:
        raise ProviderUnavailable("No production content-safety adapter is configured")


class VerificationProvider(Protocol):
    async def send(self, destination: str, code: str) -> str: ...


class UnconfiguredVerificationProvider:
    async def send(self, destination: str, code: str) -> str:
        raise ProviderUnavailable("No production verification provider is configured")


@dataclass(frozen=True, slots=True)
class UploadDescriptor:
    provider_upload_id: str
    part_urls: list[str]


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


@dataclass(frozen=True, slots=True)
class WechatCover:
    ref: str
    filename: str
    mime_type: str
    content: bytes


class WechatProvider(Protocol):
    async def authorization_url(self, *, state: str, redirect_uri: str) -> str: ...

    async def create_or_update_draft(
        self,
        *,
        account_ref: str,
        html: str,
        title: str,
        digest: str,
        cover: WechatCover | None,
    ) -> WechatResult: ...

    async def publish(self, *, account_ref: str, media_id: str) -> WechatResult: ...

    async def reconcile(
        self, *, operation_type: str, external_id: str, account_ref: str
    ) -> WechatResult: ...

    async def refresh_account(self, *, account_ref: str) -> WechatResult: ...


class UnconfiguredWechatProvider:
    async def authorization_url(self, *, state: str, redirect_uri: str) -> str:
        raise ProviderUnavailable("WeChat third-party platform is not configured")

    async def create_or_update_draft(
        self,
        *,
        account_ref: str,
        html: str,
        title: str,
        digest: str,
        cover: WechatCover | None,
    ) -> WechatResult:
        raise ProviderUnavailable("WeChat third-party platform is not configured")

    async def publish(self, *, account_ref: str, media_id: str) -> WechatResult:
        raise ProviderUnavailable("WeChat third-party platform is not configured")

    async def reconcile(
        self, *, operation_type: str, external_id: str, account_ref: str
    ) -> WechatResult:
        raise ProviderUnavailable("WeChat third-party platform is not configured")

    async def refresh_account(self, *, account_ref: str) -> WechatResult:
        raise ProviderUnavailable("WeChat third-party platform is not configured")

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.local_document_processing import BuiltInDocumentScanner, LocalDocumentProcessingProvider
from app.model_content_safety import ModelContentSafetyProvider
from app.production_providers import (
    HttpDocumentProcessingProvider,
    HttpLayoutExtractionProvider,
    HttpRerankProvider,
    HttpVerificationProvider,
    HttpWechatGatewayProvider,
    OpenAICompatibleEmbeddingProvider,
    OpenAICompatibleModelProvider,
    OpenAIModerationProvider,
    S3StorageProvider,
    SignedJsonClient,
)
from app.providers import (
    ContentSafetyProvider,
    DocumentProcessingProvider,
    EmbeddingProvider,
    EnvironmentSecretProvider,
    LayoutExtractionProvider,
    ModelProvider,
    ProviderUnavailable,
    RerankProvider,
    SecretProvider,
    StorageProvider,
    UnconfiguredContentSafetyProvider,
    UnconfiguredDocumentProcessingProvider,
    UnconfiguredEmbeddingProvider,
    UnconfiguredModelProvider,
    UnconfiguredRerankProvider,
    UnconfiguredStorageProvider,
    UnconfiguredVerificationProvider,
    VerificationProvider,
    WebReferenceProvider,
    WechatProvider,
)
from app.web_references import SafeHttpWebReferenceProvider
from app.wechat_open_platform import DirectWechatProvider
from app.wechat_public_layout import WeChatPublicLayoutExtractionProvider


@dataclass(frozen=True, slots=True)
class ProviderBundle:
    model: ModelProvider
    embedding: EmbeddingProvider
    rerank: RerankProvider
    content_safety: ContentSafetyProvider
    verification: VerificationProvider
    storage: StorageProvider
    document_processing: DocumentProcessingProvider
    layout_extraction: LayoutExtractionProvider
    wechat: WechatProvider
    web_reference: WebReferenceProvider


def _required(value: str, name: str) -> str:
    if not value:
        raise ProviderUnavailable(f"{name} is required for the selected provider")
    return value


def _secret(provider: SecretProvider, reference: str, name: str) -> str:
    return provider.resolve(_required(reference, name))


def build_providers(
    settings: Settings, secret_provider: SecretProvider | None = None
) -> ProviderBundle:
    secrets = secret_provider or EnvironmentSecretProvider()
    layout_extraction = _build_layout_extraction(settings, secrets)
    if settings.model_provider_mode not in {"openai_compatible", "openai"}:
        raise ProviderUnavailable("MODEL_PROVIDER_MODE must be openai_compatible or openai")
    try:
        model: ModelProvider = OpenAICompatibleModelProvider(
            api_base=_required(settings.model_api_base, "MODEL_API_BASE"),
            api_key=_secret(secrets, settings.model_api_key_ref, "MODEL_API_KEY_REF"),
            model=_required(settings.model_name, "MODEL_NAME"),
            api_style=settings.model_api_style,
            timeout_seconds=settings.model_timeout_seconds,
        )
    except ProviderUnavailable:
        if settings.environment == "production":
            raise
        model = UnconfiguredModelProvider()
    if settings.embedding_provider_mode not in {"openai", "openai_compatible"}:
        raise ProviderUnavailable("EMBEDDING_PROVIDER_MODE must be openai or openai_compatible")
    try:
        embedding: EmbeddingProvider = OpenAICompatibleEmbeddingProvider(
            api_base=_required(settings.embedding_api_base, "EMBEDDING_API_BASE"),
            api_key=_secret(secrets, settings.embedding_api_key_ref, "EMBEDDING_API_KEY_REF"),
            model=_required(settings.embedding_model, "EMBEDDING_MODEL"),
            dimension=settings.embedding_dimension,
        )
    except ProviderUnavailable:
        if settings.environment == "production":
            raise
        embedding = UnconfiguredEmbeddingProvider()
    if settings.rerank_provider_mode not in {"http", "openai_compatible"}:
        raise ProviderUnavailable("RERANK_PROVIDER_MODE must be http or openai_compatible")
    try:
        rerank: RerankProvider = HttpRerankProvider(
            api_base=_required(settings.rerank_api_base, "RERANK_API_BASE"),
            api_key=_secret(secrets, settings.rerank_api_key_ref, "RERANK_API_KEY_REF"),
            model=_required(settings.rerank_model, "RERANK_MODEL"),
        )
    except ProviderUnavailable:
        if settings.environment == "production":
            raise
        rerank = UnconfiguredRerankProvider()
    if settings.content_safety_provider_mode == "model":
        content_safety: ContentSafetyProvider = ModelContentSafetyProvider(model)
    elif settings.content_safety_provider_mode not in {"openai", "openai_compatible"}:
        raise ProviderUnavailable(
            "CONTENT_SAFETY_PROVIDER_MODE must be model, openai or openai_compatible"
        )
    else:
        try:
            content_safety = OpenAIModerationProvider(
                api_base=_required(settings.content_safety_api_base, "CONTENT_SAFETY_API_BASE"),
                api_key=_secret(
                    secrets,
                    settings.content_safety_api_key_ref,
                    "CONTENT_SAFETY_API_KEY_REF",
                ),
                model=settings.content_safety_model,
            )
        except ProviderUnavailable:
            if settings.environment == "production":
                raise
            content_safety = UnconfiguredContentSafetyProvider()
    if settings.verification_provider_mode == "disabled":
        verification: VerificationProvider = UnconfiguredVerificationProvider()
    elif settings.verification_provider_mode == "http":
        try:
            verification = HttpVerificationProvider(
                _signed_client(
                    settings.verification_service_url,
                    settings.verification_secret_ref,
                    "VERIFICATION",
                    secrets,
                )
            )
        except ProviderUnavailable:
            if settings.environment == "production":
                raise
            verification = UnconfiguredVerificationProvider()
    else:
        raise ProviderUnavailable("VERIFICATION_PROVIDER_MODE must be disabled or http")
    if settings.storage_provider_mode != "s3":
        raise ProviderUnavailable("STORAGE_PROVIDER_MODE must be s3")
    try:
        storage: StorageProvider = S3StorageProvider(
            endpoint_url=_required(settings.object_storage_endpoint, "OBJECT_STORAGE_ENDPOINT"),
            bucket=_required(settings.object_storage_bucket, "OBJECT_STORAGE_BUCKET"),
            region=settings.object_storage_region,
            access_key=_secret(
                secrets,
                settings.object_storage_access_key_ref,
                "OBJECT_STORAGE_ACCESS_KEY_REF",
            ),
            secret_key=_secret(
                secrets,
                settings.object_storage_secret_key_ref,
                "OBJECT_STORAGE_SECRET_KEY_REF",
            ),
            presign_seconds=settings.object_storage_presign_seconds,
        )
    except ProviderUnavailable:
        if settings.environment == "production":
            raise
        storage = UnconfiguredStorageProvider()
    if settings.document_provider_mode == "local":
        document: DocumentProcessingProvider = LocalDocumentProcessingProvider(
            storage,
            BuiltInDocumentScanner(),
        )
    elif settings.document_provider_mode == "http":
        try:
            document = HttpDocumentProcessingProvider(
                _signed_client(
                    settings.document_service_url,
                    settings.document_service_secret_ref,
                    "DOCUMENT",
                    secrets,
                )
            )
        except ProviderUnavailable:
            if settings.environment == "production":
                raise
            document = UnconfiguredDocumentProcessingProvider()
    else:
        raise ProviderUnavailable("DOCUMENT_PROVIDER_MODE must be local or http")
    return ProviderBundle(
        model=model,
        embedding=embedding,
        rerank=rerank,
        content_safety=content_safety,
        verification=verification,
        storage=storage,
        document_processing=document,
        layout_extraction=layout_extraction,
        wechat=_build_wechat(settings, secrets),
        web_reference=SafeHttpWebReferenceProvider(),
    )


def _build_layout_extraction(
    settings: Settings, secrets: SecretProvider
) -> LayoutExtractionProvider:
    if settings.layout_provider_mode == "wechat_public":
        return WeChatPublicLayoutExtractionProvider(
            timeout_seconds=settings.model_timeout_seconds,
        )
    if settings.layout_provider_mode == "http":
        return HttpLayoutExtractionProvider(
            _signed_client(
                settings.layout_service_url,
                settings.layout_service_secret_ref,
                "LAYOUT",
                secrets,
            )
        )
    raise ProviderUnavailable("LAYOUT_PROVIDER_MODE must be wechat_public or http")


def _signed_client(
    url: str,
    secret_reference: str,
    prefix: str,
    secrets: SecretProvider,
) -> SignedJsonClient:
    return SignedJsonClient(
        base_url=_required(url, f"{prefix}_SERVICE_URL"),
        secret=_secret(secrets, secret_reference, f"{prefix}_SECRET_REF"),
    )


def _build_wechat(settings: Settings, secrets: SecretProvider) -> WechatProvider:
    if settings.wechat_provider_mode == "direct":
        return DirectWechatProvider(secrets)
    if settings.wechat_provider_mode not in {"http_gateway", "configured"}:
        raise ProviderUnavailable("WECHAT_PROVIDER_MODE must be direct or http_gateway")
    return HttpWechatGatewayProvider(
        SignedJsonClient(
            base_url=_required(settings.wechat_gateway_url, "WECHAT_GATEWAY_URL"),
            secret=_secret(
                secrets, settings.wechat_gateway_secret_ref, "WECHAT_GATEWAY_SECRET_REF"
            ),
        )
    )

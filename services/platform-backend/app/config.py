from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit

IOS_WEBVIEW_ORIGIN = "capacitor://localhost"
DEFAULT_DATABASE_URL = "postgresql+asyncpg://localhost:5432/wechat_ai"
DEFAULT_RETRIEVAL_DATABASE_URL = "postgresql+asyncpg://localhost:5433/wechat_ai_retrieval"


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    return default if value is None else value.lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    value = os.getenv(name)
    return default if value is None else int(value)


def _float(name: str, default: float) -> float:
    value = os.getenv(name)
    return default if value is None else float(value)


@dataclass(frozen=True, slots=True)
class Settings:
    environment: str = "development"
    database_url: str = DEFAULT_DATABASE_URL
    retrieval_database_url: str = ""
    token_secret: str = "development-only-change-me-please"
    model_secret_master_key: str = ""
    access_token_ttl_seconds: int = 604_800
    refresh_token_ttl_seconds: int = 604_800
    admin_access_token_ttl_seconds: int = 600
    admin_session_ttl_seconds: int = 28_800
    cookie_secure: bool = False
    auto_create_schema: bool = False
    mock_external_services: bool = True
    inline_mock_workers: bool = False
    celery_broker_url: str = "amqp://guest:guest@localhost:5672//"
    celery_result_backend: str = "redis://localhost:6379/1"
    model_provider_mode: str = "mock"
    model_api_style: str = "responses"
    model_api_base: str = ""
    model_api_key_ref: str = ""
    model_name: str = ""
    model_timeout_seconds: float = 120.0
    embedding_provider_mode: str = "mock"
    embedding_api_base: str = ""
    embedding_api_key_ref: str = ""
    embedding_model: str = ""
    embedding_dimension: int = 1024
    rerank_provider_mode: str = "mock"
    rerank_api_base: str = ""
    rerank_api_key_ref: str = ""
    rerank_model: str = ""
    chunk_target_characters: int = 800
    chunk_overlap_characters: int = 120
    chunking_version: str = "zh-char-v1"
    external_knowledge_sync_interval_seconds: int = 21_600
    content_safety_provider_mode: str = "mock"
    content_safety_api_base: str = ""
    content_safety_api_key_ref: str = ""
    content_safety_model: str = "omni-moderation-latest"
    verification_provider_mode: str = "mock"
    verification_service_url: str = ""
    verification_secret_ref: str = ""
    storage_provider_mode: str = "mock"
    object_storage_endpoint: str = ""
    object_storage_bucket: str = ""
    object_storage_region: str = "us-east-1"
    object_storage_access_key_ref: str = ""
    object_storage_secret_key_ref: str = ""
    object_storage_presign_seconds: int = 3600
    document_provider_mode: str = "mock"
    document_service_url: str = ""
    document_service_secret_ref: str = ""
    layout_provider_mode: str = "wechat_public"
    layout_service_url: str = ""
    layout_service_secret_ref: str = ""
    wechat_provider_mode: str = "mock"
    wechat_gateway_url: str = ""
    wechat_gateway_secret_ref: str = ""
    wechat_component_app_id: str = ""
    wechat_component_app_secret: str = ""
    wechat_message_token: str = ""
    wechat_encoding_aes_key: str = ""
    wechat_public_base_url: str = ""
    wechat_authorization_callback_url: str = ""
    wechat_ticket_callback_url: str = ""
    wechat_domain_verification_filename: str = ""
    wechat_domain_verification_content: str = ""
    verification_code_ttl_seconds: int = 600
    default_quota_balance: int = 500
    allowed_origins: tuple[str, ...] = (
        "http://localhost:9000",
        "http://127.0.0.1:9000",
        "http://localhost:9001",
        "http://localhost:9003",
        "http://127.0.0.1:9003",
        "http://localhost:9004",
        "http://127.0.0.1:9004",
    )

    @classmethod
    def from_env(cls) -> Settings:
        origins = tuple(
            origin.strip()
            for origin in os.getenv(
                "ALLOWED_ORIGINS",
                "http://localhost:9000,http://127.0.0.1:9000,http://localhost:9001,"
                "http://localhost:9003,"
                "http://127.0.0.1:9003,http://localhost:9004,http://127.0.0.1:9004",
            ).split(",")
            if origin.strip()
        )
        wechat_public_base_url = os.getenv("WECHAT_PUBLIC_BASE_URL", "").rstrip("/")
        if wechat_public_base_url and wechat_public_base_url not in origins:
            origins = (*origins, wechat_public_base_url)
        settings = cls(
            environment=os.getenv("APP_ENV", "development"),
            database_url=os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL),
            retrieval_database_url=os.getenv(
                "RETRIEVAL_DATABASE_URL",
                "" if os.getenv("APP_ENV") == "test" else DEFAULT_RETRIEVAL_DATABASE_URL,
            ),
            token_secret=os.getenv("TOKEN_SECRET", "development-only-change-me-please"),
            model_secret_master_key=os.getenv("MODEL_SECRET_MASTER_KEY", ""),
            access_token_ttl_seconds=_int("ACCESS_TOKEN_TTL_SECONDS", 604_800),
            refresh_token_ttl_seconds=_int("REFRESH_TOKEN_TTL_SECONDS", 604_800),
            admin_access_token_ttl_seconds=_int("ADMIN_ACCESS_TOKEN_TTL_SECONDS", 600),
            admin_session_ttl_seconds=_int("ADMIN_SESSION_TTL_SECONDS", 28_800),
            cookie_secure=_bool("COOKIE_SECURE", False),
            auto_create_schema=_bool("AUTO_CREATE_SCHEMA", False),
            mock_external_services=_bool("MOCK_EXTERNAL_SERVICES", True),
            inline_mock_workers=_bool("INLINE_MOCK_WORKERS", False),
            celery_broker_url=os.getenv("CELERY_BROKER_URL", "amqp://guest:guest@localhost:5672//"),
            celery_result_backend=os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1"),
            model_provider_mode=os.getenv("MODEL_PROVIDER_MODE", "mock"),
            model_api_style=os.getenv("MODEL_API_STYLE", "responses"),
            model_api_base=os.getenv("MODEL_API_BASE", ""),
            model_api_key_ref=os.getenv("MODEL_API_KEY_REF", ""),
            model_name=os.getenv("MODEL_NAME", ""),
            model_timeout_seconds=_float("MODEL_TIMEOUT_SECONDS", 120.0),
            embedding_provider_mode=os.getenv("EMBEDDING_PROVIDER_MODE", "mock"),
            embedding_api_base=os.getenv("EMBEDDING_API_BASE", ""),
            embedding_api_key_ref=os.getenv("EMBEDDING_API_KEY_REF", ""),
            embedding_model=os.getenv("EMBEDDING_MODEL", ""),
            embedding_dimension=_int("EMBEDDING_DIMENSION", 1024),
            rerank_provider_mode=os.getenv("RERANK_PROVIDER_MODE", "mock"),
            rerank_api_base=os.getenv("RERANK_API_BASE", ""),
            rerank_api_key_ref=os.getenv("RERANK_API_KEY_REF", ""),
            rerank_model=os.getenv("RERANK_MODEL", ""),
            chunk_target_characters=_int("CHUNK_TARGET_CHARACTERS", 800),
            chunk_overlap_characters=_int("CHUNK_OVERLAP_CHARACTERS", 120),
            chunking_version=os.getenv("CHUNKING_VERSION", "zh-char-v1"),
            external_knowledge_sync_interval_seconds=_int(
                "EXTERNAL_KNOWLEDGE_SYNC_INTERVAL_SECONDS", 21_600
            ),
            content_safety_provider_mode=os.getenv("CONTENT_SAFETY_PROVIDER_MODE", "mock"),
            content_safety_api_base=os.getenv("CONTENT_SAFETY_API_BASE", ""),
            content_safety_api_key_ref=os.getenv("CONTENT_SAFETY_API_KEY_REF", ""),
            content_safety_model=os.getenv("CONTENT_SAFETY_MODEL", "omni-moderation-latest"),
            verification_provider_mode=os.getenv("VERIFICATION_PROVIDER_MODE", "mock"),
            verification_service_url=os.getenv("VERIFICATION_SERVICE_URL", ""),
            verification_secret_ref=os.getenv("VERIFICATION_SECRET_REF", ""),
            storage_provider_mode=os.getenv("STORAGE_PROVIDER_MODE", "mock"),
            object_storage_endpoint=os.getenv(
                "OBJECT_STORAGE_ENDPOINT", os.getenv("S3_ENDPOINT", "")
            ),
            object_storage_bucket=os.getenv(
                "OBJECT_STORAGE_BUCKET", os.getenv("S3_BUCKET_QUARANTINE", "")
            ),
            object_storage_region=os.getenv(
                "OBJECT_STORAGE_REGION", os.getenv("S3_REGION", "us-east-1")
            ),
            object_storage_access_key_ref=os.getenv(
                "OBJECT_STORAGE_ACCESS_KEY_REF", "env:S3_ACCESS_KEY"
            ),
            object_storage_secret_key_ref=os.getenv(
                "OBJECT_STORAGE_SECRET_KEY_REF", "env:S3_SECRET_KEY"
            ),
            object_storage_presign_seconds=_int("OBJECT_STORAGE_PRESIGN_SECONDS", 3600),
            document_provider_mode=os.getenv("DOCUMENT_PROVIDER_MODE", "mock"),
            document_service_url=os.getenv("DOCUMENT_SERVICE_URL", ""),
            document_service_secret_ref=os.getenv("DOCUMENT_SERVICE_SECRET_REF", ""),
            layout_provider_mode=os.getenv("LAYOUT_PROVIDER_MODE", "wechat_public"),
            layout_service_url=os.getenv("LAYOUT_SERVICE_URL", ""),
            layout_service_secret_ref=os.getenv("LAYOUT_SERVICE_SECRET_REF", ""),
            wechat_provider_mode=os.getenv("WECHAT_PROVIDER_MODE", "mock"),
            wechat_gateway_url=os.getenv("WECHAT_GATEWAY_URL", ""),
            wechat_gateway_secret_ref=os.getenv("WECHAT_GATEWAY_SECRET_REF", ""),
            wechat_component_app_id=os.getenv("WECHAT_COMPONENT_APP_ID", ""),
            wechat_component_app_secret=os.getenv("WECHAT_COMPONENT_APP_SECRET", ""),
            wechat_message_token=os.getenv("WECHAT_MESSAGE_TOKEN", ""),
            wechat_encoding_aes_key=os.getenv("WECHAT_ENCODING_AES_KEY", ""),
            wechat_public_base_url=wechat_public_base_url,
            wechat_authorization_callback_url=os.getenv(
                "WECHAT_AUTHORIZATION_CALLBACK_URL", ""
            )
            or (
                f"{wechat_public_base_url}/callbacks/v1/wechat/authorize"
                if wechat_public_base_url
                else ""
            ),
            wechat_ticket_callback_url=os.getenv("WECHAT_TICKET_CALLBACK_URL", "")
            or (
                f"{wechat_public_base_url}/callbacks/v1/wechat/tickets"
                if wechat_public_base_url
                else ""
            ),
            wechat_domain_verification_filename=os.getenv(
                "WECHAT_DOMAIN_VERIFICATION_FILENAME", ""
            ),
            wechat_domain_verification_content=os.getenv(
                "WECHAT_DOMAIN_VERIFICATION_CONTENT", ""
            ),
            verification_code_ttl_seconds=_int("VERIFICATION_CODE_TTL_SECONDS", 600),
            default_quota_balance=_int("DEFAULT_QUOTA_BALANCE", 500),
            allowed_origins=origins,
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.environment != "test":
            if not self.database_url.startswith("postgresql+asyncpg://"):
                raise RuntimeError("DATABASE_URL must use PostgreSQL with asyncpg outside tests")
            if (
                not self.retrieval_database_url.startswith("postgresql+asyncpg://")
                or self.retrieval_database_url == self.database_url
            ):
                raise RuntimeError("RETRIEVAL_DATABASE_URL must use a separate PostgreSQL database")
        if self.wechat_provider_mode not in {"mock", "direct", "http_gateway", "configured"}:
            raise RuntimeError("WECHAT_PROVIDER_MODE must be mock, direct, or http_gateway")
        direct_wechat = {
            "WECHAT_COMPONENT_APP_ID": self.wechat_component_app_id,
            "WECHAT_COMPONENT_APP_SECRET": self.wechat_component_app_secret,
            "WECHAT_MESSAGE_TOKEN": self.wechat_message_token,
            "WECHAT_ENCODING_AES_KEY": self.wechat_encoding_aes_key,
            "WECHAT_AUTHORIZATION_CALLBACK_URL": self.wechat_authorization_callback_url,
            "WECHAT_TICKET_CALLBACK_URL": self.wechat_ticket_callback_url,
        }
        if self.wechat_provider_mode == "direct" and any(direct_wechat.values()):
            missing_wechat = [name for name, value in direct_wechat.items() if not value]
            if missing_wechat:
                raise RuntimeError(
                    "Direct WeChat environment configuration is incomplete: "
                    + ", ".join(missing_wechat)
                )
            if len(self.wechat_encoding_aes_key) != 43:
                raise RuntimeError("WECHAT_ENCODING_AES_KEY must contain 43 characters")
            if not 3 <= len(self.wechat_message_token) <= 32:
                raise RuntimeError("WECHAT_MESSAGE_TOKEN must contain 3 to 32 characters")
        if self.wechat_public_base_url:
            public_url = urlsplit(self.wechat_public_base_url)
            if (
                public_url.scheme != "https"
                or not public_url.hostname
                or public_url.username
                or public_url.password
                or public_url.query
                or public_url.fragment
                or public_url.path not in {"", "/"}
            ):
                raise RuntimeError("WECHAT_PUBLIC_BASE_URL must be an HTTPS origin")
        verification_values = (
            self.wechat_domain_verification_filename,
            self.wechat_domain_verification_content,
        )
        if any(verification_values) and not all(verification_values):
            raise RuntimeError(
                "WECHAT_DOMAIN_VERIFICATION_FILENAME and "
                "WECHAT_DOMAIN_VERIFICATION_CONTENT must be configured together"
            )
        if self.wechat_domain_verification_filename and (
            not self.wechat_domain_verification_filename.startswith("MP_verify_")
            or not self.wechat_domain_verification_filename.endswith(".txt")
            or not self.wechat_domain_verification_filename.removesuffix(".txt")
            .removeprefix("MP_verify_")
            .replace("-", "")
            .replace("_", "")
            .isalnum()
        ):
            raise RuntimeError("WECHAT_DOMAIN_VERIFICATION_FILENAME is invalid")
        if len(self.wechat_domain_verification_content) > 512:
            raise RuntimeError("WECHAT_DOMAIN_VERIFICATION_CONTENT is too long")
        if self.model_api_style not in {"responses", "chat_completions"}:
            raise RuntimeError("MODEL_API_STYLE must be responses or chat_completions")
        if self.model_timeout_seconds <= 0:
            raise RuntimeError("MODEL_TIMEOUT_SECONDS must be positive")
        if not 1 <= self.embedding_dimension <= 8192:
            raise RuntimeError("EMBEDDING_DIMENSION must be between 1 and 8192")
        if not 200 <= self.chunk_target_characters <= 4000:
            raise RuntimeError("CHUNK_TARGET_CHARACTERS must be between 200 and 4000")
        if not 0 <= self.chunk_overlap_characters < self.chunk_target_characters:
            raise RuntimeError("CHUNK_OVERLAP_CHARACTERS must be smaller than chunk target")
        if not 300 <= self.external_knowledge_sync_interval_seconds <= 604_800:
            raise RuntimeError(
                "EXTERNAL_KNOWLEDGE_SYNC_INTERVAL_SECONDS must be between 300 and 604800"
            )
        if not 60 <= self.object_storage_presign_seconds <= 86_400:
            raise RuntimeError("OBJECT_STORAGE_PRESIGN_SECONDS must be between 60 and 86400")
        if self.environment == "production":
            if self.wechat_provider_mode == "direct" and any(direct_wechat.values()):
                if not self.wechat_authorization_callback_url.startswith("https://") or not (
                    self.wechat_ticket_callback_url.startswith("https://")
                ):
                    raise RuntimeError("Production WeChat callback URLs must use HTTPS")
            if len(self.model_secret_master_key) < 32:
                raise RuntimeError("MODEL_SECRET_MASTER_KEY must be a strong production secret")
            if (
                self.token_secret == "development-only-change-me-please"
                or len(self.token_secret) < 32
            ):
                raise RuntimeError("TOKEN_SECRET must be a strong production secret")
            if not self.cookie_secure:
                raise RuntimeError("COOKIE_SECURE must be true in production")
            if self.auto_create_schema:
                raise RuntimeError("Production schema changes must run through Alembic")
            if not self.database_url.startswith("postgresql+asyncpg://"):
                raise RuntimeError("Production DATABASE_URL must use PostgreSQL with asyncpg")
            modes = {
                "MODEL_PROVIDER_MODE": self.model_provider_mode,
                "CONTENT_SAFETY_PROVIDER_MODE": self.content_safety_provider_mode,
                "EMBEDDING_PROVIDER_MODE": self.embedding_provider_mode,
                "RERANK_PROVIDER_MODE": self.rerank_provider_mode,
                "VERIFICATION_PROVIDER_MODE": self.verification_provider_mode,
                "STORAGE_PROVIDER_MODE": self.storage_provider_mode,
                "DOCUMENT_PROVIDER_MODE": self.document_provider_mode,
                "LAYOUT_PROVIDER_MODE": self.layout_provider_mode,
                "WECHAT_PROVIDER_MODE": self.wechat_provider_mode,
            }
            if self.mock_external_services or any(mode == "mock" for mode in modes.values()):
                raise RuntimeError("Mock providers must not run in the production environment")
            required = {
                "MODEL_API_BASE": self.model_api_base,
                "MODEL_API_KEY_REF": self.model_api_key_ref,
                "MODEL_NAME": self.model_name,
                "EMBEDDING_API_BASE": self.embedding_api_base,
                "EMBEDDING_API_KEY_REF": self.embedding_api_key_ref,
                "EMBEDDING_MODEL": self.embedding_model,
                "RERANK_API_BASE": self.rerank_api_base,
                "RERANK_API_KEY_REF": self.rerank_api_key_ref,
                "RERANK_MODEL": self.rerank_model,
                "CONTENT_SAFETY_API_BASE": self.content_safety_api_base,
                "CONTENT_SAFETY_API_KEY_REF": self.content_safety_api_key_ref,
                "VERIFICATION_SERVICE_URL": self.verification_service_url,
                "VERIFICATION_SECRET_REF": self.verification_secret_ref,
                "OBJECT_STORAGE_ENDPOINT": self.object_storage_endpoint,
                "OBJECT_STORAGE_BUCKET": self.object_storage_bucket,
                "OBJECT_STORAGE_ACCESS_KEY_REF": self.object_storage_access_key_ref,
                "OBJECT_STORAGE_SECRET_KEY_REF": self.object_storage_secret_key_ref,
                "DOCUMENT_SERVICE_URL": self.document_service_url,
                "DOCUMENT_SERVICE_SECRET_REF": self.document_service_secret_ref,
                **(
                    {
                        "LAYOUT_SERVICE_URL": self.layout_service_url,
                        "LAYOUT_SERVICE_SECRET_REF": self.layout_service_secret_ref,
                    }
                    if self.layout_provider_mode == "http"
                    else {}
                ),
                **(
                    {
                        "WECHAT_GATEWAY_URL": self.wechat_gateway_url,
                        "WECHAT_GATEWAY_SECRET_REF": self.wechat_gateway_secret_ref,
                    }
                    if self.wechat_provider_mode in {"http_gateway", "configured"}
                    else {}
                ),
            }
            missing = [name for name, value in required.items() if not value]
            if missing:
                raise RuntimeError(
                    "Production provider configuration is incomplete: " + ", ".join(missing)
                )
            if (
                not self.retrieval_database_url.startswith("postgresql+asyncpg://")
                or self.retrieval_database_url == self.database_url
            ):
                raise RuntimeError(
                    "Production RETRIEVAL_DATABASE_URL must be a separate PostgreSQL database"
                )
            if self.embedding_dimension != 1024:
                raise RuntimeError(
                    "Production EMBEDDING_DIMENSION must match retrieval halfvec(1024)"
                )
            if any(
                origin == "*"
                or (not origin.startswith("https://") and origin != IOS_WEBVIEW_ORIGIN)
                for origin in self.allowed_origins
            ):
                raise RuntimeError(
                    "Production ALLOWED_ORIGINS must be explicit HTTPS origins or "
                    f"the exact iOS WebView origin {IOS_WEBVIEW_ORIGIN}"
                )

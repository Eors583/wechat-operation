from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.security import new_uuid


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class IdMixin:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        server_default=func.now(),
        onupdate=utcnow,
        nullable=False,
    )


class OwnerMixin:
    owner_type: Mapped[str] = mapped_column(String(16), default="user", nullable=False)
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)


class User(Base, IdMixin, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("status IN ('active','disabled','pending')", name="ck_users_status"),
    )

    phone: Mapped[str | None] = mapped_column(String(32), unique=True)
    email: Mapped[str | None] = mapped_column(String(320), unique=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    theme_preference: Mapped[str] = mapped_column(String(16), default="system", nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthIdentity(Base, IdMixin, TimestampMixin):
    __tablename__ = "auth_identities"
    __table_args__ = (
        UniqueConstraint("provider", "provider_subject", name="uq_auth_identity_subject"),
    )

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_subject: Mapped[str] = mapped_column(String(320), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VerificationChallenge(Base, IdMixin, TimestampMixin):
    __tablename__ = "verification_challenges"
    __table_args__ = (Index("ix_verification_destination_created", "destination", "created_at"),)

    destination: Mapped[str] = mapped_column(String(320), nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RefreshToken(Base, IdMixin, TimestampMixin):
    __tablename__ = "refresh_tokens"
    __table_args__ = (Index("ix_refresh_family", "family_id"),)

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    family_id: Mapped[str] = mapped_column(String(36), nullable=False)
    device_name: Mapped[str | None] = mapped_column(String(120))
    platform: Mapped[str] = mapped_column(String(32), default="web", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by_id: Mapped[str | None] = mapped_column(String(36))


class AccountDeletionRequest(Base, IdMixin):
    __tablename__ = "account_deletion_requests"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_account_deletion_user"),
        CheckConstraint(
            "status IN ('scheduled','processing','completed','failed')",
            name="ck_account_deletion_status",
        ),
        Index("ix_account_deletion_due", "status", "purge_after"),
    )

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="scheduled", nullable=False)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )
    purge_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)


class Admin(Base, IdMixin, TimestampMixin):
    __tablename__ = "admins"
    __table_args__ = (CheckConstraint("status IN ('active','disabled')", name="ck_admins_status"),)

    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    permissions: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AdminSession(Base, IdMixin, TimestampMixin):
    __tablename__ = "admin_sessions"

    admin_id: Mapped[str] = mapped_column(String(36), ForeignKey("admins.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    device_name: Mapped[str | None] = mapped_column(String(120))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QuotaAccount(Base, IdMixin, TimestampMixin, OwnerMixin):
    __tablename__ = "quota_accounts"
    __table_args__ = (
        UniqueConstraint("owner_type", "owner_id", name="uq_quota_owner"),
        CheckConstraint("balance >= 0", name="ck_quota_balance_nonnegative"),
    )

    balance: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class QuotaLedger(Base, IdMixin):
    __tablename__ = "quota_ledger"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "business_type", "business_id", "direction", name="uq_quota_action"
        ),
        CheckConstraint("amount > 0", name="ck_quota_amount_positive"),
    )

    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("quota_accounts.id"), nullable=False
    )
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    business_type: Mapped[str] = mapped_column(String(64), nullable=False)
    business_id: Mapped[str] = mapped_column(String(80), nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )


class ResourceLimit(Base, IdMixin, TimestampMixin, OwnerMixin):
    __tablename__ = "resource_limits"
    __table_args__ = (UniqueConstraint("owner_type", "owner_id", name="uq_resource_limit_owner"),)

    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    wechat_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    storage_bytes: Mapped[int] = mapped_column(BigInteger, default=5_368_709_120, nullable=False)
    single_file_bytes: Mapped[int] = mapped_column(BigInteger, default=104_857_600, nullable=False)
    official_account_count: Mapped[int] = mapped_column(Integer, default=5, nullable=False)


class Project(Base, IdMixin, TimestampMixin, OwnerMixin):
    __tablename__ = "projects"
    __table_args__ = (Index("ix_projects_owner_sort", "owner_id", "sort_order"),)

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    writing_requirements: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Task(Base, IdMixin, TimestampMixin, OwnerMixin):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_owner_last_message", "owner_id", "last_message_at", "id"),
        CheckConstraint("status IN ('active','archived','deleted')", name="ck_tasks_status"),
    )

    project_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("projects.id"))
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    current_article_id: Mapped[str | None] = mapped_column(String(36))
    current_skill_id: Mapped[str | None] = mapped_column(String(36))
    use_preferences: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Message(Base, IdMixin):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("task_id", "client_message_id", name="uq_message_client_id"),
        Index("ix_messages_task_created", "task_id", "created_at", "id"),
    )

    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    plain_text: Mapped[str] = mapped_column(Text, nullable=False)
    client_message_id: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )


class AIRun(Base, IdMixin, TimestampMixin):
    __tablename__ = "ai_runs"
    __table_args__ = (
        UniqueConstraint("owner_id", "idempotency_key", name="uq_ai_run_owner_idem"),
        Index("ix_ai_runs_owner_status_created", "owner_id", "status", "created_at"),
    )

    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id"), nullable=False)
    run_type: Mapped[str] = mapped_column(String(40), default="conversation", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="accepted", nullable=False)
    model_route_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    prompt_version_id: Mapped[str | None] = mapped_column(String(36))
    skill_version_id: Mapped[str | None] = mapped_column(String(36))
    context_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    quota_reserved: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AIRunAttempt(Base, IdMixin):
    __tablename__ = "ai_run_attempts"
    __table_args__ = (UniqueConstraint("run_id", "attempt_no", name="uq_ai_attempt_no"),)

    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("ai_runs.id"), nullable=False)
    deployment_id: Mapped[str | None] = mapped_column(String(36))
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    purpose: Mapped[str | None] = mapped_column(String(80))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=0, nullable=False)
    provider_request_id: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )


class AIRunEvent(Base, IdMixin):
    __tablename__ = "ai_run_events"
    __table_args__ = (
        UniqueConstraint("run_id", "seq", name="uq_ai_event_seq"),
        Index("ix_ai_events_run_seq", "run_id", "seq"),
    )

    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("ai_runs.id"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )


class ContextSnapshot(Base, IdMixin):
    __tablename__ = "context_snapshots"
    __table_args__ = (Index("ix_context_task_created", "task_id", "created_at"),)

    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id"), nullable=False)
    summary_id: Mapped[str | None] = mapped_column(String(36))
    message_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    document_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    preference_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    skill_version_id: Mapped[str | None] = mapped_column(String(36))
    token_budget: Mapped[dict[str, int]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )


class Asset(Base, IdMixin, TimestampMixin, OwnerMixin):
    __tablename__ = "assets"
    __table_args__ = (
        UniqueConstraint("object_key", name="uq_asset_object_key"),
        Index("ix_assets_owner_hash_size", "owner_id", "sha256", "size_bytes"),
    )

    project_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("projects.id"))
    task_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("tasks.id"))
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(150), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    object_key: Mapped[str] = mapped_column(String(500), nullable=False)
    scan_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UploadSession(Base, IdMixin, TimestampMixin):
    __tablename__ = "upload_sessions"

    asset_id: Mapped[str] = mapped_column(String(36), ForeignKey("assets.id"), nullable=False)
    provider_upload_id: Mapped[str] = mapped_column(String(180), unique=True, nullable=False)
    part_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Document(Base, IdMixin, TimestampMixin, OwnerMixin):
    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_owner_project_status", "owner_id", "project_id", "status"),
    )

    asset_id: Mapped[str] = mapped_column(String(36), ForeignKey("assets.id"), nullable=False)
    project_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("projects.id"))
    source_type: Mapped[str] = mapped_column(String(32), default="upload", nullable=False)
    external_source_id: Mapped[str | None] = mapped_column(String(180))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    parser_version: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(40), default="queued", nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer)
    normalized_object_key: Mapped[str | None] = mapped_column(String(500))
    extracted_text: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(80))


class DocumentSection(Base, IdMixin):
    __tablename__ = "document_sections"
    __table_args__ = (
        UniqueConstraint("document_id", "sort_order", name="uq_document_section_order"),
    )

    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id"), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(String(36))
    section_type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255))
    text: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    page_no: Mapped[int | None] = mapped_column(Integer)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)


class DocumentChunk(Base, IdMixin, OwnerMixin):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_no", name="uq_document_chunk_no"),
        Index("ix_chunks_owner_project_document", "owner_id", "project_id", "document_id"),
    )

    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id"), nullable=False)
    section_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("document_sections.id"))
    section_title: Mapped[str | None] = mapped_column(String(255))
    project_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("projects.id"))
    page_no: Mapped[int | None] = mapped_column(Integer)
    start_ms: Mapped[int | None] = mapped_column(Integer)
    end_ms: Mapped[int | None] = mapped_column(Integer)
    chunk_no: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    chunking_version: Mapped[str] = mapped_column(String(40), default="zh-char-v1", nullable=False)
    embedding_model: Mapped[str | None] = mapped_column(String(120))
    indexing_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)


class LibraryItem(Base, IdMixin, TimestampMixin, OwnerMixin):
    __tablename__ = "library_items"
    __table_args__ = (
        UniqueConstraint("owner_id", "item_type", "source_id", name="uq_library_source"),
        Index("ix_library_owner_updated", "owner_id", "updated_at", "id"),
        Index("ix_library_owner_project_type", "owner_id", "project_id", "item_type"),
    )

    item_type: Mapped[str] = mapped_column(String(24), nullable=False)
    source_id: Mapped[str] = mapped_column(String(36), nullable=False)
    project_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("projects.id"))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    display_status: Mapped[str] = mapped_column(String(40), nullable=False)
    search_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Article(Base, IdMixin, TimestampMixin, OwnerMixin):
    __tablename__ = "articles"
    __table_args__ = (
        Index("ix_articles_owner_project_status_updated", "owner_id", "project_id", "status"),
    )

    project_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("projects.id"))
    source_task_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("tasks.id"))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="editing", nullable=False)
    current_version_no: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ArticleVersion(Base, IdMixin):
    __tablename__ = "article_versions"
    __table_args__ = (UniqueConstraint("article_id", "version_no", name="uq_article_version_no"),)

    article_id: Mapped[str] = mapped_column(String(36), ForeignKey("articles.id"), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    content_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    plain_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    created_by_type: Mapped[str] = mapped_column(String(16), nullable=False)
    created_by_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )


class ArticleRevision(Base, IdMixin, TimestampMixin):
    __tablename__ = "article_revisions"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "article_id",
            "idempotency_key",
            name="uq_article_revision_owner_article_idem",
        ),
        Index("ix_article_revisions_owner_status_created", "owner_id", "status", "created_at"),
    )

    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    article_id: Mapped[str] = mapped_column(String(36), ForeignKey("articles.id"), nullable=False)
    base_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("article_versions.id"), nullable=False
    )
    base_version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    base_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    selection_from: Mapped[int | None] = mapped_column(Integer)
    selection_to: Mapped[int | None] = mapped_column(Integer)
    selected_text: Mapped[str] = mapped_column(Text, nullable=False)
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="accepted", nullable=False)
    model_route_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    prompt_version_id: Mapped[str | None] = mapped_column(String(36))
    replacement_text: Mapped[str | None] = mapped_column(Text)
    provider_request_id: Mapped[str | None] = mapped_column(String(120))
    quota_reserved: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ArticleAsset(Base, IdMixin):
    __tablename__ = "article_assets"
    __table_args__ = (
        UniqueConstraint("article_version_id", "asset_id", "node_id", name="uq_article_asset_node"),
    )

    article_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("article_versions.id"), nullable=False
    )
    asset_id: Mapped[str] = mapped_column(String(36), ForeignKey("assets.id"), nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    node_id: Mapped[str | None] = mapped_column(String(100))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class LayoutTemplate(Base, IdMixin, TimestampMixin, OwnerMixin):
    __tablename__ = "layout_templates"
    __table_args__ = (Index("ix_layout_account_updated", "official_account_id", "updated_at"),)

    official_account_id: Mapped[str | None] = mapped_column(String(36))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1000))
    extraction_status: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    current_version_no: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LayoutTemplateVersion(Base, IdMixin):
    __tablename__ = "layout_template_versions"
    __table_args__ = (
        UniqueConstraint("template_id", "version_no", name="uq_layout_template_version"),
    )

    template_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("layout_templates.id"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    style_tokens: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    source_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    extractor_version: Mapped[str] = mapped_column(String(40), default="manual-v1", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )


class ArticleRender(Base, IdMixin):
    __tablename__ = "article_renders"
    __table_args__ = (
        UniqueConstraint("owner_id", "checksum", name="uq_article_render_owner_checksum"),
    )

    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    article_id: Mapped[str] = mapped_column(String(36), ForeignKey("articles.id"), nullable=False)
    article_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("article_versions.id"), nullable=False
    )
    template_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("layout_template_versions.id")
    )
    official_account_id: Mapped[str | None] = mapped_column(String(36))
    cover_asset_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("assets.id"))
    html_object_key: Mapped[str | None] = mapped_column(String(500))
    html: Mapped[str] = mapped_column(Text, nullable=False)
    structure: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    compatibility_status: Mapped[str] = mapped_column(String(32), nullable=False)
    stale_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )


class ArticleConfirmation(Base, IdMixin):
    __tablename__ = "article_confirmations"
    __table_args__ = (
        UniqueConstraint(
            "render_id", "user_id", "action", name="uq_confirmation_render_user_action"
        ),
        Index("ix_confirmation_render_action", "render_id", "action"),
    )

    render_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("article_renders.id"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OfficialAccount(Base, IdMixin, TimestampMixin, OwnerMixin):
    __tablename__ = "official_accounts"
    __table_args__ = (
        UniqueConstraint("owner_id", "authorizer_appid", name="uq_official_account_owner_appid"),
    )

    authorizer_appid: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(40), default="connected", nullable=False)
    capability_flags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    token_secret_ref: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    technical_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WechatAuthorizationState(Base, IdMixin, TimestampMixin):
    __tablename__ = "wechat_authorization_states"

    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    platform_config_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("wechat_platform_configs.id")
    )
    state_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    redirect_uri: Mapped[str] = mapped_column(String(1000), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WechatOperation(Base, IdMixin, TimestampMixin):
    __tablename__ = "wechat_operations"
    __table_args__ = (
        UniqueConstraint("owner_id", "idempotency_key", name="uq_wechat_owner_idem"),
        Index("ix_wechat_status_created", "status", "created_at"),
    )

    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    official_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("official_accounts.id"), nullable=False
    )
    article_id: Mapped[str] = mapped_column(String(36), ForeignKey("articles.id"), nullable=False)
    article_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("article_versions.id"), nullable=False
    )
    render_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("article_renders.id"), nullable=False
    )
    operation_type: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(48), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    render_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    media_id: Mapped[str | None] = mapped_column(String(180))
    publish_id: Mapped[str | None] = mapped_column(String(180))
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80))


class WechatCallback(Base, IdMixin):
    __tablename__ = "wechat_callbacks"

    event_key: Mapped[str] = mapped_column(String(180), unique=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    encrypted_payload: Mapped[str] = mapped_column(Text, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Skill(Base, IdMixin, TimestampMixin):
    __tablename__ = "skills"
    __table_args__ = (UniqueConstraint("scope", "code", name="uq_skill_scope_code"),)

    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    owner_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    category: Mapped[str] = mapped_column(String(80), default="content", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="draft", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_version_no: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SkillVersion(Base, IdMixin):
    __tablename__ = "skill_versions"
    __table_args__ = (UniqueConstraint("skill_id", "version_no", name="uq_skill_version_no"),)

    skill_id: Mapped[str] = mapped_column(String(36), ForeignKey("skills.id"), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    output_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    tool_policy: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="draft", nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )


class UserSkillSetting(Base, IdMixin, TimestampMixin):
    __tablename__ = "user_skill_settings"
    __table_args__ = (UniqueConstraint("user_id", "skill_id", name="uq_user_skill_setting"),)

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    skill_id: Mapped[str] = mapped_column(String(36), ForeignKey("skills.id"), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class PromptBundle(Base, IdMixin, TimestampMixin):
    __tablename__ = "prompt_bundles"

    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="draft", nullable=False)
    current_version_no: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class PromptVersion(Base, IdMixin):
    __tablename__ = "prompt_versions"
    __table_args__ = (UniqueConstraint("bundle_id", "version_no", name="uq_prompt_version_no"),)

    bundle_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("prompt_bundles.id"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    system_template: Mapped[str] = mapped_column(Text, nullable=False)
    operation_templates: Mapped[dict[str, str]] = mapped_column(JSON, default=dict, nullable=False)
    variable_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    output_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="draft", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )


class ModelProviderRecord(Base, IdMixin, TimestampMixin):
    __tablename__ = "model_providers"

    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    adapter: Mapped[str] = mapped_column(String(80), nullable=False)
    base_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    secret_ref: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="draft", nullable=False)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class ModelDeployment(Base, IdMixin, TimestampMixin):
    __tablename__ = "model_deployments"
    __table_args__ = (
        UniqueConstraint("provider_id", "alias", name="uq_deployment_provider_alias"),
    )

    provider_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("model_providers.id"), nullable=False
    )
    model_id: Mapped[str] = mapped_column(String(180), nullable=False)
    alias: Mapped[str] = mapped_column(String(120), nullable=False)
    model_type: Mapped[str] = mapped_column(String(32), nullable=False)
    capabilities: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    context_window: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rpm_limit: Mapped[int | None] = mapped_column(Integer)
    tpm_limit: Mapped[int | None] = mapped_column(Integer)
    input_cost: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=0, nullable=False)
    output_cost: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="draft", nullable=False)


class ModelRouteVersion(Base, IdMixin):
    __tablename__ = "model_route_versions"
    __table_args__ = (
        UniqueConstraint("purpose", "version_no", name="uq_model_route_version"),
        Index("ix_model_route_purpose_status", "purpose", "status"),
    )

    purpose: Mapped[str] = mapped_column(String(64), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    primary_deployment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("model_deployments.id"), nullable=False
    )
    fallback_deployment_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    policy: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="draft", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserPreference(Base, IdMixin, TimestampMixin):
    __tablename__ = "user_preferences"
    __table_args__ = (Index("ix_preferences_user_status", "user_id", "status"),)

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    project_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("projects.id"))
    preference_type: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(String(24), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=0, nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(24), default="candidate", nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserPreferenceMemory(Base, TimestampMixin):
    __tablename__ = "user_preference_memories"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)


class TaskMemorySummary(Base, IdMixin):
    __tablename__ = "task_memory_summaries"
    __table_args__ = (UniqueConstraint("task_id", "message_range", name="uq_task_memory_range"),)

    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id"), nullable=False)
    message_range: Mapped[str] = mapped_column(String(120), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    facts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )


class ExternalKnowledgeSource(Base, IdMixin, TimestampMixin):
    __tablename__ = "external_knowledge_sources"
    __table_args__ = (UniqueConstraint("source_type", "name", name="uq_external_source_name"),)

    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    secret_ref: Mapped[str | None] = mapped_column(String(255))
    scope: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="disabled", nullable=False)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_cursor: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80))


class ExternalKnowledgeMapping(Base, IdMixin, TimestampMixin):
    __tablename__ = "external_knowledge_mappings"
    __table_args__ = (UniqueConstraint("source_id", "external_node_id", name="uq_external_node"),)

    source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("external_knowledge_sources.id"), nullable=False
    )
    external_node_id: Mapped[str] = mapped_column(String(180), nullable=False)
    document_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("documents.id"))
    external_version: Mapped[str | None] = mapped_column(String(100))
    sync_status: Mapped[str] = mapped_column(String(32), nullable=False)


class IdempotencyRecord(Base, IdMixin):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("actor_type", "actor_id", "scope", "key", name="uq_idempotency_key"),
    )

    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    scope: Mapped[str] = mapped_column(String(100), nullable=False)
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="processing", nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OutboxEvent(Base, IdMixin):
    __tablename__ = "outbox_events"
    __table_args__ = (Index("ix_outbox_status_created", "status", "created_at"),)

    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(36), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class InboxMessage(Base, IdMixin):
    __tablename__ = "inbox_messages"
    __table_args__ = (UniqueConstraint("consumer", "message_id", name="uq_inbox_consumer_message"),)

    consumer: Mapped[str] = mapped_column(String(80), nullable=False)
    message_id: Mapped[str] = mapped_column(String(100), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )


class JobRecord(Base, IdMixin, TimestampMixin):
    __tablename__ = "job_records"
    __table_args__ = (Index("ix_jobs_type_status_created", "job_type", "status", "created_at"),)

    owner_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(36), nullable=False)
    queue: Mapped[str] = mapped_column(String(32), nullable=False)
    stage: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    frozen_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base, IdMixin):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_actor_created", "actor_type", "actor_id", "created_at"),)

    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(36))
    reason: Mapped[str | None] = mapped_column(String(500))
    request_id: Mapped[str | None] = mapped_column(String(80))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )


class SystemSetting(Base, IdMixin):
    __tablename__ = "system_settings"
    __table_args__ = (
        UniqueConstraint("section", "version_no", name="uq_system_setting_version"),
        Index("ix_system_setting_status", "section", "status"),
    )

    section: Mapped[str] = mapped_column(String(80), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    values: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="draft", nullable=False)
    created_by_admin_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("admins.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WechatPlatformConfig(Base, IdMixin, TimestampMixin):
    __tablename__ = "wechat_platform_configs"

    environment: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    component_appid: Mapped[str] = mapped_column(String(120), nullable=False)
    component_secret_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    message_token_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    encoding_aes_key_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    authorization_callback_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    ticket_callback_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    permission_set: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="draft", nullable=False)
    component_verify_ticket_ref: Mapped[str | None] = mapped_column(Text)
    component_access_token_ref: Mapped[str | None] = mapped_column(Text)
    component_access_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_ticket_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_token_refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

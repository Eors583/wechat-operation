from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    RootModel,
    create_model,
    model_validator,
)
from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, Numeric, inspect
from sqlalchemy.orm import DeclarativeBase

from app.models import (
    AIRun,
    Article,
    ArticleConfirmation,
    ArticleRender,
    ArticleRevision,
    ArticleVersion,
    Asset,
    AuditLog,
    Document,
    DocumentChunk,
    DocumentSection,
    JobRecord,
    LayoutTemplate,
    LayoutTemplateVersion,
    LibraryItem,
    Message,
    ModelDeployment,
    ModelRouteVersion,
    OfficialAccount,
    Project,
    PromptBundle,
    PromptVersion,
    QuotaAccount,
    QuotaLedger,
    ResourceLimit,
    Skill,
    SkillVersion,
    SystemSetting,
    Task,
    UploadSession,
    User,
    UserPreference,
    UserSkillSetting,
    WechatOperation,
    WechatPlatformConfig,
)
from app.style_token_contracts import StyleTokenPayload


class ContractModel(BaseModel):
    """Strict response base so generated clients see stable object shapes."""

    model_config = ConfigDict(extra="forbid")


class ErrorResponse(ContractModel):
    code: str
    message: str
    request_id: str
    retryable: bool
    details: dict[str, JsonValue]


COMMON_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorResponse, "description": "Unified API error response."}
    for status in (400, 401, 403, 404, 409, 410, 413, 422, 429, 500, 503)
}
USER_SESSION_COOKIE_HEADERS: dict[str, dict[str, Any]] = {
    "Set-Cookie": {
        "description": (
            "For the web flow, sets ua_session (HttpOnly, Path=/api/v1/auth) and "
            "ua_csrf (script-readable, Path=/). Native flows use the response body "
            "refresh_token and do not create a browser session."
        ),
        "schema": {"type": "string"},
    }
}
ADMIN_SESSION_COOKIE_HEADERS: dict[str, dict[str, Any]] = {
    "Set-Cookie": {
        "description": (
            "Sets admin_session (HttpOnly, Path=/admin-api/v1/auth) and admin_csrf "
            "(script-readable, Path=/) for the administration browser flow."
        ),
        "schema": {"type": "string"},
    }
}


def _is_none(value: object) -> bool:
    return value is None


class SparseContractModel(ContractModel):
    """Strict sparse JSON object whose absent optional fields stay absent."""


class TiptapMarkAttrs(SparseContractModel):
    href: str | None = Field(default=None, max_length=2048, exclude_if=_is_none)
    target: Literal["_blank", "_self"] | None = Field(default=None, exclude_if=_is_none)
    rel: str | None = Field(default=None, max_length=80, exclude_if=_is_none)
    css_class: str | None = Field(
        default=None,
        alias="class",
        serialization_alias="class",
        max_length=120,
        exclude_if=_is_none,
    )


class TiptapMark(SparseContractModel):
    type: Literal["bold", "italic", "strike", "code", "link"]
    attrs: TiptapMarkAttrs | None = Field(default=None, exclude_if=_is_none)

    @model_validator(mode="after")
    def validate_attrs(self) -> TiptapMark:
        values = self.attrs.model_dump(exclude_none=True, by_alias=True) if self.attrs else {}
        if self.type == "link" and not values.get("href"):
            raise ValueError("link marks require attrs.href")
        if self.type != "link" and values:
            raise ValueError("only link marks may contain attributes")
        return self


class TiptapNodeAttrs(SparseContractModel):
    colspan: int | None = Field(default=None, ge=1, le=1, strict=True, exclude_if=_is_none)
    rowspan: int | None = Field(default=None, ge=1, le=1, strict=True, exclude_if=_is_none)
    colwidth: list[int] | None = Field(
        default=None, min_length=1, max_length=1, exclude_if=_is_none
    )
    level: int | None = Field(default=None, ge=1, le=3, exclude_if=_is_none)
    module: Literal["lead", "body", "highlight", "caption"] | None = Field(
        default=None, exclude_if=_is_none
    )
    src: str | None = Field(default=None, max_length=2048, exclude_if=_is_none)
    alt: str | None = Field(default=None, max_length=500, exclude_if=_is_none)
    title: str | None = Field(default=None, max_length=500, exclude_if=_is_none)
    asset_id: str | None = Field(default=None, max_length=64, exclude_if=_is_none)
    start: int | None = Field(default=None, ge=1, le=1_000_000, exclude_if=_is_none)
    language: str | None = Field(default=None, max_length=80, exclude_if=_is_none)


class TiptapNode(SparseContractModel):
    type: Literal[
        "table",
        "tableRow",
        "tableCell",
        "tableHeader",
        "paragraph",
        "text",
        "heading",
        "bulletList",
        "orderedList",
        "listItem",
        "blockquote",
        "hardBreak",
        "horizontalRule",
        "codeBlock",
        "image",
    ]
    attrs: TiptapNodeAttrs | None = Field(default=None, exclude_if=_is_none)
    content: list[TiptapNode] | None = Field(default=None, exclude_if=_is_none)
    marks: list[TiptapMark] | None = Field(default=None, exclude_if=_is_none)
    text: str | None = Field(default=None, exclude_if=_is_none)

    @model_validator(mode="after")
    def validate_text_node(self) -> TiptapNode:
        if self.type == "text" and self.text is None:
            raise ValueError("text nodes require text")
        if self.type == "text" and self.content is not None:
            raise ValueError("text nodes cannot contain child nodes")
        if self.type != "text" and self.text is not None:
            raise ValueError("non-text nodes cannot contain direct text")
        if self.type != "text" and self.marks is not None:
            raise ValueError("marks are only valid on text nodes")
        values = self.attrs.model_dump(exclude_none=True) if self.attrs else {}
        allowed_attrs = {
            "tableCell": {"colspan", "rowspan", "colwidth"},
            "tableHeader": {"colspan", "rowspan", "colwidth"},
            "paragraph": {"module"},
            "heading": {"level"},
            "orderedList": {"start"},
            "codeBlock": {"language"},
            "image": {"src", "alt", "title", "asset_id"},
        }.get(self.type, set())
        if set(values) - allowed_attrs:
            raise ValueError(f"{self.type} nodes contain unsupported attributes")
        if self.type == "heading" and "level" not in values:
            raise ValueError("heading nodes require attrs.level")
        if self.type == "image" and "src" not in values:
            raise ValueError("image nodes require attrs.src")
        return self


class TiptapDocument(ContractModel):
    type: Literal["doc"]
    content: list[TiptapNode] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_tree(self) -> TiptapDocument:
        block_types = {
            "table",
            "paragraph",
            "heading",
            "bulletList",
            "orderedList",
            "blockquote",
            "horizontalRule",
            "codeBlock",
            "image",
        }
        allowed_children = {
            "table": {"tableRow"},
            "tableRow": {"tableCell", "tableHeader"},
            "tableCell": block_types - {"table"},
            "tableHeader": block_types - {"table"},
            "paragraph": {"text", "hardBreak"},
            "heading": {"text", "hardBreak"},
            "bulletList": {"listItem"},
            "orderedList": {"listItem"},
            "listItem": block_types,
            "blockquote": block_types,
            "codeBlock": {"text"},
        }
        leaf_types = {"text", "hardBreak", "horizontalRule", "image"}

        def walk(node: TiptapNode, parent_type: str) -> None:
            children = node.content or []
            expected = block_types if parent_type == "doc" else allowed_children.get(parent_type)
            if expected is None or node.type not in expected:
                raise ValueError(f"{node.type} is not valid inside {parent_type}")
            if node.type in leaf_types and node.content is not None:
                raise ValueError(f"{node.type} nodes cannot contain child nodes")
            if (
                node.type in {"bulletList", "orderedList", "listItem", "blockquote"}
                and not children
            ):
                raise ValueError(f"{node.type} nodes require child nodes")
            if node.type == "listItem" and children[0].type != "paragraph":
                raise ValueError("listItem nodes must start with a paragraph")
            if node.type in {"table", "tableRow", "tableCell", "tableHeader"} and not children:
                raise ValueError("table nodes require children")
            if node.type == "table":
                counts = [len(row.content or []) for row in children]
                if len(children) > 200 or len(set(counts)) != 1 or not 1 <= counts[0] <= 20:
                    raise ValueError("table must be rectangular, at most 200 rows and 20 columns")
            for child in children:
                walk(child, node.type)

        for child in self.content:
            walk(child, "doc")
        return self


def _column_type(column: Any) -> Any:
    if isinstance(column.type, JSON):
        return JsonValue
    if isinstance(column.type, Boolean):
        return bool
    if isinstance(column.type, Integer):
        return int
    if isinstance(column.type, Numeric | Float):
        return float
    if isinstance(column.type, DateTime):
        return datetime
    return str


def orm_contract(
    name: str,
    model: type[DeclarativeBase],
    *,
    exclude: set[str] | None = None,
    overrides: dict[str, tuple[Any, Any]] | None = None,
) -> type[BaseModel]:
    """Derive public storage fields once instead of copying every SQLAlchemy table."""

    hidden = exclude or set()
    fields: dict[str, Any] = {}
    for column in inspect(model).columns:
        if column.key in hidden:
            continue
        annotation = _column_type(column)
        if column.nullable:
            annotation = annotation | None
        fields[column.key] = (annotation, ...)
    fields.update(overrides or {})
    return create_model(name, __base__=ContractModel, **fields)


ArticleStatus = Literal[
    "editing",
    "local_draft",
    "wechat_draft",
    "published",
    "publishing",
    "wechat_draft_queued",
    "wechat_draft_submitting",
    "wechat_draft_reconciling",
    "wechat_draft_unknown",
    "wechat_draft_failed",
    "wechat_draft_mocked",
    "wechat_draft_cancelled",
    "publish_queued",
    "publish_submitting",
    "publish_reconciling",
    "publish_unknown",
    "publish_failed",
    "publish_mocked",
    "publish_cancelled",
]
LibraryDisplayStatus = Literal[
    "processing",
    "ready",
    "failed",
    "local_draft",
    "wechat_draft",
    "published",
    "publishing",
    "wechat_draft_queued",
    "wechat_draft_submitting",
    "wechat_draft_reconciling",
    "wechat_draft_unknown",
    "wechat_draft_failed",
    "wechat_draft_mocked",
    "wechat_draft_cancelled",
    "publish_queued",
    "publish_submitting",
    "publish_reconciling",
    "publish_unknown",
    "publish_failed",
    "publish_mocked",
    "publish_cancelled",
]
WechatOperationStatus = Literal[
    "queued", "submitting", "reconciling", "unknown", "failed", "mocked", "succeeded", "cancelled"
]
AIRunStatus = Literal[
    "accepted",
    "validating",
    "clarifying",
    "retrieving",
    "planning",
    "generating",
    "validating_output",
    "saving_version",
    "ready_for_formatting",
    "completed",
    "failed",
    "cancelled",
]
ArticleRevisionStatus = Literal["accepted", "generating", "completed", "failed", "cancelled"]
DocumentStatus = Literal[
    "queued", "processing", "indexing", "completed", "failed", "blocked_external", "deleted"
]
AssetScanStatus = Literal[
    "pending", "queued", "processing", "clean", "mocked_clean", "failed", "blocked_external"
]
LayoutExtractionStatus = Literal["manual", "queued", "completed", "failed"]


ProjectResource = orm_contract("ProjectResource", Project)
TaskResource = orm_contract("TaskResource", Task)
MessageResource = orm_contract("MessageResource", Message)
AIRunResource = orm_contract("AIRunResource", AIRun, overrides={"status": (AIRunStatus, ...)})
QuotaLedgerResource = orm_contract("QuotaLedgerResource", QuotaLedger)
UploadSessionResource = orm_contract("UploadSessionResource", UploadSession)
AssetResource = orm_contract(
    "AssetResource", Asset, overrides={"scan_status": (AssetScanStatus, ...)}
)
DocumentResource = orm_contract(
    "DocumentResource", Document, overrides={"status": (DocumentStatus, ...)}
)
DocumentSectionResource = orm_contract("DocumentSectionResource", DocumentSection)
DocumentChunkResource = orm_contract("DocumentChunkResource", DocumentChunk)
ArticleResource = orm_contract(
    "ArticleResource",
    Article,
    overrides={
        "status": (
            ArticleStatus,
            Field(
                ...,
                description=(
                    "Article aggregate state. 'publishing' is read-only legacy compatibility; "
                    "new operations write the explicit publish_* states."
                ),
            ),
        )
    },
)
ArticleRevisionResource = orm_contract(
    "ArticleRevisionResource",
    ArticleRevision,
    overrides={"status": (ArticleRevisionStatus, ...)},
)
ArticleVersionResource = orm_contract(
    "ArticleVersionResource",
    ArticleVersion,
    overrides={"content_json": (TiptapDocument, ...)},
)
LibraryItemResource = orm_contract(
    "LibraryItemResource",
    LibraryItem,
    overrides={"display_status": (LibraryDisplayStatus, ...)},
)
SkillResource = orm_contract("SkillResource", Skill)
SkillVersionResource = orm_contract("SkillVersionResource", SkillVersion)
UserSkillSettingResource = orm_contract("UserSkillSettingResource", UserSkillSetting)
UserPreferenceResource = orm_contract("UserPreferenceResource", UserPreference)
LayoutTemplateResource = orm_contract(
    "LayoutTemplateResource",
    LayoutTemplate,
    overrides={"extraction_status": (LayoutExtractionStatus, ...)},
)
LayoutTemplateVersionResource = orm_contract(
    "LayoutTemplateVersionResource",
    LayoutTemplateVersion,
    overrides={"style_tokens": (StyleTokenPayload, ...)},
)
ArticleRenderResource = orm_contract("ArticleRenderResource", ArticleRender)
ArticleConfirmationResource = orm_contract("ArticleConfirmationResource", ArticleConfirmation)
WechatOperationResource = orm_contract(
    "WechatOperationResource",
    WechatOperation,
    overrides={"status": (WechatOperationStatus, ...)},
)
AdminUserResource = orm_contract("AdminUserResource", User, exclude={"password_hash", "deleted_at"})
QuotaAccountResource = orm_contract("QuotaAccountResource", QuotaAccount)
ResourceLimitResource = orm_contract("ResourceLimitResource", ResourceLimit)
ModelDeploymentResource = orm_contract("ModelDeploymentResource", ModelDeployment)
ModelRouteResource = orm_contract("ModelRouteResource", ModelRouteVersion)
PromptBundleResource = orm_contract("PromptBundleResource", PromptBundle)
PromptVersionResource = orm_contract("PromptVersionResource", PromptVersion)
JobResource = orm_contract("JobResource", JobRecord)
WechatConfigStorageResource = orm_contract(
    "WechatConfigStorageResource",
    WechatPlatformConfig,
    exclude={
        "component_secret_ref",
        "message_token_ref",
        "encoding_aes_key_ref",
        "component_verify_ticket_ref",
        "component_access_token_ref",
    },
)
AdminOfficialAccountResource = orm_contract(
    "AdminOfficialAccountResource",
    OfficialAccount,
    exclude={"token_secret_ref", "technical_metadata"},
)
SystemSettingResource = orm_contract("SystemSettingResource", SystemSetting)
AuditLogResource = orm_contract("AuditLogResource", AuditLog)


class ItemsResponse[T](ContractModel):
    items: list[T]


class CursorPageResponse[T](ItemsResponse[T]):
    next_cursor: str | None


class VerificationCodeResponse(ContractModel):
    challenge_id: str
    expires_at: datetime
    delivery_status: str
    provider_mode: Literal["mock", "configured"]
    debug_code: str | None = None


class VerificationTokenResponse(ContractModel):
    verification_token: str


class RegisteredUserResponse(ContractModel):
    id: str
    display_name: str
    status: str


class AuthUserResponse(ContractModel):
    id: str
    display_name: str
    status: str | None = None


class AuthTokenResponse(ContractModel):
    access_token: str
    token_type: Literal["bearer"]
    expires_in: int
    refresh_token: str | None
    user: AuthUserResponse


class MeResponse(ContractModel):
    id: str
    email: str | None
    phone: str | None
    display_name: str
    theme_preference: Literal["system", "light", "dark"]
    quota_balance: int


class MePatchResponse(ContractModel):
    id: str
    theme_preference: Literal["system", "light", "dark"]


class ModelOptionResource(ContractModel):
    id: str
    name: str
    provider_name: str
    model_id: str
    model_type: Literal["chat", "vision"]
    context_window: int
    max_output_tokens: int


class ModelOptionListResponse(ContractModel):
    items: list[ModelOptionResource]


class AccountDeletionResponse(ContractModel):
    deletion_request_id: str
    status: Literal["scheduled"]
    requested_at: datetime
    purge_after: datetime


class QuotaResponse(ContractModel):
    balance: int
    version: int
    ledger: list[QuotaLedgerResource]  # type: ignore[valid-type]


class RunCreationResponse(ContractModel):
    task: TaskResource  # type: ignore[valid-type]
    message: MessageResource  # type: ignore[valid-type]
    ai_run: AIRunResource  # type: ignore[valid-type]


class TaskAIRunSummary(ContractModel):
    id: str
    status: AIRunStatus
    run_type: str
    error_code: str | None
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None


TaskDetailResponse = create_model(
    "TaskDetailResponse",
    __base__=TaskResource,
    messages=(list[MessageResource], ...),  # type: ignore[valid-type]
    messages_next_cursor=(str | None, ...),
    latest_ai_run=(TaskAIRunSummary | None, ...),
)

MessagePageResponse = CursorPageResponse[MessageResource]  # type: ignore[valid-type]


class UploadCreateResponse(ContractModel):
    upload: UploadSessionResource  # type: ignore[valid-type]
    asset: AssetResource  # type: ignore[valid-type]
    part_urls: list[str]
    part_size_bytes: int = Field(
        gt=0,
        description=(
            "Maximum bytes for each upload part. All parts except the final part use this size."
        ),
    )
    provider_mode: Literal["mock", "configured"]


class UploadCompleteResponse(ContractModel):
    asset: AssetResource  # type: ignore[valid-type]
    document: DocumentResource  # type: ignore[valid-type]
    library_item: LibraryItemResource | None  # type: ignore[valid-type]


DocumentDetailResponse = create_model(
    "DocumentDetailResponse",
    __base__=DocumentResource,
    sections=(list[DocumentSectionResource], ...),  # type: ignore[valid-type]
    chunks=(list[DocumentChunkResource], ...),  # type: ignore[valid-type]
    sections_truncated=(bool, ...),
    chunks_truncated=(bool, ...),
)


class ArticleWithVersionResponse(ContractModel):
    article: ArticleResource  # type: ignore[valid-type]
    version: ArticleVersionResource  # type: ignore[valid-type]


class SavedArticleResponse(ContractModel):
    article: ArticleResource  # type: ignore[valid-type]
    library_item: LibraryItemResource  # type: ignore[valid-type]


class CurrentWechatOperationResponse(ContractModel):
    operation: WechatOperationResource | None  # type: ignore[valid-type]


class ArticleLibrarySource(ContractModel):
    article: ArticleResource  # type: ignore[valid-type]
    version: ArticleVersionResource  # type: ignore[valid-type]


class DocumentLibrarySource(ContractModel):
    document: DocumentResource  # type: ignore[valid-type]


class LibraryItemDetailResponse(ContractModel):
    item: LibraryItemResource  # type: ignore[valid-type]
    source: ArticleLibrarySource | DocumentLibrarySource | None


SkillListItem = create_model(
    "SkillListItem",
    __base__=SkillResource,
    enabled=(bool, ...),
    version=(SkillVersionResource | None, ...),
)


class SkillDetailResponse(ContractModel):
    skill: SkillResource  # type: ignore[valid-type]
    version: SkillVersionResource | None  # type: ignore[valid-type]
    enabled: bool | None = None


class SkillVersionResponse(ContractModel):
    skill: SkillResource  # type: ignore[valid-type]
    version: SkillVersionResource | None  # type: ignore[valid-type]


LayoutTemplateListItem = create_model(
    "LayoutTemplateListItem",
    __base__=LayoutTemplateResource,
    version=(LayoutTemplateVersionResource | None, ...),
)


class LayoutTemplateVersionResponse(ContractModel):
    template: LayoutTemplateResource  # type: ignore[valid-type]
    version: LayoutTemplateVersionResource | None  # type: ignore[valid-type]


class LayoutTemplateDetailResponse(ContractModel):
    template: LayoutTemplateResource  # type: ignore[valid-type]
    versions: list[LayoutTemplateVersionResource]  # type: ignore[valid-type]


class LayoutExtractionResponse(ContractModel):
    template: LayoutTemplateResource  # type: ignore[valid-type]
    version: LayoutTemplateVersionResource | None  # type: ignore[valid-type]
    provider_status: Literal["queued", "completed", "failed"]
    message: str


class AuthorizationUrlResponse(ContractModel):
    authorization_url: str
    expires_in: int


class OfficialAccountResponse(ContractModel):
    id: str
    name: str
    avatar_url: str | None
    status: str
    ui_status: Literal["connected", "reconnect_required", "unsupported"]
    capabilities: list[str]
    authorized_at: datetime | None
    last_synced_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AdminIdentityResponse(ContractModel):
    id: str
    username: str
    permissions: list[str]


class AdminAuthResponse(ContractModel):
    access_token: str
    token_type: Literal["bearer"]
    expires_in: int
    admin: AdminIdentityResponse


class AdminRefreshResponse(ContractModel):
    access_token: str
    token_type: Literal["bearer"]
    expires_in: int


class DashboardCountPair(ContractModel):
    total: int
    active: int | None = None
    failed: int | None = None
    today: int | None = None
    new_today: int | None = None


class DashboardSingleCount(ContractModel):
    processing: int | None = None
    failed: int | None = None


class DashboardAccountHealth(ContractModel):
    healthy: int
    degraded: int
    down: int


class DashboardRecentChange(ContractModel):
    id: str
    type: str
    name: str
    version: str
    published_at: datetime


class DashboardResponse(ContractModel):
    users: DashboardCountPair
    ai: DashboardCountPair
    documents: DashboardSingleCount
    wechat: DashboardSingleCount
    jobs: DashboardSingleCount
    ai_average_latency_ms: int
    abnormal_models: int
    account_health: DashboardAccountHealth
    recent_changes: list[DashboardRecentChange]


class UserOfficialAccountSummary(ContractModel):
    id: str
    name: str
    status: str
    last_synced_at: datetime | None


class AdminUserDetailResponse(ContractModel):
    user: AdminUserResource  # type: ignore[valid-type]
    quota: QuotaAccountResource | None  # type: ignore[valid-type]
    limits: ResourceLimitResource | None  # type: ignore[valid-type]
    official_accounts: list[UserOfficialAccountSummary]
    failed_jobs: list[JobResource]  # type: ignore[valid-type]
    content_accessed: Literal[False]


class AdminUserPatchResponse(ContractModel):
    user: AdminUserResource  # type: ignore[valid-type]
    limits: ResourceLimitResource  # type: ignore[valid-type]


class QuotaAdjustmentResponse(ContractModel):
    balance: int
    version: int


class ModelProviderResponse(ContractModel):
    id: str
    code: str
    name: str
    adapter: str
    base_url: str
    secret_configured: bool
    status: str
    last_tested_at: datetime | None
    last_test_result: JsonValue
    created_at: datetime
    updated_at: datetime


class ModelConfigurationResponse(ContractModel):
    id: str
    name: str
    base_url: str
    model_id: str
    model_type: str
    adapter: str
    secret_configured: bool
    status: Literal["draft", "testing", "available", "disabled"]
    last_tested_at: datetime | None
    last_test_result: JsonValue
    created_at: datetime
    updated_at: datetime


class ProviderTestResponse(ContractModel):
    passed: bool
    simulated: bool
    secret_available: bool
    message: str


class ValidationTestResponse(ContractModel):
    passed: bool
    simulated: bool
    message: str
    provider_request_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class SystemSettingsValidationResponse(ContractModel):
    passed: bool
    checks: list[str]


class SystemSettingBundleResponse(ContractModel):
    items: list[SystemSettingResource]  # type: ignore[valid-type]


class ExternalKnowledgeTarget(ContractModel):
    type: Literal["team", "space", "kb_entry"]
    id: str


class ExternalKnowledgeSourceResponse(ContractModel):
    id: str
    source_type: Literal["lexiang"]
    name: str
    app_key: str
    secret_configured: bool
    targets: list[ExternalKnowledgeTarget]
    owner_staff_ids: dict[str, str]
    sync_owner_id: str | None
    status: str
    last_tested_at: datetime | None
    last_test_result: JsonValue
    last_synced_at: datetime | None
    error_code: str | None
    created_at: datetime
    updated_at: datetime


class ExternalKnowledgeSourceListResponse(ContractModel):
    items: list[ExternalKnowledgeSourceResponse]


class RouteTestResponse(ValidationTestResponse):
    checked_deployments: list[str]


class PromptVersionsResponse(ContractModel):
    bundle: PromptBundleResource  # type: ignore[valid-type]
    versions: list[PromptVersionResource]  # type: ignore[valid-type]


class WechatConfigResponse(ContractModel):
    id: str
    environment: str
    component_appid: str
    component_secret_configured: bool
    message_token_configured: bool
    encoding_aes_key_configured: bool
    authorization_callback_url: str
    ticket_callback_url: str
    permission_set: list[str]
    status: str
    last_ticket_at: datetime | None
    last_token_refresh_at: datetime | None
    updated_at: datetime


class WechatConfigTestResponse(ContractModel):
    passed: bool
    simulated: bool
    secrets_available: bool
    message: str


class AdminListItem(ContractModel):
    id: str
    username: str
    status: str
    permissions: list[str]
    last_login_at: datetime | None
    created_at: datetime


class AdminCreatedResponse(ContractModel):
    id: str
    username: str
    status: str


class AdminPatchedResponse(AdminCreatedResponse):
    permissions: list[str]


class CallbackAckResponse(ContractModel):
    accepted: Literal[True]
    duplicate: bool


class AuthorizationCallbackAckResponse(CallbackAckResponse):
    official_account_id: str | None = None


ProjectListResponse = CursorPageResponse[ProjectResource]  # type: ignore[valid-type]
TaskPageResponse = CursorPageResponse[TaskResource]  # type: ignore[valid-type]
ArticleVersionListResponse = CursorPageResponse[ArticleVersionResource]  # type: ignore[valid-type]
LibraryItemPageResponse = CursorPageResponse[LibraryItemResource]  # type: ignore[valid-type]
SkillListResponse = CursorPageResponse[SkillListItem]
PreferenceListResponse = CursorPageResponse[UserPreferenceResource]  # type: ignore[valid-type]
LayoutTemplateListResponse = CursorPageResponse[LayoutTemplateListItem]
OfficialAccountListResponse = CursorPageResponse[OfficialAccountResponse]
AdminUserListResponse = ItemsResponse[AdminUserResource]  # type: ignore[valid-type]
ModelProviderListResponse = ItemsResponse[ModelProviderResponse]
ModelConfigurationListResponse = ItemsResponse[ModelConfigurationResponse]
ModelDeploymentListResponse = ItemsResponse[ModelDeploymentResource]  # type: ignore[valid-type]
ModelRouteListResponse = ItemsResponse[ModelRouteResource]  # type: ignore[valid-type]
PromptBundleListResponse = ItemsResponse[PromptBundleResource]  # type: ignore[valid-type]
SkillAdminListResponse = ItemsResponse[SkillResource]  # type: ignore[valid-type]


class SkillVersionListResponse(ContractModel):
    items: list[SkillVersionResource]  # type: ignore[valid-type]


JobListResponse = ItemsResponse[JobResource]  # type: ignore[valid-type]
WechatConfigListResponse = ItemsResponse[WechatConfigResponse]
AdminOfficialAccountListResponse = ItemsResponse[
    AdminOfficialAccountResource  # type: ignore[valid-type]
]
SystemSettingListResponse = ItemsResponse[SystemSettingResource]  # type: ignore[valid-type]
AdminListResponse = ItemsResponse[AdminListItem]
AuditLogListResponse = ItemsResponse[AuditLogResource]  # type: ignore[valid-type]


class PublicSettingsResponse(RootModel[dict[str, JsonValue]]):
    pass

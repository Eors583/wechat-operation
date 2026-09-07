export type ConfigStatus = 'draft' | 'testing' | 'published' | 'disabled'
export type HealthStatus = 'healthy' | 'degraded' | 'down'
export type UserStatus = 'active' | 'ai_suspended' | 'wechat_suspended' | 'disabled'
export type TaskStatus = 'queued' | 'running' | 'failed' | 'unknown' | 'completed' | 'cancelled'
export type ThemePreference = 'light' | 'dark' | 'system'

export interface ApiErrorBody {
  code: string
  message: string
  request_id: string
  retryable: boolean
  details?: Record<string, unknown>
}

export interface CursorPage<T> {
  items: T[]
  next_cursor: string | null
  total: number
}

export interface AdminIdentity {
  id: string
  username: string
  display_name: string
  role: 'super_admin' | 'operations' | 'auditor'
  permissions: string[]
  last_login_at: string | null
}

export interface DashboardMetric {
  label: string
  value: string
  delta?: string
  tone: 'primary' | 'positive' | 'warning' | 'negative'
  route: string
}

export interface DashboardSummary {
  metrics: DashboardMetric[]
  ai_success_rate: number
  ai_average_latency_ms: number
  current_abnormal_models: number
  account_health: Record<HealthStatus, number>
  failed_tasks: Record<string, number>
  recent_changes: Array<{
    id: string
    type: string
    name: string
    version: string
    published_at: string
  }>
}

export type ModelAdapter =
  | 'openai_responses'
  | 'openai_chat_completions'
  | 'litellm_responses'
  | 'litellm_chat_completions'
  | 'manus_v2'
export type ModelConfigurationStatus = 'draft' | 'testing' | 'available' | 'disabled'

export interface ModelConfiguration {
  id: string
  name: string
  model_id: string
  model_type: 'chat' | 'embedding' | 'rerank' | 'vision'
  adapter: ModelAdapter
  base_url: string
  secret_configured: boolean
  status: ModelConfigurationStatus
  last_tested_at: string | null
  last_test_result: { passed: boolean; message: string } | null
  created_at: string
  updated_at: string
}

export type ModelPurpose =
  | 'intent_detection'
  | 'fast_task'
  | 'article_planning'
  | 'article_generation'
  | 'article_revision'
  | 'file_extraction'
  | 'content_check'
  | 'vision'
  | 'memory_summary'
  | 'layout_extraction'
  | 'embedding'
  | 'rerank'

export interface ModelRoute {
  id: string
  purpose: ModelPurpose
  display_name: string
  version: number
  primary_deployment_id: string
  fallback_deployment_ids: string[]
  timeout_ms: number
  max_attempts: number
  status: ConfigStatus
  updated_at: string
}

export interface PromptVersion {
  id: string
  bundle_code: string
  display_name: string
  version: number
  description: string
  system_template: string
  operation_template: string
  variables: string[]
  checksum: string
  status: ConfigStatus
  updated_by: string
  updated_at: string
  test_result?: { passed: boolean; latency_ms: number; output_excerpt: string }
}

export interface OfficialSkill {
  id: string
  version_id?: string
  code: string
  name: string
  description: string
  scenarios: string[]
  instructions: string
  version: number
  sort_order: number
  status: ConfigStatus
  enabled_users: number
  updated_at: string
}

export interface UserQuota {
  ai_monthly: number
  ai_used: number
  storage_gb: number
  storage_used_gb: number
  max_file_mb: number
  official_accounts: number
  official_accounts_used: number
}

export interface UserRecord {
  id: string
  masked_phone: string
  masked_email: string
  display_name: string
  status: UserStatus
  registered_at: string
  last_login_at: string | null
  quota: UserQuota
  capabilities: { ai: boolean; wechat: boolean; uploads: boolean }
  bound_accounts: number
  failed_tasks: number
}

export interface WechatPlatformConfig {
  component_appid: string
  app_secret_configured: boolean
  message_token_configured: boolean
  encoding_aes_key_configured: boolean
  ticket_callback_url: string
  authorization_callback_url: string
  status: ConfigStatus
  ticket_health: HealthStatus
  token_health: HealthStatus
  last_ticket_at: string | null
  last_token_refresh_at: string | null
  affected_capabilities: string[]
}

export interface OfficialAccount {
  id: string
  name: string
  owner_id: string
  owner_display_name: string
  status: 'connected' | 'reconnect_required' | 'limited'
  authorized_at: string
  token_expires_at: string | null
  draft_capable: boolean
  publish_capable: boolean
  last_refresh_result: string
  recent_task_status: TaskStatus | null
}

export interface JobRecord {
  id: string
  type:
    | 'ai'
    | 'file_parse'
    | 'embedding'
    | 'knowledge_sync'
    | 'wechat_draft'
    | 'wechat_publish'
    | 'preference'
  owner_display_name: string
  resource_label: string
  stage: string
  status: TaskStatus
  attempt_count: number
  frozen_snapshot_id: string
  model_or_account: string
  duration_ms: number
  error_code?: string
  error_message?: string
  external_id?: string
  created_at: string
  updated_at: string
}

export interface SystemSettings {
  version: number
  status: ConfigStatus
  welcome_message: string
  example_prompts: string[]
  allowed_extensions: string[]
  max_file_mb: number
  link_fetch_enabled: boolean
  max_clarification_rounds: number
  min_article_length: number
  max_article_length: number
  ai_run_credit_cost: number
  preference_enabled_by_default: boolean
  autosave_seconds: number
  history_versions: number
  wechat_draft_enabled: boolean
  wechat_publish_enabled: boolean
  max_article_images: number
  feature_flags: Record<string, boolean>
  updated_at: string
}

export interface ExternalKnowledgeTarget {
  type: 'team' | 'space' | 'kb_entry'
  id: string
}

export interface ExternalKnowledgeSource {
  id: string
  name: string
  app_key: string
  secret_configured: boolean
  targets: ExternalKnowledgeTarget[]
  owner_staff_ids: Record<string, string>
  sync_owner_id: string | null
  status: 'active' | 'disabled'
  last_tested_at: string | null
  last_test_passed: boolean
  last_synced_at: string | null
  error_code: string | null
  created_at: string
  updated_at: string
}

export interface AdminAccount {
  id: string
  username: string
  display_name: string
  role: AdminIdentity['role']
  status: 'active' | 'disabled'
  last_login_at: string | null
  created_at: string
}

export interface AuditLog {
  id: string
  actor: string
  action: string
  resource_type: string
  resource_label: string
  reason: string
  request_id: string
  ip_address: string
  created_at: string
  result: 'success' | 'denied' | 'failed'
}

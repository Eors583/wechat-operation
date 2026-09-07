import type {
  AdminAccount,
  AuditLog,
  ConfigStatus,
  DashboardSummary,
  ExternalKnowledgeSource,
  ExternalKnowledgeTarget,
  JobRecord,
  ModelConfiguration,
  ModelConfigurationStatus,
  ModelRoute,
  OfficialAccount,
  OfficialSkill,
  PromptVersion,
  SystemSettings,
  TaskStatus,
  UserRecord,
  UserStatus,
  WechatPlatformConfig,
} from "./contracts";
import { adminOpenApi, adminOpenApiData, requestId } from "./client";

type JsonRecord = Record<string, unknown>;

const record = (value: unknown): JsonRecord =>
  typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as JsonRecord)
    : {};
const text = (value: unknown, fallback = "") =>
  typeof value === "string" ? value : fallback;
const number = (value: unknown, fallback = 0) =>
  typeof value === "number" && Number.isFinite(value) ? value : fallback;
const boolean = (value: unknown, fallback = false) =>
  typeof value === "boolean" ? value : fallback;
const strings = (value: unknown) =>
  Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
const scenarios = (value: unknown) =>
  text(record(value).scenario)
    .split(/[、,，\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
const configStatus = (value: unknown): ConfigStatus =>
  value === "active"
    ? "published"
    : ["draft", "testing", "published", "disabled"].includes(text(value))
      ? (text(value) as ConfigStatus)
      : "draft";
const modelConfigurationStatus = (value: unknown): ModelConfigurationStatus =>
  ["draft", "testing", "available", "disabled"].includes(text(value))
    ? (text(value) as ModelConfigurationStatus)
    : "draft";
const taskStatus = (value: unknown): TaskStatus => {
  const status = text(value);
  if (["accepted", "queued", "retrying"].includes(status)) return "queued";
  if (
    ["processing", "generating", "submitting", "reconciling"].includes(status)
  )
    return "running";
  return ["failed", "unknown", "completed", "cancelled"].includes(status)
    ? (status as TaskStatus)
    : "queued";
};
const userStatus = (value: unknown): UserStatus =>
  value === "disabled" ? "disabled" : "active";
const mask = (value: string | null, prefix: number, suffix: number) =>
  !value
    ? "—"
    : value.length <= prefix + suffix
      ? "***"
      : `${value.slice(0, prefix)}***${value.slice(-suffix)}`;
const permissionsForRole = (role: AdminAccount["role"]): string[] => {
  if (role === "super_admin") return ["*"];
  if (role === "auditor") return ["dashboard:read", "audit:read", "jobs:read"];
  return [
    "dashboard:read",
    "ai_config:read",
    "ai_config:write",
    "ai_config:test",
    "prompts:read",
    "prompts:write",
    "prompts:test",
    "prompts:publish",
    "skills:read",
    "skills:write",
    "skills:test",
    "skills:publish",
    "users:read",
    "users:write",
    "jobs:read",
    "jobs:retry",
    "jobs:cancel",
    "jobs:reconcile",
    "wechat_config:read",
    "wechat_config:write",
    "wechat_config:test",
    "wechat_config:publish",
    "wechat_accounts:read",
    "wechat_accounts:write",
    "settings:read",
    "settings:write",
    "settings:publish",
    "audit:read",
  ];
};

const systemSettingsSections = (settings: SystemSettings) => ({
  home: {
    welcome_message: settings.welcome_message,
    example_prompts: settings.example_prompts,
  },
  files: {
    allowed_extensions: settings.allowed_extensions,
    max_file_mb: settings.max_file_mb,
    link_fetch_enabled: settings.link_fetch_enabled,
  },
  ai: {
    max_clarification_rounds: settings.max_clarification_rounds,
    min_article_length: settings.min_article_length,
    max_article_length: settings.max_article_length,
    ai_run_credit_cost: settings.ai_run_credit_cost,
    preference_enabled_by_default: settings.preference_enabled_by_default,
  },
  articles: {
    autosave_seconds: settings.autosave_seconds,
    history_versions: settings.history_versions,
  },
  wechat: {
    wechat_draft_enabled: settings.wechat_draft_enabled,
    wechat_publish_enabled: settings.wechat_publish_enabled,
    max_article_images: settings.max_article_images,
  },
  features: { feature_flags: settings.feature_flags },
});

async function loadPublishedAiSettings(): Promise<JsonRecord> {
  const response = await adminOpenApiData(
    adminOpenApi.GET("/admin-api/v1/system-settings", {
      params: { query: { section: "ai" } },
    }),
  );
  const byVersion = (
    left: (typeof response.items)[number],
    right: (typeof response.items)[number],
  ) => right.version_no - left.version_no;
  const current =
    [...response.items]
      .filter((item) => item.status === "published")
      .sort(byVersion)[0] ?? [...response.items].sort(byVersion)[0];
  return record(current?.values);
}

export const adminRepository = {
  async saveModelConfiguration(
    model: ModelConfiguration,
    apiKey: string,
    exists: boolean,
    validationToken?: string,
  ): Promise<void> {
    if (exists) {
      await adminOpenApiData(
        adminOpenApi.PATCH(
          "/admin-api/v1/model-configurations/{configuration_id}",
          {
            params: { path: { configuration_id: model.id } },
            body: {
              name: model.name,
              model_id: model.model_id,
              model_type: model.model_type,
              adapter: model.adapter,
              base_url: model.base_url,
              ...(apiKey ? { api_key: apiKey } : {}),
            },
          },
        ),
      );
    } else {
      await adminOpenApiData(
        adminOpenApi.POST("/admin-api/v1/model-configurations", {
          body: {
            name: model.name,
            model_id: model.model_id,
            model_type: model.model_type,
            adapter: model.adapter,
            base_url: model.base_url,
            api_key: apiKey,
            validation_token: validationToken,
          },
        }),
      );
    }
  },

  async testModelConfigurationBeforeSave(
    model: ModelConfiguration,
    apiKey: string,
  ): Promise<{
    passed: boolean;
    message: string;
    validation_token: string | null;
  }> {
    const result = await adminOpenApiData(
      adminOpenApi.POST("/admin-api/v1/model-configurations/test", {
        body: {
          name: model.name,
          base_url: model.base_url,
          api_key: apiKey,
          model_id: model.model_id,
          model_type: model.model_type,
          adapter: model.adapter,
        },
      }),
    );
    return { ...result, validation_token: result.validation_token ?? null };
  },

  async testModelConfiguration(
    configurationId: string,
  ): Promise<{ passed: boolean; message: string }> {
    return adminOpenApiData(
      adminOpenApi.POST(
        "/admin-api/v1/model-configurations/{configuration_id}/test",
        {
          params: { path: { configuration_id: configurationId } },
        },
      ),
    );
  },

  async deleteModelConfiguration(configurationId: string): Promise<void> {
    await adminOpenApiData(
      adminOpenApi.DELETE(
        "/admin-api/v1/model-configurations/{configuration_id}",
        {
          params: { path: { configuration_id: configurationId } },
        },
      ),
    );
  },

  async setModelConfigurationStatus(
    configurationId: string,
    status: "available" | "disabled",
  ): Promise<void> {
    await adminOpenApiData(
      adminOpenApi.PATCH(
        "/admin-api/v1/model-configurations/{configuration_id}/status",
        {
          params: { path: { configuration_id: configurationId } },
          body: { status },
        },
      ),
    );
  },

  async modelRoutes(purpose?: ModelRoute["purpose"]): Promise<ModelRoute[]> {
    const response = await adminOpenApiData(
      adminOpenApi.GET("/admin-api/v1/model-routes", {
        params: { query: purpose ? { purpose } : {} },
      }),
    );
    return response.items.map((item) => {
      const policy = record(item.policy);
      return {
        id: item.id,
        purpose: item.purpose as ModelRoute["purpose"],
        display_name: text(policy.display_name, "未命名模型路由"),
        version: item.version_no,
        primary_deployment_id: item.primary_deployment_id,
        fallback_deployment_ids: strings(item.fallback_deployment_ids),
        timeout_ms: number(policy.timeout_ms, 120_000),
        max_attempts: number(policy.max_attempts, 2),
        status: configStatus(item.status),
        updated_at: item.published_at ?? item.created_at,
      };
    });
  },

  async testRoute(
    routeId: string,
  ): Promise<{ passed: boolean; message: string }> {
    return adminOpenApiData(
      adminOpenApi.POST("/admin-api/v1/model-routes/{route_id}/test", {
        params: { path: { route_id: routeId } },
      }),
    );
  },

  async publishRoute(routeId: string): Promise<void> {
    await adminOpenApiData(
      adminOpenApi.POST("/admin-api/v1/model-routes/{route_id}/publish", {
        params: { path: { route_id: routeId } },
      }),
    );
  },

  async saveRouteDraft(route: ModelRoute): Promise<void> {
    await adminOpenApiData(
      adminOpenApi.POST("/admin-api/v1/model-routes", {
        body: {
          purpose: route.purpose,
          primary_deployment_id: route.primary_deployment_id,
          fallback_deployment_ids: route.fallback_deployment_ids,
          policy: {
            display_name: route.display_name,
            timeout_ms: route.timeout_ms,
            max_attempts: route.max_attempts,
          },
        },
      }),
    );
  },

  async disableRoute(routeId: string): Promise<void> {
    await adminOpenApiData(
      adminOpenApi.POST("/admin-api/v1/model-routes/{route_id}/disable", {
        params: { path: { route_id: routeId } },
      }),
    );
  },

  async retryJob(jobId: string, reason: string): Promise<void> {
    await adminOpenApiData(
      adminOpenApi.POST("/admin-api/v1/jobs/{job_id}/retry", {
        params: { path: { job_id: jobId } },
        body: { reason },
      }),
    );
  },

  async cancelJob(jobId: string, reason: string): Promise<void> {
    await adminOpenApiData(
      adminOpenApi.POST("/admin-api/v1/jobs/{job_id}/cancel", {
        params: { path: { job_id: jobId } },
        body: { reason },
      }),
    );
  },

  async reconcileJob(jobId: string, reason: string): Promise<void> {
    await adminOpenApiData(
      adminOpenApi.POST("/admin-api/v1/jobs/{job_id}/reconcile", {
        params: { path: { job_id: jobId } },
        body: { reason },
      }),
    );
  },

  async updateUser(
    userId: string,
    input: {
      status?: "active" | "disabled";
      ai_enabled?: boolean;
      wechat_enabled?: boolean;
      storage_bytes?: number;
      single_file_bytes?: number;
      official_account_count?: number;
      reason: string;
    },
  ): Promise<void> {
    await adminOpenApiData(
      adminOpenApi.PATCH("/admin-api/v1/users/{user_id}", {
        params: { path: { user_id: userId } },
        body: input,
      }),
    );
  },

  async recordUserDiagnostic(
    userId: string,
    reason: string,
  ): Promise<{ message: string }> {
    return adminOpenApiData(
      adminOpenApi.POST("/admin-api/v1/users/{user_id}/diagnostics", {
        params: { path: { user_id: userId } },
        body: { reason },
      }),
    );
  },

  async adjustQuota(
    userId: string,
    direction: "credit" | "debit",
    amount: number,
    reason: string,
  ): Promise<void> {
    await adminOpenApiData(
      adminOpenApi.POST("/admin-api/v1/users/{user_id}/quota-adjustments", {
        params: {
          path: { user_id: userId },
          header: { "Idempotency-Key": requestId("admin-quota") },
        },
        body: { direction, amount, reason },
      }),
    );
  },

  async dashboard(): Promise<{ summary: DashboardSummary; jobs: JobRecord[] }> {
    const [source, jobs] = await Promise.all([
      adminOpenApiData(adminOpenApi.GET("/admin-api/v1/dashboard")),
      this.jobs(),
    ]);
    const aiTotal = source.ai.today ?? source.ai.total;
    const aiFailed = source.ai.failed ?? 0;
    return {
      summary: {
        metrics: [
          {
            label: "用户总数",
            value: String(source.users.total),
            delta: `今日新增 ${source.users.new_today ?? 0}`,
            tone: "primary",
            route: "/users",
          },
          {
            label: "今日 AI 任务",
            value: String(aiTotal),
            delta: `${aiFailed} 今日失败`,
            tone: aiFailed ? "warning" : "positive",
            route: "/tasks",
          },
          {
            label: "公众号连接",
            value: String(
              source.account_health.healthy +
                source.account_health.degraded +
                source.account_health.down,
            ),
            tone: "primary",
            route: "/wechat/accounts",
          },
          {
            label: "失败任务",
            value: String(source.jobs.failed ?? 0),
            tone: (source.jobs.failed ?? 0) ? "negative" : "positive",
            route: "/tasks",
          },
        ],
        ai_success_rate: aiTotal
          ? Math.round(((aiTotal - aiFailed) / aiTotal) * 1000) / 10
          : 100,
        ai_average_latency_ms: source.ai_average_latency_ms,
        current_abnormal_models: source.abnormal_models,
        account_health: source.account_health,
        failed_tasks: { failed: source.jobs.failed ?? 0 },
        recent_changes: [...source.recent_changes],
      },
      jobs,
    };
  },

  async jobs(): Promise<JobRecord[]> {
    const response = await adminOpenApiData(
      adminOpenApi.GET("/admin-api/v1/jobs", {
        params: { query: { limit: 500 } },
      }),
    );
    return response.items.map((item): JobRecord => {
      const frozen = record(item.frozen_payload);
      const typeMap: Record<string, JobRecord["type"]> = {
        ai_run: "ai",
        article_revision: "ai",
        document_processing: "file_parse",
        layout_extraction: "file_parse",
        article_index: "embedding",
        knowledge_sync: "knowledge_sync",
        external_knowledge_sync: "knowledge_sync",
        wechat_draft: "wechat_draft",
        wechat_publish: "wechat_publish",
        preference: "preference",
      };
      return {
        id: item.id,
        type: typeMap[item.job_type] ?? "ai",
        owner_display_name: item.owner_id
          ? `用户 ${item.owner_id.slice(0, 8)}`
          : "系统",
        resource_label: `${item.resource_type} · ${item.resource_id.slice(0, 12)}`,
        stage: item.stage,
        status: taskStatus(item.status),
        attempt_count: item.attempts,
        frozen_snapshot_id: text(frozen.snapshot_id, item.resource_id),
        model_or_account: text(
          frozen.model_id,
          text(frozen.official_account_id, item.queue),
        ),
        duration_ms: number(frozen.duration_ms),
        ...(item.error_code ? { error_code: item.error_code } : {}),
        ...(item.error_message ? { error_message: item.error_message } : {}),
        ...(text(frozen.external_id)
          ? { external_id: text(frozen.external_id) }
          : {}),
        created_at: item.created_at,
        updated_at: item.updated_at,
      };
    });
  },

  async modelConfigurations(): Promise<ModelConfiguration[]> {
    const response = await adminOpenApiData(
      adminOpenApi.GET("/admin-api/v1/model-configurations"),
    );
    return response.items.map((item) => {
      const test = record(item.last_test_result);
      return {
        id: item.id,
        name: item.name,
        model_id: item.model_id,
        model_type: ["chat", "embedding", "rerank", "vision"].includes(
          item.model_type,
        )
          ? (item.model_type as ModelConfiguration["model_type"])
          : "chat",
        adapter: [
          "openai_responses",
          "openai_chat_completions",
          "litellm_responses",
          "litellm_chat_completions",
          "manus_v2",
        ].includes(item.adapter)
          ? (item.adapter as ModelConfiguration["adapter"])
          : "openai_chat_completions",
        base_url: item.base_url,
        secret_configured: item.secret_configured,
        status: modelConfigurationStatus(item.status),
        last_tested_at: item.last_tested_at,
        last_test_result: text(test.message)
          ? { passed: boolean(test.passed), message: text(test.message) }
          : null,
        created_at: item.created_at,
        updated_at: item.updated_at,
      };
    });
  },

  async prompts(): Promise<PromptVersion[]> {
    const bundles = await adminOpenApiData(
      adminOpenApi.GET("/admin-api/v1/prompt-bundles"),
    );
    const details = await Promise.all(
      bundles.items.map((bundle) =>
        adminOpenApiData(
          adminOpenApi.GET(
            "/admin-api/v1/prompt-bundles/{bundle_id}/versions",
            {
              params: { path: { bundle_id: bundle.id } },
            },
          ),
        ),
      ),
    );
    return details.flatMap(({ bundle, versions }) =>
      versions.map((version): PromptVersion => {
        const operation = record(version.operation_templates);
        const variables = record(version.variable_schema);
        return {
          id: version.id,
          bundle_code: bundle.code,
          display_name: bundle.name,
          version: version.version_no,
          description: "",
          system_template: version.system_template,
          operation_template:
            Object.values(operation).filter(
              (item): item is string => typeof item === "string",
            )[0] ?? "",
          variables: Object.keys(variables),
          checksum: version.checksum,
          status: configStatus(version.status),
          updated_by: "管理员",
          updated_at: version.created_at,
        };
      }),
    );
  },

  async savePrompt(prompt: PromptVersion, exists: boolean): Promise<string> {
    const bundles = await adminOpenApiData(
      adminOpenApi.GET("/admin-api/v1/prompt-bundles"),
    );
    const bundle = bundles.items.find(
      (item) => item.code === prompt.bundle_code,
    );
    if (!bundle) throw new Error(`提示词集合 ${prompt.bundle_code} 不存在。`);
    const body = {
      system_template: prompt.system_template,
      operation_templates: { default: prompt.operation_template },
      variable_schema: Object.fromEntries(
        prompt.variables.map((name) => [name, { type: "string" }]),
      ),
      output_schema: { type: "object" },
    };
    if (exists) {
      const saved = await adminOpenApiData(
        adminOpenApi.PATCH("/admin-api/v1/prompt-versions/{version_id}", {
          params: { path: { version_id: prompt.id } },
          body,
        }),
      );
      return saved.id;
    }
    const saved = await adminOpenApiData(
      adminOpenApi.POST("/admin-api/v1/prompt-bundles/{bundle_id}/versions", {
        params: { path: { bundle_id: bundle.id } },
        body,
      }),
    );
    return saved.id;
  },

  async testPrompt(
    versionId: string,
    input?: string,
  ): Promise<{ passed: boolean; message: string }> {
    return adminOpenApiData(
      adminOpenApi.POST("/admin-api/v1/prompt-versions/{version_id}/test", {
        params: { path: { version_id: versionId } },
        body: input ? { input } : undefined,
      }),
    );
  },

  async publishPrompt(versionId: string): Promise<void> {
    await adminOpenApiData(
      adminOpenApi.POST("/admin-api/v1/prompt-versions/{version_id}/publish", {
        params: { path: { version_id: versionId } },
      }),
    );
  },

  async disablePrompt(versionId: string): Promise<void> {
    await adminOpenApiData(
      adminOpenApi.POST("/admin-api/v1/prompt-versions/{version_id}/disable", {
        params: { path: { version_id: versionId } },
      }),
    );
  },

  async rollbackPrompt(source: PromptVersion): Promise<void> {
    const restoredId = await this.savePrompt(
      { ...source, id: crypto.randomUUID(), status: "draft" },
      false,
    );
    const tested = await this.testPrompt(restoredId);
    if (!tested.passed) throw new Error(tested.message);
    await this.publishPrompt(restoredId);
  },

  async skills(): Promise<OfficialSkill[]> {
    const response = await adminOpenApiData(
      adminOpenApi.GET("/admin-api/v1/official-skills"),
    );
    const versions = await Promise.all(
      response.items.map((item) =>
        adminOpenApiData(
          adminOpenApi.GET(
            "/admin-api/v1/official-skills/{skill_id}/versions",
            {
              params: { path: { skill_id: item.id } },
            },
          ),
        ),
      ),
    );
    return response.items.map((item, index) => {
      const version = versions[index]?.items[0];
      return {
        id: item.id,
        version_id: version?.id,
        code: item.code,
        name: item.name,
        description: item.description,
        category: item.category,
        scenarios: scenarios(version?.input_schema),
        instructions: version?.instructions ?? "",
        version: version?.version_no ?? item.current_version_no,
        sort_order: item.sort_order,
        status: configStatus(
          item.status === "disabled"
            ? "disabled"
            : (version?.status ?? item.status),
        ),
        enabled_users: 0,
        updated_at: item.updated_at,
      };
    });
  },

  async saveSkill(skill: OfficialSkill, exists: boolean): Promise<void> {
    let skillId = skill.id;
    if (exists) {
      await adminOpenApiData(
        adminOpenApi.PATCH("/admin-api/v1/official-skills/{skill_id}", {
          params: { path: { skill_id: skillId } },
          body: {
            name: skill.name,
            description: skill.description,
            category: skill.category,
            sort_order: skill.sort_order,
          },
        }),
      );
    } else {
      const created = await adminOpenApiData(
        adminOpenApi.POST("/admin-api/v1/official-skills", {
          body: {
            code: skill.code,
            name: skill.name,
            description: skill.description,
            category: skill.category,
            sort_order: skill.sort_order,
          },
        }),
      );
      skillId = created.id;
    }
    const body = {
      instructions: skill.instructions,
      input_schema: { type: "object", scenario: skill.scenarios.join("、") },
      output_schema: { type: "object" },
      tool_policy: { wechat_publish: false },
    };
    if (skill.version_id) {
      await adminOpenApiData(
        adminOpenApi.PATCH("/admin-api/v1/skill-versions/{version_id}", {
          params: { path: { version_id: skill.version_id } },
          body,
        }),
      );
    } else {
      await adminOpenApiData(
        adminOpenApi.POST("/admin-api/v1/official-skills/{skill_id}/versions", {
          params: { path: { skill_id: skillId } },
          body,
        }),
      );
    }
  },

  async testSkill(
    versionId: string,
    input?: string,
  ): Promise<{ passed: boolean; message: string }> {
    return adminOpenApiData(
      adminOpenApi.POST("/admin-api/v1/skill-versions/{version_id}/test", {
        params: { path: { version_id: versionId } },
        body: input ? { input } : undefined,
      }),
    );
  },

  async publishSkill(versionId: string): Promise<void> {
    await adminOpenApiData(
      adminOpenApi.POST("/admin-api/v1/skill-versions/{version_id}/publish", {
        params: { path: { version_id: versionId } },
      }),
    );
  },

  async disableSkill(skillId: string): Promise<void> {
    await adminOpenApiData(
      adminOpenApi.POST("/admin-api/v1/official-skills/{skill_id}/disable", {
        params: { path: { skill_id: skillId } },
      }),
    );
  },

  async restoreSkill(skillId: string): Promise<void> {
    await adminOpenApiData(
      adminOpenApi.POST("/admin-api/v1/official-skills/{skill_id}/restore", {
        params: { path: { skill_id: skillId } },
      }),
    );
  },

  async reorderSkill(skillId: string, sortOrder: number): Promise<void> {
    await adminOpenApiData(
      adminOpenApi.PATCH("/admin-api/v1/official-skills/{skill_id}", {
        params: { path: { skill_id: skillId } },
        body: { sort_order: sortOrder },
      }),
    );
  },

  async users(): Promise<UserRecord[]> {
    const list = await adminOpenApiData(
      adminOpenApi.GET("/admin-api/v1/users", {
        params: { query: { limit: 200 } },
      }),
    );
    const details = await Promise.all(
      list.items.map((item) =>
        adminOpenApiData(
          adminOpenApi.GET("/admin-api/v1/users/{user_id}", {
            params: { path: { user_id: item.id } },
          }),
        ),
      ),
    );
    return details.map(
      ({ user, quota, limits, official_accounts, failed_jobs }) => ({
        id: user.id,
        masked_phone: mask(user.phone, 3, 4),
        masked_email: mask(user.email, 2, 4),
        display_name: user.display_name,
        status: userStatus(user.status),
        registered_at: user.created_at,
        last_login_at: user.last_login_at,
        quota: {
          ai_monthly: quota?.balance ?? 0,
          ai_used: 0,
          storage_gb: (limits?.storage_bytes ?? 0) / 1024 ** 3,
          storage_used_gb: 0,
          max_file_mb: (limits?.single_file_bytes ?? 0) / 1024 ** 2,
          official_accounts: limits?.official_account_count ?? 0,
          official_accounts_used: official_accounts.length,
        },
        capabilities: {
          ai: limits?.ai_enabled ?? false,
          wechat: limits?.wechat_enabled ?? false,
          uploads: (limits?.storage_bytes ?? 0) > 0,
        },
        bound_accounts: official_accounts.length,
        failed_tasks: failed_jobs.length,
      }),
    );
  },

  async wechatConfigs(): Promise<WechatPlatformConfig[]> {
    const response = await adminOpenApiData(
      adminOpenApi.GET("/admin-api/v1/wechat-platform-configs"),
    );
    return response.items.map((item) => ({
      component_appid: item.component_appid,
      app_secret_configured: item.component_secret_configured,
      message_token_configured: item.message_token_configured,
      encoding_aes_key_configured: item.encoding_aes_key_configured,
      ticket_callback_url: item.ticket_callback_url,
      authorization_callback_url: item.authorization_callback_url,
      status: configStatus(item.status),
      ticket_health: item.last_ticket_at ? "healthy" : "down",
      token_health: item.last_token_refresh_at ? "healthy" : "down",
      last_ticket_at: item.last_ticket_at,
      last_token_refresh_at: item.last_token_refresh_at,
      affected_capabilities:
        item.status === "published" &&
        item.last_ticket_at &&
        item.last_token_refresh_at
          ? []
          : ["新增公众号绑定", "公众号草稿与发布"],
    }));
  },

  async saveWechatConfig(
    config: WechatPlatformConfig,
    secretRefs: {
      appSecret?: string;
      messageToken?: string;
      encodingAesKey?: string;
    },
  ): Promise<void> {
    await adminOpenApiData(
      adminOpenApi.PUT("/admin-api/v1/wechat-platform-configs/{environment}", {
        params: { path: { environment: "production" } },
        body: {
          environment: "production",
          component_appid: config.component_appid,
          component_appsecret: secretRefs.appSecret || null,
          message_token: secretRefs.messageToken || null,
          encoding_aes_key: secretRefs.encodingAesKey || null,
          authorization_callback_url: config.authorization_callback_url,
          ticket_callback_url: config.ticket_callback_url,
          permission_set: ["draft", "publish"],
        },
      }),
    );
  },

  async testWechatConfig(): Promise<{ passed: boolean; message: string }> {
    return adminOpenApiData(
      adminOpenApi.POST(
        "/admin-api/v1/wechat-platform-configs/{environment}/test",
        {
          params: { path: { environment: "production" } },
        },
      ),
    );
  },

  async publishWechatConfig(): Promise<void> {
    await adminOpenApiData(
      adminOpenApi.POST(
        "/admin-api/v1/wechat-platform-configs/{environment}/publish",
        {
          params: { path: { environment: "production" } },
        },
      ),
    );
  },

  async officialAccounts(): Promise<OfficialAccount[]> {
    const [response, users] = await Promise.all([
      adminOpenApiData(
        adminOpenApi.GET("/admin-api/v1/official-accounts", {
          params: { query: { limit: 500 } },
        }),
      ),
      adminOpenApiData(
        adminOpenApi.GET("/admin-api/v1/users", {
          params: { query: { limit: 200 } },
        }),
      ),
    ]);
    const names = new Map(
      users.items.map((item) => [item.id, item.display_name]),
    );
    return response.items.map((item) => {
      const capabilities = strings(item.capability_flags);
      const status: OfficialAccount["status"] =
        item.status === "connected"
          ? "connected"
          : item.status === "reconnect_required"
            ? "reconnect_required"
            : "limited";
      return {
        id: item.id,
        name: item.name,
        owner_id: item.owner_id,
        owner_display_name:
          names.get(item.owner_id) ?? `用户 ${item.owner_id.slice(0, 8)}`,
        status,
        authorized_at: item.authorized_at ?? item.created_at,
        token_expires_at: item.token_expires_at,
        draft_capable: capabilities.includes("draft"),
        publish_capable: capabilities.includes("publish"),
        last_refresh_result: item.last_synced_at ? "最近同步成功" : "尚未同步",
        recent_task_status: null,
      };
    });
  },

  async refreshOfficialAccount(
    accountId: string,
    reason: string,
  ): Promise<void> {
    await adminOpenApiData(
      adminOpenApi.POST(
        "/admin-api/v1/official-accounts/{account_id}/refresh",
        {
          params: { path: { account_id: accountId } },
          body: { reason },
        },
      ),
    );
  },

  async markOfficialAccountReconnect(
    accountId: string,
    reason: string,
  ): Promise<void> {
    await adminOpenApiData(
      adminOpenApi.POST(
        "/admin-api/v1/official-accounts/{account_id}/mark-reconnect",
        {
          params: { path: { account_id: accountId } },
          body: { reason },
        },
      ),
    );
  },

  async systemSettings(): Promise<SystemSettings> {
    const response = await adminOpenApiData(
      adminOpenApi.GET("/admin-api/v1/system-settings"),
    );
    const latest = [...response.items]
      .sort((a, b) => b.version_no - a.version_no)
      .filter(
        (item, index, items) =>
          items.findIndex((candidate) => candidate.section === item.section) ===
          index,
      );
    const merged = Object.assign(
      {},
      ...latest.map((item) => record(item.values)),
    );
    const newest = [...latest].sort((a, b) =>
      b.created_at.localeCompare(a.created_at),
    )[0];
    return {
      version: Math.max(0, ...latest.map((item) => item.version_no)),
      status:
        latest.length === 6 &&
        latest.every((item) => item.status === "published")
          ? "published"
          : configStatus(newest?.status),
      welcome_message: text(merged.welcome_message),
      example_prompts: strings(merged.example_prompts),
      allowed_extensions: strings(merged.allowed_extensions),
      max_file_mb: number(merged.max_file_mb, 100),
      link_fetch_enabled: boolean(merged.link_fetch_enabled),
      max_clarification_rounds: number(merged.max_clarification_rounds, 3),
      min_article_length: number(merged.min_article_length, 300),
      max_article_length: number(merged.max_article_length, 20_000),
      ai_run_credit_cost: number(merged.ai_run_credit_cost, 1),
      preference_enabled_by_default: boolean(
        merged.preference_enabled_by_default,
        true,
      ),
      autosave_seconds: number(merged.autosave_seconds, 10),
      history_versions: number(merged.history_versions, 50),
      wechat_draft_enabled: boolean(merged.wechat_draft_enabled, true),
      wechat_publish_enabled: boolean(merged.wechat_publish_enabled, true),
      max_article_images: number(merged.max_article_images, 20),
      feature_flags: Object.fromEntries(
        Object.entries(record(merged.feature_flags)).filter(
          (entry): entry is [string, boolean] => typeof entry[1] === "boolean",
        ),
      ),
      updated_at:
        newest?.published_at ?? newest?.created_at ?? new Date(0).toISOString(),
    };
  },

  async validateSystemSettings(
    settings: SystemSettings,
  ): Promise<{ passed: boolean; checks: readonly string[] }> {
    return adminOpenApiData(
      adminOpenApi.POST("/admin-api/v1/system-settings/validate", {
        body: { sections: systemSettingsSections(settings) },
      }),
    );
  },

  async saveSystemSettings(settings: SystemSettings): Promise<string[]> {
    const saved = await adminOpenApiData(
      adminOpenApi.POST("/admin-api/v1/system-settings/bulk-drafts", {
        body: { sections: systemSettingsSections(settings) },
      }),
    );
    return saved.items.map((item) => item.id);
  },

  async publishSystemSettings(
    settingIds: string[],
    reason: string,
  ): Promise<void> {
    await adminOpenApiData(
      adminOpenApi.POST("/admin-api/v1/system-settings/bulk-publish", {
        body: { setting_ids: settingIds, reason },
      }),
    );
  },

  async loadAiRunCreditCost(): Promise<number> {
    return number((await loadPublishedAiSettings()).ai_run_credit_cost, 1);
  },

  async saveAiRunCreditCost(cost: number): Promise<void> {
    const values = await loadPublishedAiSettings();
    const draft = await adminOpenApiData(
      adminOpenApi.POST("/admin-api/v1/system-settings", {
        body: {
          section: "ai",
          values: { ...values, ai_run_credit_cost: cost },
        },
      }),
    );
    await adminOpenApiData(
      adminOpenApi.POST("/admin-api/v1/system-settings/{setting_id}/publish", {
        params: { path: { setting_id: draft.id } },
      }),
    );
  },

  async externalKnowledgeSources(): Promise<ExternalKnowledgeSource[]> {
    const response = await adminOpenApiData(
      adminOpenApi.GET("/admin-api/v1/external-knowledge-sources"),
    );
    return response.items.map((item) => ({
      id: item.id,
      name: item.name,
      app_key: item.app_key,
      secret_configured: item.secret_configured,
      targets: item.targets.map((target) => ({
        type: target.type,
        id: target.id,
      })),
      owner_staff_ids: { ...item.owner_staff_ids },
      sync_owner_id: item.sync_owner_id,
      status: item.status === "active" ? "active" : "disabled",
      last_tested_at: item.last_tested_at,
      last_test_passed: boolean(record(item.last_test_result).passed),
      last_synced_at: item.last_synced_at,
      error_code: item.error_code,
      created_at: item.created_at,
      updated_at: item.updated_at,
    }));
  },

  async createExternalKnowledgeSource(input: {
    name: string;
    appKey: string;
    secretRef: string;
    targets: ExternalKnowledgeTarget[];
    ownerStaffIds: Record<string, string>;
    syncOwnerId: string;
  }): Promise<void> {
    await adminOpenApiData(
      adminOpenApi.POST("/admin-api/v1/external-knowledge-sources", {
        body: {
          name: input.name,
          app_key: input.appKey,
          secret_ref: input.secretRef,
          targets: input.targets,
          owner_staff_ids: input.ownerStaffIds,
          sync_owner_id: input.syncOwnerId,
        },
      }),
    );
  },

  async updateExternalKnowledgeSource(
    sourceId: string,
    input: {
      name?: string;
      appKey?: string;
      secretRef?: string;
      targets?: ExternalKnowledgeTarget[];
      ownerStaffIds?: Record<string, string>;
      syncOwnerId?: string;
      status?: "active" | "disabled";
      reason: string;
    },
  ): Promise<void> {
    await adminOpenApiData(
      adminOpenApi.PATCH(
        "/admin-api/v1/external-knowledge-sources/{source_id}",
        {
          params: { path: { source_id: sourceId } },
          body: {
            name: input.name,
            app_key: input.appKey,
            secret_ref: input.secretRef,
            targets: input.targets,
            owner_staff_ids: input.ownerStaffIds,
            sync_owner_id: input.syncOwnerId,
            status: input.status,
            reason: input.reason,
          },
        },
      ),
    );
  },

  async testExternalKnowledgeSource(
    sourceId: string,
  ): Promise<{ passed: boolean; message: string }> {
    return adminOpenApiData(
      adminOpenApi.POST(
        "/admin-api/v1/external-knowledge-sources/{source_id}/test",
        {
          params: { path: { source_id: sourceId } },
        },
      ),
    );
  },

  async syncExternalKnowledgeSource(
    sourceId: string,
    reason: string,
  ): Promise<void> {
    await adminOpenApiData(
      adminOpenApi.POST(
        "/admin-api/v1/external-knowledge-sources/{source_id}/sync",
        {
          params: { path: { source_id: sourceId } },
          body: { reason },
        },
      ),
    );
  },

  async admins(): Promise<AdminAccount[]> {
    const response = await adminOpenApiData(
      adminOpenApi.GET("/admin-api/v1/admins"),
    );
    return response.items.map((item) => ({
      id: item.id,
      username: item.username,
      display_name: item.username,
      role: item.permissions.includes("*")
        ? "super_admin"
        : item.permissions.includes("audit:read") &&
            item.permissions.length === 1
          ? "auditor"
          : "operations",
      status: item.status === "disabled" ? "disabled" : "active",
      last_login_at: item.last_login_at,
      created_at: item.created_at,
    }));
  },

  async createAdmin(account: AdminAccount, password: string): Promise<void> {
    await adminOpenApiData(
      adminOpenApi.POST("/admin-api/v1/admins", {
        body: {
          username: account.username,
          password,
          permissions: permissionsForRole(account.role),
        },
      }),
    );
  },

  async updateAdmin(
    adminId: string,
    input: { status?: "active" | "disabled"; role?: AdminAccount["role"] },
    reason: string,
  ): Promise<void> {
    await adminOpenApiData(
      adminOpenApi.PATCH("/admin-api/v1/admins/{admin_id}", {
        params: { path: { admin_id: adminId } },
        body: {
          status: input.status,
          permissions: input.role ? permissionsForRole(input.role) : undefined,
          reason,
        },
      }),
    );
  },

  async audits(): Promise<AuditLog[]> {
    const response = await adminOpenApiData(
      adminOpenApi.GET("/admin-api/v1/audit-logs", {
        params: { query: { limit: 500 } },
      }),
    );
    return response.items.map((item) => ({
      id: item.id,
      actor: `${item.actor_type}:${item.actor_id}`,
      action: item.action,
      resource_type: item.target_type,
      resource_label: item.target_id ?? "—",
      reason: item.reason ?? "",
      request_id: item.request_id ?? "—",
      ip_address: "未记录",
      created_at: item.created_at,
      result: "success",
    }));
  },
};

<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'
import type { SystemSettings } from '@/api/contracts'
import { adminRepository } from '@/api/repository'
import AppIcon from '@/components/base/AppIcon.vue'
import StatusBadge from '@/components/base/StatusBadge.vue'
import ConfirmActionDialog from '@/components/composite/ConfirmActionDialog.vue'
import PageHeader from '@/components/composite/PageHeader.vue'

type SettingsTab = 'home' | 'files' | 'ai' | 'articles' | 'wechat' | 'features'

const settings = reactive<SystemSettings>({
  version: 0,
  status: 'draft',
  welcome_message: '',
  example_prompts: [],
  allowed_extensions: [],
  max_file_mb: 0,
  link_fetch_enabled: false,
  max_clarification_rounds: 0,
  min_article_length: 0,
  max_article_length: 0,
  ai_run_credit_cost: 0,
  preference_enabled_by_default: false,
  autosave_seconds: 0,
  history_versions: 0,
  wechat_draft_enabled: false,
  wechat_publish_enabled: false,
  max_article_images: 0,
  feature_flags: {},
  updated_at: new Date(0).toISOString(),
})
const tab = ref<SettingsTab>('home')
const saving = ref(false)
const testing = ref(false)
const publishConfirm = ref(false)
const testReport = ref<string[]>([])
const pendingSettingIds = ref<string[]>([])
const extensionOptions = [
  'pdf',
  'docx',
  'pptx',
  'xlsx',
  'csv',
  'txt',
  'md',
  'html',
  'png',
  'jpg',
  'mp3',
  'mp4',
]
const tabOptions = [
  { name: 'home', label: '创作首页', icon: 'home' },
  { name: 'files', label: '文件设置', icon: 'upload_file' },
  { name: 'ai', label: 'AI 设置', icon: 'smart_toy' },
  { name: 'articles', label: '文章设置', icon: 'edit_note' },
  { name: 'wechat', label: '公众号设置', icon: 'forum' },
  { name: 'features', label: '功能开关', icon: 'tune' },
] as const
const featureLabels: Record<string, string> = {
  personal_skills: '个人技能',
  template_extraction: '公众号链接提取模板',
  external_knowledge: '外部知识源',
  visual_understanding: '图片理解',
}
const publishReady = computed(
  () => settings.status === 'testing' && testReport.value.every((item) => item.startsWith('通过')),
)

function errorMessage(error: unknown, fallback: string): void {
  ElMessage.error(error instanceof Error ? error.message : fallback)
}

onMounted(async () => {
  try {
    Object.assign(settings, await adminRepository.systemSettings())
  } catch (error) {
    errorMessage(error, '系统设置加载失败。')
  }
})

function markDraft(): void {
  settings.status = 'draft'
  testReport.value = []
  pendingSettingIds.value = []
}
function addPrompt(): void {
  settings.example_prompts.push('新的示例指令')
  markDraft()
}
function removePrompt(index: number): void {
  settings.example_prompts.splice(index, 1)
  markDraft()
}

async function saveDraft(): Promise<void> {
  saving.value = true
  try {
    pendingSettingIds.value = await adminRepository.saveSystemSettings(settings)
    settings.status = 'draft'
    settings.updated_at = new Date().toISOString()
    ElMessage.success('系统设置草稿已保存，线上继续使用当前发布版本。')
  } catch (error) {
    errorMessage(error, '系统设置保存失败。')
  } finally {
    saving.value = false
  }
}

async function runValidation(): Promise<void> {
  testing.value = true
  testReport.value = []
  try {
    const result = await adminRepository.validateSystemSettings(settings)
    testReport.value = result.checks.map((item) => `${result.passed ? '通过' : '失败'}：${item}`)
    settings.status = result.passed ? 'testing' : 'draft'
    ElMessage[result.passed ? 'success' : 'error'](
      result.passed ? '服务端配置检查通过，可以发布。' : '服务端配置检查未通过，请修正后重试。',
    )
  } catch (error) {
    settings.status = 'draft'
    errorMessage(error, '服务端配置检查失败。')
  } finally {
    testing.value = false
  }
}

async function publish(reason = '管理员发布系统设置'): Promise<void> {
  if (!publishReady.value) return
  try {
    if (pendingSettingIds.value.length !== 6)
      pendingSettingIds.value = await adminRepository.saveSystemSettings(settings)
    await adminRepository.publishSystemSettings(pendingSettingIds.value, reason)
    Object.assign(settings, await adminRepository.systemSettings())
    pendingSettingIds.value = []
    ElMessage.success(`系统设置 v${settings.version} 已发布，用户下次打开页面或发起请求时生效。`)
  } catch (error) {
    errorMessage(error, '系统设置发布失败。')
  }
}
</script>

<template>
  <section class="admin-page">
    <PageHeader
      title="系统设置"
      description="统一控制创作首页、文件、AI、文章、公众号和公共功能。设置先保存草稿并校验，发布后由前后端共同执行。"
      eyebrow="系统治理"
    >
      <template #actions>
        <el-button @click="$router.push('/settings/admins')"
          ><AppIcon name="admin_panel_settings" />管理员账号</el-button
        >
        <el-button @click="$router.push('/settings/audit')"
          ><AppIcon name="fact_check" />审计日志</el-button
        >
      </template>
    </PageHeader>

    <el-card shadow="never" class="surface-card version-banner">
      <div class="version-row">
        <AppIcon name="tune" />
        <div class="version-copy">
          <strong>系统设置 v{{ settings.version }}</strong
          ><span
            >更新于 {{ settings.updated_at }}；发布后用户下一次打开页面或发起请求时使用新值。</span
          >
        </div>
        <StatusBadge :status="settings.status" />
      </div>
    </el-card>

    <div class="settings-layout">
      <el-card shadow="never" class="surface-card settings-nav" :body-style="{ padding: '8px' }">
        <el-menu :default-active="tab" @select="(value: string) => (tab = value as SettingsTab)">
          <el-menu-item v-for="item in tabOptions" :key="item.name" :index="item.name"
            ><AppIcon :name="item.icon" /><span>{{ item.label }}</span></el-menu-item
          >
        </el-menu>
      </el-card>

      <el-card shadow="never" class="surface-card settings-main">
        <el-select v-model="tab" class="mobile-tab" aria-label="设置分类">
          <el-option
            v-for="item in tabOptions"
            :key="item.name"
            :label="item.label"
            :value="item.name"
          />
        </el-select>

        <div v-if="tab === 'home'" class="settings-panel">
          <div class="panel-heading">
            <h2>创作首页</h2>
            <p>用户进入 AI 创作页时显示的新手引导。</p>
          </div>
          <el-form label-position="top"
            ><el-form-item label="欢迎语"
              ><el-input
                v-model="settings.welcome_message"
                type="textarea"
                :autosize="{ minRows: 3, maxRows: 8 }"
                maxlength="300"
                show-word-limit
                @update:model-value="markDraft" /></el-form-item
          ></el-form>
          <div class="field-group">
            <div class="field-heading">
              <div><strong>示例指令</strong><span>帮助用户快速开始，不会自动发送。</span></div>
              <el-button link type="primary" @click="addPrompt"
                ><AppIcon name="add" />添加</el-button
              >
            </div>
            <div class="prompt-list">
              <div
                v-for="(prompt, index) in settings.example_prompts"
                :key="index"
                class="prompt-row"
              >
                <AppIcon name="drag_indicator" />
                <el-input
                  v-model="settings.example_prompts[index]"
                  :aria-label="`示例 ${index + 1}`"
                  @update:model-value="markDraft"
                />
                <el-button
                  text
                  circle
                  type="danger"
                  :aria-label="`删除示例 ${index + 1}`"
                  @click="removePrompt(index)"
                  ><AppIcon name="delete"
                /></el-button>
              </div>
            </div>
          </div>
        </div>

        <div v-else-if="tab === 'files'" class="settings-panel">
          <div class="panel-heading">
            <h2>文件设置</h2>
            <p>前端提示与后端校验使用同一发布值。</p>
          </div>
          <el-form label-position="top">
            <el-form-item label="支持格式"
              ><el-select
                v-model="settings.allowed_extensions"
                multiple
                filterable
                allow-create
                @update:model-value="markDraft"
                ><el-option
                  v-for="item in extensionOptions"
                  :key="item"
                  :label="item"
                  :value="item" /></el-select
            ></el-form-item>
            <el-form-item label="默认单文件大小（MB）"
              ><el-input-number
                v-model="settings.max_file_mb"
                :min="1"
                :max="2048"
                @change="markDraft"
            /></el-form-item>
          </el-form>
          <div class="switch-row">
            <AppIcon name="link" /><span
              ><strong>网页链接抓取</strong
              ><small>后端仍执行 HTTPS、受控域名、重定向、大小和私网地址检查</small></span
            ><el-switch v-model="settings.link_fetch_enabled" @change="markDraft" />
          </div>
          <el-alert
            type="warning"
            :closable="false"
            show-icon
            title="允许格式不等于信任内容。文件仍需扩展名、MIME、Magic Number、大小和病毒扫描联合校验。"
          />
        </div>

        <div v-else-if="tab === 'ai'" class="settings-panel">
          <div class="panel-heading">
            <h2>AI 公共限制</h2>
            <p>控制追问、文章长度和偏好功能默认值。</p>
          </div>
          <el-form label-position="top" class="two-column">
            <el-form-item label="最大追问轮数"
              ><el-input-number
                v-model="settings.max_clarification_rounds"
                :min="0"
                :max="10"
                @change="markDraft"
            /></el-form-item>
            <div class="switch-row compact">
              <span><strong>默认启用写作偏好</strong></span
              ><el-switch v-model="settings.preference_enabled_by_default" @change="markDraft" />
            </div>
            <el-form-item label="文章最小长度（字）"
              ><el-input-number
                v-model="settings.min_article_length"
                :min="100"
                @change="markDraft"
            /></el-form-item>
            <el-form-item label="文章最大长度（字）"
              ><el-input-number
                v-model="settings.max_article_length"
                :min="500"
                @change="markDraft"
            /></el-form-item>
          </el-form>
          <el-alert
            type="info"
            :closable="false"
            title="用户本轮明确要求高于历史偏好；低置信度偏好只作为候选，不能直接生效。"
          />
        </div>

        <div v-else-if="tab === 'articles'" class="settings-panel">
          <div class="panel-heading">
            <h2>文章设置</h2>
            <p>管理自动保存间隔和可见历史版本数量。</p>
          </div>
          <el-form label-position="top" class="two-column">
            <el-form-item label="自动保存间隔（秒）"
              ><el-input-number
                v-model="settings.autosave_seconds"
                :min="5"
                :max="300"
                @change="markDraft"
            /></el-form-item>
            <el-form-item label="历史版本数量"
              ><el-input-number
                v-model="settings.history_versions"
                :min="5"
                :max="500"
                @change="markDraft"
            /></el-form-item>
          </el-form>
          <el-alert
            type="info"
            :closable="false"
            show-icon
            title="历史恢复会创建新版本，不覆盖旧版本。文章保存仍使用乐观锁，冲突时返回 409。"
          />
        </div>

        <div v-else-if="tab === 'wechat'" class="settings-panel">
          <div class="panel-heading">
            <h2>公众号设置</h2>
            <p>控制用户端草稿与发布入口以及图片限制。</p>
          </div>
          <div class="switch-list">
            <div class="switch-row">
              <AppIcon name="drafts" /><span
                ><strong>存入公众号草稿</strong
                ><small>开启后仍要求有效授权和最终预览确认</small></span
              ><el-switch v-model="settings.wechat_draft_enabled" @change="markDraft" />
            </div>
            <div class="switch-row">
              <AppIcon name="publish" /><span
                ><strong>正式发布</strong
                ><small>关闭时隐藏入口且后端拒绝命令；不影响已有文章</small></span
              ><el-switch v-model="settings.wechat_publish_enabled" @change="markDraft" />
            </div>
          </div>
          <el-form label-position="top"
            ><el-form-item label="单篇文章图片上限"
              ><el-input-number
                v-model="settings.max_article_images"
                :min="0"
                :max="200"
                @change="markDraft" /></el-form-item
          ></el-form>
          <el-alert
            type="warning"
            :closable="false"
            title="草稿和发布必须加载同一不可变 Render 的最终预览并由用户确认；管理端开关不能绕过确认。"
          />
        </div>

        <div v-else class="settings-panel">
          <div class="panel-heading">
            <h2>功能开关</h2>
            <p>入口显示与后端能力校验同步更新。</p>
          </div>
          <div class="switch-list">
            <div v-for="(enabled, key) in settings.feature_flags" :key="key" class="switch-row">
              <AppIcon name="tune" /><span
                ><strong>{{ featureLabels[key] ?? key }}</strong
                ><small>关闭只影响新的入口和请求，不删除历史数据。</small></span
              ><el-switch v-model="settings.feature_flags[key]" @change="markDraft" />
            </div>
          </div>
        </div>
      </el-card>
    </div>

    <el-card v-if="testReport.length" shadow="never" class="surface-card test-report">
      <h2>发布前检查</h2>
      <div
        v-for="item in testReport"
        :key="item"
        :class="item.startsWith('通过') ? 'check-pass' : 'check-fail'"
      >
        <AppIcon :name="item.startsWith('通过') ? 'check_circle' : 'error'" />{{ item }}
      </div>
    </el-card>

    <el-card shadow="never" class="surface-card action-footer">
      <div>
        <strong>v{{ settings.version }} · <StatusBadge :status="settings.status" /></strong
        ><span>运行中的任务使用开始时的配置快照。</span>
      </div>
      <div>
        <el-button :loading="saving" @click="saveDraft"><AppIcon name="save" />保存草稿</el-button
        ><el-button :loading="testing" @click="runValidation"
          ><AppIcon name="fact_check" />运行发布检查</el-button
        ><el-button type="success" :disabled="!publishReady" @click="publishConfirm = true"
          ><AppIcon name="publish" />发布设置</el-button
        >
      </div>
    </el-card>

    <ConfirmActionDialog
      v-model="publishConfirm"
      title="发布系统设置"
      :description="`发布 v${settings.version + 1} 后，用户下一次打开页面或发起请求时使用新设置；正在运行的任务继续使用原快照。`"
      confirm-label="确认发布"
      require-reason
      @confirm="publish"
    />
  </section>
</template>

<style scoped lang="scss">
.version-banner {
  margin-bottom: 18px;
  background: var(--app-action-primary-soft);
}
.version-row {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  min-width: 0;
}
.version-copy {
  display: grid;
  gap: 3px;
  min-width: 0;
}
.version-copy span {
  color: var(--app-text-secondary);
  overflow-wrap: anywhere;
}
.settings-layout {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
  gap: 18px;
  min-width: 0;
  align-items: start;
}
.settings-nav {
  position: sticky;
  top: 20px;
  min-width: 0;
  overflow: clip;
}
.settings-nav :deep(.el-menu) {
  border: 0;
}
.settings-nav :deep(.el-menu-item) {
  border-radius: 8px;
  gap: 10px;
}
.settings-main {
  min-width: 0;
  overflow: clip;
}
.mobile-tab {
  display: none;
  width: 100%;
  margin-bottom: 18px;
}
.settings-panel {
  display: grid;
  gap: 18px;
  min-width: 0;
}
.panel-heading h2,
.test-report h2 {
  margin: 0;
  font-size: 20px;
}
.panel-heading p {
  margin: 4px 0 0;
  color: var(--app-text-secondary);
  overflow-wrap: anywhere;
}
.settings-panel :deep(.el-form-item:last-child) {
  margin-bottom: 0;
}
.settings-panel :deep(.el-select) {
  width: 100%;
}
.field-group,
.prompt-list {
  display: grid;
  gap: 10px;
  min-width: 0;
}
.field-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
}
.field-heading > div {
  display: grid;
  min-width: 0;
}
.field-heading span,
.switch-row small {
  color: var(--app-text-secondary);
  font-size: 12px;
  overflow-wrap: anywhere;
}
.prompt-row {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.two-column {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  min-width: 0;
}
.two-column :deep(.el-input-number) {
  width: 100%;
}
.switch-list {
  border: 1px solid var(--app-border-default);
  border-radius: 8px;
  overflow: clip;
}
.switch-row {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  min-width: 0;
  padding: 14px 16px;
  border-bottom: 1px solid var(--app-border-default);
}
.switch-row:last-child {
  border-bottom: 0;
}
.switch-row > span {
  display: flex;
  min-width: 0;
  flex-direction: column;
}
.switch-row.compact {
  align-self: start;
  border: 1px solid var(--app-border-default);
  border-radius: 8px;
}
.test-report {
  display: grid;
  gap: 8px;
  min-width: 0;
  margin-top: 18px;
}
.test-report div {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  overflow-wrap: anywhere;
}
.check-pass {
  color: var(--app-action-success);
}
.check-fail {
  color: var(--app-action-danger);
}
.action-footer {
  position: sticky;
  z-index: 10;
  bottom: 12px;
  margin-top: 18px;
}
.action-footer :deep(.el-card__body) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  min-width: 0;
  padding: 14px 16px;
}
.action-footer div {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  min-width: 0;
}
.action-footer span {
  color: var(--app-text-secondary);
  overflow-wrap: anywhere;
}

@media (max-width: 899px) {
  .settings-layout {
    grid-template-columns: minmax(0, 1fr);
  }
  .settings-nav {
    display: none;
  }
  .mobile-tab {
    display: block;
  }
  .action-footer {
    position: static;
  }
  .action-footer :deep(.el-card__body) {
    align-items: stretch;
    flex-direction: column;
  }
}
@media (max-width: 599px) {
  .version-row {
    grid-template-columns: auto minmax(0, 1fr);
  }
  .version-row > :last-child {
    grid-column: 2;
    justify-self: start;
  }
  .two-column {
    grid-template-columns: minmax(0, 1fr);
  }
  .action-footer div:last-child {
    align-items: stretch;
    flex-direction: column;
  }
  .action-footer div:last-child .el-button {
    width: 100%;
    margin-left: 0;
  }
}
</style>

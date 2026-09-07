<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'
import type { ConfigStatus, PromptVersion } from '@/api/contracts'
import { adminRepository } from '@/api/repository'
import AppIcon from '@/components/base/AppIcon.vue'
import StatusBadge from '@/components/base/StatusBadge.vue'
import ConfirmActionDialog from '@/components/composite/ConfirmActionDialog.vue'
import PageHeader from '@/components/composite/PageHeader.vue'
import { cloneData } from '@/utils/clone'

const prompts = ref<PromptVersion[]>([])
const selectedId = ref(prompts.value[0]?.id ?? '')
const activeTab = ref<'editor' | 'test' | 'history'>('editor')
const saving = ref(false)
const testing = ref(false)
const confirmPublish = ref(false)
const confirmRollback = ref(false)
const testInput = ref(
  '请根据一份行业趋势摘要，为企业服务领域读者生成一篇结构清晰、只引用已提供资料的公众号文章。',
)
const testOutput = ref('')
const persistedIds = ref(new Set(prompts.value.map((item) => item.id)))
const newVersionDialog = ref(false)
const newVersionForm = reactive({ displayName: '', description: '' })

const current = computed(() => prompts.value.find((item) => item.id === selectedId.value) ?? null)
const bundleOptions = computed(() =>
  prompts.value.map((item) => ({
    label: `${item.display_name} · v${item.version}`,
    value: item.id,
  })),
)
const previousPublished = computed(
  () =>
    prompts.value
      .filter(
        (item) =>
          current.value &&
          item.bundle_code === current.value.bundle_code &&
          item.status === 'published' &&
          item.id !== current.value.id,
      )
      .sort((a, b) => b.version - a.version)[0] ?? null,
)
const bundleHistory = computed(() =>
  current.value
    ? prompts.value
        .filter((item) => item.bundle_code === current.value?.bundle_code)
        .sort((a, b) => b.version - a.version)
    : [],
)

function errorMessage(error: unknown, fallback: string): void {
  ElMessage.error(error instanceof Error ? error.message : fallback)
}

onMounted(async () => {
  try {
    prompts.value = await adminRepository.prompts()
    persistedIds.value = new Set(prompts.value.map((item) => item.id))
    selectedId.value = prompts.value[0]?.id ?? ''
  } catch (error) {
    errorMessage(error, '提示词版本加载失败。')
  }
})

function markDraft(): void {
  if (current.value?.status === 'draft') current.value.updated_at = new Date().toISOString()
}

function openNewVersion(): void {
  if (!current.value) return
  newVersionForm.displayName = current.value.display_name
  newVersionForm.description = current.value.description
  newVersionDialog.value = true
}

function createVersion(): void {
  if (!current.value || !newVersionForm.displayName.trim()) return
  const source = current.value
  const version =
    Math.max(
      ...prompts.value
        .filter((item) => item.bundle_code === source.bundle_code)
        .map((item) => item.version),
      source.version,
    ) + 1
  const item: PromptVersion = {
    ...cloneData(source),
    id: `${source.bundle_code}-v${version}-${crypto.randomUUID().slice(0, 5)}`,
    display_name: newVersionForm.displayName.trim(),
    description: newVersionForm.description.trim(),
    version,
    status: 'draft',
    checksum: '待保存后计算',
    test_result: undefined,
    updated_at: new Date().toISOString(),
  }
  prompts.value.unshift(item)
  selectedId.value = item.id
  newVersionDialog.value = false
  activeTab.value = 'editor'
  ElMessage.success(`已创建 ${item.display_name} v${item.version} 草稿。`)
}

function openVersion(id: string): void {
  selectedId.value = id
  activeTab.value = 'editor'
}

async function saveDraft(): Promise<void> {
  if (!current.value || current.value.status !== 'draft') return
  saving.value = true
  try {
    const savedId = await adminRepository.savePrompt(
      current.value,
      persistedIds.value.has(current.value.id),
    )
    prompts.value = await adminRepository.prompts()
    persistedIds.value = new Set(prompts.value.map((item) => item.id))
    selectedId.value = savedId
    ElMessage.success('提示词草稿和变量 Schema 已保存。')
  } catch (error) {
    errorMessage(error, '提示词保存失败。')
  } finally {
    saving.value = false
  }
}

async function runTest(): Promise<void> {
  if (
    !current.value ||
    !['draft', 'testing'].includes(current.value.status) ||
    !testInput.value.trim()
  )
    return
  testing.value = true
  testOutput.value = ''
  try {
    if (!persistedIds.value.has(current.value.id)) await saveDraft()
    const target = prompts.value.find((item) => item.id === selectedId.value)
    if (!target) return
    const result = await adminRepository.testPrompt(target.id, testInput.value)
    prompts.value = await adminRepository.prompts()
    persistedIds.value = new Set(prompts.value.map((item) => item.id))
    selectedId.value = target.id
    testOutput.value = result.message
    ElMessage[result.passed ? 'success' : 'warning'](result.message)
  } catch (error) {
    errorMessage(error, '提示词测试失败。')
  } finally {
    testing.value = false
  }
}

async function publish(): Promise<void> {
  if (!current.value || current.value.status !== 'testing') return
  try {
    await adminRepository.publishPrompt(current.value.id)
    prompts.value = await adminRepository.prompts()
    persistedIds.value = new Set(prompts.value.map((item) => item.id))
    ElMessage.success(`v${current.value?.version ?? ''} 已发布；只影响新的 AI 请求。`)
  } catch (error) {
    errorMessage(error, '提示词发布失败。')
  }
}

async function rollback(): Promise<void> {
  if (!current.value || !previousPublished.value) return
  try {
    await adminRepository.rollbackPrompt(previousPublished.value)
    prompts.value = await adminRepository.prompts()
    persistedIds.value = new Set(prompts.value.map((item) => item.id))
    selectedId.value =
      prompts.value.find(
        (item) => item.bundle_code === current.value?.bundle_code && item.status === 'published',
      )?.id ?? ''
    ElMessage.success('已从上一发布版本创建并发布新的恢复版本，历史版本未覆盖。')
  } catch (error) {
    errorMessage(error, '提示词恢复失败。')
  }
}

async function setStatus(status: ConfigStatus): Promise<void> {
  if (!current.value) return
  if (status === 'disabled') {
    try {
      await adminRepository.disablePrompt(current.value.id)
      prompts.value = await adminRepository.prompts()
      persistedIds.value = new Set(prompts.value.map((item) => item.id))
    } catch (error) {
      errorMessage(error, '提示词停用失败。')
    }
    return
  }
  current.value.status = status
  current.value.updated_at = new Date().toISOString()
}
</script>

<template>
  <section class="admin-page">
    <PageHeader
      title="提示词版本"
      description="平台安全边界、操作协议和输出 Schema 分版本管理。生产文本不可直接覆盖，必须经过草稿、固定案例测试和发布。"
      eyebrow="AI 配置"
    >
      <template #actions
        ><el-button @click="openNewVersion"><AppIcon name="add" />创建新版本</el-button></template
      >
    </PageHeader>

    <el-alert
      class="prompt-policy"
      type="info"
      :closable="false"
      show-icon
      title="外部文件、公众号网页和知识片段始终进入“不可信资料区”，不能成为系统指令。测试记录只保存变量哈希、版本和校验值，不在普通日志保存用户正文。"
    />

    <div class="mobile-picker">
      <el-select v-model="selectedId" aria-label="选择提示词版本">
        <el-option
          v-for="option in bundleOptions"
          :key="option.value"
          :label="option.label"
          :value="option.value"
        />
      </el-select>
    </div>

    <section class="prompt-workspace">
      <el-card shadow="never" class="surface-card prompt-sidebar" :body-style="{ padding: '0' }">
        <button
          v-for="prompt in prompts"
          :key="prompt.id"
          class="prompt-item"
          :class="{ 'prompt-item--active': prompt.id === selectedId }"
          @click="selectedId = prompt.id"
        >
          <span
            ><strong>{{ prompt.display_name }}</strong
            ><small>{{ prompt.bundle_code }} · v{{ prompt.version }}</small></span
          >
          <StatusBadge :status="prompt.status" />
        </button>
      </el-card>

      <el-card
        v-if="current"
        shadow="never"
        class="surface-card prompt-main"
        :body-style="{ padding: '0' }"
      >
        <div class="prompt-heading">
          <div class="min-width-zero">
            <div class="prompt-title">
              <h2>{{ current.display_name }}</h2>
              <StatusBadge :status="current.status" />
            </div>
            <div class="text-secondary">
              <code>{{ current.bundle_code }}</code> · v{{ current.version }} ·
              {{ current.checksum }}
            </div>
          </div>
          <el-dropdown trigger="click">
            <el-button text circle aria-label="更多提示词操作"
              ><AppIcon name="more_vert"
            /></el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item @click="setStatus('disabled')"
                  ><AppIcon name="pause" />停用此版本</el-dropdown-item
                >
                <el-dropdown-item :disabled="!previousPublished" @click="confirmRollback = true"
                  ><AppIcon name="history" />恢复上一发布版本</el-dropdown-item
                >
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>

        <el-tabs v-model="activeTab" class="prompt-tabs">
          <el-tab-pane name="editor" label="内容与变量">
            <div class="editor-panel">
              <el-alert
                v-if="current.status !== 'draft'"
                type="warning"
                :closable="false"
                show-icon
                title="已测试、已发布或已停用的版本只读；请先创建新版本再修改。"
              />
              <el-form label-position="top">
                <el-form-item label="版本说明"
                  ><el-input
                    v-model="current.description"
                    :disabled="current.status !== 'draft'"
                    @update:model-value="markDraft"
                /></el-form-item>
                <el-form-item label="系统模板"
                  ><el-input
                    v-model="current.system_template"
                    type="textarea"
                    :autosize="{ minRows: 5, maxRows: 12 }"
                    :disabled="current.status !== 'draft'"
                    @update:model-value="markDraft"
                /></el-form-item>
                <el-form-item label="操作模板"
                  ><el-input
                    v-model="current.operation_template"
                    type="textarea"
                    :autosize="{ minRows: 5, maxRows: 12 }"
                    :disabled="current.status !== 'draft'"
                    @update:model-value="markDraft"
                /></el-form-item>
                <el-form-item label="允许的变量">
                  <el-select
                    v-model="current.variables"
                    multiple
                    filterable
                    allow-create
                    default-first-option
                    :disabled="current.status !== 'draft'"
                    @update:model-value="markDraft"
                  >
                    <el-option
                      v-for="variable in current.variables"
                      :key="variable"
                      :label="variable"
                      :value="variable"
                    />
                  </el-select>
                </el-form-item>
              </el-form>
              <el-alert
                type="info"
                :closable="false"
                :title="`输出 Schema 与变量 Schema 由后端契约校验。当前校验值：${current.checksum}`"
              />
            </div>
          </el-tab-pane>

          <el-tab-pane name="test" label="固定案例测试">
            <div class="test-panel">
              <el-form label-position="top"
                ><el-form-item label="固定案例输入"
                  ><el-input
                    v-model="testInput"
                    type="textarea"
                    :autosize="{ minRows: 5, maxRows: 12 }" /></el-form-item
              ></el-form>
              <div class="test-toolbar">
                <el-button
                  type="primary"
                  :loading="testing"
                  :disabled="!testInput.trim() || !['draft', 'testing'].includes(current.status)"
                  @click="runTest"
                  ><AppIcon name="play_arrow" />运行测试</el-button
                >
                <span class="text-secondary"
                  >测试版本 v{{ current.version }} · {{ current.bundle_code }}</span
                >
              </div>
              <el-card
                v-if="testOutput || current.test_result"
                shadow="never"
                class="test-result"
                :body-style="{ padding: '0' }"
              >
                <div class="result-title">
                  <strong>测试结果</strong
                  ><el-tag :type="current.test_result?.passed ? 'success' : 'danger'">{{
                    current.test_result?.passed ? '通过' : '未通过'
                  }}</el-tag>
                </div>
                <pre class="result-output">{{
                  testOutput || current.test_result?.output_excerpt
                }}</pre>
              </el-card>
            </div>
          </el-tab-pane>

          <el-tab-pane name="history" label="版本记录">
            <el-timeline class="history-panel">
              <el-timeline-item
                v-for="version in bundleHistory"
                :key="version.id"
                :timestamp="`${version.updated_by} · ${version.updated_at}`"
                :type="
                  version.status === 'published'
                    ? 'success'
                    : version.status === 'testing'
                      ? 'warning'
                      : 'primary'
                "
              >
                <strong>v{{ version.version }} · {{ version.status }}</strong>
                <p class="long-text">{{ version.description }}</p>
                <el-button
                  v-if="version.id !== current.id"
                  link
                  type="primary"
                  @click="openVersion(version.id)"
                  >查看此版本</el-button
                >
              </el-timeline-item>
            </el-timeline>
          </el-tab-pane>
        </el-tabs>

        <div class="prompt-actions">
          <el-button :loading="saving" :disabled="current.status !== 'draft'" @click="saveDraft"
            ><AppIcon name="save" />保存草稿</el-button
          >
          <el-button @click="activeTab = 'test'"><AppIcon name="science" />测试</el-button>
          <span />
          <el-button
            type="success"
            :disabled="current.status !== 'testing'"
            @click="confirmPublish = true"
            ><AppIcon name="publish" />发布新版本</el-button
          >
        </div>
      </el-card>
    </section>

    <el-dialog
      v-model="newVersionDialog"
      title="创建提示词新版本"
      width="min(560px, calc(100vw - 24px))"
      align-center
      class="version-dialog"
    >
      <el-form label-position="top" class="version-form">
        <el-form-item label="显示名称"
          ><el-input v-model.trim="newVersionForm.displayName"
        /></el-form-item>
        <el-form-item label="版本说明"
          ><el-input
            v-model="newVersionForm.description"
            type="textarea"
            :autosize="{ minRows: 3, maxRows: 8 }"
        /></el-form-item>
        <el-alert
          type="info"
          :closable="false"
          title="新版本复制当前内容并进入草稿状态，不会覆盖或影响已发布版本。"
        />
      </el-form>
      <template #footer
        ><el-button @click="newVersionDialog = false">取消</el-button
        ><el-button type="primary" @click="createVersion">创建草稿</el-button></template
      >
    </el-dialog>

    <ConfirmActionDialog
      v-model="confirmPublish"
      title="发布提示词版本"
      :description="`发布 ${current?.display_name} v${current?.version} 后，只影响新的 AI 请求；正在运行的任务继续使用原提示词快照。`"
      confirm-label="确认发布"
      tone="primary"
      require-reason
      @confirm="publish"
    />
    <ConfirmActionDialog
      v-model="confirmRollback"
      title="恢复上一发布版本"
      :description="`系统会复制 v${previousPublished?.version ?? '—'} 并生成一个新的发布版本，不会覆盖历史记录。`"
      confirm-label="恢复并发布"
      tone="warning"
      require-reason
      @confirm="rollback"
    />
  </section>
</template>

<style scoped lang="scss">
.prompt-policy {
  margin-bottom: 18px;
}
.mobile-picker {
  display: none;
  margin-bottom: 14px;
}
.mobile-picker :deep(.el-select) {
  width: 100%;
}
.prompt-workspace {
  display: grid;
  grid-template-columns: minmax(240px, 300px) minmax(0, 1fr);
  gap: 18px;
  min-width: 0;
  align-items: start;
}
.prompt-sidebar {
  position: sticky;
  top: 20px;
  min-width: 0;
  max-height: calc(100dvh - 104px);
  overflow-y: auto;
}
.prompt-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  width: 100%;
  min-width: 0;
  padding: 14px 16px;
  border: 0;
  border-bottom: 1px solid var(--app-border-default);
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
}
.prompt-item:hover,
.prompt-item--active {
  background: var(--app-action-primary-soft);
  color: var(--app-action-primary);
}
.prompt-item > span {
  display: flex;
  min-width: 0;
  flex-direction: column;
}
.prompt-item strong,
.prompt-item small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.prompt-item small {
  color: var(--app-text-secondary);
}
.prompt-main {
  min-width: 0;
  overflow: clip;
}
.prompt-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
  padding: 20px;
  border-bottom: 1px solid var(--app-border-default);
}
.min-width-zero {
  min-width: 0;
}
.prompt-title {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  min-width: 0;
}
h2 {
  margin: 0;
  font-size: 22px;
  overflow-wrap: anywhere;
}
.prompt-heading code {
  overflow-wrap: anywhere;
}
.prompt-tabs {
  min-width: 0;
}
.prompt-tabs :deep(.el-tabs__header) {
  margin: 0;
  padding: 0 20px;
}
.prompt-tabs :deep(.el-tab-pane) {
  min-width: 0;
  padding: 20px;
}
.editor-panel,
.test-panel,
.version-form {
  display: grid;
  gap: 16px;
  min-width: 0;
}
.editor-panel :deep(.el-form-item:last-child),
.test-panel :deep(.el-form-item) {
  margin-bottom: 0;
}
.test-toolbar,
.result-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  min-width: 0;
}
.test-result {
  min-width: 0;
  overflow: clip;
}
.result-title {
  padding: 14px 16px;
  border-bottom: 1px solid var(--app-border-default);
}
.result-output {
  max-height: 320px;
  margin: 0;
  padding: 16px;
  overflow: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
}
.history-panel {
  padding-left: 4px;
}
.history-panel p {
  margin: 4px 0;
}
.prompt-actions {
  display: grid;
  grid-template-columns: auto auto minmax(0, 1fr) auto;
  gap: 8px;
  min-width: 0;
  padding: 16px 20px;
  border-top: 1px solid var(--app-border-default);
}

@media (max-width: 899px) {
  .mobile-picker {
    display: block;
  }
  .prompt-workspace {
    grid-template-columns: minmax(0, 1fr);
  }
  .prompt-sidebar {
    display: none;
  }
}
@media (max-width: 599px) {
  .prompt-actions {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .prompt-actions > * {
    width: 100%;
  }
  .prompt-actions > span {
    display: none;
  }
}
</style>

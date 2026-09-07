<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'
import type { ModelAdapter, ModelConfiguration, ModelRoute } from '@/api/contracts'
import { adminRepository } from '@/api/repository'
import AppIcon from '@/components/base/AppIcon.vue'
import StatusBadge from '@/components/base/StatusBadge.vue'
import ConfirmActionDialog from '@/components/composite/ConfirmActionDialog.vue'
import DataTableShell from '@/components/composite/DataTableShell.vue'
import PageHeader from '@/components/composite/PageHeader.vue'
import { cloneData } from '@/utils/clone'
import { customProviderId, findProviderPreset, providerPresets } from '@/config/modelProviders'

type Tab = 'models' | 'layout-agent' | 'credits'
type PublishedStatus = 'available' | 'disabled'

const adapterOptions: Array<{ label: string; value: ModelAdapter }> = [
  { label: 'OpenAI 兼容协议（Chat Completions）', value: 'openai_chat_completions' },
  { label: 'OpenAI 兼容协议（Responses）', value: 'openai_responses' },
  { label: 'LiteLLM（Responses）', value: 'litellm_responses' },
  { label: 'LiteLLM（Chat Completions）', value: 'litellm_chat_completions' },
  { label: 'Manus v2 任务协议', value: 'manus_v2' },
]
const modelTypeOptions: Array<{ label: string; value: ModelConfiguration['model_type'] }> = [
  { label: '对话', value: 'chat' },
  { label: '向量', value: 'embedding' },
  { label: '重排', value: 'rerank' },
  { label: '视觉', value: 'vision' },
]

const tab = ref<Tab>('models')
const models = ref<ModelConfiguration[]>([])
const layoutRoutes = ref<ModelRoute[]>([])
const selectedLayoutRouteId = ref('')
const savingLayoutRoute = ref(false)
const testingLayoutRoute = ref(false)
const publishingLayoutRoute = ref(false)
const disablingLayoutRoute = ref(false)
const creditCost = ref(1)
const creditSaving = ref(false)
const testingId = ref<string | null>(null)
const modelDialog = ref(false)
const testingDraft = ref(false)
const validationToken = ref('')
const testedSignature = ref('')
const draftTestResult = ref<{ passed: boolean; message: string } | null>(null)
const providerId = ref(providerPresets[0]?.id ?? customProviderId)
const apiKey = ref('')
const selectedProvider = computed(() =>
  providerPresets.find((provider) => provider.id === providerId.value),
)
const confirmDialog = reactive({
  open: false,
  title: '',
  description: '',
  tone: 'primary' as 'primary' | 'negative' | 'warning',
  confirmLabel: '确认',
  action: null as null | (() => void),
})
const modelForm = reactive<ModelConfiguration>(emptyModelConfiguration())
const layoutRouteForm = reactive<ModelRoute>(emptyLayoutRoute())
const availableLayoutModels = computed(() =>
  models.value.filter(
    (model) => model.status === 'available' && ['chat', 'vision'].includes(model.model_type),
  ),
)
const layoutModelOptions = computed(() =>
  models.value.filter((model) => ['chat', 'vision'].includes(model.model_type)),
)
const selectedLayoutRoute = computed(
  () => layoutRoutes.value.find((route) => route.id === selectedLayoutRouteId.value) ?? null,
)
const selectedLayoutModel = computed(
  () => models.value.find((model) => model.id === layoutRouteForm.primary_deployment_id) ?? null,
)
const layoutRouteReady = computed(
  () =>
    Boolean(layoutRouteForm.primary_deployment_id) &&
    !layoutRouteForm.fallback_deployment_ids.includes(layoutRouteForm.primary_deployment_id) &&
    layoutRouteForm.timeout_ms >= 10_000 &&
    layoutRouteForm.timeout_ms <= 300_000 &&
    layoutRouteForm.max_attempts >= 1 &&
    layoutRouteForm.max_attempts <= 5,
)

onMounted(async () => {
  const [configuration, routes, credits] = await Promise.allSettled([
    adminRepository.modelConfigurations(),
    adminRepository.modelRoutes('layout_extraction'),
    adminRepository.loadAiRunCreditCost(),
  ])
  if (configuration.status === 'fulfilled') models.value = configuration.value
  else
    ElMessage.error(
      configuration.reason instanceof Error ? configuration.reason.message : '模型配置加载失败。',
    )
  if (routes.status === 'fulfilled') {
    layoutRoutes.value = routes.value
    const preferred =
      routes.value.find((route) => route.status === 'published') ?? routes.value[0] ?? null
    if (preferred) selectLayoutRoute(preferred.id)
  } else
    ElMessage.error(
      routes.reason instanceof Error ? routes.reason.message : '排版智能体配置加载失败。',
    )
  if (credits.status === 'fulfilled') creditCost.value = credits.value
  else
    ElMessage.error(credits.reason instanceof Error ? credits.reason.message : '积分配置加载失败。')
})

function emptyLayoutRoute(): ModelRoute {
  return {
    id: '',
    purpose: 'layout_extraction',
    display_name: '排版学习智能体',
    version: 0,
    primary_deployment_id: '',
    fallback_deployment_ids: [],
    timeout_ms: 120_000,
    max_attempts: 2,
    status: 'draft',
    updated_at: '',
  }
}

function selectLayoutRoute(routeId: string): void {
  const route = layoutRoutes.value.find((item) => item.id === routeId)
  if (!route) return
  selectedLayoutRouteId.value = route.id
  Object.assign(layoutRouteForm, cloneData(route))
}

function newLayoutRouteDraft(): void {
  const source = selectedLayoutRoute.value
  Object.assign(
    layoutRouteForm,
    source
      ? {
          ...cloneData(source),
          id: '',
          version: source.version + 1,
          status: 'draft',
          updated_at: '',
        }
      : emptyLayoutRoute(),
  )
  selectedLayoutRouteId.value = ''
}

function keepFallbacksDistinct(): void {
  layoutRouteForm.fallback_deployment_ids = layoutRouteForm.fallback_deployment_ids.filter(
    (id) => id !== layoutRouteForm.primary_deployment_id,
  )
}

async function reloadLayoutRoutes(preferredId?: string): Promise<void> {
  layoutRoutes.value = await adminRepository.modelRoutes('layout_extraction')
  const preferred =
    layoutRoutes.value.find((route) => route.id === preferredId) ?? layoutRoutes.value[0] ?? null
  if (preferred) selectLayoutRoute(preferred.id)
  else newLayoutRouteDraft()
}

async function saveLayoutRoute(): Promise<void> {
  if (!layoutRouteReady.value) return
  savingLayoutRoute.value = true
  try {
    await adminRepository.saveRouteDraft({
      ...cloneData(layoutRouteForm),
      id: '',
      purpose: 'layout_extraction',
      status: 'draft',
    })
    await reloadLayoutRoutes()
    ElMessage.success('排版智能体路由草稿已保存；测试通过后才能发布。')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '排版智能体路由保存失败。')
  } finally {
    savingLayoutRoute.value = false
  }
}

async function testLayoutRoute(): Promise<void> {
  if (!selectedLayoutRoute.value) return
  testingLayoutRoute.value = true
  try {
    const routeId = selectedLayoutRoute.value.id
    const result = await adminRepository.testRoute(routeId)
    await reloadLayoutRoutes(routeId)
    ElMessage[result.passed ? 'success' : 'warning'](result.message)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '排版智能体固定案例测试失败。')
  } finally {
    testingLayoutRoute.value = false
  }
}

async function publishLayoutRoute(): Promise<void> {
  if (!selectedLayoutRoute.value || selectedLayoutRoute.value.status !== 'testing') return
  publishingLayoutRoute.value = true
  try {
    const routeId = selectedLayoutRoute.value.id
    await adminRepository.publishRoute(routeId)
    await reloadLayoutRoutes(routeId)
    ElMessage.success('排版智能体模型路由已发布，只影响新的模板提取任务。')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '排版智能体路由发布失败。')
  } finally {
    publishingLayoutRoute.value = false
  }
}

async function disableLayoutRoute(): Promise<void> {
  if (!selectedLayoutRoute.value || selectedLayoutRoute.value.status !== 'published') return
  disablingLayoutRoute.value = true
  try {
    const routeId = selectedLayoutRoute.value.id
    await adminRepository.disableRoute(routeId)
    await reloadLayoutRoutes(routeId)
    ElMessage.success('排版智能体路由已停用；运行中的任务继续使用冻结配置。')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '排版智能体路由停用失败。')
  } finally {
    disablingLayoutRoute.value = false
  }
}

function requestLayoutRoutePublish(): void {
  if (!selectedLayoutRoute.value) return
  confirmDialog.title = '发布排版智能体路由'
  confirmDialog.description = `发布“${selectedLayoutRoute.value.display_name}”v${selectedLayoutRoute.value.version} 后，新的链接排版提取将使用该冻结模型链；运行中的任务不切换。`
  confirmDialog.tone = 'primary'
  confirmDialog.confirmLabel = '确认发布'
  confirmDialog.action = () => void publishLayoutRoute()
  confirmDialog.open = true
}

function requestLayoutRouteDisable(): void {
  if (!selectedLayoutRoute.value) return
  confirmDialog.title = '停用排版智能体路由'
  confirmDialog.description = `停用“${selectedLayoutRoute.value.display_name}”v${selectedLayoutRoute.value.version} 后，新模板无法使用这条模型路由；运行中的任务继续使用冻结配置。`
  confirmDialog.tone = 'warning'
  confirmDialog.confirmLabel = '确认停用'
  confirmDialog.action = () => void disableLayoutRoute()
  confirmDialog.open = true
}

function emptyModelConfiguration(): ModelConfiguration {
  return {
    id: '',
    name: '',
    model_id: '',
    model_type: 'chat',
    adapter: 'openai_chat_completions',
    base_url: '',
    secret_configured: false,
    status: 'draft',
    last_tested_at: null,
    last_test_result: null,
    created_at: '',
    updated_at: '',
  }
}

function adapterLabel(adapter: ModelAdapter): string {
  return adapterOptions.find((option) => option.value === adapter)?.label ?? adapter
}

function modelTypeLabel(modelType: ModelConfiguration['model_type']): string {
  return modelTypeOptions.find((option) => option.value === modelType)?.label ?? modelType
}

function formatTimestamp(value: string | null): string {
  if (!value) return '尚未测试'
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat('zh-CN', {
        dateStyle: 'short',
        timeStyle: 'medium',
        hour12: false,
      }).format(date)
}

function openModel(item?: ModelConfiguration): void {
  Object.assign(modelForm, item ? cloneData(item) : emptyModelConfiguration())
  const preset = item ? findProviderPreset(item) : providerPresets[0]
  providerId.value = preset?.id ?? customProviderId
  if (!item) {
    modelForm.id = crypto.randomUUID()
    applyProviderPreset()
  }
  apiKey.value = ''
  validationToken.value = ''
  testedSignature.value = ''
  draftTestResult.value = null
  modelDialog.value = true
}

function isExistingModel(): boolean {
  return models.value.some((item) => item.id === modelForm.id)
}

function modelSignature(): string {
  return JSON.stringify({
    name: modelForm.name,
    base_url: modelForm.base_url,
    model_id: modelForm.model_id,
    model_type: modelForm.model_type,
    adapter: modelForm.adapter,
    api_key: apiKey.value,
  })
}

function hasCurrentPassedTest(): boolean {
  return Boolean(validationToken.value && testedSignature.value === modelSignature())
}

function applyProviderPreset(): void {
  const provider = selectedProvider.value
  if (!provider) return
  const model = provider.models[0]
  modelForm.base_url = provider.baseUrl
  modelForm.adapter = provider.adapter
  if (model) {
    modelForm.model_id = model.id
    modelForm.name = model.label
    modelForm.model_type = model.type
  }
}

function applyModelPreset(): void {
  const model = selectedProvider.value?.models.find((item) => item.id === modelForm.model_id)
  if (!model) return
  modelForm.name = model.label
  modelForm.model_type = model.type
}

function modelFormReady(): boolean {
  return Boolean(
    modelForm.name.trim() &&
    modelForm.base_url.trim() &&
    modelForm.model_id.trim() &&
    modelForm.model_type &&
    modelForm.adapter &&
    (modelForm.secret_configured || apiKey.value.trim()),
  )
}

async function saveModel(): Promise<void> {
  const exists = isExistingModel()
  if (!modelFormReady() || (!exists && !hasCurrentPassedTest())) return
  try {
    await adminRepository.saveModelConfiguration(
      modelForm,
      apiKey.value.trim(),
      exists,
      validationToken.value || undefined,
    )
    models.value = await adminRepository.modelConfigurations()
    modelDialog.value = false
    ElMessage.success(exists ? '模型草稿已保存。' : '模型连接测试通过，配置已保存。')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '模型保存失败。')
  }
}

async function testDraftModel(): Promise<void> {
  if (!modelFormReady() || !apiKey.value.trim()) return
  testingDraft.value = true
  validationToken.value = ''
  testedSignature.value = ''
  draftTestResult.value = null
  try {
    const signature = modelSignature()
    const result = await adminRepository.testModelConfigurationBeforeSave(
      modelForm,
      apiKey.value.trim(),
    )
    draftTestResult.value = result
    if (result.passed && result.validation_token) {
      validationToken.value = result.validation_token
      testedSignature.value = signature
      ElMessage.success(result.message)
    } else {
      ElMessage.warning(result.message)
    }
  } catch (error) {
    draftTestResult.value = {
      passed: false,
      message: error instanceof Error ? error.message : '模型连接测试失败。',
    }
  } finally {
    testingDraft.value = false
  }
}

async function testModel(item: ModelConfiguration): Promise<void> {
  testingId.value = item.id
  try {
    const result = await adminRepository.testModelConfiguration(item.id)
    models.value = await adminRepository.modelConfigurations()
    ElMessage[result.passed ? 'success' : 'warning'](`${item.name}：${result.message}`)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '模型测试失败。')
  } finally {
    testingId.value = null
  }
}

function requestStatusChange(item: ModelConfiguration, status: PublishedStatus): void {
  const isDisable = status === 'disabled'
  confirmDialog.title = isDisable ? '停用模型' : '发布模型'
  confirmDialog.description = isDisable
    ? `停用“${item.name}”后，新任务不会再选择它；已经开始的任务继续使用冻结快照。`
    : `发布“${item.name}”后，只影响新任务。运行中的任务不会切换配置。`
  confirmDialog.tone = isDisable ? 'warning' : 'primary'
  confirmDialog.confirmLabel = '确认'
  confirmDialog.action = () => void setConfigurationStatus(item, status)
  confirmDialog.open = true
}

function requestDelete(item: ModelConfiguration): void {
  confirmDialog.title = '删除模型配置'
  confirmDialog.description = `确定永久删除“${item.name}”吗？模型配置、连接测试记录以及未被其他模型共用的密钥配置都会删除。相关路由将自动移除该模型；主模型有备用时会自动切换，没有备用时会删除该路由。`
  confirmDialog.tone = 'negative'
  confirmDialog.confirmLabel = '删除'
  confirmDialog.action = () => void deleteModel(item)
  confirmDialog.open = true
}

async function deleteModel(item: ModelConfiguration): Promise<void> {
  try {
    await adminRepository.deleteModelConfiguration(item.id)
    models.value = await adminRepository.modelConfigurations()
    ElMessage.success(`“${item.name}”已删除。`)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '模型删除失败。')
  }
}

async function setConfigurationStatus(
  item: ModelConfiguration,
  status: PublishedStatus,
): Promise<void> {
  try {
    await adminRepository.setModelConfigurationStatus(item.id, status)
    models.value = await adminRepository.modelConfigurations()
    ElMessage.success(status === 'disabled' ? '模型已停用。' : '模型已发布。')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '模型状态更新失败。')
  }
}

async function saveCreditCost(): Promise<void> {
  if (!Number.isInteger(creditCost.value) || creditCost.value < 0 || creditCost.value > 10_000) {
    ElMessage.error('单次 AI 运行积分必须是 0 到 10000 的整数。')
    return
  }
  creditSaving.value = true
  try {
    await adminRepository.saveAiRunCreditCost(creditCost.value)
    ElMessage.success('积分配置已发布，仅对新发起的 AI 任务生效。')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '积分配置保存失败。')
  } finally {
    creditSaving.value = false
  }
}
</script>

<template>
  <section class="admin-page">
    <PageHeader
      title="模型、排版智能体与积分"
      description="集中管理模型调用、排版学习智能体路由和单次 AI 运行积分。发布后的调整只作用于新任务。"
      eyebrow="AI 配置"
    >
      <template #actions>
        <el-button v-if="tab === 'models'" type="primary" @click="openModel()">
          <AppIcon name="add" />添加模型
        </el-button>
      </template>
    </PageHeader>

    <el-alert
      class="policy-banner"
      type="info"
      :closable="false"
      show-icon
      title="API Key 会加密保存且永不回显；编辑模型时留空即可保留原密钥。模型和积分配置发布后只影响新任务。"
    />

    <el-tabs v-model="tab" class="config-tabs">
      <el-tab-pane name="models" label="模型配置">
        <DataTableShell
          title="模型配置"
          description="添加时选择厂商和模型，再填写 API Key 即可；只有自定义厂商需要填写协议参数。"
        >
          <el-table :data="models" row-key="id" class="model-table">
            <el-table-column prop="name" label="模型" min-width="190" sortable>
              <template #default="{ row }">
                <strong>{{ row.name }}</strong>
                <div class="cell-subtext cell-wrap">{{ row.model_id }}</div>
              </template>
            </el-table-column>
            <el-table-column label="接口" min-width="300">
              <template #default="{ row }">
                <div class="cell-wrap">{{ row.base_url }}</div>
                <div class="cell-subtext cell-wrap">{{ adapterLabel(row.adapter) }}</div>
              </template>
            </el-table-column>
            <el-table-column label="类型" width="90">
              <template #default="{ row }"
                ><el-tag effect="plain">{{ modelTypeLabel(row.model_type) }}</el-tag></template
              >
            </el-table-column>
            <el-table-column label="状态" min-width="190">
              <template #default="{ row }">
                <StatusBadge :status="row.status" />
                <div class="cell-subtext">{{ formatTimestamp(row.last_tested_at) }}</div>
                <div v-if="row.last_test_result?.passed === false" class="error-excerpt">
                  {{ row.last_test_result.message }}
                </div>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="190" fixed="right" align="right">
              <template #default="{ row }">
                <div class="table-actions">
                  <el-button link :loading="testingId === row.id" @click="testModel(row)"
                    ><AppIcon name="science" />测试</el-button
                  >
                  <el-button link aria-label="编辑模型" @click="openModel(row)"
                    ><AppIcon name="edit"
                  /></el-button>
                  <el-button
                    link
                    type="danger"
                    :aria-label="`删除模型 ${row.name}`"
                    @click="requestDelete(row)"
                    ><AppIcon name="delete"
                  /></el-button>
                  <el-button
                    v-if="row.status === 'testing'"
                    link
                    type="success"
                    aria-label="发布模型"
                    @click="requestStatusChange(row, 'available')"
                    ><AppIcon name="publish"
                  /></el-button>
                  <el-button
                    v-if="row.status === 'available'"
                    link
                    type="danger"
                    aria-label="停用模型"
                    @click="requestStatusChange(row, 'disabled')"
                    ><AppIcon name="pause"
                  /></el-button>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </DataTableShell>
      </el-tab-pane>

      <el-tab-pane name="layout-agent" label="排版智能体">
        <section class="layout-agent-grid">
          <el-card shadow="never" class="surface-card layout-agent-card">
            <template #header>
              <div class="layout-agent-heading">
                <div>
                  <h2>排版学习智能体模型路由</h2>
                  <p>
                    为公众号链接解析选择主模型和有序备用模型。路由固定为
                    <code>layout_extraction</code>。
                  </p>
                </div>
                <StatusBadge :status="selectedLayoutRoute?.status ?? 'draft'" />
              </div>
            </template>

            <div class="layout-agent-form">
              <el-alert
                type="info"
                :closable="false"
                show-icon
                title="排版智能体只输出受控 StyleToken；安全校验、模板版本和微信 HTML 仍由确定性服务负责。视觉模型为后续截图理解预留，当前也兼容具备结构化输出能力的对话模型。"
              />

              <el-alert
                v-if="!availableLayoutModels.length"
                type="warning"
                :closable="false"
                show-icon
                title="还没有已发布的对话或视觉模型。请先在“模型配置”中添加、测试并发布模型。"
              />

              <el-form label-position="top">
                <el-form-item label="配置名称">
                  <el-input
                    v-model.trim="layoutRouteForm.display_name"
                    maxlength="120"
                    show-word-limit
                    placeholder="例如：公众号排版学习智能体"
                  />
                </el-form-item>

                <el-form-item label="主模型">
                  <el-select
                    v-model="layoutRouteForm.primary_deployment_id"
                    filterable
                    placeholder="请选择已经测试并发布的模型"
                    @change="keepFallbacksDistinct"
                  >
                    <el-option
                      v-for="model in layoutModelOptions"
                      :key="model.id"
                      :label="`${model.name} · ${modelTypeLabel(model.model_type)} · ${model.model_id}`"
                      :value="model.id"
                      :disabled="model.status !== 'available'"
                    />
                  </el-select>
                </el-form-item>

                <el-alert
                  v-if="selectedLayoutModel && selectedLayoutModel.model_type !== 'vision'"
                  type="warning"
                  :closable="false"
                  show-icon
                  title="当前主模型是对话模型，可完成结构化版式学习；接入页面截图后建议切换到已验证的视觉模型。"
                />

                <el-form-item label="备用模型（按选择顺序尝试）">
                  <el-select
                    v-model="layoutRouteForm.fallback_deployment_ids"
                    multiple
                    filterable
                    collapse-tags
                    collapse-tags-tooltip
                    placeholder="可选；主模型失败后依次切换"
                  >
                    <el-option
                      v-for="model in layoutModelOptions"
                      :key="model.id"
                      :label="`${model.name} · ${modelTypeLabel(model.model_type)}`"
                      :value="model.id"
                      :disabled="
                        model.status !== 'available' ||
                        model.id === layoutRouteForm.primary_deployment_id
                      "
                    />
                  </el-select>
                </el-form-item>

                <div class="layout-agent-limits">
                  <el-form-item label="单次超时（毫秒）">
                    <el-input-number
                      v-model="layoutRouteForm.timeout_ms"
                      :min="10000"
                      :max="300000"
                      :step="10000"
                      controls-position="right"
                    />
                  </el-form-item>
                  <el-form-item label="最多模型尝试次数">
                    <el-input-number
                      v-model="layoutRouteForm.max_attempts"
                      :min="1"
                      :max="5"
                      :step="1"
                      controls-position="right"
                    />
                  </el-form-item>
                </div>
              </el-form>

              <div class="layout-agent-actions">
                <el-button @click="newLayoutRouteDraft">
                  <AppIcon name="add" />新建路由草稿
                </el-button>
                <el-button
                  type="primary"
                  :loading="savingLayoutRoute"
                  :disabled="!layoutRouteReady"
                  @click="saveLayoutRoute"
                >
                  <AppIcon name="save" />保存新草稿版本
                </el-button>
                <el-button
                  :loading="testingLayoutRoute"
                  :disabled="!selectedLayoutRoute || selectedLayoutRoute.status === 'published'"
                  @click="testLayoutRoute"
                >
                  <AppIcon name="science" />测试已保存版本
                </el-button>
                <el-button
                  v-if="selectedLayoutRoute?.status === 'testing'"
                  type="success"
                  :loading="publishingLayoutRoute"
                  @click="requestLayoutRoutePublish"
                >
                  <AppIcon name="publish" />发布路由
                </el-button>
                <el-button
                  v-if="selectedLayoutRoute?.status === 'published'"
                  type="warning"
                  :loading="disablingLayoutRoute"
                  @click="requestLayoutRouteDisable"
                >
                  <AppIcon name="pause" />停用路由
                </el-button>
              </div>
            </div>
          </el-card>

          <el-card shadow="never" class="surface-card layout-history-card">
            <template #header>
              <div class="layout-history-heading">
                <div>
                  <h2>路由版本</h2>
                  <p>测试和发布只作用于选中的不可变版本。</p>
                </div>
                <el-tag effect="plain">{{ layoutRoutes.length }} 个版本</el-tag>
              </div>
            </template>
            <div v-if="layoutRoutes.length" class="layout-route-list">
              <button
                v-for="route in layoutRoutes"
                :key="route.id"
                type="button"
                class="layout-route-item"
                :class="{ 'layout-route-item--active': route.id === selectedLayoutRouteId }"
                @click="selectLayoutRoute(route.id)"
              >
                <span>
                  <strong>{{ route.display_name }} · v{{ route.version }}</strong>
                  <small>{{ formatTimestamp(route.updated_at) }}</small>
                </span>
                <StatusBadge :status="route.status" />
              </button>
            </div>
            <el-empty v-else description="尚未创建排版智能体路由" />
          </el-card>
        </section>
      </el-tab-pane>

      <el-tab-pane name="credits" label="积分配置">
        <el-card shadow="never" class="surface-card credits-card">
          <template #header>
            <div class="credits-heading">
              <div>
                <h2>AI 运行积分</h2>
                <p>统一设置每次新 AI 任务预占和结算的积分数量。</p>
              </div>
              <el-tag effect="plain">ai_run_credit_cost</el-tag>
            </div>
          </template>
          <div class="credits-form">
            <el-alert
              type="info"
              :closable="false"
              show-icon
              title="任务开始时预占积分；任务失败或取消会自动返还。发布后的积分值只对新发起的任务生效，不修改运行中任务。设置为 0 表示免费。"
            />
            <el-form label-position="top">
              <el-form-item label="每次 AI 运行消耗积分">
                <div class="credit-input-row">
                  <el-input-number
                    v-model="creditCost"
                    :min="0"
                    :max="10000"
                    :step="1"
                    controls-position="right"
                  />
                  <span>积分</span>
                </div>
              </el-form-item>
            </el-form>
            <div class="credit-actions">
              <el-button
                type="primary"
                :loading="creditSaving"
                :disabled="!Number.isInteger(creditCost) || creditCost < 0 || creditCost > 10000"
                @click="saveCreditCost"
              >
                <AppIcon name="publish" />保存并发布积分配置
              </el-button>
            </div>
          </div>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <el-dialog
      v-model="modelDialog"
      :title="models.some((item) => item.id === modelForm.id) ? '编辑模型' : '添加模型'"
      width="min(680px, calc(100vw - 24px))"
      align-center
      class="model-dialog edit-dialog"
      destroy-on-close
    >
      <el-form label-position="top" class="dialog-form">
        <el-form-item label="模型厂商">
          <el-select v-model="providerId" @change="applyProviderPreset">
            <el-option
              v-for="provider in providerPresets"
              :key="provider.id"
              :label="provider.label"
              :value="provider.id"
            />
            <el-option label="自定义 OpenAI 兼容服务" :value="customProviderId" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="selectedProvider" label="模型">
          <el-select v-model="modelForm.model_id" @change="applyModelPreset">
            <el-option
              v-for="model in selectedProvider.models"
              :key="model.id"
              :label="model.label"
              :value="model.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item
          class="api-key-field"
          :label="modelForm.secret_configured ? 'API Key（留空保持原密钥）' : 'API Key'"
        >
          <el-input
            v-model.trim="apiKey"
            type="password"
            show-password
            autocomplete="new-password"
            :placeholder="modelForm.secret_configured ? '已安全保存，不会回显' : '粘贴厂商 API Key'"
          />
        </el-form-item>
        <template v-if="providerId === customProviderId">
          <el-divider class="advanced-divider" content-position="left">自定义服务参数</el-divider>
          <el-form-item label="显示名称"><el-input v-model.trim="modelForm.name" /></el-form-item>
          <el-form-item label="调用 model 值"
            ><el-input v-model.trim="modelForm.model_id"
          /></el-form-item>
          <el-form-item label="API 地址"
            ><el-input v-model.trim="modelForm.base_url" type="url"
          /></el-form-item>
          <el-form-item label="模型类型">
            <el-select v-model="modelForm.model_type">
              <el-option
                v-for="option in modelTypeOptions"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="接口协议">
            <el-select v-model="modelForm.adapter">
              <el-option
                v-for="option in adapterOptions.filter((item) => item.value !== 'manus_v2')"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
          </el-form-item>
        </template>
        <el-alert
          v-else-if="providerId === 'manus'"
          class="provider-tip"
          type="info"
          :closable="false"
          show-icon
          title="使用 Manus v2 异步任务接口；连接测试会创建一个最小任务，可能产生少量厂商费用。"
        />
        <el-alert
          v-if="draftTestResult"
          class="draft-test-result"
          :type="draftTestResult.passed && hasCurrentPassedTest() ? 'success' : 'error'"
          :closable="false"
          show-icon
          :title="
            draftTestResult.passed && !hasCurrentPassedTest()
              ? '配置已修改，请重新测试连接。'
              : draftTestResult.message
          "
        />
      </el-form>
      <template #footer>
        <div class="dialog-actions">
          <el-button @click="modelDialog = false">取消</el-button>
          <el-button
            v-if="!isExistingModel()"
            :loading="testingDraft"
            :disabled="!modelFormReady() || !apiKey.trim()"
            @click="testDraftModel"
          >
            <AppIcon name="science" />测试连接
          </el-button>
          <el-button
            type="primary"
            :disabled="!modelFormReady() || (!isExistingModel() && !hasCurrentPassedTest())"
            @click="saveModel"
            >保存草稿</el-button
          >
        </div>
      </template>
    </el-dialog>

    <ConfirmActionDialog
      v-model="confirmDialog.open"
      :title="confirmDialog.title"
      :description="confirmDialog.description"
      :tone="confirmDialog.tone"
      :confirm-label="confirmDialog.confirmLabel"
      @confirm="confirmDialog.action?.()"
    />
  </section>
</template>

<style scoped lang="scss">
.policy-banner {
  margin-bottom: var(--space-5);
}
.config-tabs {
  min-width: 0;
}
.model-table {
  width: 100%;
}
.cell-wrap,
.error-excerpt {
  max-width: 360px;
  overflow-wrap: anywhere;
  word-break: break-word;
}
.cell-subtext {
  margin-top: 3px;
  color: var(--app-text-secondary);
  font-size: 12px;
}
.error-excerpt {
  margin-top: var(--space-1);
  color: var(--app-action-danger);
  font-size: 12px;
  line-height: 1.45;
}
.table-actions,
.dialog-actions {
  display: flex;
  min-width: 0;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--space-1);
}
.table-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}
.credits-card {
  min-width: 0;
}
.layout-agent-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(280px, 0.75fr);
  align-items: start;
  gap: var(--space-5);
  min-width: 0;
}
.layout-agent-card,
.layout-history-card,
.layout-agent-heading > *,
.layout-history-heading > *,
.layout-agent-form,
.layout-route-item > span {
  min-width: 0;
}
.layout-agent-heading,
.layout-history-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  min-width: 0;
}
.layout-agent-heading h2,
.layout-history-heading h2 {
  margin: 0;
  font-size: 18px;
  overflow-wrap: anywhere;
}
.layout-agent-heading p,
.layout-history-heading p {
  margin: var(--space-1) 0 0;
  color: var(--app-text-secondary);
  line-height: 1.55;
  overflow-wrap: anywhere;
}
.layout-agent-heading code {
  overflow-wrap: anywhere;
}
.layout-agent-form {
  display: grid;
  gap: var(--space-5);
}
.layout-agent-form :deep(.el-form-item),
.layout-agent-form :deep(.el-select),
.layout-agent-form :deep(.el-input-number) {
  width: 100%;
  min-width: 0;
  max-width: 100%;
}
.layout-agent-limits {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-4);
  min-width: 0;
}
.layout-agent-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--space-2);
  min-width: 0;
}
.layout-agent-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}
.layout-route-list {
  display: grid;
  min-width: 0;
}
.layout-route-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--space-3);
  width: 100%;
  min-width: 0;
  padding: var(--space-4);
  color: var(--app-text-primary);
  text-align: left;
  background: transparent;
  border: 0;
  border-bottom: 1px solid var(--app-border-default);
  cursor: pointer;
}
.layout-route-item:last-child {
  border-bottom: 0;
}
.layout-route-item:hover,
.layout-route-item--active {
  color: var(--app-action-primary);
  background: var(--app-action-primary-soft);
}
.layout-route-item > span {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}
.layout-route-item strong,
.layout-route-item small {
  overflow-wrap: anywhere;
}
.layout-route-item small {
  color: var(--app-text-secondary);
}
.credits-heading {
  display: flex;
  min-width: 0;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
}
.credits-heading > * {
  min-width: 0;
}
.credits-heading h2 {
  margin: 0;
  font-size: 18px;
}
.credits-heading p {
  margin: var(--space-1) 0 0;
  color: var(--app-text-secondary);
  overflow-wrap: anywhere;
}
.credits-form {
  display: grid;
  min-width: 0;
  max-width: 680px;
  gap: var(--space-5);
}
.credit-input-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-width: 0;
}
.credit-input-row :deep(.el-input-number) {
  width: min(280px, 100%);
  max-width: 100%;
}
.credit-actions {
  display: flex;
  min-width: 0;
  justify-content: flex-end;
}
.dialog-form {
  display: grid;
  min-width: 0;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 var(--space-4);
}
.dialog-form :deep(.el-form-item),
.dialog-form :deep(.el-select) {
  min-width: 0;
  width: 100%;
}
.api-key-field,
.advanced-divider,
.provider-tip {
  grid-column: 1 / -1;
}
.draft-test-result {
  grid-column: 1 / -1;
  min-width: 0;
}
.advanced-divider {
  margin: var(--space-2) 0 var(--space-4);
}
.provider-tip {
  min-width: 0;
}
:global(.model-dialog .el-dialog__body) {
  max-height: calc(100dvh - 190px);
  overflow-y: auto;
}

@media (max-width: 1199px) {
  .layout-agent-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 599px) {
  .layout-agent-grid,
  .layout-agent-limits {
    grid-template-columns: minmax(0, 1fr);
  }
  .layout-agent-heading,
  .layout-history-heading {
    align-items: stretch;
    flex-direction: column;
  }
  .layout-agent-actions {
    align-items: stretch;
    flex-direction: column;
  }
  .layout-agent-actions .el-button {
    width: 100%;
  }
  .credits-heading {
    align-items: stretch;
    flex-direction: column;
  }
  .credit-input-row {
    align-items: stretch;
    flex-direction: column;
  }
  .credit-input-row :deep(.el-input-number),
  .credit-actions .el-button {
    width: 100%;
  }
  .dialog-form {
    grid-template-columns: minmax(0, 1fr);
  }
  :global(.model-dialog .el-dialog__body) {
    max-height: calc(100dvh - 132px);
  }
}
</style>

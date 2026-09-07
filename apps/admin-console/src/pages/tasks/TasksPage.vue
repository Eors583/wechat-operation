<script setup lang="ts">
import type { AdminTableColumn } from '@/components/base/AdminElementAdapters'
import { useAdminNotifier } from '@/composables/useAdminNotifier'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import type { JobRecord, TaskStatus } from '@/api/contracts'
import { adminRepository } from '@/api/repository'
import StatusBadge from '@/components/base/StatusBadge.vue'
import ConfirmActionDialog from '@/components/composite/ConfirmActionDialog.vue'
import DataTableShell from '@/components/composite/DataTableShell.vue'
import PageHeader from '@/components/composite/PageHeader.vue'

const notifier = useAdminNotifier()
const route = useRoute()
const jobs = ref<JobRecord[]>([])
const query = ref('')
const typeFilter = ref<JobRecord['type'] | 'all'>('all')
const statusFilter = ref<TaskStatus | 'all'>('all')
const selectedId = ref('')
const detailOpen = ref(false)
const busyId = ref<string | null>(null)
const confirm = reactive({
  open: false,
  title: '',
  description: '',
  tone: 'primary' as 'primary' | 'negative' | 'warning',
  action: null as null | ((reason: string) => void),
})

const typeLabels: Record<JobRecord['type'], string> = {
  ai: 'AI 生成',
  file_parse: '文件解析',
  embedding: 'Embedding',
  knowledge_sync: '知识同步',
  wechat_draft: '公众号草稿',
  wechat_publish: '正式发布',
  preference: '偏好总结',
}
const typeLabel = (value: unknown): string =>
  typeof value === 'string' && value in typeLabels
    ? typeLabels[value as JobRecord['type']]
    : String(value)
const copyText = (value: string): Promise<void> => window.navigator.clipboard.writeText(value)

const selected = computed(() => jobs.value.find((item) => item.id === selectedId.value) ?? null)
const filteredJobs = computed(() =>
  jobs.value.filter((job) => {
    const search = query.value.trim().toLowerCase()
    return (
      (typeFilter.value === 'all' || job.type === typeFilter.value) &&
      (statusFilter.value === 'all' || job.status === statusFilter.value) &&
      (!search ||
        `${job.id}${job.resource_label}${job.owner_display_name}${job.error_code ?? ''}${job.error_message ?? ''}`
          .toLowerCase()
          .includes(search))
    )
  }),
)
const counts = computed(() => ({
  failed: jobs.value.filter((item) => item.status === 'failed').length,
  unknown: jobs.value.filter((item) => item.status === 'unknown').length,
  running: jobs.value.filter((item) => ['queued', 'running'].includes(item.status)).length,
  completed: jobs.value.filter((item) => item.status === 'completed').length,
}))

const columns: AdminTableColumn<JobRecord>[] = [
  { name: 'task', label: '任务', field: 'resource_label', align: 'left' },
  { name: 'type', label: '类型', field: 'type', align: 'left' },
  { name: 'stage', label: '当前阶段', field: 'stage', align: 'left' },
  { name: 'status', label: '状态', field: 'status', align: 'left', sortable: true },
  { name: 'target', label: '模型 / 公众号', field: 'model_or_account', align: 'left' },
  { name: 'duration', label: '耗时 / 尝试', field: 'duration_ms', align: 'right', sortable: true },
  { name: 'updated', label: '更新时间', field: 'updated_at', align: 'left', sortable: true },
  { name: 'actions', label: '操作', field: 'id', align: 'right' },
]

onMounted(async () => {
  try {
    jobs.value = await adminRepository.jobs()
  } catch (error) {
    notifier.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '后台任务加载失败。',
    })
  }
})

watch(
  () => route.query.job,
  (jobId) => {
    if (typeof jobId === 'string') {
      const job = jobs.value.find((item) => item.id === jobId)
      if (job) openDetail(job)
    }
  },
  { immediate: true },
)

function openDetail(job: JobRecord): void {
  selectedId.value = job.id
  detailOpen.value = true
}

function requestRetry(job: JobRecord): void {
  if (job.status !== 'failed') {
    notifier.notify({
      type: 'warning',
      message:
        job.status === 'unknown'
          ? '结果不确定，必须先对账，不能直接重试。'
          : '只有明确失败的任务可以重试。',
    })
    return
  }
  confirm.title = '按冻结快照重试任务'
  confirm.description = `将使用原输入、上下文、配置版本和资源快照 ${job.frozen_snapshot_id} 重放任务。管理员不能修改用户要求；原失败记录会保留。`
  confirm.tone = 'warning'
  confirm.action = () => void retry(job)
  confirm.open = true
}

async function retry(job: JobRecord): Promise<void> {
  busyId.value = job.id
  try {
    await adminRepository.retryJob(job.id, '管理员从任务控制台按冻结快照重试')
    jobs.value = await adminRepository.jobs()
    notifier.notify({
      type: 'positive',
      message: '已按冻结快照加入重试队列，原失败记录保留且不会创建重复文章。',
    })
  } catch (error) {
    notifier.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '任务重试失败。',
    })
  } finally {
    busyId.value = null
  }
}

function requestReconcile(job: JobRecord): void {
  if (job.status !== 'unknown') return
  confirm.title = '核对外部最终结果'
  confirm.description = `任务请求已发出但响应丢失。系统会用外部业务 ID ${job.external_id ?? '（未记录）'} 查询微信最终结果，在确认前不会再次创建草稿或提交发布。`
  confirm.tone = 'primary'
  confirm.action = () => void reconcile(job)
  confirm.open = true
}

async function reconcile(job: JobRecord): Promise<void> {
  busyId.value = job.id
  try {
    await adminRepository.reconcileJob(job.id, '管理员从任务控制台发起外部结果对账')
    jobs.value = await adminRepository.jobs()
    notifier.notify({
      type: 'positive',
      message: '对账请求已提交；系统会关联原结果并禁止重复发送。',
    })
  } catch (error) {
    notifier.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '任务对账失败。',
    })
  } finally {
    busyId.value = null
  }
}

function requestCancel(job: JobRecord): void {
  if (!['queued', 'running'].includes(job.status)) return
  confirm.title = '取消未完成任务'
  confirm.description =
    '取消只在未执行或安全检查点生效；已经保存的消息、文章版本和阶段结果会保留，未使用额度将释放。'
  confirm.tone = 'negative'
  confirm.action = () => void cancel(job)
  confirm.open = true
}

async function cancel(job: JobRecord): Promise<void> {
  busyId.value = job.id
  try {
    await adminRepository.cancelJob(job.id, '管理员从任务控制台取消未执行任务')
    jobs.value = await adminRepository.jobs()
    notifier.notify({ type: 'positive', message: '取消请求已记录，任务将在安全检查点停止。' })
  } catch (error) {
    notifier.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '任务取消失败。',
    })
  } finally {
    busyId.value = null
  }
}

function clearFilters(): void {
  query.value = ''
  typeFilter.value = 'all'
  statusFilter.value = 'all'
}
</script>

<template>
  <section class="admin-page">
    <PageHeader
      title="任务与对账"
      description="处理 AI、解析、Embedding、知识同步、偏好、草稿与发布任务。只重试冻结的明确失败任务；结果不确定时必须先核对。"
      eyebrow="平台运营"
    />

    <section class="summary-grid">
      <el-card flat bordered class="surface-card summary-card failed"
        ><admin-card-section
          ><app-icon name="error" />
          <div>
            <span>明确失败</span><strong>{{ counts.failed }}</strong>
          </div></admin-card-section
        ></el-card
      >
      <el-card flat bordered class="surface-card summary-card unknown"
        ><admin-card-section
          ><app-icon name="help" />
          <div>
            <span>待核对</span><strong>{{ counts.unknown }}</strong>
          </div></admin-card-section
        ></el-card
      >
      <el-card flat bordered class="surface-card summary-card running"
        ><admin-card-section
          ><app-icon name="sync" />
          <div>
            <span>执行中</span><strong>{{ counts.running }}</strong>
          </div></admin-card-section
        ></el-card
      >
      <el-card flat bordered class="surface-card summary-card completed"
        ><admin-card-section
          ><app-icon name="check_circle" />
          <div>
            <span>样本已完成</span><strong>{{ counts.completed }}</strong>
          </div></admin-card-section
        ></el-card
      >
    </section>

    <admin-banner rounded class="safety-banner"
      ><template #avatar><app-icon name="verified_user" color="primary" /></template
      ><strong>防重复规则：</strong>微信请求已发出但响应丢失时标记
      <code>UNKNOWN</code>。管理员必须先按外部 ID
      对账，禁止直接重放，避免重复草稿或重复发布。</admin-banner
    >

    <el-card flat bordered class="surface-card filter-card"
      ><admin-card-section class="filters"
        ><admin-input
          v-model="query"
          outlined
          dense
          clearable
          debounce="180"
          label="搜索任务、用户、错误代码或原因"
          ><template #prepend><app-icon name="search" /></template></admin-input
        ><admin-select
          v-model="typeFilter"
          outlined
          dense
          emit-value
          map-options
          :options="[
            { label: '全部类型', value: 'all' },
            ...Object.entries(typeLabels).map(([value, label]) => ({ value, label })),
          ]"
          label="任务类型" /><admin-select
          v-model="statusFilter"
          outlined
          dense
          emit-value
          map-options
          :options="[
            { label: '全部状态', value: 'all' },
            { label: '排队中', value: 'queued' },
            { label: '执行中', value: 'running' },
            { label: '明确失败', value: 'failed' },
            { label: '结果待核对', value: 'unknown' },
            { label: '已完成', value: 'completed' },
            { label: '已取消', value: 'cancelled' },
          ]"
          label="任务状态" /><admin-button
          flat
          color="primary"
          icon="filter_alt_off"
          label="清除"
          @click="clearFilters" /></admin-card-section
    ></el-card>

    <DataTableShell
      title="后台任务"
      :description="`显示 ${filteredJobs.length} 个任务；错误全文在详情中完整换行显示`"
    >
      <admin-table
        flat
        :rows="filteredJobs"
        :columns="columns"
        row-key="id"
        :pagination="{ rowsPerPage: 15 }"
      >
        <template #body-cell-task="props"
          ><admin-cell :props="props"
            ><div class="task-cell">
              <strong>{{ props.row.resource_label }}</strong
              ><span>{{ props.row.owner_display_name }}</span
              ><code>{{ props.row.id }}</code>
            </div></admin-cell
          ></template
        >
        <template #body-cell-type="props"
          ><admin-cell :props="props"
            ><admin-badge outline color="primary">{{
              typeLabel(props.row.type)
            }}</admin-badge></admin-cell
          ></template
        >
        <template #body-cell-stage="props"
          ><admin-cell :props="props"
            ><code class="stage-code">{{ props.row.stage }}</code>
            <div v-if="props.row.error_code" class="caption-text tone-danger">
              {{ props.row.error_code }}
            </div></admin-cell
          ></template
        >
        <template #body-cell-status="props"
          ><admin-cell :props="props"><StatusBadge :status="props.row.status" /></admin-cell
        ></template>
        <template #body-cell-target="props"
          ><admin-cell :props="props"
            ><div class="cell-wrap">{{ props.row.model_or_account }}</div></admin-cell
          ></template
        >
        <template #body-cell-duration="props"
          ><admin-cell :props="props"
            >{{ (props.row.duration_ms / 1000).toFixed(1) }} 秒
            <div class="caption-text text-secondary">
              {{ props.row.attempt_count }} 次尝试
            </div></admin-cell
          ></template
        >
        <template #body-cell-updated="props"
          ><admin-cell :props="props">{{ props.row.updated_at }}</admin-cell></template
        >
        <template #body-cell-actions="props"
          ><admin-cell :props="props"
            ><div class="table-actions">
              <admin-button
                v-if="props.row.status === 'failed'"
                flat
                dense
                no-caps
                color="warning"
                icon="replay"
                label="冻结重试"
                :loading="busyId === props.row.id"
                @click.stop="requestRetry(props.row)"
              /><admin-button
                v-if="props.row.status === 'unknown'"
                unelevated
                dense
                no-caps
                color="primary"
                icon="fact_check"
                label="先对账"
                :loading="busyId === props.row.id"
                @click.stop="requestReconcile(props.row)"
              /><admin-button
                v-if="['queued', 'running'].includes(props.row.status)"
                flat
                dense
                no-caps
                color="negative"
                icon="stop"
                label="取消"
                @click.stop="requestCancel(props.row)"
              /><admin-button
                flat
                dense
                round
                icon="chevron_right"
                aria-label="查看任务详情"
                @click.stop="openDetail(props.row)"
              /></div></admin-cell
        ></template>
      </admin-table>
    </DataTableShell>

    <admin-dialog v-model="detailOpen" width="min(800px, calc(100vw - 48px))" persistent>
      <el-card v-if="selected" class="task-dialog">
        <admin-toolbar
          ><admin-avatar
            :color="
              selected.status === 'unknown'
                ? 'warning'
                : selected.status === 'failed'
                  ? 'negative'
                  : 'primary'
            "
            text-color="white"
            :icon="
              selected.status === 'unknown'
                ? 'help'
                : selected.status === 'failed'
                  ? 'error'
                  : 'sync'
            " />
          <div class="drawer-title">
            <admin-toolbar-title>{{ typeLabels[selected.type] }}</admin-toolbar-title
            ><code>{{ selected.id }}</code>
          </div>
          <admin-space /><admin-button
            flat
            round
            dense
            icon="close"
            aria-label="关闭"
            @click="detailOpen = false" /></admin-toolbar
        ><el-divider />
        <div class="drawer-scroll">
          <div class="drawer-content">
            <admin-banner v-if="selected.status === 'unknown'" rounded class="unknown-banner"
              ><template #avatar><app-icon name="warning" color="warning" /></template
              ><strong>禁止直接重试</strong>
              <div>
                外部结果不确定，必须先查询最终状态。外部业务 ID：<code>{{
                  selected.external_id ?? '未记录'
                }}</code>
              </div></admin-banner
            >
            <div class="detail-heading">
              <div>
                <h2>{{ selected.resource_label }}</h2>
                <span>{{ selected.owner_display_name }}</span>
              </div>
              <StatusBadge :status="selected.status" />
            </div>
            <el-card flat bordered
              ><admin-list separator
                ><admin-item
                  ><admin-item-section
                    ><admin-item-label caption>当前阶段</admin-item-label
                    ><admin-item-label
                      ><code>{{ selected.stage }}</code></admin-item-label
                    ></admin-item-section
                  ></admin-item
                ><admin-item
                  ><admin-item-section
                    ><admin-item-label caption>模型 / 公众号</admin-item-label
                    ><admin-item-label class="long-text">{{
                      selected.model_or_account
                    }}</admin-item-label></admin-item-section
                  ></admin-item
                ><admin-item
                  ><admin-item-section
                    ><admin-item-label caption>冻结快照</admin-item-label
                    ><admin-item-label
                      ><code>{{ selected.frozen_snapshot_id }}</code></admin-item-label
                    ></admin-item-section
                  ></admin-item
                ><admin-item
                  ><admin-item-section
                    ><admin-item-label caption>尝试与耗时</admin-item-label
                    ><admin-item-label
                      >{{ selected.attempt_count }} 次 ·
                      {{ (selected.duration_ms / 1000).toFixed(2) }} 秒</admin-item-label
                    ></admin-item-section
                  ></admin-item
                ><admin-item
                  ><admin-item-section
                    ><admin-item-label caption>创建 / 更新</admin-item-label
                    ><admin-item-label
                      >{{ selected.created_at }} / {{ selected.updated_at }}</admin-item-label
                    ></admin-item-section
                  ></admin-item
                ></admin-list
              ></el-card
            >
            <el-card v-if="selected.error_message" flat bordered class="error-card"
              ><admin-card-section class="error-title"
                ><div>
                  <app-icon name="error" color="negative" /><strong>{{
                    selected.error_code
                  }}</strong>
                </div>
                <admin-button
                  flat
                  round
                  dense
                  icon="content_copy"
                  aria-label="复制错误全文"
                  @click="copyText(selected.error_message ?? '')" /></admin-card-section
              ><el-divider /><admin-card-section class="error-message">{{
                selected.error_message
              }}</admin-card-section></el-card
            >
            <div>
              <h3>阶段记录</h3>
              <admin-timeline color="primary" layout="dense"
                ><admin-timeline-entry
                  title="任务已接收"
                  :subtitle="selected.created_at"
                  icon="check" /><admin-timeline-entry
                  :title="selected.stage"
                  :subtitle="selected.updated_at"
                  :color="
                    selected.status === 'failed'
                      ? 'negative'
                      : selected.status === 'unknown'
                        ? 'warning'
                        : 'primary'
                  "
                  :icon="
                    selected.status === 'failed'
                      ? 'error'
                      : selected.status === 'unknown'
                        ? 'help'
                        : 'sync'
                  " /><admin-timeline-entry
                  v-if="selected.status === 'completed'"
                  title="最终结果已确认"
                  :subtitle="selected.updated_at"
                  color="positive"
                  icon="check_circle"
              /></admin-timeline>
            </div>
            <admin-banner rounded class="privacy-banner"
              ><template #avatar><app-icon name="visibility_off" color="primary" /></template
              >任务详情只展示诊断元数据、错误和冻结快照
              ID，不默认加载用户正文、对话全文或原始文件内容。</admin-banner
            >
          </div>
        </div>
        <div
          v-if="['failed', 'unknown', 'queued', 'running'].includes(selected.status)"
          class="drawer-actions"
        >
          <admin-button
            v-if="selected.status === 'failed'"
            unelevated
            color="warning"
            icon="replay"
            label="按冻结快照重试"
            :loading="busyId === selected.id"
            @click="requestRetry(selected)"
          /><admin-button
            v-if="selected.status === 'unknown'"
            unelevated
            color="primary"
            icon="fact_check"
            label="核对最终结果"
            :loading="busyId === selected.id"
            @click="requestReconcile(selected)"
          /><admin-button
            v-if="['queued', 'running'].includes(selected.status)"
            outline
            color="negative"
            icon="stop"
            label="在安全检查点取消"
            @click="requestCancel(selected)"
          />
        </div>
      </el-card>
    </admin-dialog>

    <ConfirmActionDialog
      v-model="confirm.open"
      :title="confirm.title"
      :description="confirm.description"
      confirm-label="确认并写入审计"
      :tone="confirm.tone"
      require-reason
      @confirm="(reason) => confirm.action?.(reason)"
    />
  </section>
</template>

<style scoped lang="scss">
.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
  min-width: 0;
  margin-bottom: 18px;
}
.summary-card {
  min-width: 0;
}
.summary-card .admin-card-section {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}
.summary-card .el-icon {
  font-size: 30px;
}
.summary-card.failed .el-icon {
  color: var(--app-action-danger);
}
.summary-card.unknown .el-icon {
  color: var(--app-action-warning);
}
.summary-card.running .el-icon {
  color: var(--app-action-primary);
}
.summary-card.completed .el-icon {
  color: var(--app-action-success);
}
.summary-card div {
  min-width: 0;
}
.summary-card span {
  display: block;
  color: var(--app-text-secondary);
  overflow-wrap: anywhere;
}
.summary-card strong {
  display: block;
  font-size: 25px;
}
.safety-banner {
  margin-bottom: 18px;
  border: 1px solid color-mix(in srgb, var(--app-action-primary) 25%, var(--app-border-default));
  background: var(--app-action-primary-soft);
  overflow-wrap: anywhere;
}
.filter-card {
  margin-bottom: 18px;
}
.filters {
  display: grid;
  grid-template-columns: minmax(260px, 1fr) minmax(170px, 0.45fr) minmax(170px, 0.45fr) auto;
  gap: 10px;
  min-width: 0;
}
.task-cell {
  min-width: 0;
  max-width: 320px;
}
.task-cell strong,
.task-cell span,
.task-cell code {
  display: block;
  overflow-wrap: anywhere;
}
.task-cell span,
.task-cell code {
  color: var(--app-text-secondary);
  font-size: 11px;
}
.stage-code,
.cell-wrap {
  max-width: 260px;
  overflow-wrap: anywhere;
}
.table-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 4px;
}
.task-dialog {
  width: 100%;
  max-width: 100%;
  height: min(720px, calc(100dvh - 96px));
  min-width: 0;
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr) auto;
}
.drawer-title {
  min-width: 0;
}
.drawer-title code {
  display: block;
  padding-left: 12px;
  color: var(--app-text-secondary);
  font-size: 11px;
  overflow-wrap: anywhere;
}
.drawer-scroll {
  min-width: 0;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
}
.drawer-content {
  display: grid;
  gap: 16px;
  min-width: 0;
  padding: 18px;
}
.unknown-banner {
  border: 1px solid color-mix(in srgb, var(--app-action-warning) 35%, var(--app-border-default));
  background: color-mix(in srgb, var(--app-action-warning) 9%, var(--app-bg-surface));
  overflow-wrap: anywhere;
}
.detail-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
}
.detail-heading > div {
  min-width: 0;
}
.detail-heading h2 {
  margin: 0;
  font-size: 20px;
  overflow-wrap: anywhere;
}
.detail-heading span {
  color: var(--app-text-secondary);
}
.error-card {
  min-width: 0;
  overflow: clip;
  border-color: color-mix(in srgb, var(--app-action-danger) 35%, var(--app-border-default));
}
.error-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
}
.error-title > div {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
}
.error-title strong {
  min-width: 0;
  overflow-wrap: anywhere;
}
.error-message {
  max-height: 280px;
  overflow-y: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  color: var(--app-action-danger);
}
h3 {
  margin: 0;
  font-size: 17px;
}
.privacy-banner {
  border: 1px solid var(--app-border-default);
  background: var(--app-bg-subtle);
  overflow-wrap: anywhere;
}
.drawer-actions {
  display: flex;
  align-items: stretch;
  flex-wrap: wrap;
  gap: 8px;
  min-width: 0;
  padding: 12px 18px;
  border-top: 1px solid var(--app-border-default);
  background: var(--app-bg-surface);
}

@media (max-width: 1199px) {
  .summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .filters {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 599px) {
  .summary-grid,
  .filters {
    grid-template-columns: minmax(0, 1fr);
  }
  .detail-heading {
    align-items: flex-start;
    flex-direction: column;
  }
  .drawer-actions .el-button {
    flex: 1 1 100%;
  }
}
</style>

<script setup lang="ts">
import type { AdminTableColumn } from '@/components/base/AdminElementAdapters'
import { useAdminNotifier } from '@/composables/useAdminNotifier'
import { computed, onMounted, reactive, ref } from 'vue'
import type { UserRecord, UserStatus } from '@/api/contracts'
import { adminRepository } from '@/api/repository'
import StatusBadge from '@/components/base/StatusBadge.vue'
import ConfirmActionDialog from '@/components/composite/ConfirmActionDialog.vue'
import DataTableShell from '@/components/composite/DataTableShell.vue'
import PageHeader from '@/components/composite/PageHeader.vue'

const notifier = useAdminNotifier()
const users = ref<UserRecord[]>([])
const query = ref('')
const statusFilter = ref<UserStatus | 'all'>('all')
const registeredFrom = ref('')
const registeredTo = ref('')
const detailOpen = ref(false)
const detailTab = ref<'overview' | 'quota' | 'activity'>('overview')
const selectedId = ref('')
const confirm = reactive({
  open: false,
  title: '',
  description: '',
  tone: 'primary' as 'primary' | 'negative' | 'warning',
  action: null as null | ((reason: string) => void),
})

const selected = computed(() => users.value.find((item) => item.id === selectedId.value) ?? null)
const filteredUsers = computed(() =>
  users.value.filter((user) => {
    const search = query.value.trim().toLowerCase()
    const matchQuery =
      !search ||
      `${user.id}${user.masked_phone}${user.masked_email}${user.display_name}`
        .toLowerCase()
        .includes(search)
    const matchStatus = statusFilter.value === 'all' || user.status === statusFilter.value
    const date = user.registered_at.slice(0, 10)
    return (
      matchQuery &&
      matchStatus &&
      (!registeredFrom.value || date >= registeredFrom.value) &&
      (!registeredTo.value || date <= registeredTo.value)
    )
  }),
)

const totals = computed(() => ({
  active: users.value.filter((item) => item.status === 'active').length,
  restricted: users.value.filter((item) =>
    ['ai_suspended', 'wechat_suspended'].includes(item.status),
  ).length,
  disabled: users.value.filter((item) => item.status === 'disabled').length,
  aiUsage: users.value.reduce((sum, item) => sum + item.quota.ai_used, 0),
}))

const columns: AdminTableColumn<UserRecord>[] = [
  { name: 'user', label: '用户', field: 'display_name', align: 'left', sortable: true },
  { name: 'status', label: '账号状态', field: 'status', align: 'left' },
  {
    name: 'usage',
    label: 'AI 用量',
    field: (row) => row.quota.ai_used,
    align: 'left',
    sortable: true,
  },
  { name: 'storage', label: '存储', field: (row) => row.quota.storage_used_gb, align: 'left' },
  { name: 'accounts', label: '公众号', field: 'bound_accounts', align: 'center' },
  { name: 'last_login', label: '最近登录', field: 'last_login_at', align: 'left', sortable: true },
  { name: 'actions', label: '操作', field: 'id', align: 'right' },
]

onMounted(async () => {
  try {
    users.value = await adminRepository.users()
  } catch (error) {
    notifier.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '用户列表加载失败。',
    })
  }
})

function openDetail(user: UserRecord, tab: 'overview' | 'quota' | 'activity' = 'overview'): void {
  selectedId.value = user.id
  detailTab.value = tab
  detailOpen.value = true
}

function openUserRow(_event: Event, user: UserRecord): void {
  openDetail(user)
}

function requestStatus(status: UserStatus): void {
  if (!selected.value) return
  const descriptions: Record<UserStatus, string> = {
    active: '恢复账号后，用户可以继续登录；AI、公众号和上传能力仍按能力开关校验。',
    ai_suspended: '限制 AI 生成后，用户仍可查看和编辑已有文章，新的 AI 请求将被后端拒绝。',
    wechat_suspended: '暂停公众号能力后，用户仍可创作和保存文章，但不能新建草稿或正式发布。',
    disabled: '禁用账号会立即撤销全部用户会话并阻止登录，已有数据保留且不会删除。',
  }
  confirm.title =
    status === 'disabled' ? '禁用用户账号' : status === 'active' ? '恢复用户账号' : '调整用户能力'
  confirm.description = descriptions[status]
  confirm.tone = status === 'disabled' ? 'negative' : status === 'active' ? 'primary' : 'warning'
  confirm.action = (reason) => void applyUserStatus(status, reason)
  confirm.open = true
}

async function applyUserStatus(status: UserStatus, reason: string): Promise<void> {
  if (!selected.value) return
  try {
    await adminRepository.updateUser(selected.value.id, {
      status: status === 'disabled' ? 'disabled' : 'active',
      ai_enabled: !['ai_suspended', 'disabled'].includes(status),
      wechat_enabled: !['wechat_suspended', 'disabled'].includes(status),
      reason,
    })
    users.value = await adminRepository.users()
    notifier.notify({
      type: 'positive',
      message: status === 'disabled' ? '用户已禁用，已有设备会话已撤销。' : '用户状态已更新。',
    })
  } catch (error) {
    notifier.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '用户状态更新失败。',
    })
  }
}

function requestQuotaSave(): void {
  if (!selected.value) return
  confirm.title = '保存用户额度与能力'
  confirm.description =
    '新额度会在用户下一次操作时校验；已有任务不会被中途终止。所有调整都会写入管理员审计日志。'
  confirm.tone = 'primary'
  confirm.action = (reason) => void saveUserLimits(reason)
  confirm.open = true
}

async function saveUserLimits(reason: string): Promise<void> {
  if (!selected.value) return
  try {
    await adminRepository.updateUser(selected.value.id, {
      ai_enabled: selected.value.capabilities.ai,
      wechat_enabled: selected.value.capabilities.wechat,
      storage_bytes: Math.round(selected.value.quota.storage_gb * 1024 ** 3),
      single_file_bytes: Math.round(selected.value.quota.max_file_mb * 1024 ** 2),
      official_account_count: selected.value.quota.official_accounts,
      reason,
    })
    users.value = await adminRepository.users()
    notifier.notify({ type: 'positive', message: '额度和能力开关已保存，下一次请求生效。' })
  } catch (error) {
    notifier.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '额度保存失败。',
    })
  }
}

function requestDiagnostics(): void {
  if (!selected.value) return
  confirm.title = '申请受控排障模式'
  confirm.description =
    '默认页面不展示用户文章正文、对话全文和原始资料。只有具备权限、填写工单原因并生成审计记录后，后端才会签发短期受控排障授权。'
  confirm.tone = 'warning'
  confirm.action = (reason) => void recordDiagnostic(reason)
  confirm.open = true
}

async function recordDiagnostic(reason: string): Promise<void> {
  if (!selected.value) return
  try {
    const result = await adminRepository.recordUserDiagnostic(selected.value.id, reason)
    notifier.notify({ type: 'positive', message: result.message })
  } catch (error) {
    notifier.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '排障申请记录失败。',
    })
  }
}

function clearFilters(): void {
  query.value = ''
  statusFilter.value = 'all'
  registeredFrom.value = ''
  registeredTo.value = ''
}
</script>

<template>
  <section class="admin-page">
    <PageHeader
      title="用户与额度"
      description="查看账号、用量、绑定公众号和失败任务，调整资源额度与能力开关。默认不读取用户文章正文、对话全文或原始资料。"
      eyebrow="平台运营"
    />

    <section class="summary-grid" aria-label="用户状态摘要">
      <el-card flat bordered class="surface-card summary-card"
        ><admin-card-section
          ><span>正常用户</span><strong>{{ totals.active }}</strong
          ><app-icon name="check_circle" color="positive" /></admin-card-section
      ></el-card>
      <el-card flat bordered class="surface-card summary-card"
        ><admin-card-section
          ><span>能力受限</span><strong>{{ totals.restricted }}</strong
          ><app-icon name="gpp_maybe" color="warning" /></admin-card-section
      ></el-card>
      <el-card flat bordered class="surface-card summary-card"
        ><admin-card-section
          ><span>禁用账号</span><strong>{{ totals.disabled }}</strong
          ><app-icon name="block" color="negative" /></admin-card-section
      ></el-card>
      <el-card flat bordered class="surface-card summary-card"
        ><admin-card-section
          ><span>样本 AI 用量</span><strong>{{ totals.aiUsage.toLocaleString() }}</strong
          ><app-icon name="smart_toy" color="primary" /></admin-card-section
      ></el-card>
    </section>

    <el-card flat bordered class="surface-card filter-card">
      <admin-card-section class="filters">
        <admin-input
          v-model="query"
          outlined
          dense
          clearable
          debounce="180"
          label="手机号、邮箱、用户 ID 或名称"
          ><template #prepend><app-icon name="search" /></template
        ></admin-input>
        <admin-select
          v-model="statusFilter"
          outlined
          dense
          emit-value
          map-options
          :options="[
            { label: '全部状态', value: 'all' },
            { label: '正常', value: 'active' },
            { label: 'AI 已限制', value: 'ai_suspended' },
            { label: '公众号已限制', value: 'wechat_suspended' },
            { label: '已禁用', value: 'disabled' },
          ]"
          label="账号状态"
        />
        <admin-input
          v-model="registeredFrom"
          outlined
          dense
          type="date"
          label="注册日期从"
          stack-label
        />
        <admin-input
          v-model="registeredTo"
          outlined
          dense
          type="date"
          label="注册日期至"
          stack-label
        />
        <admin-button
          flat
          color="primary"
          icon="filter_alt_off"
          label="清除"
          @click="clearFilters"
        />
      </admin-card-section>
    </el-card>

    <DataTableShell title="用户列表" :description="`找到 ${filteredUsers.length} 位用户`">
      <admin-table
        flat
        :rows="filteredUsers"
        :columns="columns"
        row-key="id"
        :pagination="{ rowsPerPage: 15 }"
        @row-click="openUserRow"
      >
        <template #body-cell-user="props"
          ><admin-cell :props="props"
            ><div class="user-cell">
              <admin-avatar color="blue-1" text-color="primary" icon="person" />
              <div>
                <strong>{{ props.row.display_name }}</strong>
                <div class="caption-text text-secondary">
                  {{ props.row.masked_phone }} · {{ props.row.masked_email }}
                </div>
                <code>{{ props.row.id }}</code>
              </div>
            </div></admin-cell
          ></template
        >
        <template #body-cell-status="props"
          ><admin-cell :props="props"
            ><StatusBadge :status="props.row.status" />
            <div class="capability-dots">
              <el-tooltip :content="`AI ${props.row.capabilities.ai ? '可用' : '停用'}`">
                <span
                  class="capability-dot"
                  role="img"
                  tabindex="0"
                  :aria-label="`AI ${props.row.capabilities.ai ? '可用' : '停用'}`"
                  :title="`AI ${props.row.capabilities.ai ? '可用' : '停用'}`"
                >
                  <app-icon
                    name="smart_toy"
                    :color="props.row.capabilities.ai ? 'positive' : 'grey-5'"
                  />
                </span>
              </el-tooltip>
              <el-tooltip :content="`公众号 ${props.row.capabilities.wechat ? '可用' : '停用'}`">
                <span
                  class="capability-dot"
                  role="img"
                  tabindex="0"
                  :aria-label="`公众号 ${props.row.capabilities.wechat ? '可用' : '停用'}`"
                  :title="`公众号 ${props.row.capabilities.wechat ? '可用' : '停用'}`"
                >
                  <app-icon
                    name="forum"
                    :color="props.row.capabilities.wechat ? 'positive' : 'grey-5'"
                  />
                </span>
              </el-tooltip>
              <el-tooltip :content="`上传 ${props.row.capabilities.uploads ? '可用' : '停用'}`">
                <span
                  class="capability-dot"
                  role="img"
                  tabindex="0"
                  :aria-label="`上传 ${props.row.capabilities.uploads ? '可用' : '停用'}`"
                  :title="`上传 ${props.row.capabilities.uploads ? '可用' : '停用'}`"
                >
                  <app-icon
                    name="upload_file"
                    :color="props.row.capabilities.uploads ? 'positive' : 'grey-5'"
                  />
                </span>
              </el-tooltip></div></admin-cell
        ></template>
        <template #body-cell-usage="props"
          ><admin-cell :props="props"
            ><div class="progress-label">
              <span
                >{{ props.row.quota.ai_used.toLocaleString() }} /
                {{ props.row.quota.ai_monthly.toLocaleString() }}</span
              ><strong
                >{{
                  Math.round((props.row.quota.ai_used / props.row.quota.ai_monthly) * 100)
                }}%</strong
              >
            </div>
            <admin-progress
              rounded
              size="8px"
              :value="props.row.quota.ai_used / props.row.quota.ai_monthly"
              :color="
                props.row.quota.ai_used / props.row.quota.ai_monthly > 0.9 ? 'warning' : 'primary'
              " /></admin-cell
        ></template>
        <template #body-cell-storage="props"
          ><admin-cell :props="props"
            >{{ props.row.quota.storage_used_gb }} / {{ props.row.quota.storage_gb }} GB</admin-cell
          ></template
        >
        <template #body-cell-accounts="props"
          ><admin-cell :props="props"
            ><strong>{{ props.row.bound_accounts }}</strong> / {{ props.row.quota.official_accounts
            }}<admin-badge v-if="props.row.failed_tasks" class="badge-offset" color="negative"
              >{{ props.row.failed_tasks }} 失败</admin-badge
            ></admin-cell
          ></template
        >
        <template #body-cell-last_login="props"
          ><admin-cell :props="props"
            >{{ props.row.last_login_at ?? '从未登录' }}
            <div class="caption-text text-secondary">
              注册 {{ props.row.registered_at }}
            </div></admin-cell
          ></template
        >
        <template #body-cell-actions="props"
          ><admin-cell :props="props"
            ><admin-button
              flat
              dense
              no-caps
              color="primary"
              label="查看"
              icon-right="chevron_right"
              @click.stop="openDetail(props.row)" /></admin-cell
        ></template>
      </admin-table>
    </DataTableShell>

    <admin-dialog v-model="detailOpen" width="min(760px, calc(100vw - 48px))">
      <el-card v-if="selected" class="user-dialog">
        <admin-toolbar
          ><admin-avatar color="primary" text-color="white" icon="person" />
          <div class="drawer-title">
            <admin-toolbar-title>{{ selected.display_name }}</admin-toolbar-title
            ><code>{{ selected.id }}</code>
          </div>
          <admin-space /><admin-button
            flat
            round
            dense
            icon="close"
            aria-label="关闭用户详情"
            @click="detailOpen = false"
        /></admin-toolbar>
        <el-divider />
        <admin-tabs
          v-model="detailTab"
          dense
          no-caps
          active-color="primary"
          indicator-color="primary"
          ><admin-tab name="overview" label="概况" /><admin-tab
            name="quota"
            label="额度与能力" /><admin-tab name="activity" label="登录与任务" /></admin-tabs
        ><el-divider />
        <div class="drawer-scroll">
          <admin-tab-panels v-model="detailTab">
            <admin-tab-panel name="overview" class="detail-panel">
              <admin-banner rounded class="privacy-banner"
                ><template #avatar><app-icon name="visibility_off" color="primary" /></template
                ><strong>内容隐私边界</strong>
                <div>此页面不加载用户文章正文、对话全文和原始资料。</div>
                <template #action
                  ><admin-button
                    flat
                    color="primary"
                    label="申请受控排障"
                    @click="requestDiagnostics" /></template
              ></admin-banner>
              <admin-list class="admin-list-surface"
                ><admin-item
                  ><admin-item-section
                    ><admin-item-label caption>账号状态</admin-item-label
                    ><admin-item-label
                      ><StatusBadge
                        :status="
                          selected.status
                        " /></admin-item-label></admin-item-section></admin-item
                ><admin-item
                  ><admin-item-section
                    ><admin-item-label caption>联系方式（脱敏）</admin-item-label
                    ><admin-item-label
                      >{{ selected.masked_phone }} · {{ selected.masked_email }}</admin-item-label
                    ></admin-item-section
                  ></admin-item
                ><admin-item
                  ><admin-item-section
                    ><admin-item-label caption>注册与最近登录</admin-item-label
                    ><admin-item-label
                      >{{ selected.registered_at }} /
                      {{ selected.last_login_at ?? '从未登录' }}</admin-item-label
                    ></admin-item-section
                  ></admin-item
                ><admin-item
                  ><admin-item-section
                    ><admin-item-label caption>绑定公众号 / 失败任务</admin-item-label
                    ><admin-item-label
                      >{{ selected.bound_accounts }} 个 /
                      {{ selected.failed_tasks }} 个</admin-item-label
                    ></admin-item-section
                  ></admin-item
                ></admin-list
              >
              <div class="status-actions">
                <admin-button
                  outline
                  color="warning"
                  icon="smart_toy"
                  label="限制 AI 生成"
                  @click="requestStatus('ai_suspended')"
                /><admin-button
                  outline
                  color="warning"
                  icon="forum"
                  label="暂停公众号能力"
                  @click="requestStatus('wechat_suspended')"
                /><admin-button
                  v-if="selected.status !== 'disabled'"
                  outline
                  color="negative"
                  icon="block"
                  label="禁用账号"
                  @click="requestStatus('disabled')"
                /><admin-button
                  v-else
                  outline
                  color="positive"
                  icon="restore"
                  label="恢复账号"
                  @click="requestStatus('active')"
                />
              </div>
            </admin-tab-panel>

            <admin-tab-panel name="quota" class="detail-panel">
              <admin-banner rounded class="quota-banner"
                >额度调整在用户下一次操作时校验，不会中断正在运行的任务。</admin-banner
              >
              <div class="quota-grid">
                <admin-input
                  v-model.number="selected.quota.ai_monthly"
                  outlined
                  type="number"
                  min="0"
                  label="每月 AI 额度"
                /><admin-input
                  v-model.number="selected.quota.storage_gb"
                  outlined
                  type="number"
                  min="1"
                  suffix="GB"
                  label="存储额度"
                /><admin-input
                  v-model.number="selected.quota.max_file_mb"
                  outlined
                  type="number"
                  min="1"
                  suffix="MB"
                  label="单文件上限"
                /><admin-input
                  v-model.number="selected.quota.official_accounts"
                  outlined
                  type="number"
                  min="0"
                  max="100"
                  label="公众号数量"
                />
              </div>
              <h3>能力开关</h3>
              <admin-list class="admin-list-surface"
                ><admin-item tag="label"
                  ><admin-item-section avatar><app-icon name="smart_toy" /></admin-item-section
                  ><admin-item-section
                    ><admin-item-label>AI 生成</admin-item-label
                    ><admin-item-label caption
                      >关闭后仍可查看和编辑已有文章</admin-item-label
                    ></admin-item-section
                  ><admin-item-section side
                    ><admin-toggle
                      v-model="selected.capabilities.ai" /></admin-item-section></admin-item
                ><admin-item tag="label"
                  ><admin-item-section avatar><app-icon name="forum" /></admin-item-section
                  ><admin-item-section
                    ><admin-item-label>公众号草稿与发布</admin-item-label
                    ><admin-item-label caption
                      >关闭后仍可继续创作和保存</admin-item-label
                    ></admin-item-section
                  ><admin-item-section side
                    ><admin-toggle
                      v-model="selected.capabilities.wechat" /></admin-item-section></admin-item
                ><admin-item tag="label"
                  ><admin-item-section avatar><app-icon name="upload_file" /></admin-item-section
                  ><admin-item-section
                    ><admin-item-label>资料上传</admin-item-label
                    ><admin-item-label caption
                      >控制新上传，不删除已有资料</admin-item-label
                    ></admin-item-section
                  ><admin-item-section side
                    ><admin-toggle
                      v-model="selected.capabilities.uploads" /></admin-item-section></admin-item
              ></admin-list>
              <admin-button
                unelevated
                color="primary"
                icon="save"
                label="保存额度与能力"
                @click="requestQuotaSave"
              />
            </admin-tab-panel>

            <admin-tab-panel name="activity" class="detail-panel">
              <admin-list class="admin-list-surface"
                ><admin-item
                  ><admin-item-section avatar
                    ><admin-avatar
                      color="blue-1"
                      text-color="primary"
                      icon="devices" /></admin-item-section
                  ><admin-item-section
                    ><admin-item-label>最近 Web 会话</admin-item-label
                    ><admin-item-label caption
                      >{{ selected.last_login_at ?? '无记录' }} · 会话详情不暴露 Cookie 或
                      Token</admin-item-label
                    ></admin-item-section
                  ><admin-item-section side
                    ><StatusBadge
                      :status="
                        selected.status === 'disabled' ? 'disabled' : 'active'
                      " /></admin-item-section></admin-item
                ><admin-item
                  ><admin-item-section avatar
                    ><admin-avatar
                      color="orange-1"
                      text-color="warning"
                      icon="error" /></admin-item-section
                  ><admin-item-section
                    ><admin-item-label>失败任务</admin-item-label
                    ><admin-item-label caption
                      >{{ selected.failed_tasks }} 个任务需要管理员检查</admin-item-label
                    ></admin-item-section
                  ><admin-item-section side
                    ><admin-button
                      flat
                      color="primary"
                      label="前往任务"
                      to="/tasks" /></admin-item-section></admin-item
              ></admin-list>
            </admin-tab-panel>
          </admin-tab-panels>
        </div>
      </el-card>
    </admin-dialog>

    <ConfirmActionDialog
      v-model="confirm.open"
      :title="confirm.title"
      :description="confirm.description"
      confirm-label="确认并记录审计"
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
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 4px 12px;
  align-items: center;
}
.summary-card span {
  color: var(--app-text-secondary);
}
.summary-card strong {
  font-size: 25px;
}
.summary-card .el-icon {
  grid-column: 2;
  grid-row: 1 / span 2;
  font-size: 28px;
}
.filter-card {
  margin-bottom: 18px;
}
.filters {
  display: grid;
  grid-template-columns:
    minmax(240px, 1fr) minmax(170px, 0.5fr) minmax(160px, 0.4fr) minmax(160px, 0.4fr)
    auto;
  gap: 10px;
  min-width: 0;
  align-items: start;
}
.user-cell {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.user-cell > div {
  min-width: 0;
  max-width: 310px;
  overflow-wrap: anywhere;
}
.user-cell code {
  color: var(--app-text-secondary);
  font-size: 11px;
}
.capability-dots {
  display: flex;
  gap: 6px;
  margin-top: 6px;
}
.capability-dot {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: help;
  border-radius: 50%;
}
.capability-dot:focus-visible {
  outline: 3px solid var(--app-focus-ring);
  outline-offset: 2px;
}
.progress-label {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  min-width: 160px;
  margin-bottom: 5px;
  font-size: 12px;
}
.user-dialog {
  width: 100%;
  max-width: 100%;
  height: min(720px, calc(100dvh - 96px));
  min-width: 0;
  display: grid;
  grid-template-rows: auto auto auto auto minmax(0, 1fr);
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
.detail-panel {
  display: grid;
  gap: 16px;
  min-width: 0;
}
.privacy-banner {
  border: 1px solid color-mix(in srgb, var(--app-action-primary) 25%, var(--app-border-default));
  background: var(--app-action-primary-soft);
  overflow-wrap: anywhere;
}
.quota-banner {
  border: 1px solid var(--app-border-default);
  background: var(--app-bg-subtle);
  overflow-wrap: anywhere;
}
.status-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.quota-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  min-width: 0;
}
h3 {
  margin: 4px 0 -6px;
  font-size: 17px;
}

@media (max-width: 1199px) {
  .filters {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .filters .el-button {
    justify-self: start;
  }
}
@media (max-width: 899px) {
  .summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 599px) {
  .summary-grid,
  .filters,
  .quota-grid {
    grid-template-columns: minmax(0, 1fr);
  }
  .status-actions .el-button {
    flex: 1 1 100%;
  }
}
</style>

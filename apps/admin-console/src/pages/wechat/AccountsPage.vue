<script setup lang="ts">
import type { AdminTableColumn } from '@/components/base/AdminElementAdapters'
import { useAdminNotifier } from '@/composables/useAdminNotifier'
import { computed, onMounted, ref } from 'vue'
import type { OfficialAccount } from '@/api/contracts'
import { adminRepository } from '@/api/repository'
import StatusBadge from '@/components/base/StatusBadge.vue'
import ConfirmActionDialog from '@/components/composite/ConfirmActionDialog.vue'
import DataTableShell from '@/components/composite/DataTableShell.vue'
import PageHeader from '@/components/composite/PageHeader.vue'

const notifier = useAdminNotifier()
const accounts = ref<OfficialAccount[]>([])
const query = ref('')
const statusFilter = ref<OfficialAccount['status'] | 'all'>('all')
const selectedId = ref('')
const detailOpen = ref(false)
const refreshing = ref<string | null>(null)
const reconnectConfirm = ref(false)

const selected = computed(() => accounts.value.find((item) => item.id === selectedId.value) ?? null)
const filteredAccounts = computed(() =>
  accounts.value.filter((account) => {
    const search = query.value.trim().toLowerCase()
    return (
      (statusFilter.value === 'all' || account.status === statusFilter.value) &&
      (!search ||
        `${account.name}${account.owner_display_name}${account.owner_id}`
          .toLowerCase()
          .includes(search))
    )
  }),
)
const summary = computed(() => ({
  connected: accounts.value.filter((item) => item.status === 'connected').length,
  reconnect: accounts.value.filter((item) => item.status === 'reconnect_required').length,
  limited: accounts.value.filter((item) => item.status === 'limited').length,
  failed: accounts.value.filter((item) =>
    ['failed', 'unknown'].includes(item.recent_task_status ?? ''),
  ).length,
}))

const columns: AdminTableColumn<OfficialAccount>[] = [
  { name: 'account', label: '公众号', field: 'name', align: 'left', sortable: true },
  { name: 'owner', label: '所属用户', field: 'owner_display_name', align: 'left' },
  { name: 'status', label: '连接状态', field: 'status', align: 'left' },
  { name: 'capabilities', label: '能力状态', field: 'draft_capable', align: 'left' },
  { name: 'token', label: 'Token 状态', field: 'token_expires_at', align: 'left' },
  { name: 'task', label: '最近任务', field: 'recent_task_status', align: 'left' },
  { name: 'actions', label: '操作', field: 'id', align: 'right' },
]

onMounted(async () => {
  try {
    accounts.value = await adminRepository.officialAccounts()
  } catch (error) {
    notifier.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '公众号连接加载失败。',
    })
  }
})

function openDetail(item: OfficialAccount): void {
  selectedId.value = item.id
  detailOpen.value = true
}

async function refreshToken(item: OfficialAccount): Promise<void> {
  refreshing.value = item.id
  try {
    await adminRepository.refreshOfficialAccount(item.id, '管理员手动刷新公众号 Token')
    accounts.value = await adminRepository.officialAccounts()
    notifier.notify({ type: 'positive', message: 'Token 刷新请求已完成，连接状态已同步。' })
  } catch (error) {
    notifier.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : 'Token 刷新失败。',
    })
  } finally {
    refreshing.value = null
  }
}

async function markReconnect(reason = '管理员确认授权需要重新连接'): Promise<void> {
  if (!selected.value) return
  try {
    await adminRepository.markOfficialAccountReconnect(selected.value.id, reason)
    accounts.value = await adminRepository.officialAccounts()
    detailOpen.value = false
    notifier.notify({ type: 'positive', message: '已标记需要重新连接，用户端会显示一致状态。' })
  } catch (error) {
    notifier.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '连接状态更新失败。',
    })
  }
}
</script>

<template>
  <section class="admin-page">
    <PageHeader
      title="公众号连接"
      description="查看用户已绑定公众号的连接、Token、能力和近期任务。管理员只能维护连接与处理异常，不能代替用户创建草稿或发布文章。"
      eyebrow="公众号管理"
    >
      <template #actions
        ><admin-button
          outline
          color="primary"
          icon="settings_input_antenna"
          label="平台配置"
          to="/wechat/platform"
      /></template>
    </PageHeader>

    <section class="summary-grid">
      <el-card flat bordered class="surface-card summary-card"
        ><admin-card-section
          ><admin-avatar color="green-1" text-color="positive" icon="link" />
          <div>
            <span>连接正常</span><strong>{{ summary.connected }}</strong>
          </div></admin-card-section
        ></el-card
      >
      <el-card flat bordered class="surface-card summary-card"
        ><admin-card-section
          ><admin-avatar color="red-1" text-color="negative" icon="link_off" />
          <div>
            <span>需重新连接</span><strong>{{ summary.reconnect }}</strong>
          </div></admin-card-section
        ></el-card
      >
      <el-card flat bordered class="surface-card summary-card"
        ><admin-card-section
          ><admin-avatar color="orange-1" text-color="warning" icon="gpp_maybe" />
          <div>
            <span>能力受限</span><strong>{{ summary.limited }}</strong>
          </div></admin-card-section
        ></el-card
      >
      <el-card flat bordered class="surface-card summary-card"
        ><admin-card-section
          ><admin-avatar color="purple-1" text-color="deep-purple" icon="error" />
          <div>
            <span>失败或待核对任务</span><strong>{{ summary.failed }}</strong>
          </div></admin-card-section
        ></el-card
      >
    </section>

    <admin-banner rounded class="boundary-banner"
      ><template #avatar><app-icon name="verified_user" color="primary" /></template
      >管理员操作只更新连接状态或刷新 Token。草稿与发布始终由用户确认同一 Render
      后发起，管理端没有“代用户发布”入口。</admin-banner
    >

    <el-card flat bordered class="surface-card filter-card"
      ><admin-card-section class="filters"
        ><admin-input
          v-model="query"
          outlined
          dense
          clearable
          debounce="180"
          label="搜索公众号、用户或用户 ID"
          ><template #prepend><app-icon name="search" /></template></admin-input
        ><admin-select
          v-model="statusFilter"
          outlined
          dense
          emit-value
          map-options
          :options="[
            { label: '全部状态', value: 'all' },
            { label: '连接正常', value: 'connected' },
            { label: '需重新连接', value: 'reconnect_required' },
            { label: '能力受限', value: 'limited' },
          ]"
          label="连接状态" /></admin-card-section
    ></el-card>

    <DataTableShell
      title="已绑定公众号"
      :description="`共 ${filteredAccounts.length} 个连接；状态与用户端保持一致`"
    >
      <admin-table
        flat
        :rows="filteredAccounts"
        :columns="columns"
        row-key="id"
        :pagination="{ rowsPerPage: 15 }"
      >
        <template #body-cell-account="props"
          ><admin-cell :props="props"
            ><div class="account-cell">
              <admin-avatar color="green-1" text-color="green-8" icon="forum" />
              <div>
                <strong>{{ props.row.name }}</strong
                ><span>授权于 {{ props.row.authorized_at }}</span>
              </div>
            </div></admin-cell
          ></template
        >
        <template #body-cell-owner="props"
          ><admin-cell :props="props"
            ><div class="cell-wrap">{{ props.row.owner_display_name }}</div>
            <code>{{ props.row.owner_id }}</code></admin-cell
          ></template
        >
        <template #body-cell-status="props"
          ><admin-cell :props="props"><StatusBadge :status="props.row.status" /></admin-cell
        ></template>
        <template #body-cell-capabilities="props"
          ><admin-cell :props="props"
            ><div class="capability-list">
              <span
                ><app-icon name="drafts" :color="props.row.draft_capable ? 'positive' : 'grey-5'" />
                草稿 {{ props.row.draft_capable ? '可用' : '不可用' }}</span
              ><span
                ><app-icon
                  name="publish"
                  :color="props.row.publish_capable ? 'positive' : 'grey-5'"
                />
                发布 {{ props.row.publish_capable ? '可用' : '不可用' }}</span
              >
            </div></admin-cell
          ></template
        >
        <template #body-cell-token="props"
          ><admin-cell :props="props"
            ><div class="cell-wrap">{{ props.row.last_refresh_result }}</div>
            <span class="caption-text text-secondary">{{
              props.row.token_expires_at ? `到期 ${props.row.token_expires_at}` : '无有效 Token'
            }}</span></admin-cell
          ></template
        >
        <template #body-cell-task="props"
          ><admin-cell :props="props"
            ><StatusBadge
              v-if="props.row.recent_task_status"
              :status="props.row.recent_task_status"
            /><span v-else>暂无任务</span></admin-cell
          ></template
        >
        <template #body-cell-actions="props"
          ><admin-cell :props="props"
            ><div class="table-actions">
              <admin-button
                flat
                dense
                no-caps
                icon="refresh"
                label="刷新"
                :loading="refreshing === props.row.id"
                @click="refreshToken(props.row)"
              /><admin-button
                flat
                dense
                no-caps
                color="primary"
                label="详情"
                icon-right="chevron_right"
                @click="openDetail(props.row)"
              /></div></admin-cell
        ></template>
      </admin-table>
    </DataTableShell>

    <admin-dialog v-model="detailOpen" width="min(760px, calc(100vw - 48px))">
      <el-card v-if="selected" class="account-dialog">
        <admin-toolbar
          ><admin-avatar color="green-1" text-color="green-8" icon="forum" />
          <div class="drawer-title">
            <admin-toolbar-title>{{ selected.name }}</admin-toolbar-title
            ><span>{{ selected.owner_display_name }}</span>
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
            <admin-banner
              rounded
              :class="selected.status === 'connected' ? 'connected-banner' : 'warning-banner'"
              ><template #avatar
                ><app-icon
                  :name="selected.status === 'connected' ? 'check_circle' : 'warning'"
                  :color="selected.status === 'connected' ? 'positive' : 'warning'" /></template
              ><strong>{{
                selected.status === 'connected'
                  ? '连接状态正常'
                  : selected.status === 'reconnect_required'
                    ? '需要用户重新连接'
                    : '授权能力受限'
              }}</strong>
              <div>{{ selected.last_refresh_result }}</div></admin-banner
            >
            <el-card flat bordered
              ><admin-list separator
                ><admin-item
                  ><admin-item-section
                    ><admin-item-label caption>所属用户</admin-item-label
                    ><admin-item-label
                      >{{ selected.owner_display_name }}（{{
                        selected.owner_id
                      }}）</admin-item-label
                    ></admin-item-section
                  ></admin-item
                ><admin-item
                  ><admin-item-section
                    ><admin-item-label caption>授权时间</admin-item-label
                    ><admin-item-label>{{
                      selected.authorized_at
                    }}</admin-item-label></admin-item-section
                  ></admin-item
                ><admin-item
                  ><admin-item-section
                    ><admin-item-label caption>Token 到期</admin-item-label
                    ><admin-item-label>{{
                      selected.token_expires_at ?? '无有效 Token'
                    }}</admin-item-label></admin-item-section
                  ></admin-item
                ></admin-list
              ></el-card
            >
            <div>
              <h3>用户可用能力</h3>
              <div class="capability-cards">
                <el-card flat bordered :class="{ unavailable: !selected.draft_capable }"
                  ><admin-card-section
                    ><app-icon name="drafts" /><strong>公众号草稿</strong
                    ><span>{{
                      selected.draft_capable ? '正常' : '当前不支持'
                    }}</span></admin-card-section
                  ></el-card
                ><el-card flat bordered :class="{ unavailable: !selected.publish_capable }"
                  ><admin-card-section
                    ><app-icon name="publish" /><strong>正式发布</strong
                    ><span>{{
                      selected.publish_capable ? '正常' : '当前不支持'
                    }}</span></admin-card-section
                  ></el-card
                >
              </div>
            </div>
            <el-card flat bordered
              ><admin-card-section
                ><h3>最近微信任务</h3>
                <p class="text-secondary">
                  管理端只显示状态与诊断元数据，不展示文章正文或代用户执行。
                </p>
                <div class="recent-task">
                  <StatusBadge
                    v-if="selected.recent_task_status"
                    :status="selected.recent_task_status"
                  /><admin-button
                    flat
                    color="primary"
                    label="打开任务与对账"
                    :to="{ path: '/tasks', query: { account: selected.id } }"
                  /></div></admin-card-section
            ></el-card>
            <div class="drawer-actions">
              <admin-button
                outline
                color="primary"
                icon="refresh"
                label="刷新 Token"
                :loading="refreshing === selected.id"
                @click="refreshToken(selected)"
              /><admin-button
                outline
                color="negative"
                icon="link_off"
                label="标记需重新连接"
                :disable="selected.status === 'reconnect_required'"
                @click="reconnectConfirm = true"
              />
            </div>
          </div>
        </div>
      </el-card>
    </admin-dialog>

    <ConfirmActionDialog
      v-model="reconnectConfirm"
      title="标记公众号需要重新连接"
      :description="`标记后，${selected?.name ?? '该公众号'} 的新草稿和发布操作会被后端阻止，用户端显示重新绑定提示；已有文章和模板不受影响。`"
      confirm-label="确认标记"
      tone="negative"
      require-reason
      @confirm="markReconnect"
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
  margin-top: 3px;
  font-size: 24px;
}
.boundary-banner {
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
  grid-template-columns: minmax(240px, 1fr) minmax(180px, 260px);
  gap: 12px;
  min-width: 0;
}
.account-cell {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.account-cell > div {
  min-width: 0;
  max-width: 280px;
}
.account-cell strong,
.account-cell span {
  display: block;
  overflow-wrap: anywhere;
}
.account-cell span,
code {
  color: var(--app-text-secondary);
  font-size: 11px;
}
.cell-wrap {
  max-width: 290px;
  overflow-wrap: anywhere;
}
.capability-list {
  display: grid;
  gap: 4px;
  min-width: 150px;
}
.capability-list span {
  display: flex;
  align-items: center;
  gap: 5px;
}
.table-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 4px;
}
.account-dialog {
  width: 100%;
  max-width: 100%;
  height: min(720px, calc(100dvh - 96px));
  min-width: 0;
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
}
.drawer-title {
  min-width: 0;
}
.drawer-title span {
  display: block;
  padding-left: 12px;
  color: var(--app-text-secondary);
  font-size: 12px;
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
.connected-banner,
.warning-banner {
  overflow-wrap: anywhere;
}
.connected-banner {
  border: 1px solid color-mix(in srgb, var(--app-action-success) 30%, var(--app-border-default));
  background: color-mix(in srgb, var(--app-action-success) 8%, var(--app-bg-surface));
}
.warning-banner {
  border: 1px solid color-mix(in srgb, var(--app-action-warning) 30%, var(--app-border-default));
  background: color-mix(in srgb, var(--app-action-warning) 8%, var(--app-bg-surface));
}
h3 {
  margin: 0 0 8px;
  font-size: 17px;
}
.capability-cards {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  min-width: 0;
}
.capability-cards .admin-card-section {
  display: grid;
  gap: 5px;
}
.capability-cards .el-icon {
  color: var(--app-action-success);
  font-size: 24px;
}
.capability-cards span {
  color: var(--app-text-secondary);
}
.capability-cards .unavailable {
  opacity: 0.66;
}
.capability-cards .unavailable .el-icon {
  color: var(--app-text-secondary);
}
.recent-task,
.drawer-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  min-width: 0;
}

@media (max-width: 1023px) {
  .summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 599px) {
  .summary-grid,
  .filters,
  .capability-cards {
    grid-template-columns: minmax(0, 1fr);
  }
  .drawer-actions {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>

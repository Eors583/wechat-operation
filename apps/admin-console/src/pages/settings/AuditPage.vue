<script setup lang="ts">
import type { AdminTableColumn } from '@/components/base/AdminElementAdapters'
import { computed, onMounted, ref } from 'vue'
import type { AuditLog } from '@/api/contracts'
import { adminRepository } from '@/api/repository'
import StatusBadge from '@/components/base/StatusBadge.vue'
import DataTableShell from '@/components/composite/DataTableShell.vue'
import PageHeader from '@/components/composite/PageHeader.vue'

const audits = ref<AuditLog[]>([])
const query = ref('')
const resultFilter = ref<AuditLog['result'] | 'all'>('all')
const actionFilter = ref('all')
const selectedId = ref('')
const detailOpen = ref(false)

const selected = computed(() => audits.value.find((item) => item.id === selectedId.value) ?? null)
const actions = computed(() => [...new Set(audits.value.map((item) => item.action))])
const filtered = computed(() =>
  audits.value.filter((item) => {
    const search = query.value.trim().toLowerCase()
    return (
      (resultFilter.value === 'all' || item.result === resultFilter.value) &&
      (actionFilter.value === 'all' || item.action === actionFilter.value) &&
      (!search ||
        `${item.actor}${item.action}${item.resource_type}${item.resource_label}${item.reason}${item.request_id}`
          .toLowerCase()
          .includes(search))
    )
  }),
)

const columns: AdminTableColumn<AuditLog>[] = [
  { name: 'time', label: '时间', field: 'created_at', align: 'left', sortable: true },
  { name: 'actor', label: '管理员', field: 'actor', align: 'left', sortable: true },
  { name: 'action', label: '动作', field: 'action', align: 'left' },
  { name: 'resource', label: '资源', field: 'resource_label', align: 'left' },
  { name: 'reason', label: '原因', field: 'reason', align: 'left' },
  { name: 'request', label: '请求 / IP', field: 'request_id', align: 'left' },
  { name: 'result', label: '结果', field: 'result', align: 'left' },
  { name: 'actions', label: '操作', field: 'id', align: 'right' },
]

onMounted(async () => {
  try {
    audits.value = await adminRepository.audits()
  } catch {
    /* Table remains empty. */
  }
})

function openDetail(item: AuditLog): void {
  selectedId.value = item.id
  detailOpen.value = true
}

function exportCsv(): void {
  const header = ['时间', '管理员', '动作', '资源类型', '资源', '原因', 'Request ID', 'IP', '结果']
  const rows = filtered.value.map((item) => [
    item.created_at,
    item.actor,
    item.action,
    item.resource_type,
    item.resource_label,
    item.reason,
    item.request_id,
    item.ip_address,
    item.result,
  ])
  const csv = [header, ...rows]
    .map((row) => row.map((cell) => `"${cell.replaceAll('"', '""')}"`).join(','))
    .join('\r\n')
  const url = URL.createObjectURL(new Blob([`\ufeff${csv}`], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = `admin-audit-${new Date().toISOString().slice(0, 10)}.csv`
  link.click()
  URL.revokeObjectURL(url)
}
</script>

<template>
  <section class="admin-page">
    <PageHeader
      title="审计日志"
      description="只读查看配置发布、额度调整、任务重试、管理员账号和受控排障等高风险操作。日志不记录 Cookie、密钥或用户正文。"
      eyebrow="系统治理"
    >
      <template #actions
        ><admin-button
          outline
          color="primary"
          icon="download"
          label="导出当前结果"
          @click="exportCsv"
      /></template>
    </PageHeader>

    <section class="summary-grid">
      <el-card flat bordered class="surface-card summary-card"
        ><admin-card-section
          ><app-icon name="fact_check" color="primary" />
          <div>
            <span>审计记录</span><strong>{{ audits.length }}</strong>
          </div></admin-card-section
        ></el-card
      ><el-card flat bordered class="surface-card summary-card"
        ><admin-card-section
          ><app-icon name="check_circle" color="positive" />
          <div>
            <span>成功</span
            ><strong>{{ audits.filter((item) => item.result === 'success').length }}</strong>
          </div></admin-card-section
        ></el-card
      ><el-card flat bordered class="surface-card summary-card"
        ><admin-card-section
          ><app-icon name="gpp_bad" color="negative" />
          <div>
            <span>拒绝 / 失败</span
            ><strong>{{ audits.filter((item) => item.result !== 'success').length }}</strong>
          </div></admin-card-section
        ></el-card
      >
    </section>

    <admin-banner rounded class="audit-banner"
      ><template #avatar><app-icon name="lock" color="primary" /></template
      >审计日志保存动作、资源引用、原因、请求 ID、管理员和结果；不保存 Authorization、Cookie、模型
      Key、微信 Secret、用户文章或文件全文。</admin-banner
    >

    <el-card flat bordered class="surface-card filter-card"
      ><admin-card-section class="filters"
        ><admin-input
          v-model="query"
          outlined
          dense
          clearable
          debounce="180"
          label="搜索管理员、资源、原因或 Request ID"
          ><template #prepend><app-icon name="search" /></template></admin-input
        ><admin-select
          v-model="actionFilter"
          outlined
          dense
          emit-value
          map-options
          :options="[
            { label: '全部动作', value: 'all' },
            ...actions.map((value) => ({ label: value, value })),
          ]"
          label="动作" /><admin-select
          v-model="resultFilter"
          outlined
          dense
          emit-value
          map-options
          :options="[
            { label: '全部结果', value: 'all' },
            { label: '成功', value: 'success' },
            { label: '拒绝', value: 'denied' },
            { label: '失败', value: 'failed' },
          ]"
          label="结果" /></admin-card-section
    ></el-card>

    <DataTableShell title="审计记录" :description="`显示 ${filtered.length} 条不可修改记录`">
      <admin-table
        flat
        :rows="filtered"
        :columns="columns"
        row-key="id"
        :pagination="{ rowsPerPage: 20 }"
      >
        <template #body-cell-time="props"
          ><admin-cell :props="props">{{ props.row.created_at }}</admin-cell></template
        >
        <template #body-cell-actor="props"
          ><admin-cell :props="props"
            ><div class="actor-cell">
              <admin-avatar
                color="blue-1"
                text-color="primary"
                icon="admin_panel_settings"
                size="32px"
              /><strong>{{ props.row.actor }}</strong>
            </div></admin-cell
          ></template
        >
        <template #body-cell-action="props"
          ><admin-cell :props="props"
            ><code class="cell-wrap">{{ props.row.action }}</code></admin-cell
          ></template
        >
        <template #body-cell-resource="props"
          ><admin-cell :props="props"
            ><div class="cell-wrap">
              <strong>{{ props.row.resource_label }}</strong
              ><span>{{ props.row.resource_type }}</span>
            </div></admin-cell
          ></template
        >
        <template #body-cell-reason="props"
          ><admin-cell :props="props"
            ><div class="reason-cell">{{ props.row.reason }}</div></admin-cell
          ></template
        >
        <template #body-cell-request="props"
          ><admin-cell :props="props"
            ><code>{{ props.row.request_id }}</code>
            <div class="caption-text text-secondary">{{ props.row.ip_address }}</div></admin-cell
          ></template
        >
        <template #body-cell-result="props"
          ><admin-cell :props="props"
            ><StatusBadge
              :status="
                props.row.result === 'success'
                  ? 'healthy'
                  : props.row.result === 'denied'
                    ? 'degraded'
                    : 'down'
              "
              :label="
                props.row.result === 'success'
                  ? '成功'
                  : props.row.result === 'denied'
                    ? '已拒绝'
                    : '失败'
              " /></admin-cell
        ></template>
        <template #body-cell-actions="props"
          ><admin-cell :props="props"
            ><admin-button
              flat
              dense
              no-caps
              color="primary"
              label="详情"
              icon-right="chevron_right"
              @click="openDetail(props.row)" /></admin-cell
        ></template>
      </admin-table>
    </DataTableShell>

    <admin-dialog v-model="detailOpen" width="min(720px, calc(100vw - 48px))">
      <el-card v-if="selected" class="audit-dialog"
        ><admin-toolbar
          ><admin-avatar color="primary" text-color="white" icon="fact_check" />
          <div class="drawer-title">
            <admin-toolbar-title>审计详情</admin-toolbar-title><code>{{ selected.id }}</code>
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
            <div class="result-row">
              <StatusBadge
                :status="
                  selected.result === 'success'
                    ? 'healthy'
                    : selected.result === 'denied'
                      ? 'degraded'
                      : 'down'
                "
                :label="
                  selected.result === 'success'
                    ? '操作成功'
                    : selected.result === 'denied'
                      ? '操作已拒绝'
                      : '操作失败'
                "
              /><span>{{ selected.created_at }}</span>
            </div>
            <el-card flat bordered
              ><admin-list separator
                ><admin-item
                  ><admin-item-section
                    ><admin-item-label caption>管理员</admin-item-label
                    ><admin-item-label>{{ selected.actor }}</admin-item-label></admin-item-section
                  ></admin-item
                ><admin-item
                  ><admin-item-section
                    ><admin-item-label caption>动作</admin-item-label
                    ><admin-item-label
                      ><code>{{ selected.action }}</code></admin-item-label
                    ></admin-item-section
                  ></admin-item
                ><admin-item
                  ><admin-item-section
                    ><admin-item-label caption>资源</admin-item-label
                    ><admin-item-label class="long-text"
                      >{{ selected.resource_type }} ·
                      {{ selected.resource_label }}</admin-item-label
                    ></admin-item-section
                  ></admin-item
                ><admin-item
                  ><admin-item-section
                    ><admin-item-label caption>操作原因</admin-item-label
                    ><admin-item-label class="long-text">{{
                      selected.reason
                    }}</admin-item-label></admin-item-section
                  ></admin-item
                ><admin-item
                  ><admin-item-section
                    ><admin-item-label caption>请求标识</admin-item-label
                    ><admin-item-label
                      ><code>{{ selected.request_id }}</code> ·
                      {{ selected.ip_address }}</admin-item-label
                    ></admin-item-section
                  ></admin-item
                ></admin-list
              ></el-card
            ><admin-banner rounded class="immutable-banner"
              ><template #avatar><app-icon name="verified" color="positive" /></template
              >审计记录为只读事实，不提供编辑或删除入口。审计接口不返回正文、凭据或完整个人信息。</admin-banner
            >
          </div>
        </div></el-card
      >
    </admin-dialog>
  </section>
</template>

<style scoped lang="scss">
.summary-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  min-width: 0;
  margin-bottom: 18px;
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
.summary-card div {
  min-width: 0;
}
.summary-card span {
  display: block;
  color: var(--app-text-secondary);
}
.summary-card strong {
  display: block;
  font-size: 25px;
}
.audit-banner {
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
  grid-template-columns: minmax(260px, 1fr) minmax(190px, 0.45fr) minmax(160px, 0.35fr);
  gap: 10px;
  min-width: 0;
}
.actor-cell {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.actor-cell strong {
  overflow-wrap: anywhere;
}
.cell-wrap {
  max-width: 290px;
  overflow-wrap: anywhere;
}
.cell-wrap strong,
.cell-wrap span {
  display: block;
  overflow-wrap: anywhere;
}
.cell-wrap span {
  color: var(--app-text-secondary);
  font-size: 11px;
}
.reason-cell {
  max-width: 340px;
  white-space: normal;
  overflow-wrap: anywhere;
}
.audit-dialog {
  width: 100%;
  max-width: 100%;
  height: min(700px, calc(100dvh - 96px));
  min-width: 0;
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
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
.result-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  color: var(--app-text-secondary);
}
.immutable-banner {
  border: 1px solid var(--app-border-default);
  background: var(--app-bg-subtle);
  overflow-wrap: anywhere;
}

@media (max-width: 899px) {
  .filters {
    grid-template-columns: minmax(0, 1fr);
  }
}
@media (max-width: 599px) {
  .summary-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>

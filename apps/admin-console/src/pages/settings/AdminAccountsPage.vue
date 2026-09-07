<script setup lang="ts">
import type { AdminTableColumn } from '@/components/base/AdminElementAdapters'
import { useAdminNotifier } from '@/composables/useAdminNotifier'
import { computed, onMounted, reactive, ref } from 'vue'
import type { AdminAccount } from '@/api/contracts'
import { adminRepository } from '@/api/repository'
import StatusBadge from '@/components/base/StatusBadge.vue'
import ConfirmActionDialog from '@/components/composite/ConfirmActionDialog.vue'
import DataTableShell from '@/components/composite/DataTableShell.vue'
import PageHeader from '@/components/composite/PageHeader.vue'
import { cloneData } from '@/utils/clone'

const notifier = useAdminNotifier()
const admins = ref<AdminAccount[]>([])
const query = ref('')
const editorOpen = ref(false)
const confirm = reactive({
  open: false,
  title: '',
  description: '',
  tone: 'primary' as 'primary' | 'negative' | 'warning',
  action: null as null | ((reason: string) => Promise<void> | void),
})
const form = reactive<AdminAccount>({
  id: '',
  username: '',
  display_name: '',
  role: 'operations',
  status: 'active',
  last_login_at: null,
  created_at: '',
})
const initialPassword = ref('')

const roleLabels: Record<AdminAccount['role'], string> = {
  super_admin: '超级管理员',
  operations: '运营管理员',
  auditor: '审计员',
}
const roleLabel = (value: unknown): string =>
  typeof value === 'string' && value in roleLabels
    ? roleLabels[value as AdminAccount['role']]
    : String(value)
const filtered = computed(() =>
  admins.value.filter(
    (item) =>
      !query.value.trim() ||
      `${item.username}${item.display_name}${roleLabels[item.role]}`
        .toLowerCase()
        .includes(query.value.trim().toLowerCase()),
  ),
)
const columns: AdminTableColumn<AdminAccount>[] = [
  { name: 'account', label: '管理员', field: 'display_name', align: 'left', sortable: true },
  { name: 'role', label: '角色', field: 'role', align: 'left' },
  { name: 'status', label: '状态', field: 'status', align: 'left' },
  { name: 'last_login', label: '最近登录', field: 'last_login_at', align: 'left' },
  { name: 'created', label: '创建时间', field: 'created_at', align: 'left' },
  { name: 'actions', label: '操作', field: 'id', align: 'right' },
]

onMounted(async () => {
  try {
    admins.value = await adminRepository.admins()
  } catch (error) {
    notifier.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '管理员列表加载失败。',
    })
  }
})

function openCreate(): void {
  Object.assign(form, {
    id: crypto.randomUUID(),
    username: '',
    display_name: '',
    role: 'operations',
    status: 'active',
    last_login_at: null,
    created_at: new Date().toISOString(),
  })
  initialPassword.value = ''
  editorOpen.value = true
}

function openEdit(item: AdminAccount): void {
  Object.assign(form, cloneData(item))
  initialPassword.value = ''
  editorOpen.value = true
}

async function save(): Promise<void> {
  if (!form.username.trim() || !form.display_name.trim()) return
  if (admins.value.some((item) => item.username === form.username && item.id !== form.id)) {
    notifier.notify({ type: 'negative', message: '管理员账号已存在。' })
    return
  }
  const index = admins.value.findIndex((item) => item.id === form.id)
  const isNew = index < 0
  try {
    if (isNew) {
      await adminRepository.createAdmin(form, initialPassword.value)
    } else await adminRepository.updateAdmin(form.id, { role: form.role }, '更新管理员角色')
    admins.value = await adminRepository.admins()
    editorOpen.value = false
    notifier.notify({
      type: 'positive',
      message: isNew ? '管理员已创建。' : '管理员资料和角色已更新。',
    })
  } catch (error) {
    notifier.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '管理员保存失败。',
    })
  }
}

function requestDisable(item: AdminAccount): void {
  if (item.id === 'admin-1') {
    notifier.notify({ type: 'warning', message: '不能在当前会话中停用自己。' })
    return
  }
  confirm.title = '停用管理员账号'
  confirm.description = `停用 ${item.display_name} 后，其全部管理会话立即撤销，不能继续登录。普通用户账号与数据不受影响。`
  confirm.tone = 'negative'
  confirm.action = async (reason) => {
    try {
      await adminRepository.updateAdmin(item.id, { status: 'disabled' }, reason)
      admins.value = await adminRepository.admins()
      notifier.notify({ type: 'positive', message: '管理员已停用，管理会话已撤销。' })
    } catch (error) {
      notifier.notify({
        type: 'negative',
        message: error instanceof Error ? error.message : '管理员停用失败。',
      })
    }
  }
  confirm.open = true
}

async function restore(item: AdminAccount): Promise<void> {
  try {
    await adminRepository.updateAdmin(item.id, { status: 'active' }, '恢复管理员账号')
    admins.value = await adminRepository.admins()
    notifier.notify({ type: 'positive', message: '管理员账号已恢复。' })
  } catch (error) {
    notifier.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '管理员恢复失败。',
    })
  }
}
</script>

<template>
  <section class="admin-page">
    <PageHeader
      title="管理员账号"
      description="管理独立后台账号、角色和状态。管理员会话与普通用户会话完全隔离，所有变更写入审计日志。"
      eyebrow="系统治理"
    >
      <template #actions
        ><admin-button
          outline
          color="primary"
          icon="fact_check"
          label="查看审计"
          to="/settings/audit" /><admin-button
          unelevated
          color="primary"
          icon="person_add"
          label="添加管理员"
          @click="openCreate"
      /></template>
    </PageHeader>

    <admin-banner rounded class="security-banner"
      ><template #avatar><app-icon name="admin_panel_settings" color="primary" /></template
      >首个超级管理员由部署 CLI 初始化。管理员使用账号 +
      密码登录；连续失败后启用图形验证码和限流，管理 Cookie 不能调用用户接口。</admin-banner
    >

    <section class="role-grid">
      <el-card flat bordered class="surface-card role-card"
        ><admin-card-section
          ><admin-avatar color="red-1" text-color="negative" icon="shield" />
          <div><strong>超级管理员</strong><span>配置、账号、额度、任务和审计完整权限</span></div>
          <admin-badge color="negative">{{
            admins.filter((item) => item.role === 'super_admin').length
          }}</admin-badge></admin-card-section
        ></el-card
      >
      <el-card flat bordered class="surface-card role-card"
        ><admin-card-section
          ><admin-avatar color="blue-1" text-color="primary" icon="settings_suggest" />
          <div><strong>运营管理员</strong><span>模型、技能、用户状态、公众号和任务</span></div>
          <admin-badge color="primary">{{
            admins.filter((item) => item.role === 'operations').length
          }}</admin-badge></admin-card-section
        ></el-card
      >
      <el-card flat bordered class="surface-card role-card"
        ><admin-card-section
          ><admin-avatar color="purple-1" text-color="deep-purple" icon="fact_check" />
          <div><strong>审计员</strong><span>只读运行状态和审计记录</span></div>
          <admin-badge color="deep-purple">{{
            admins.filter((item) => item.role === 'auditor').length
          }}</admin-badge></admin-card-section
        ></el-card
      >
    </section>

    <el-card flat bordered class="surface-card search-card"
      ><admin-card-section
        ><admin-input
          v-model="query"
          outlined
          dense
          clearable
          debounce="180"
          label="搜索账号、姓名或角色"
          ><template #prepend
            ><app-icon name="search" /></template></admin-input></admin-card-section
    ></el-card>

    <DataTableShell title="管理员列表" :description="`共 ${filtered.length} 个管理账号`">
      <admin-table
        flat
        :rows="filtered"
        :columns="columns"
        row-key="id"
        :pagination="{ rowsPerPage: 15 }"
      >
        <template #body-cell-account="props"
          ><admin-cell :props="props"
            ><div class="admin-cell">
              <admin-avatar color="blue-1" text-color="primary" icon="admin_panel_settings" />
              <div>
                <strong>{{ props.row.display_name }}</strong
                ><code>{{ props.row.username }}</code>
              </div>
            </div></admin-cell
          ></template
        >
        <template #body-cell-role="props"
          ><admin-cell :props="props"
            ><admin-badge
              outline
              :color="
                props.row.role === 'super_admin'
                  ? 'negative'
                  : props.row.role === 'auditor'
                    ? 'deep-purple'
                    : 'primary'
              "
              >{{ roleLabel(props.row.role) }}</admin-badge
            ></admin-cell
          ></template
        >
        <template #body-cell-status="props"
          ><admin-cell :props="props"><StatusBadge :status="props.row.status" /></admin-cell
        ></template>
        <template #body-cell-last_login="props"
          ><admin-cell :props="props">{{
            props.row.last_login_at ?? '尚未登录'
          }}</admin-cell></template
        >
        <template #body-cell-created="props"
          ><admin-cell :props="props">{{ props.row.created_at }}</admin-cell></template
        >
        <template #body-cell-actions="props"
          ><admin-cell :props="props"
            ><div class="table-actions">
              <admin-button
                flat
                round
                dense
                icon="edit"
                aria-label="编辑管理员"
                @click="openEdit(props.row)"
              /><admin-button
                v-if="props.row.status === 'active'"
                flat
                round
                dense
                color="negative"
                icon="block"
                aria-label="停用管理员"
                :disable="props.row.id === 'admin-1'"
                @click="requestDisable(props.row)"
              /><admin-button
                v-else
                flat
                round
                dense
                color="positive"
                icon="restore"
                aria-label="恢复管理员"
                @click="restore(props.row)"
              /></div></admin-cell
        ></template>
      </admin-table>
    </DataTableShell>

    <admin-dialog v-model="editorOpen" width="min(620px, calc(100vw - 48px))">
      <el-card class="admin-dialog"
        ><admin-toolbar
          ><admin-toolbar-title>{{
            admins.some((item) => item.id === form.id) ? '编辑管理员' : '添加管理员'
          }}</admin-toolbar-title
          ><admin-button
            flat
            round
            dense
            icon="close"
            aria-label="关闭"
            @click="editorOpen = false" /></admin-toolbar
        ><el-divider /><admin-card-section class="admin-form"
          ><admin-input
            v-model.trim="form.username"
            outlined
            label="登录账号"
            autocomplete="off" /><admin-input
            v-model.trim="form.display_name"
            outlined
            label="显示姓名" /><admin-select
            v-model="form.role"
            outlined
            emit-value
            map-options
            :options="[
              { label: '超级管理员', value: 'super_admin' },
              { label: '运营管理员', value: 'operations' },
              { label: '审计员', value: 'auditor' },
            ]"
            label="角色" /><admin-input
            v-if="!admins.some((item) => item.id === form.id)"
            v-model="initialPassword"
            outlined
            type="password"
            autocomplete="new-password"
            label="初始密码"
            hint="仅用于首次登录；生产环境应通过安全渠道交付并强制修改" /></admin-card-section
        ><admin-card-actions align="right"
          ><admin-button flat label="取消" @click="editorOpen = false" /><admin-button
            unelevated
            color="primary"
            label="保存管理员"
            :disable="
              !form.username ||
              !form.display_name ||
              (!admins.some((item) => item.id === form.id) && initialPassword.length < 12)
            "
            @click="save" /></admin-card-actions
      ></el-card>
    </admin-dialog>

    <ConfirmActionDialog
      v-model="confirm.open"
      :title="confirm.title"
      :description="confirm.description"
      confirm-label="确认并记录审计"
      :tone="confirm.tone"
      require-reason
      @confirm="confirm.action?.($event)"
    />
  </section>
</template>

<style scoped lang="scss">
.security-banner {
  margin-bottom: 18px;
  border: 1px solid color-mix(in srgb, var(--app-action-primary) 25%, var(--app-border-default));
  background: var(--app-action-primary-soft);
  overflow-wrap: anywhere;
}
.role-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  min-width: 0;
  margin-bottom: 18px;
}
.role-card {
  min-width: 0;
}
.role-card .admin-card-section {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 11px;
  align-items: center;
  min-width: 0;
}
.role-card div {
  min-width: 0;
}
.role-card strong,
.role-card span {
  display: block;
  overflow-wrap: anywhere;
}
.role-card span {
  margin-top: 3px;
  color: var(--app-text-secondary);
  font-size: 12px;
}
.search-card {
  margin-bottom: 18px;
}
.search-card .el-input {
  max-width: 520px;
}
.admin-cell {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.admin-cell > div {
  min-width: 0;
}
.admin-cell strong,
.admin-cell code {
  display: block;
  overflow-wrap: anywhere;
}
.admin-cell code {
  color: var(--app-text-secondary);
}
.table-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 3px;
}
.admin-dialog {
  width: min(580px, calc(100vw - 32px));
  max-width: 100%;
}
.admin-form {
  display: grid;
  gap: 14px;
  min-width: 0;
}
@media (max-width: 899px) {
  .role-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
@media (max-width: 599px) {
  .admin-dialog {
    width: 100%;
  }
}
</style>

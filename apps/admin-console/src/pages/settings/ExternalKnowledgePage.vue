<script setup lang="ts">
import { useAdminNotifier } from '@/composables/useAdminNotifier'
import { computed, onMounted, reactive, ref } from 'vue'
import type { ExternalKnowledgeSource, ExternalKnowledgeTarget, UserRecord } from '@/api/contracts'
import { adminRepository } from '@/api/repository'
import StatusBadge from '@/components/base/StatusBadge.vue'
import ConfirmActionDialog from '@/components/composite/ConfirmActionDialog.vue'
import PageHeader from '@/components/composite/PageHeader.vue'

interface OwnerMapping {
  ownerId: string
  staffId: string
}

const notifier = useAdminNotifier()
const sources = ref<ExternalKnowledgeSource[]>([])
const users = ref<UserRecord[]>([])
const loading = ref(false)
const saving = ref(false)
const testingId = ref<string | null>(null)
const syncingId = ref<string | null>(null)
const editorOpen = ref(false)
const selected = ref<ExternalKnowledgeSource | null>(null)
const actionSource = ref<ExternalKnowledgeSource | null>(null)
const actionKind = ref<'enable' | 'disable' | 'sync' | null>(null)
const form = reactive({
  name: '',
  appKey: '',
  secretRef: '',
  syncOwnerId: '',
  targets: [{ type: 'space', id: '' }] as ExternalKnowledgeTarget[],
  mappings: [{ ownerId: '', staffId: '' }] as OwnerMapping[],
})

const userOptions = computed(() =>
  users.value.map((user) => ({
    label: `${user.display_name} · ${user.id}`,
    value: user.id,
  })),
)
const validMappings = computed(() =>
  form.mappings.filter((item) => item.ownerId.trim() && item.staffId.trim()),
)
const validTargets = computed(() => form.targets.filter((item) => item.id.trim()))
const canSave = computed(() =>
  Boolean(
    form.name.trim() &&
    form.appKey.trim().length >= 3 &&
    (selected.value?.secret_configured || form.secretRef.trim().length >= 5) &&
    validTargets.value.length > 0 &&
    validMappings.value.length > 0 &&
    validMappings.value.some((item) => item.ownerId === form.syncOwnerId),
  ),
)
const actionDescription = computed(() => {
  if (!actionSource.value) return ''
  if (actionKind.value === 'sync')
    return `将“${actionSource.value.name}”授权范围内的在线页面增量同步到本地资料库。远端不可用时不会影响本地检索。`
  if (actionKind.value === 'enable')
    return `启用“${actionSource.value.name}”后，已映射用户的 AI 请求可在限定范围内查询乐享内容。`
  return `停用“${actionSource.value.name}”后，不再发起新的远端搜索或同步；已同步的本地资料仍然保留。`
})

onMounted(load)

async function load(): Promise<void> {
  loading.value = true
  try {
    ;[sources.value, users.value] = await Promise.all([
      adminRepository.externalKnowledgeSources(),
      adminRepository.users(),
    ])
  } catch (error) {
    notifier.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '外部知识源加载失败。',
    })
  } finally {
    loading.value = false
  }
}

function resetForm(): void {
  selected.value = null
  Object.assign(form, {
    name: '',
    appKey: '',
    secretRef: '',
    syncOwnerId: '',
    targets: [{ type: 'space', id: '' }],
    mappings: [{ ownerId: '', staffId: '' }],
  })
}

function openCreate(): void {
  resetForm()
  editorOpen.value = true
}

function openEdit(source: ExternalKnowledgeSource): void {
  selected.value = source
  Object.assign(form, {
    name: source.name,
    appKey: source.app_key,
    secretRef: '',
    syncOwnerId: source.sync_owner_id ?? '',
    targets: source.targets.map((target) => ({ ...target })),
    mappings: Object.entries(source.owner_staff_ids).map(([ownerId, staffId]) => ({
      ownerId,
      staffId,
    })),
  })
  editorOpen.value = true
}

function addTarget(): void {
  if (form.targets.length < 20) form.targets.push({ type: 'space', id: '' })
}

function removeTarget(index: number): void {
  if (form.targets.length > 1) form.targets.splice(index, 1)
}

function addMapping(): void {
  form.mappings.push({ ownerId: '', staffId: '' })
}

function removeMapping(index: number): void {
  if (form.mappings.length > 1) form.mappings.splice(index, 1)
}

function ownerStaffIds(): Record<string, string> {
  return Object.fromEntries(
    validMappings.value.map((item) => [item.ownerId.trim(), item.staffId.trim()]),
  )
}

async function save(): Promise<void> {
  if (!canSave.value) return
  saving.value = true
  try {
    if (selected.value) {
      await adminRepository.updateExternalKnowledgeSource(selected.value.id, {
        name: form.name.trim(),
        appKey: form.appKey.trim(),
        secretRef: form.secretRef.trim() || undefined,
        targets: validTargets.value.map((target) => ({ ...target, id: target.id.trim() })),
        ownerStaffIds: ownerStaffIds(),
        syncOwnerId: form.syncOwnerId,
        reason: '管理员更新乐享知识源配置',
      })
      await load()
    } else {
      await adminRepository.createExternalKnowledgeSource({
        name: form.name.trim(),
        appKey: form.appKey.trim(),
        secretRef: form.secretRef.trim(),
        targets: validTargets.value.map((target) => ({ ...target, id: target.id.trim() })),
        ownerStaffIds: ownerStaffIds(),
        syncOwnerId: form.syncOwnerId,
      })
      await load()
    }
    editorOpen.value = false
    notifier.notify({ type: 'positive', message: '外部知识源配置已保存；凭据值不会回显。' })
  } catch (error) {
    notifier.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '外部知识源保存失败。',
    })
  } finally {
    saving.value = false
  }
}

async function testSource(source: ExternalKnowledgeSource): Promise<void> {
  testingId.value = source.id
  try {
    const result = await adminRepository.testExternalKnowledgeSource(source.id)
    await load()
    notifier.notify({ type: result.passed ? 'positive' : 'warning', message: result.message })
  } catch (error) {
    notifier.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '连接测试失败。',
    })
  } finally {
    testingId.value = null
  }
}

function requestAction(source: ExternalKnowledgeSource, kind: 'enable' | 'disable' | 'sync'): void {
  actionSource.value = source
  actionKind.value = kind
}

async function confirmAction(reason: string): Promise<void> {
  const source = actionSource.value
  const kind = actionKind.value
  if (!source || !kind) return
  if (kind === 'sync') syncingId.value = source.id
  try {
    if (kind === 'sync') {
      await adminRepository.syncExternalKnowledgeSource(source.id, reason)
    } else {
      await adminRepository.updateExternalKnowledgeSource(source.id, {
        status: kind === 'enable' ? 'active' : 'disabled',
        reason,
      })
      await load()
    }
    notifier.notify({
      type: 'positive',
      message:
        kind === 'sync'
          ? '增量同步任务已进入 sync 队列。'
          : `知识源已${kind === 'enable' ? '启用' : '停用'}。`,
    })
  } catch (error) {
    notifier.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '操作失败。',
    })
  } finally {
    syncingId.value = null
    actionSource.value = null
    actionKind.value = null
  }
}

function formatTime(value: string | null): string {
  return value
    ? new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(
        new Date(value),
      )
    : '尚未执行'
}
</script>

<template>
  <section class="admin-page">
    <PageHeader
      title="外部知识库"
      description="连接腾讯乐享企业知识，按用户身份和明确授权范围检索。密钥仅保存引用；远端异常时自动降级为本地资料检索。"
      eyebrow="系统治理"
    >
      <template #actions
        ><admin-button
          unelevated
          color="primary"
          icon="add"
          label="添加乐享知识源"
          @click="openCreate"
      /></template>
    </PageHeader>

    <admin-banner rounded class="security-banner">
      <template #avatar><app-icon name="shield" color="primary" /></template>
      乐享查询始终携带映射后的真实成员
      ID，并限制在配置的团队、空间或条目范围内。远端内容视为不可信上下文，不会执行其中的指令。
    </admin-banner>

    <admin-inner-loading :showing="loading" label="正在加载外部知识源…" />
    <div v-if="sources.length" class="source-grid">
      <el-card
        v-for="source in sources"
        :key="source.id"
        flat
        bordered
        class="surface-card source-card"
      >
        <admin-card-section class="source-head">
          <div>
            <div class="source-title">
              <admin-avatar color="blue-1" text-color="primary" icon="corporate_fare" />
              <h2>{{ source.name }}</h2>
            </div>
            <p>{{ source.app_key }}</p>
          </div>
          <StatusBadge :status="source.status" />
        </admin-card-section>
        <el-divider />
        <admin-card-section class="source-details">
          <div>
            <span>授权范围</span><strong>{{ source.targets.length }} 个目标</strong>
          </div>
          <div>
            <span>成员映射</span
            ><strong>{{ Object.keys(source.owner_staff_ids).length }} 位用户</strong>
          </div>
          <div>
            <span>密钥引用</span
            ><strong>{{ source.secret_configured ? '已配置' : '未配置' }}</strong>
          </div>
          <div>
            <span>连接测试</span
            ><strong :class="source.last_test_passed ? 'tone-success' : 'tone-warning'">{{
              source.last_test_passed ? '已通过' : '未通过'
            }}</strong
            ><small>{{ formatTime(source.last_tested_at) }}</small>
          </div>
          <div>
            <span>最近同步</span><strong>{{ formatTime(source.last_synced_at) }}</strong
            ><small v-if="source.error_code" class="tone-danger">{{ source.error_code }}</small>
          </div>
        </admin-card-section>
        <admin-card-section class="scope-list">
          <admin-badge
            v-for="target in source.targets"
            :key="`${target.type}:${target.id}`"
            dense
            outline
            color="primary"
            :icon="
              target.type === 'team' ? 'groups' : target.type === 'space' ? 'folder' : 'description'
            "
            >{{ target.type }} · {{ target.id }}</admin-badge
          >
        </admin-card-section>
        <el-divider />
        <admin-card-actions class="source-actions">
          <admin-button flat color="primary" icon="edit" label="编辑" @click="openEdit(source)" />
          <admin-button
            outline
            color="primary"
            icon="science"
            label="连接测试"
            :loading="testingId === source.id"
            @click="testSource(source)"
          />
          <admin-button
            v-if="source.status === 'disabled'"
            outline
            color="positive"
            icon="play_circle"
            label="启用"
            :disable="!source.last_test_passed"
            @click="requestAction(source, 'enable')"
          />
          <admin-button
            v-else
            outline
            color="warning"
            icon="pause_circle"
            label="停用"
            @click="requestAction(source, 'disable')"
          />
          <admin-space />
          <admin-button
            unelevated
            color="primary"
            icon="sync"
            label="增量同步"
            :disable="source.status !== 'active'"
            :loading="syncingId === source.id"
            @click="requestAction(source, 'sync')"
          />
        </admin-card-actions>
      </el-card>
    </div>
    <el-card v-else-if="!loading" flat bordered class="surface-card empty-state"
      ><app-icon name="hub" />
      <h2>尚未连接外部知识库</h2>
      <p>添加乐享 AppKey、Secret 引用、授权范围和用户身份映射后，先运行连接测试再启用。</p>
      <admin-button
        unelevated
        color="primary"
        icon="add"
        label="添加乐享知识源"
        @click="openCreate"
    /></el-card>

    <admin-dialog v-model="editorOpen" width="min(920px, calc(100vw - 48px))" persistent>
      <el-card class="editor-dialog">
        <admin-toolbar
          ><admin-toolbar-title>{{ selected ? '编辑' : '添加' }}乐享知识源</admin-toolbar-title
          ><admin-button
            flat
            round
            dense
            icon="close"
            aria-label="关闭"
            @click="editorOpen = false"
        /></admin-toolbar>
        <el-divider />
        <admin-card-section class="editor-form">
          <admin-banner rounded class="security-banner"
            ><template #avatar><app-icon name="key" /></template>Secret 请填写部署环境中的引用，例如
            <code>env:LEXIANG_APP_SECRET</code
            >。页面和业务数据库均不保存或回显密钥明文。</admin-banner
          >
          <div class="two-column">
            <admin-input
              v-model.trim="form.name"
              outlined
              label="知识源名称"
              maxlength="120"
              counter
            /><admin-input
              v-model.trim="form.appKey"
              outlined
              label="乐享 AppKey"
              maxlength="255"
            />
          </div>
          <admin-input
            v-model.trim="form.secretRef"
            outlined
            autocomplete="off"
            :label="
              selected?.secret_configured ? '替换 Secret 引用（留空保持当前值）' : 'Secret 引用'
            "
            hint="只接受 Secret Provider 可解析的引用"
          />

          <section class="form-section">
            <div class="section-heading">
              <div>
                <h3>授权目标</h3>
                <p>至少 1 个、最多 20 个；只允许 team、space 或 kb_entry。</p>
              </div>
              <admin-button
                flat
                color="primary"
                icon="add"
                label="添加目标"
                :disable="form.targets.length >= 20"
                @click="addTarget"
              />
            </div>
            <div class="repeater">
              <div v-for="(target, index) in form.targets" :key="index" class="target-row">
                <admin-select
                  v-model="target.type"
                  outlined
                  emit-value
                  map-options
                  :options="[
                    { label: '团队', value: 'team' },
                    { label: '空间', value: 'space' },
                    { label: '知识条目', value: 'kb_entry' },
                  ]"
                  label="类型"
                /><admin-input
                  v-model.trim="target.id"
                  outlined
                  label="乐享目标 ID"
                  maxlength="180"
                /><admin-button
                  flat
                  round
                  color="negative"
                  icon="delete"
                  :disable="form.targets.length === 1"
                  :aria-label="`删除授权目标 ${index + 1}`"
                  @click="removeTarget(index)"
                />
              </div>
            </div>
          </section>

          <section class="form-section">
            <div class="section-heading">
              <div>
                <h3>用户身份映射</h3>
                <p>平台用户 ID 映射到乐享成员 Staff ID；查询权限以该成员为准。</p>
              </div>
              <admin-button
                flat
                color="primary"
                icon="person_add"
                label="添加映射"
                @click="addMapping"
              />
            </div>
            <div class="repeater">
              <div v-for="(mapping, index) in form.mappings" :key="index" class="mapping-row">
                <admin-select
                  v-model="mapping.ownerId"
                  outlined
                  use-input
                  fill-input
                  hide-selected
                  emit-value
                  map-options
                  input-debounce="0"
                  :options="userOptions"
                  label="平台用户"
                  new-value-mode="add-unique"
                /><admin-input
                  v-model.trim="mapping.staffId"
                  outlined
                  label="乐享 Staff ID"
                  maxlength="180"
                /><admin-button
                  flat
                  round
                  color="negative"
                  icon="delete"
                  :disable="form.mappings.length === 1"
                  :aria-label="`删除用户映射 ${index + 1}`"
                  @click="removeMapping(index)"
                />
              </div>
            </div>
          </section>

          <admin-select
            v-model="form.syncOwnerId"
            outlined
            emit-value
            map-options
            :options="validMappings.map((item) => ({ label: item.ownerId, value: item.ownerId }))"
            label="本地同步资料所有者"
            hint="在线页面会作为该用户的私有资料写入本地资料库"
          />
        </admin-card-section>
        <el-divider />
        <admin-card-actions align="right" class="editor-actions"
          ><admin-button flat label="取消" @click="editorOpen = false" /><admin-button
            unelevated
            color="primary"
            icon="save"
            label="保存配置"
            :disable="!canSave"
            :loading="saving"
            @click="save"
        /></admin-card-actions>
      </el-card>
    </admin-dialog>

    <ConfirmActionDialog
      :model-value="actionKind !== null"
      :title="
        actionKind === 'sync'
          ? '启动增量同步'
          : actionKind === 'enable'
            ? '启用外部知识源'
            : '停用外部知识源'
      "
      :description="actionDescription"
      :confirm-label="
        actionKind === 'sync' ? '确认同步' : actionKind === 'enable' ? '确认启用' : '确认停用'
      "
      :tone="actionKind === 'disable' ? 'warning' : 'primary'"
      require-reason
      @update:model-value="
        (value) => {
          if (!value) {
            actionKind = null
            actionSource = null
          }
        }
      "
      @confirm="confirmAction"
    />
  </section>
</template>

<style scoped lang="scss">
.security-banner {
  margin-bottom: 18px;
  border: 1px solid var(--app-border-default);
  background: var(--app-action-primary-soft);
  overflow-wrap: anywhere;
}
.source-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
  min-width: 0;
}
.source-grid > * {
  min-width: 0;
}
.source-card {
  display: flex;
  min-width: 0;
  flex-direction: column;
  overflow: clip;
}
.source-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  min-width: 0;
}
.source-head > div {
  min-width: 0;
}
.source-title {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.source-title h2 {
  min-width: 0;
  margin: 0;
  font-size: 19px;
  overflow-wrap: anywhere;
}
.source-head p {
  margin: 6px 0 0 52px;
  color: var(--app-text-secondary);
  overflow-wrap: anywhere;
}
.source-details {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  min-width: 0;
}
.source-details > div {
  display: grid;
  min-width: 0;
  gap: 3px;
}
.source-details span,
.source-details small {
  color: var(--app-text-secondary);
}
.source-details strong,
.source-details small {
  min-width: 0;
  overflow-wrap: anywhere;
}
.scope-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-width: 0;
  padding-top: 0;
}
.scope-list .el-tag {
  max-width: 100%;
  height: auto;
  min-height: 28px;
  white-space: normal;
  overflow-wrap: anywhere;
}
.source-actions {
  gap: 8px;
  min-width: 0;
  flex-wrap: wrap;
}
.empty-state {
  display: grid;
  justify-items: center;
  gap: 10px;
  min-width: 0;
  padding: 44px 20px;
  text-align: center;
}
.empty-state > .el-icon {
  color: var(--app-text-secondary);
  font-size: 52px;
}
.empty-state h2 {
  margin: 0;
  font-size: 20px;
}
.empty-state p {
  max-width: 620px;
  margin: 0 0 8px;
  color: var(--app-text-secondary);
  overflow-wrap: anywhere;
}
.editor-dialog {
  width: min(900px, calc(100vw - 32px));
  max-width: 100%;
  max-height: min(900px, calc(100dvh - 32px));
}
.editor-form {
  display: grid;
  gap: 18px;
  min-width: 0;
  overflow-y: auto;
}
.editor-form > .security-banner {
  margin-bottom: 0;
}
.two-column {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  min-width: 0;
}
.form-section {
  display: grid;
  gap: 12px;
  min-width: 0;
}
.section-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
}
.section-heading > div {
  min-width: 0;
}
.section-heading h3 {
  margin: 0;
  font-size: 17px;
}
.section-heading p {
  margin: 3px 0 0;
  color: var(--app-text-secondary);
  overflow-wrap: anywhere;
}
.repeater {
  display: grid;
  gap: 9px;
  min-width: 0;
}
.target-row,
.mapping-row {
  display: grid;
  grid-template-columns: minmax(150px, 0.45fr) minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
  min-width: 0;
}
.editor-actions {
  flex-wrap: wrap;
}
code {
  overflow-wrap: anywhere;
}

@media (max-width: 1023px) {
  .source-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
@media (max-width: 599px) {
  .source-details,
  .two-column {
    grid-template-columns: minmax(0, 1fr);
  }
  .target-row,
  .mapping-row {
    grid-template-columns: minmax(0, 1fr) auto;
  }
  .target-row > :nth-child(2),
  .mapping-row > :nth-child(2) {
    grid-column: 1 / -1;
    grid-row: 2;
  }
  .target-row > :last-child,
  .mapping-row > :last-child {
    grid-column: 2;
    grid-row: 1;
  }
  .editor-dialog {
    width: 100%;
    max-height: calc(100dvh - 48px);
  }
  .editor-actions .el-button {
    flex: 1 1 auto;
  }
}
</style>

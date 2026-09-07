<script setup lang="ts">
import { useAdminNotifier } from '@/composables/useAdminNotifier'
import { computed, onMounted, reactive, ref } from 'vue'
import type { ConfigStatus, OfficialSkill } from '@/api/contracts'
import { adminRepository } from '@/api/repository'
import StatusBadge from '@/components/base/StatusBadge.vue'
import ConfirmActionDialog from '@/components/composite/ConfirmActionDialog.vue'
import PageHeader from '@/components/composite/PageHeader.vue'
import { cloneData } from '@/utils/clone'

const notifier = useAdminNotifier()
const skills = ref<OfficialSkill[]>([])
const query = ref('')
const statusFilter = ref<ConfigStatus | 'all'>('all')
const editorOpen = ref(false)
const editorTab = ref<'content' | 'test'>('content')
const testing = ref(false)
const testInput = ref('请把这份行业趋势资料改写成面向企业管理者的公众号文章，保留所有可验证数据。')
const testOutput = ref('')
const publishConfirm = ref(false)
const disableConfirm = ref(false)

const form = reactive<OfficialSkill>({
  id: '',
  code: '',
  name: '',
  description: '',
  scenarios: [],
  instructions: '',
  version: 1,
  sort_order: 1,
  status: 'draft',
  enabled_users: 0,
  updated_at: '',
})

onMounted(async () => {
  try {
    skills.value = await adminRepository.skills()
  } catch (error) {
    notifier.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '官方技能加载失败。',
    })
  }
})

const filteredSkills = computed(() =>
  skills.value
    .filter((item) => statusFilter.value === 'all' || item.status === statusFilter.value)
    .filter(
      (item) =>
        !query.value.trim() ||
        `${item.name}${item.code}${item.description}${item.scenarios.join('')}`
          .toLowerCase()
          .includes(query.value.trim().toLowerCase()),
    )
    .sort((a, b) => a.sort_order - b.sort_order),
)

function now(): string {
  return new Date().toISOString()
}

function openCreate(): void {
  Object.assign(form, {
    id: crypto.randomUUID(),
    code: '',
    name: '',
    description: '',
    scenarios: [],
    instructions: '',
    version: 1,
    sort_order: skills.value.length + 1,
    status: 'draft',
    enabled_users: 0,
    updated_at: now(),
  })
  editorTab.value = 'content'
  testOutput.value = ''
  editorOpen.value = true
}

function openEditor(item: OfficialSkill): void {
  const next = cloneData(item)
  if (['published', 'disabled'].includes(item.status)) {
    next.version_id = undefined
    next.version += 1
    next.status = 'draft'
    next.updated_at = now()
  }
  Object.assign(form, next)
  editorTab.value = 'content'
  testOutput.value = ''
  editorOpen.value = true
}

async function saveDraft(): Promise<void> {
  if (!form.name.trim() || !form.code.trim() || !form.instructions.trim()) {
    notifier.notify({ type: 'warning', message: '请填写名称、唯一代码和写作要求。' })
    return
  }
  try {
    const exists = skills.value.some((skill) => skill.id === form.id)
    await adminRepository.saveSkill(form, exists)
    skills.value = await adminRepository.skills()
    const saved = skills.value.find((skill) => skill.code === form.code)
    if (saved) Object.assign(form, cloneData(saved))
    notifier.notify({ type: 'positive', message: '技能草稿已保存，用户端仍不可见。' })
  } catch (error) {
    notifier.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '技能草稿保存失败。',
    })
  }
}

async function runTest(): Promise<void> {
  if (!testInput.value.trim()) return
  await saveDraft()
  if (!form.version_id) return
  testing.value = true
  try {
    const result = await adminRepository.testSkill(form.version_id, testInput.value)
    skills.value = await adminRepository.skills()
    const tested = skills.value.find((skill) => skill.id === form.id)
    if (tested) Object.assign(form, cloneData(tested))
    testOutput.value = result.message
    notifier.notify({ type: result.passed ? 'positive' : 'warning', message: result.message })
  } catch (error) {
    notifier.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '技能测试失败。',
    })
  } finally {
    testing.value = false
  }
}

async function publish(): Promise<void> {
  if (form.status !== 'testing') return
  if (!form.version_id) return
  try {
    await adminRepository.publishSkill(form.version_id)
    skills.value = await adminRepository.skills()
    editorOpen.value = false
    notifier.notify({
      type: 'positive',
      message: `${form.name} v${form.version} 已发布，用户端官方技能库现在可见。`,
    })
  } catch (error) {
    notifier.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '技能发布失败。',
    })
  }
}

function requestDisable(item: OfficialSkill): void {
  Object.assign(form, cloneData(item))
  disableConfirm.value = true
}

async function disable(): Promise<void> {
  const item = skills.value.find((skill) => skill.id === form.id)
  if (!item) return
  try {
    await adminRepository.disableSkill(item.id)
    skills.value = await adminRepository.skills()
    notifier.notify({ type: 'positive', message: '技能已停用；历史任务和文章不受影响。' })
  } catch (error) {
    notifier.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '技能停用失败。',
    })
  }
}

async function restore(item: OfficialSkill): Promise<void> {
  try {
    await adminRepository.restoreSkill(item.id)
    skills.value = await adminRepository.skills()
    notifier.notify({ type: 'positive', message: '技能已恢复，用户可以再次启用和选择。' })
  } catch (error) {
    notifier.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '技能恢复失败。',
    })
  }
}

async function move(item: OfficialSkill, offset: number): Promise<void> {
  const ordered = [...skills.value].sort((a, b) => a.sort_order - b.sort_order)
  const index = ordered.findIndex((skill) => skill.id === item.id)
  const target = index + offset
  if (index < 0 || target < 0 || target >= ordered.length) return
  const targetItem = ordered[target]
  if (!targetItem) return
  const old = item.sort_order
  item.sort_order = targetItem.sort_order
  targetItem.sort_order = old
  try {
    await Promise.all([
      adminRepository.reorderSkill(item.id, item.sort_order),
      adminRepository.reorderSkill(targetItem.id, targetItem.sort_order),
    ])
    skills.value = await adminRepository.skills()
    notifier.notify({ message: '用户端技能排序已更新。' })
  } catch (error) {
    notifier.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '技能排序更新失败。',
    })
  }
}
</script>

<template>
  <section class="admin-page">
    <PageHeader
      title="官方技能库"
      description="维护平台提供的写作方法。草稿和测试版本对用户不可见；运行开始后固化技能版本，一次创作最多使用一个主技能。"
      eyebrow="AI 能力"
    >
      <template #actions
        ><admin-button
          unelevated
          color="primary"
          icon="add"
          label="新建官方技能"
          @click="openCreate"
      /></template>
    </PageHeader>

    <admin-banner rounded class="skill-policy"
      ><template #avatar><app-icon name="auto_awesome" color="primary" /></template
      >技能只能提供版本化写作指令、输入输出 Schema
      和允许工具策略，不能直接提交公众号草稿或正式发布。</admin-banner
    >

    <el-card flat bordered class="surface-card filter-card"
      ><admin-card-section class="filters"
        ><admin-input
          v-model="query"
          outlined
          dense
          clearable
          debounce="180"
          label="搜索名称、代码或场景"
          class="filter-query"
          ><template #prepend><app-icon name="search" /></template></admin-input
        ><admin-select
          v-model="statusFilter"
          outlined
          dense
          emit-value
          map-options
          :options="[
            { label: '全部状态', value: 'all' },
            { label: '草稿', value: 'draft' },
            { label: '测试中', value: 'testing' },
            { label: '已发布', value: 'published' },
            { label: '已停用', value: 'disabled' },
          ]"
          label="状态" /></admin-card-section
    ></el-card>

    <section v-if="filteredSkills.length" class="skill-grid">
      <el-card
        v-for="skill in filteredSkills"
        :key="skill.id"
        flat
        bordered
        class="surface-card skill-card"
      >
        <admin-card-section class="skill-card__head"
          ><div class="skill-icon"><app-icon name="auto_awesome" /></div>
          <div class="min-width-zero">
            <div class="skill-title">
              <h2>{{ skill.name }}</h2>
              <StatusBadge :status="skill.status" />
            </div>
            <code>{{ skill.code }}</code>
          </div>
          <div class="order-actions">
            <admin-button
              flat
              round
              dense
              icon="keyboard_arrow_up"
              aria-label="上移技能"
              :disable="skill.sort_order === 1"
              @click="move(skill, -1)"
            /><admin-button
              flat
              round
              dense
              icon="keyboard_arrow_down"
              aria-label="下移技能"
              :disable="skill.sort_order === skills.length"
              @click="move(skill, 1)"
            /></div
        ></admin-card-section>
        <admin-card-section class="skill-card__body"
          ><p>{{ skill.description }}</p>
          <div class="scenario-row">
            <admin-badge
              v-for="scenario in skill.scenarios"
              :key="scenario"
              dense
              color="grey-2"
              text-color="grey-9"
              >{{ scenario }}</admin-badge
            >
          </div>
          <div class="skill-meta">
            <span>v{{ skill.version }}</span
            ><span>排序 {{ skill.sort_order }}</span
            ><span>{{ skill.enabled_users.toLocaleString() }} 位用户已启用</span>
          </div></admin-card-section
        >
        <el-divider /><admin-card-actions class="skill-actions"
          ><admin-button
            flat
            no-caps
            icon="edit"
            :label="['published', 'disabled'].includes(skill.status) ? '创建新版本' : '编辑'"
            @click="openEditor(skill)"
          /><admin-button
            v-if="skill.status === 'published'"
            flat
            no-caps
            color="negative"
            icon="pause"
            label="停用"
            @click="requestDisable(skill)"
          /><admin-button
            v-if="skill.status === 'disabled'"
            flat
            no-caps
            color="positive"
            icon="play_arrow"
            label="恢复"
            @click="restore(skill)"
          /><admin-space /><admin-badge outline color="primary"
            >用户端排序 {{ skill.sort_order }}</admin-badge
          ></admin-card-actions
        >
      </el-card>
    </section>
    <el-card v-else flat bordered class="surface-card empty-state"
      ><app-icon name="search_off" size="44px" /><strong>没有符合条件的技能</strong
      ><span>清除筛选条件或创建一个新技能。</span></el-card
    >

    <admin-dialog v-model="editorOpen" width="min(760px, calc(100vw - 48px))" persistent>
      <el-card class="skill-editor">
        <admin-toolbar
          ><div class="min-width-zero">
            <admin-toolbar-title>{{ form.name || '新建官方技能' }}</admin-toolbar-title>
            <div class="editor-subtitle">
              {{ form.code || '尚未设置代码' }} · v{{ form.version }}
            </div>
          </div>
          <admin-button
            flat
            round
            dense
            icon="close"
            aria-label="关闭编辑器"
            @click="editorOpen = false"
        /></admin-toolbar>
        <el-divider />
        <admin-tabs
          v-model="editorTab"
          dense
          no-caps
          active-color="primary"
          indicator-color="primary"
          ><admin-tab name="content" icon="edit_note" label="技能内容" /><admin-tab
            name="test"
            icon="science"
            label="测试" /></admin-tabs
        ><el-divider />
        <div class="editor-scroll">
          <admin-tab-panels v-model="editorTab">
            <admin-tab-panel name="content" class="editor-form"
              ><div class="status-line">
                <StatusBadge :status="form.status" /><span>草稿状态下用户不可见</span>
              </div>
              <admin-input v-model.trim="form.name" outlined label="技能名称" /><admin-input
                v-model.trim="form.code"
                outlined
                label="唯一代码"
                :disable="
                  skills.some((item) => item.code === form.code && item.id !== form.id)
                " /><admin-input
                v-model="form.description"
                outlined
                type="textarea"
                autogrow
                label="简介"
                maxlength="240"
                counter /><admin-select
                v-model="form.scenarios"
                outlined
                multiple
                use-input
                use-chips
                new-value-mode="add-unique"
                label="适用场景" /><admin-input
                v-model="form.instructions"
                outlined
                type="textarea"
                autogrow
                label="写作要求"
                hint="不得包含公众号提交动作或超出允许工具策略的要求"
            /></admin-tab-panel>
            <admin-tab-panel name="test" class="editor-form"
              ><admin-input
                v-model="testInput"
                outlined
                type="textarea"
                autogrow
                label="测试要求"
              /><admin-button
                unelevated
                color="primary"
                icon="play_arrow"
                label="运行固定案例"
                :loading="testing"
                @click="runTest"
              /><el-card v-if="testOutput" flat bordered class="test-output"
                ><admin-card-section>{{ testOutput }}</admin-card-section></el-card
              ></admin-tab-panel
            >
          </admin-tab-panels>
        </div>
        <el-divider /><admin-card-actions class="editor-actions"
          ><admin-button flat icon="save" label="保存草稿" @click="saveDraft" /><admin-button
            flat
            icon="science"
            label="测试"
            @click="editorTab = 'test'" /><admin-space /><admin-button
            unelevated
            color="positive"
            icon="publish"
            label="发布"
            :disable="form.status !== 'testing'"
            @click="publishConfirm = true"
        /></admin-card-actions>
      </el-card>
    </admin-dialog>

    <ConfirmActionDialog
      v-model="publishConfirm"
      title="发布官方技能"
      :description="`发布 ${form.name} v${form.version} 后，技能会进入用户端官方技能库。新任务固化新版本，历史任务不变。`"
      confirm-label="确认发布"
      require-reason
      @confirm="publish"
    />
    <ConfirmActionDialog
      v-model="disableConfirm"
      title="停用官方技能"
      :description="`停用 ${form.name} 后，用户不能再新选此技能；历史文章、任务和已固化的运行快照不受影响。`"
      confirm-label="确认停用"
      tone="negative"
      require-reason
      @confirm="disable"
    />
  </section>
</template>

<style scoped lang="scss">
.skill-policy {
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
  grid-template-columns: minmax(220px, 1fr) minmax(160px, 220px);
  gap: 12px;
  min-width: 0;
}
.filter-query {
  min-width: 0;
}
.skill-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
  min-width: 0;
}
.skill-card {
  display: flex;
  min-width: 0;
  flex-direction: column;
}
.skill-card__head {
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr) auto;
  gap: 12px;
  min-width: 0;
  align-items: start;
}
.skill-icon {
  display: grid;
  place-items: center;
  width: 42px;
  aspect-ratio: 1;
  border-radius: 12px;
  background: var(--app-action-primary-soft);
  color: var(--app-action-primary);
}
.min-width-zero {
  min-width: 0;
}
.skill-title {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  min-width: 0;
}
.skill-title h2 {
  margin: 0;
  font-size: 18px;
  overflow-wrap: anywhere;
}
.skill-card code {
  display: block;
  margin-top: 4px;
  color: var(--app-text-secondary);
  overflow-wrap: anywhere;
}
.order-actions {
  display: flex;
}
.skill-card__body {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
}
.skill-card__body p {
  margin: 0 0 14px;
  color: var(--app-text-secondary);
  overflow-wrap: anywhere;
}
.scenario-row,
.skill-actions,
.editor-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  min-width: 0;
}
.skill-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: auto;
  padding-top: 14px;
  color: var(--app-text-secondary);
  font-size: 12px;
}
.empty-state {
  display: grid;
  justify-items: center;
  gap: 8px;
  padding: 48px 20px;
  color: var(--app-text-secondary);
  text-align: center;
}
.skill-editor {
  width: 100%;
  max-width: 100%;
  height: min(720px, calc(100dvh - 96px));
  min-width: 0;
  display: grid;
  grid-template-rows: auto auto auto auto minmax(0, 1fr) auto auto;
}
.editor-subtitle {
  padding-left: 12px;
  color: var(--app-text-secondary);
  font-size: 12px;
  overflow-wrap: anywhere;
}
.editor-scroll {
  min-width: 0;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
}
.editor-form {
  display: grid;
  gap: 15px;
  min-width: 0;
}
.editor-form :deep(.el-textarea__inner) {
  max-height: 320px;
  overflow-y: auto;
}
.status-line {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  color: var(--app-text-secondary);
  font-size: 12px;
}
.test-output {
  max-width: 100%;
  max-height: 300px;
  overflow-y: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

@media (max-width: 899px) {
  .skill-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
@media (max-width: 599px) {
  .filters {
    grid-template-columns: minmax(0, 1fr);
  }
  .skill-card__head {
    grid-template-columns: 42px minmax(0, 1fr);
  }
  .order-actions {
    grid-column: 2;
  }
  .editor-actions :deep(.el-button) {
    flex: 1 1 auto;
  }
}
</style>

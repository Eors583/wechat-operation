<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import { api } from '@/api/client'
import { queryClient } from '@/boot/query'
import { createDefaultStyles } from '@/api/styleDefaults'
import type { LayoutTemplate, ModuleKey, ModuleStyle, OfficialAccount } from '@/api/types'
import AppButton from '@/components/base/AppButton.vue'
import AppDialog from '@/components/base/AppDialog.vue'
import LockedContentEditor from '@/components/business/LockedContentEditor.vue'
import TemplateSourcePreview from '@/components/business/TemplateSourcePreview.vue'

const props = withDefaults(
  defineProps<{
    modelValue: boolean
    account?: OfficialAccount | null
    templates: LayoutTemplate[]
    hasMore?: boolean
    loadingMore?: boolean
    extractionEnabled?: boolean
  }>(),
  {
    hasMore: false,
    loadingMore: false,
    extractionEnabled: true,
  },
)
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; changed: []; 'load-more': [] }>()
const $q = useQuasar()

const localTemplates = ref<LayoutTemplate[]>([])
const selectedId = ref('')
const activeModule = ref<ModuleKey>('highlight')
const sourceUrl = ref('')
const extracting = ref(false)
const saving = ref(false)
const mobileStep = ref(1)
const previewMode = ref<'source' | 'styles'>('source')
const selectedBlockIds = ref<string[]>([])
const editedModules = ref<Record<string, ModuleKey[]>>({})
const lastSelectedBlockId = ref('')
const draftTemplateIds = new Set<string>()
const dirtyTemplateIds = new Set<string>()
const dirtyNameIds = new Set<string>()
const nameSaves = new Map<string, Promise<void>>()
const savingNameIds = ref(new Set<string>())
const notifiedFailedTemplateIds = new Set<string>()
let activeAccountId = ''
const templateAccountId = computed(() => props.account?.id ?? null)
const templateScopeKey = computed(() => templateAccountId.value ?? 'global')

const modules: { key: ModuleKey; label: string; count: number }[] = [
  { key: 'table_header', label: '表格表头', count: 1 },
  { key: 'table_cell', label: '表格单元格', count: 6 },
  { key: 'title', label: '文章标题', count: 1 },
  { key: 'lead', label: '导语', count: 1 },
  { key: 'heading_marker', label: '标题序号', count: 1 },
  { key: 'heading1', label: '一级标题', count: 4 },
  { key: 'heading2', label: '二级标题', count: 6 },
  { key: 'body', label: '正文', count: 18 },
  { key: 'highlight', label: '重点论点', count: 3 },
  { key: 'quote', label: '引用', count: 2 },
  { key: 'list', label: '列表', count: 2 },
  { key: 'caption', label: '图片说明', count: 4 },
  { key: 'divider', label: '分隔线', count: 3 },
]

const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value)) as T
watch(
  () => [templateScopeKey.value, props.templates] as const,
  ([scopeKey, value]) => {
    if (activeAccountId !== scopeKey) {
      activeAccountId = scopeKey
      localTemplates.value = clone(value)
      selectedId.value = value[0]?.id ?? ''
      draftTemplateIds.clear()
      dirtyTemplateIds.clear()
      dirtyNameIds.clear()
      notifiedFailedTemplateIds.clear()
      return
    }
    const incoming = clone(value)
    incoming.forEach((item) => {
      if (item.status === 'failed' && !notifiedFailedTemplateIds.has(item.id)) {
        notifiedFailedTemplateIds.add(item.id)
        $q.notify({ type: 'negative', message: `${item.name} 提取失败，请检查公众号文章链接。` })
      }
    })
    const drafts = localTemplates.value.filter((item) => draftTemplateIds.has(item.id))
    localTemplates.value = incoming
      .map((item) => {
        const local = localTemplates.value.find((candidate) => candidate.id === item.id)
        return local && (dirtyTemplateIds.has(item.id) || dirtyNameIds.has(item.id))
          ? {
              ...local,
              status: item.status,
              updatedAt: item.updatedAt,
              isDefault: item.isDefault,
              enabled: item.enabled,
              ...(!local.versionId && item.versionId
                ? {
                    versionId: item.versionId,
                    versionNo: item.versionNo,
                    sourceTitle: item.sourceTitle,
                    contentBlocks: item.contentBlocks,
                    sourcePreview: item.sourcePreview,
                  }
                : {}),
            }
          : item
      })
      .concat(drafts.filter((draft) => !incoming.some((item) => item.id === draft.id)))
    selectedId.value =
      selectedId.value && localTemplates.value.some((item) => item.id === selectedId.value)
        ? selectedId.value
        : (localTemplates.value[0]?.id ?? '')
  },
  { immediate: true, deep: true },
)

const selectedTemplate = computed(
  () => localTemplates.value.find((item) => item.id === selectedId.value) ?? null,
)
const sourceBlocks = computed(() => selectedTemplate.value?.contentBlocks ?? [])
const lockedGroups = computed(() => selectedTemplate.value?.lockedBlocks ?? [])
const editingLockedContent = ref(false)
const editingBlockIds = ref<string[]>([])
const editingTemplateId = ref('')
const editableBlocks = computed(() =>
  sourceBlocks.value.filter((block) => editingBlockIds.value.includes(block.id)),
)
const editLockedContent = (blockId: string) => {
  const group = lockedGroups.value.find((item) => item.blockIds.includes(blockId))
  if (!group || saving.value) return
  editingBlockIds.value = [...group.blockIds]
  editingTemplateId.value = selectedId.value
  editingLockedContent.value = true
}
const applyLockedContent = (blocks: NonNullable<LayoutTemplate['contentBlocks']>) => {
  if (!selectedTemplate.value || selectedId.value !== editingTemplateId.value || saving.value)
    return
  const edits = new Map(blocks.map((block) => [block.id, block]))
  selectedTemplate.value.contentBlocks = sourceBlocks.value.map(
    (block) => edits.get(block.id) ?? block,
  )
  markDirty()
}
watch([selectedId, templateScopeKey, () => props.modelValue], () => {
  editingLockedContent.value = false
})
let lockUndoRevision = 0
let dismissLockUndo: (() => void) | undefined
watch(
  [selectedId, templateScopeKey, () => props.modelValue, lockedGroups, saving],
  () => {
    lockUndoRevision++
    dismissLockUndo?.()
    dismissLockUndo = undefined
  },
  { deep: true, flush: 'sync' },
)
onBeforeUnmount(() => dismissLockUndo?.())
const lockedBlockIds = computed(
  () => new Set(lockedGroups.value.flatMap((group) => group.blockIds)),
)
const sourceStyles = computed(() => {
  const template = selectedTemplate.value
  return Object.fromEntries(
    (editedModules.value[selectedId.value] ?? []).map((key) => [key, template?.styles[key]]),
  ) as Partial<Record<ModuleKey, ModuleStyle>>
})
watch(
  selectedId,
  () => {
    selectedBlockIds.value = []
    lastSelectedBlockId.value = ''
    previewMode.value = 'source'
    sourceUrl.value = selectedTemplate.value?.sourceUrl ?? ''
  },
  { immediate: true },
)
watch(
  () => props.modelValue,
  (open) => {
    if (!open) return
    if (!props.account) {
      $q.notify({
        type: 'info',
        message:
          '当前是未绑定公众号的通用排版模板，可先验证样式；拿到公众号授权密钥后再绑定到具体公众号。',
      })
    }
    if (selectedTemplate.value?.extractionMode === 'deterministic_fallback') {
      $q.notify({
        type: 'warning',
        message:
          '本模板使用 HTML/DOM 基础提取结果，排版智能体未参与或调用失败；保存前请重点检查标题、引用和重点模块。',
      })
    }
  },
)
const activeStyle = computed(() => selectedTemplate.value?.styles[activeModule.value] ?? null)
const previewCopy = {
  title: '标题（对应标题样式）',
  lead: '导语（对应导语样式）：用一段简短说明帮助读者理解文章要解决的问题。',
  headingMarker: '01',
  heading1: '一级标题（对应一级标题样式）',
  body: '正文（对应正文样式）。内容宽度随阅读区域自适应，长中文段落与任意链接都能正常换行。',
  highlight: '重点论点（对应重点论点样式）',
  quote: '引用（对应引用样式）',
  heading2: '二级标题（对应二级标题样式）',
  list: '列表（对应列表样式）',
  listSecond: '保持层级清晰',
  caption: '图片说明（对应图片说明样式）',
} as const
const markDirty = () => {
  if (selectedTemplate.value) dirtyTemplateIds.add(selectedTemplate.value.id)
}
const markStyleDirty = () => {
  const keys = editedModules.value[selectedId.value] ?? []
  if (!keys.includes(activeModule.value))
    editedModules.value[selectedId.value] = [...keys, activeModule.value]
  markDirty()
}

const toggleSourceBlock = (id: string, extend: boolean) => {
  if (lockedBlockIds.value.has(id)) return
  const ids = sourceBlocks.value.map((block) => block.id)
  const start = ids.indexOf(lastSelectedBlockId.value)
  const end = ids.indexOf(id)
  if (extend && start >= 0 && end >= 0) {
    selectedBlockIds.value = [
      ...new Set([
        ...selectedBlockIds.value,
        ...ids
          .slice(Math.min(start, end), Math.max(start, end) + 1)
          .filter((key) => !lockedBlockIds.value.has(key)),
      ]),
    ]
  } else {
    selectedBlockIds.value = selectedBlockIds.value.includes(id)
      ? selectedBlockIds.value.filter((key) => key !== id)
      : [...selectedBlockIds.value, id]
  }
  lastSelectedBlockId.value = id
}

const notifyLockChange = (
  message: string,
  previous: NonNullable<LayoutTemplate['lockedBlocks']>,
) => {
  const templateId = selectedId.value
  const revision = lockUndoRevision
  dismissLockUndo = $q.notify({
    type: 'positive',
    message,
    timeout: 5000,
    actions: [
      {
        label: '撤销',
        color: 'white',
        handler: () => {
          const template = selectedTemplate.value
          if (
            !template ||
            template.id !== templateId ||
            revision !== lockUndoRevision ||
            saving.value
          )
            return
          template.lockedBlocks = previous
          const restoredLocks = new Set(previous.flatMap((group) => group.blockIds))
          selectedBlockIds.value = selectedBlockIds.value.filter((id) => !restoredLocks.has(id))
          markDirty()
        },
      },
    ],
  })
}

const lockSelection = (position: 'before_body' | 'after_body') => {
  const template = selectedTemplate.value
  if (!template || saving.value || lockedGroups.value.length >= 100) return
  const selected = new Set(selectedBlockIds.value)
  const blockIds = sourceBlocks.value
    .filter((block) => selected.has(block.id) && !lockedBlockIds.value.has(block.id))
    .map((block) => block.id)
  if (!blockIds.length) return
  const previous = clone(lockedGroups.value)
  template.lockedBlocks = [
    ...lockedGroups.value,
    {
      blockIds,
      position,
      paragraphIndex: 1,
    },
  ]
  selectedBlockIds.value = []
  markDirty()
  notifyLockChange(position === 'before_body' ? '已固定到开头。' : '已固定到结尾。', previous)
}

const unlockGroup = (index: number) => {
  if (!selectedTemplate.value || saving.value || !lockedGroups.value[index]) return
  const previous = clone(lockedGroups.value)
  selectedTemplate.value.lockedBlocks = lockedGroups.value.filter(
    (_, groupIndex) => groupIndex !== index,
  )
  markDirty()
  notifyLockChange('已解除固定。', previous)
}

const unlockSourceBlock = (blockId: string) =>
  unlockGroup(lockedGroups.value.findIndex((group) => group.blockIds.includes(blockId)))

const setStyle = <K extends keyof ModuleStyle>(key: K, value: ModuleStyle[K]) => {
  if (activeStyle.value) {
    activeStyle.value[key] = value
    markStyleDirty()
  }
}

const setBorder = (value: ModuleStyle['border']) => {
  if (!activeStyle.value) return
  activeStyle.value.border = value
  activeStyle.value.borderLeft = value === 'left' ? '4px solid #059669' : undefined
  markStyleDirty()
}

const moduleStyle = (key: ModuleKey) => {
  const style = selectedTemplate.value?.styles[key]
  if (!style) return {}
  return {
    color: style.color,
    background: style.background,
    fontSize: `${style.fontSize}px`,
    fontWeight: style.fontWeight,
    textAlign: style.align,
    lineHeight: style.lineHeight,
    marginTop: `${style.marginTop ?? 0}px`,
    marginBottom: `${style.spacing}px`,
    textIndent: `${style.textIndent ?? 0}px`,
    padding: `${style.padding}px`,
    border: style.borderAll,
    borderLeft:
      style.borderLeft ||
      (style.border === 'left' ? '4px solid var(--app-action-primary)' : undefined),
  }
}

const addTemplate = () => {
  const base = selectedTemplate.value ?? localTemplates.value[0]
  const template: LayoutTemplate = base
    ? clone(base)
    : {
        id: `template_${crypto.randomUUID()}`,
        accountId: templateAccountId.value,
        name: '新模板 1',
        enabled: true,
        sourceUrl: '',
        status: 'idle',
        updatedAt: new Date().toISOString(),
        sourcePreview: [],
        extractionMode: 'manual',
        styles: createDefaultStyles(),
      }
  if (base) {
    template.id = `template_${crypto.randomUUID()}`
    template.name = `新模板 ${localTemplates.value.length + 1}`
    template.enabled = true
    template.isDefault = false
    template.sourceUrl = ''
    template.status = 'idle'
    template.updatedAt = new Date().toISOString()
    template.sourcePreview = []
    template.sourceTitle = ''
    template.contentBlocks = []
    template.lockedBlocks = []
    template.versionNo = undefined
    template.versionId = undefined
    template.extractionMode = 'manual'
  }
  localTemplates.value.push(template)
  draftTemplateIds.add(template.id)
  dirtyTemplateIds.add(template.id)
  selectedId.value = template.id
}

const extract = async () => {
  extracting.value = true
  try {
    const template = await api.extractTemplate(templateAccountId.value, sourceUrl.value.trim())
    localTemplates.value.push(template)
    selectedId.value = template.id
    emit('changed')
    $q.notify({
      type: template.status === 'ready' ? 'positive' : 'info',
      message:
        template.status !== 'ready'
          ? '模板已提交提取，完成后会自动更新状态。'
          : template.extractionMode === 'agent'
            ? '排版智能体已完成模板学习，可以继续调整样式。'
            : '已使用基础样式提取完成；排版智能体不可用，可以继续手动调整。',
    })
  } catch (error) {
    $q.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '模板提取失败，请检查链接。',
    })
  } finally {
    extracting.value = false
  }
}

const save = async (makeDefault = false) => {
  const target = selectedTemplate.value
  if (!target) return
  await nameSaves.get(target.id)
  if (selectedId.value !== target.id) return
  if (!selectedTemplate.value || !selectedTemplate.value.name.trim() || saving.value) return
  saving.value = true
  try {
    if (makeDefault && !dirtyTemplateIds.has(selectedTemplate.value.id)) {
      const id = selectedTemplate.value.id
      await api.setDefaultTemplate(id)
      localTemplates.value.forEach((item) => {
        item.isDefault = item.id === id
      })
      await queryClient.invalidateQueries({ queryKey: ['templates'] })
      emit('changed')
      $q.notify({ type: 'positive', message: '已设为默认模板。' })
      return
    }
    selectedTemplate.value.name = selectedTemplate.value.name.trim()
    const previousId = selectedTemplate.value.id
    const saved = await api.saveTemplate(selectedTemplate.value, makeDefault)
    if (makeDefault)
      localTemplates.value.forEach((item) => {
        item.isDefault = false
      })
    const index = localTemplates.value.findIndex((item) => item.id === previousId)
    if (index >= 0) localTemplates.value[index] = saved
    selectedId.value = saved.id
    draftTemplateIds.delete(previousId)
    dirtyTemplateIds.delete(previousId)
    dirtyNameIds.delete(previousId)
    $q.notify({ type: 'positive', message: makeDefault ? '已设为默认模板。' : '模板已保存。' })
    await queryClient.invalidateQueries({ queryKey: ['templates'] })
    emit('changed')
  } catch (error) {
    $q.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '模板保存失败。',
    })
  } finally {
    saving.value = false
  }
}

const setDefault = (template: LayoutTemplate) => {
  if (saving.value || template.isDefault || !props.account) return
  selectedId.value = template.id
  void save(true)
}

const saveName = (template: LayoutTemplate) => {
  if (!template || nameSaves.has(template.id) || !dirtyNameIds.has(template.id)) return
  const name = template.name.trim()
  if (!name) {
    $q.notify({ type: 'negative', message: '模板名称不能为空。' })
    return
  }
  const id = template.id
  if (props.templates.find((item) => item.id === id)?.name === name) {
    template.name = name
    dirtyNameIds.delete(id)
    return
  }
  const scope = templateScopeKey.value
  template.name = name
  savingNameIds.value.add(id)
  const pending = (async () => {
    try {
      // New local templates need creation first; existing templates only patch their name.
      const created = draftTemplateIds.has(id)
        ? await api.saveTemplate(clone(template))
        : (await api.renameTemplate(id, name), null)
      if (templateScopeKey.value === scope) {
        const local = localTemplates.value.find((item) => item.id === id)
        if (local && created) {
          local.id = created.id
          local.status = created.status
          local.versionNo = created.versionNo
          local.versionId = created.versionId
          draftTemplateIds.delete(id)
          if (dirtyTemplateIds.delete(id)) dirtyTemplateIds.add(created.id)
          if (selectedId.value === id) selectedId.value = created.id
        }
        dirtyNameIds.delete(id)
      }
      await queryClient.invalidateQueries({ queryKey: ['templates'] })
      emit('changed')
    } catch (error) {
      $q.notify({
        type: 'negative',
        message: error instanceof Error ? error.message : '名称保存失败，请重试。',
      })
    } finally {
      nameSaves.delete(id)
      savingNameIds.value.delete(id)
    }
  })()
  nameSaves.set(id, pending)
}

const rename = (template: LayoutTemplate) => {
  if (saving.value || nameSaves.has(template.id)) return
  const scope = templateScopeKey.value
  $q.dialog({
    title: '重命名模板',
    prompt: {
      model: template.name,
      type: 'text',
      maxlength: 80,
      isValid: (value) => Boolean(String(value).trim()),
    },
    cancel: true,
  }).onOk((value: string) => {
    if (scope !== templateScopeKey.value || saving.value || nameSaves.has(template.id)) return
    const target = localTemplates.value.find((item) => item.id === template.id)
    if (!target || !value.trim()) return
    target.name = value.trim()
    dirtyNameIds.add(target.id)
    saveName(target)
  })
}

const remove = async (target: LayoutTemplate) => {
  if (saving.value || nameSaves.has(target.id) || localTemplates.value.length <= 1) return
  const removedId = target.id
  const isDraft = draftTemplateIds.has(removedId)
  saving.value = true
  try {
    if (!isDraft) await api.deleteTemplate(removedId)
    localTemplates.value = localTemplates.value.filter((item) => item.id !== removedId)
    if (selectedId.value === removedId) selectedId.value = localTemplates.value[0]?.id ?? ''
    draftTemplateIds.delete(removedId)
    dirtyTemplateIds.delete(removedId)
    dirtyNameIds.delete(removedId)
    if (!isDraft) {
      await queryClient.invalidateQueries({ queryKey: ['templates'] })
      emit('changed')
    }
  } catch (error) {
    $q.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '模板删除失败。',
    })
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <AppDialog
    :model-value="modelValue"
    title="文章排版设置"
    width="96vw"
    :persistent="saving || extracting || savingNameIds.size > 0"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <div class="template-editor">
      <section v-if="extractionEnabled" class="template-editor__extract">
        <q-input
          v-model="sourceUrl"
          outlined
          dense
          placeholder="请填写文章链接用于提取模板"
          aria-label="微信公众号文章链接"
        />
        <AppButton
          label="提取模板"
          :loading="extracting"
          :disabled="!sourceUrl.trim()"
          @click="extract"
        />
        <q-chip
          v-if="selectedTemplate?.status === 'ready'"
          color="positive"
          text-color="white"
          icon="check"
          >提取完成</q-chip
        >
        <q-chip
          v-else-if="selectedTemplate?.status === 'extracting'"
          color="warning"
          text-color="white"
          icon="hourglass_top"
          >提取中</q-chip
        >
        <q-chip
          v-else-if="selectedTemplate?.status === 'failed'"
          color="negative"
          text-color="white"
          icon="error_outline"
          >提取失败</q-chip
        >
      </section>
      <q-banner v-else rounded class="template-editor__extract-disabled"
        >链接提取模板功能当前已停用；仍可新建模板并手动调整全部样式模块。</q-banner
      >
      <q-tabs
        v-if="$q.screen.lt.md"
        v-model="mobileStep"
        class="template-editor__steps"
        dense
        active-color="primary"
        indicator-color="primary"
        align="justify"
      >
        <q-tab :name="1" label="模板" /><q-tab :name="2" label="模块" /><q-tab
          :name="3"
          label="样式"
        /><q-tab :name="4" label="预览" />
      </q-tabs>

      <div class="template-editor__grid">
        <section
          v-show="!$q.screen.lt.md || mobileStep === 1"
          class="template-editor__pane template-editor__templates"
        >
          <h3>排版模板</h3>
          <AppButton
            variant="outline"
            icon="add"
            label="新增模板"
            full-width
            @click="addTemplate"
          />
          <div class="template-editor__list">
            <div
              v-for="template in localTemplates"
              :key="template.id"
              class="template-editor__item"
              :class="{ active: selectedId === template.id }"
            >
              <button
                class="template-editor__select"
                @click="selectedId = template.id"
                @dblclick="rename(template)"
                :title="template.name"
              >
                <span>{{ template.name }}</span>
                <q-badge v-if="template.isDefault" color="primary" label="默认" />
              </button>
              <q-btn
                flat
                round
                dense
                icon="more_horiz"
                :aria-label="template.name + '的更多操作'"
                :disable="saving || savingNameIds.has(template.id)"
              >
                <q-menu>
                  <q-list>
                    <q-item
                      clickable
                      v-close-popup
                      :disable="
                        saving ||
                        template.isDefault ||
                        !account ||
                        !template.name.trim() ||
                        (!template.versionId && !draftTemplateIds.has(template.id))
                      "
                      @click="setDefault(template)"
                    >
                      <q-item-section>{{
                        template.isDefault ? '默认模板' : '设为默认模板'
                      }}</q-item-section>
                    </q-item>
                    <q-item clickable v-close-popup @click="rename(template)">
                      <q-item-section>重命名</q-item-section>
                    </q-item>
                    <q-item
                      clickable
                      v-close-popup
                      :disable="localTemplates.length <= 1"
                      @click="remove(template)"
                    >
                      <q-item-section>删除</q-item-section>
                    </q-item>
                  </q-list>
                </q-menu>
              </q-btn>
            </div>
          </div>
          <AppButton
            v-if="hasMore"
            variant="ghost"
            label="加载更多模板"
            :loading="loadingMore"
            full-width
            @click="emit('load-more')"
          />
        </section>

        <section
          v-show="!$q.screen.lt.md || mobileStep === 2"
          class="template-editor__pane template-editor__modules"
        >
          <h3>文章模块</h3>
          <button
            v-for="module in modules"
            :key="module.key"
            :class="{ active: activeModule === module.key }"
            @click="activeModule = module.key"
          >
            <span>{{ module.label }}</span
            ><small>{{ module.count }}</small>
          </button>
        </section>

        <section
          v-show="!$q.screen.lt.md || mobileStep === 3"
          class="template-editor__pane template-editor__settings"
        >
          <h3>{{ modules.find((item) => item.key === activeModule)?.label }}样式</h3>
          <template v-if="activeStyle">
            <q-toggle
              v-if="activeModule === 'heading_marker'"
              :model-value="activeStyle.enabled ?? false"
              color="primary"
              label="显示标题前序号标识"
              @update:model-value="setStyle('enabled', Boolean($event))"
            />
            <label
              >字号<q-slider
                :model-value="activeStyle.fontSize"
                :min="12"
                :max="40"
                label
                @update:model-value="setStyle('fontSize', Number($event))"
            /></label>
            <q-select
              :model-value="activeStyle.fontWeight"
              outlined
              dense
              label="字重"
              :options="['400', '500', '600', '700']"
              @update:model-value="setStyle('fontWeight', $event)"
            />
            <label class="color-field"
              >文字颜色<input
                :value="activeStyle.color"
                type="color"
                @input="setStyle('color', ($event.target as HTMLInputElement).value)"
              /><code>{{ activeStyle.color }}</code></label
            >
            <label class="color-field"
              >背景颜色<input
                :value="activeStyle.background"
                type="color"
                @input="setStyle('background', ($event.target as HTMLInputElement).value)"
              /><code>{{ activeStyle.background }}</code></label
            >
            <q-select
              :model-value="activeStyle.align"
              outlined
              dense
              label="对齐"
              :options="['left', 'center', 'right', 'justify']"
              @update:model-value="setStyle('align', $event)"
            />
            <label
              >行距<q-slider
                :model-value="activeStyle.lineHeight"
                :min="1"
                :max="2.5"
                :step="0.1"
                label
                @update:model-value="setStyle('lineHeight', Number($event))"
            /></label>
            <label
              >上间距<q-slider
                :model-value="activeStyle.marginTop ?? 0"
                :min="0"
                :max="48"
                label
                @update:model-value="setStyle('marginTop', Number($event))"
            /></label>
            <label
              >下间距<q-slider
                :model-value="activeStyle.spacing"
                :min="0"
                :max="48"
                label
                @update:model-value="setStyle('spacing', Number($event))"
            /></label>
            <label
              >首行缩进<q-slider
                :model-value="activeStyle.textIndent ?? 0"
                :min="0"
                :max="48"
                label
                @update:model-value="setStyle('textIndent', Number($event))"
            /></label>
            <label
              >内边距<q-slider
                :model-value="activeStyle.padding"
                :min="0"
                :max="32"
                label
                @update:model-value="setStyle('padding', Number($event))"
            /></label>
            <q-select
              v-if="!activeModule.startsWith('table_')"
              :model-value="activeStyle.border"
              outlined
              dense
              emit-value
              map-options
              label="左边框"
              :options="[
                { label: '无', value: 'none' },
                { label: '显示', value: 'left' },
              ]"
              @update:model-value="setBorder($event)"
            />
            <q-select
              v-else
              :model-value="activeStyle.borderAll"
              label="表格边框"
              outlined
              dense
              :options="[
                'none',
                '1px solid #d1d5db',
                '1px solid #059669',
                '2px solid #25322c',
                '1px dashed #d1d5db',
              ]"
              @update:model-value="setStyle('borderAll', $event)"
            />
          </template>
        </section>

        <section
          v-show="!$q.screen.lt.md || mobileStep === 4"
          class="template-editor__pane template-editor__preview"
        >
          <q-tabs
            v-model="previewMode"
            dense
            active-color="primary"
            indicator-color="primary"
            align="left"
            class="template-editor__preview-tabs"
          >
            <q-tab name="source" label="完整原文与固定部分" />
            <q-tab name="styles" label="正文排版样式预览" />
          </q-tabs>
          <template v-if="previewMode === 'source'">
            <div v-if="sourceBlocks.length" class="template-editor__source">
              <TemplateSourcePreview
                :key="selectedId"
                :blocks="sourceBlocks"
                :title="selectedTemplate?.sourceTitle"
                :source-url="selectedTemplate?.sourceUrl"
                :selected-ids="selectedBlockIds"
                :locked-groups="lockedGroups"
                :edited-styles="sourceStyles"
                :can-lock="!saving && lockedGroups.length < 100"
                :busy="saving"
                @toggle="toggleSourceBlock"
                @lock="lockSelection"
                @unlock="unlockSourceBlock"
                @edit="editLockedContent"
                @clear="selectedBlockIds = []"
                @select="
                  (ids, endId) => {
                    selectedBlockIds = ids
                    lastSelectedBlockId = endId
                  }
                "
              />
            </div>
            <q-banner v-else rounded class="template-editor__source-empty">
              <template v-if="selectedTemplate?.status === 'extracting'"
                >正在提取完整文章，完成后可选择固定部分。</template
              >
              <template v-else-if="selectedTemplate?.sourceUrl"
                >此模板尚无完整原文，请用上方原链接重新提取。已有排版样式仍可编辑。</template
              >
              <template v-else
                >提取文章后可预览全文并锁定一个或多个部分；也可切换到正文排版样式预览。</template
              >
            </q-banner>
          </template>
          <div v-else class="template-editor__sample">
            <div class="template-editor__paper">
              <h1 :style="moduleStyle('title')">
                {{ previewCopy.title }}
              </h1>
              <p :style="moduleStyle('lead')">
                {{ previewCopy.lead }}
              </p>
              <p
                v-if="selectedTemplate?.styles.heading_marker.enabled"
                class="template-editor__marker"
                :style="moduleStyle('heading_marker')"
              >
                {{ previewCopy.headingMarker }}
              </p>
              <h2 :style="moduleStyle('heading1')">
                {{ previewCopy.heading1 }}
              </h2>
              <p :style="moduleStyle('body')">
                {{ previewCopy.body }}
              </p>
              <p :style="moduleStyle('highlight')">
                {{ previewCopy.highlight }}
              </p>
              <blockquote :style="moduleStyle('quote')">
                {{ previewCopy.quote }}
              </blockquote>
              <h3 :style="moduleStyle('heading2')">
                {{ previewCopy.heading2 }}
              </h3>
              <ul :style="moduleStyle('list')">
                <li>{{ previewCopy.list }}</li>
                <li>{{ previewCopy.listSecond }}</li>
              </ul>
              <div class="template-editor__image"><q-icon name="image" size="42px" /></div>
              <p :style="moduleStyle('caption')">
                {{ previewCopy.caption }}
              </p>
              <hr :style="moduleStyle('divider')" />
              <div class="template-editor__table-wrap" aria-label="表格样式预览">
                <table>
                  <thead>
                    <tr>
                      <th
                        v-for="label in ['方案', '特点', '适用场景']"
                        :key="label"
                        :style="moduleStyle('table_header')"
                      >
                        {{ label }}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="(row, index) in [
                        ['方案 A', '信息清晰，方便对比', '知识科普文章'],
                        ['方案 B', '突出数据与结论', '行业分析文章'],
                      ]"
                      :key="index"
                    >
                      <td v-for="(cell, col) in row" :key="col" :style="moduleStyle('table_cell')">
                        {{ cell }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </section>
      </div>

      <div v-if="$q.screen.lt.md" class="template-editor__mobile-actions">
        <AppButton
          variant="outline"
          label="上一步"
          :disabled="mobileStep === 1"
          @click="mobileStep--"
        />
        <AppButton label="下一步" :disabled="mobileStep === 4" @click="mobileStep++" />
      </div>
    </div>
    <template #actions>
      <AppButton variant="ghost" label="取消" @click="$emit('update:modelValue', false)" />
      <AppButton variant="outline" label="查看整体结果" @click="mobileStep = 4" />
      <AppButton
        label="保存模板"
        :loading="saving"
        :disabled="!selectedTemplate || !selectedTemplate.name.trim()"
        @click="save()"
      />
    </template>
  </AppDialog>
  <LockedContentEditor
    v-model="editingLockedContent"
    :blocks="editableBlocks"
    @apply="applyLockedContent"
  />
</template>

<style scoped lang="scss">
.template-editor__table-wrap {
  min-width: 0;
  max-width: 100%;
  overflow-x: auto;
  table {
    width: 100%;
    min-width: 30rem;
    border-collapse: collapse;
    table-layout: fixed;
  }
  td,
  th {
    vertical-align: top;
    overflow-wrap: anywhere;
  }
}
.template-editor {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  min-width: 0;
  min-height: 0;
  height: min(74vh, 820px);

  &__extract {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto auto;
    align-items: center;
    gap: 12px;
    min-width: 0;
    padding: 14px 18px;
    border-bottom: 1px solid var(--app-border-default);
  }

  &__extract-disabled {
    color: var(--app-text-secondary);
    background: var(--app-bg-subtle);
    overflow-wrap: anywhere;
  }

  &__steps {
    border-bottom: 1px solid var(--app-border-default);
  }

  &__grid {
    display: grid;
    grid-template-columns: minmax(0, 0.8fr) minmax(0, 0.75fr) minmax(0, 0.9fr) minmax(0, 2.4fr);
    min-width: 0;
    min-height: 0;
  }

  &__pane {
    min-width: 0;
    min-height: 0;
    padding: 16px;
    overflow-y: auto;
    border-right: 1px solid var(--app-border-default);

    &:last-child {
      border-right: 0;
    }
    h3 {
      margin: 0 0 14px;
      font-size: 17px;
      overflow-wrap: anywhere;
    }
  }

  &__list {
    display: grid;
    gap: 6px;
    margin-top: 12px;

    .template-editor__select {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      min-width: 0;
      padding: 10px 12px;
      flex: 1;
      color: inherit;
      background: transparent;
      border: 0;
      border-radius: 8px;
      cursor: pointer;

      span {
        min-width: 0;
        overflow-wrap: anywhere;
        text-align: left;
      }
    }
  }

  &__item {
    display: flex;
    align-items: center;
    min-width: 0;
    color: var(--app-text-primary);
    border-radius: 8px;

    &.active {
      color: var(--app-action-primary);
      background: var(--app-action-soft);
    }

    > .q-btn {
      flex: 0 0 auto;
    }
  }

  &__templates > .app-button:last-child {
    margin-top: 12px;
  }

  &__modules {
    button {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      width: 100%;
      min-width: 0;
      padding: 12px;
      color: var(--app-text-primary);
      background: transparent;
      border: 0;
      border-bottom: 1px solid var(--app-border-default);
      cursor: pointer;

      &.active {
        color: var(--app-action-primary);
        background: var(--app-action-soft);
      }
      small {
        color: var(--app-text-muted);
      }
    }
  }

  &__settings {
    display: grid;
    align-content: start;
    gap: 14px;

    label {
      min-width: 0;
      color: var(--app-text-secondary);
    }
  }

  .color-field {
    display: grid;
    grid-template-columns: 1fr 36px auto;
    align-items: center;
    gap: 8px;

    input {
      width: 36px;
      height: 32px;
      padding: 0;
      border: 1px solid var(--app-border-default);
      border-radius: 6px;
    }
    code {
      min-width: 0;
      color: var(--app-text-primary);
      overflow-wrap: anywhere;
    }
  }

  &__preview {
    display: flex;
    flex-direction: column;
    background: var(--app-bg-subtle);
  }

  &__preview-tabs {
    flex: 0 0 auto;
    min-width: 0;
    margin-bottom: 12px;
  }

  &__source {
    display: flex;
    flex: 1 1 auto;
    flex-direction: column;
    gap: 12px;
    min-width: 0;
    min-height: 0;

    > .template-source-preview {
      flex: 1 1 auto;
      min-height: 16rem;
    }
  }

  &__source-empty {
    flex: 0 0 auto;
    min-width: 0;
    margin: 0;
    color: var(--app-text-secondary);
    overflow-wrap: anywhere;
    font-size: 12px;
  }

  &__sample {
    flex: 1 1 auto;
    min-width: 0;
    min-height: 0;
    overflow-y: auto;
  }

  &__paper {
    width: min(100%, 680px);
    min-width: 0;
    margin-inline: auto;
    padding: clamp(22px, 4vw, 44px);
    overflow-wrap: anywhere;
    background: var(--app-bg-surface);
    border: 1px solid var(--app-border-default);
    border-radius: 10px;

    h1 {
      margin-top: 0;
    }
    blockquote {
      margin-inline: 0;
    }
    hr {
      max-width: 100%;
    }
  }

  &__marker {
    overflow-wrap: anywhere;
  }

  &__image {
    display: grid;
    place-items: center;
    min-height: 140px;
    color: var(--app-text-muted);
    background: var(--app-bg-subtle);
    border-radius: 8px;
  }

  &__mobile-actions {
    display: flex;
    justify-content: space-between;
    gap: 12px;
    padding: 10px 16px;
    border-top: 1px solid var(--app-border-default);
  }
}

@media (max-width: 1023px) {
  .template-editor {
    grid-template-rows: auto auto minmax(0, 1fr) auto;

    &__grid {
      display: block;
    }
    &__pane {
      height: 100%;
      border-right: 0;
    }
  }
}

@media (max-width: 599px) {
  .template-editor {
    height: 72dvh;

    &__extract {
      grid-template-columns: minmax(0, 1fr) auto;
      padding: 10px;

      .q-chip {
        display: none;
      }
    }
  }
}
</style>

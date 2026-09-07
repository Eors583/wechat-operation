<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import { api } from '@/api/client'
import { createDefaultStyles } from '@/api/styleDefaults'
import type { LayoutTemplate, ModuleKey, ModuleStyle, OfficialAccount } from '@/api/types'
import AppButton from '@/components/base/AppButton.vue'
import AppDialog from '@/components/base/AppDialog.vue'

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
const togglingIds = ref(new Set<string>())
const mobileStep = ref(1)
const draftTemplateIds = new Set<string>()
const dirtyTemplateIds = new Set<string>()
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
        return local && dirtyTemplateIds.has(item.id)
          ? { ...local, status: item.status, updatedAt: item.updatedAt }
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

const setStyle = <K extends keyof ModuleStyle>(key: K, value: ModuleStyle[K]) => {
  if (activeStyle.value) {
    activeStyle.value[key] = value
    markDirty()
  }
}

const setBorder = (value: ModuleStyle['border']) => {
  if (!activeStyle.value) return
  activeStyle.value.border = value
  activeStyle.value.borderLeft = value === 'left' ? '4px solid #059669' : undefined
  markDirty()
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
        enabled: false,
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
    template.enabled = false
    template.sourceUrl = ''
    template.status = 'idle'
    template.updatedAt = new Date().toISOString()
    template.sourcePreview = []
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

const toggleEnabled = async (template: LayoutTemplate, enabled: boolean) => {
  const previous = template.enabled
  template.enabled = enabled
  dirtyTemplateIds.add(template.id)
  if (draftTemplateIds.has(template.id)) {
    selectedId.value = template.id
    return
  }
  togglingIds.value.add(template.id)
  try {
    const saved = await api.saveTemplate(template)
    const index = localTemplates.value.findIndex((item) => item.id === template.id)
    if (index >= 0) localTemplates.value[index] = saved
    dirtyTemplateIds.delete(template.id)
    emit('changed')
  } catch (error) {
    template.enabled = previous
    $q.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '模板启停状态没有保存。',
    })
  } finally {
    togglingIds.value.delete(template.id)
  }
}

const save = async () => {
  if (!selectedTemplate.value || !selectedTemplate.value.name.trim()) return
  saving.value = true
  try {
    selectedTemplate.value.name = selectedTemplate.value.name.trim()
    const previousId = selectedTemplate.value.id
    const saved = await api.saveTemplate(selectedTemplate.value)
    const index = localTemplates.value.findIndex((item) => item.id === previousId)
    if (index >= 0) localTemplates.value[index] = saved
    selectedId.value = saved.id
    draftTemplateIds.delete(previousId)
    dirtyTemplateIds.delete(previousId)
    $q.notify({ type: 'positive', message: '模板已保存。' })
    emit('changed')
  } finally {
    saving.value = false
  }
}

const remove = async () => {
  if (!selectedTemplate.value || localTemplates.value.length === 1) return
  const removedId = selectedTemplate.value.id
  const isDraft = draftTemplateIds.has(removedId)
  if (!isDraft) await api.deleteTemplate(removedId)
  localTemplates.value = localTemplates.value.filter((item) => item.id !== selectedId.value)
  selectedId.value = localTemplates.value[0]?.id ?? ''
  draftTemplateIds.delete(removedId)
  dirtyTemplateIds.delete(removedId)
  if (!isDraft) emit('changed')
}
</script>

<template>
  <AppDialog
    :model-value="modelValue"
    title="文章排版设置"
    width="96vw"
    persistent
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
          <q-input
            v-if="selectedTemplate"
            v-model="selectedTemplate.name"
            outlined
            dense
            counter
            maxlength="80"
            label="当前模板名称"
            class="template-editor__name"
            @update:model-value="markDirty"
          />
          <div class="template-editor__list">
            <button
              v-for="template in localTemplates"
              :key="template.id"
              :class="{ active: selectedId === template.id }"
              @click="selectedId = template.id"
            >
              <span>{{ template.name }}</span>
              <q-toggle
                :model-value="template.enabled"
                dense
                color="primary"
                :disable="togglingIds.has(template.id)"
                :aria-label="`${template.name}${template.enabled ? '已启用' : '已停用'}`"
                @click.stop
                @update:model-value="toggleEnabled(template, Boolean($event))"
              />
            </button>
          </div>
          <AppButton
            v-if="hasMore"
            variant="ghost"
            label="加载更多模板"
            :loading="loadingMore"
            full-width
            @click="emit('load-more')"
          />
          <AppButton
            v-if="localTemplates.length > 1"
            variant="ghost"
            label="删除当前模板"
            @click="remove"
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
          <h3>文章预览</h3>
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
      <span class="template-editor__note"
        >模板管理不受公众号连接状态影响，只在存草稿和发布时检查授权。</span
      >
      <AppButton variant="ghost" label="取消" @click="$emit('update:modelValue', false)" />
      <AppButton variant="outline" label="查看整体结果" @click="mobileStep = 4" />
      <AppButton
        label="保存模板"
        :loading="saving"
        :disabled="!selectedTemplate || !selectedTemplate.name.trim()"
        @click="save"
      />
    </template>
  </AppDialog>
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
  grid-template-rows: auto auto minmax(0, 1fr) auto;
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
    grid-template-columns: minmax(170px, 0.8fr) minmax(160px, 0.75fr) minmax(220px, 0.9fr) minmax(
        360px,
        2.4fr
      );
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

    button,
    .template-editor__templates button {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      min-width: 0;
      padding: 10px 12px;
      color: var(--app-text-primary);
      background: transparent;
      border: 0;
      border-radius: 8px;
      cursor: pointer;

      &.active {
        color: var(--app-action-primary);
        background: var(--app-action-soft);
      }
      span {
        min-width: 0;
        overflow-wrap: anywhere;
        text-align: left;
      }
    }
  }

  &__templates > .app-button:last-child {
    margin-top: 12px;
  }
  &__name {
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
    background: var(--app-bg-subtle);
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

  &__note {
    margin-right: auto;
    color: var(--app-text-secondary);
    overflow-wrap: anywhere;
  }
}

@media (max-width: 1023px) {
  .template-editor {
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
    height: calc(100vh - 69px);

    &__extract {
      grid-template-columns: minmax(0, 1fr) auto;
      padding: 10px;

      .q-chip {
        display: none;
      }
    }

    &__note {
      width: 100%;
    }
  }
}
</style>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { EditorContent, useEditor } from '@tiptap/vue-3'
import StarterKit from '@tiptap/starter-kit'
import Link from '@tiptap/extension-link'
import Image from '@tiptap/extension-image'
import { useQuasar } from 'quasar'
import type { Article, LayoutTemplate, OfficialAccount } from '@/api/types'
import { api, downloadTemplateMarker } from '@/api/client'
import { headingMarkers, headingMarkerKey, type HeadingMarker } from '@/editor/headingMarkers'
import { createDefaultStyles } from '@/api/styleDefaults'
import { queryClient } from '@/boot/query'
import { moduleParagraph } from '@/editor/moduleParagraph'
import { templatePreviewCssVariables } from '@/utils/templatePreviewStyles'
import { separateArticleTitle } from '@/utils/articleTitle'
import { tableExtensions } from '@/editor/tableExtensions'
import { useArticleFixedContent } from '@/composables/useArticleFixedContent'
import ArticleFixedContent from './ArticleFixedContent.vue'
import LockedContentEditor from './LockedContentEditor.vue'
import ArticleTableMenu from './ArticleTableMenu.vue'
import ArticleTitleChoices from './ArticleTitleChoices.vue'

const props = withDefaults(
  defineProps<{
    article: Article
    interactionLocked?: boolean
    accountId?: string | null
    accounts?: OfficialAccount[]
    accountsLoading?: boolean
    accountsError?: string
    readOnly?: boolean
    template?: LayoutTemplate | null
    templates?: LayoutTemplate[]
    templatesLoading?: boolean
    templatesError?: string
  }>(),
  {
    template: null,
    interactionLocked: false,
    accountId: null,
    accounts: () => [],
    accountsLoading: false,
    accountsError: '',
    readOnly: false,
    templates: () => [],
    templatesLoading: false,
    templatesError: '',
  },
)
defineEmits<{
  'select-template': [templateId: string | null]
  'select-account': [accountId: string | null]
}>()
const $q = useQuasar()
const editedTemplate = ref<LayoutTemplate | null>(null)
const activeTemplate = computed(() => editedTemplate.value ?? props.template)
const editingFixed = ref(false)
const editingBlocks = ref<NonNullable<LayoutTemplate['contentBlocks']>>([])
const fallbackStyles = createDefaultStyles()
const previewCssVariables = computed(() =>
  templatePreviewCssVariables(activeTemplate.value?.styles ?? fallbackStyles),
)
const hasHeadingMarker = computed(
  () => !editorMarkers.value.length && activeTemplate.value?.styles.heading_marker.enabled === true,
)
const dirty = ref(false)
const saving = ref(false)
const saveState = ref<'saved' | 'saving' | 'failed'>('saved')
const versionNo = ref(props.article.versionNo)
const title = ref(props.article.title)
const view = ref<'edit' | 'layout'>('layout')
const editorReady = ref(false)
const fullPreviewHtml = ref('')
const fullPreviewLoading = ref(false)
const fullPreviewError = ref('')
const fixedContent = useArticleFixedContent(() => activeTemplate.value)
const editorMarkers = ref<HeadingMarker[]>([])
watch(
  fixedContent.template,
  (template, _previous, onCleanup) => {
    let active = true
    const urls: string[] = []
    onCleanup(() => {
      active = false
      urls.forEach((url) => URL.revokeObjectURL(url))
    })
    editorMarkers.value = (template?.componentGroups ?? [])
      .filter((group) => group.enabled && group.kind === 'decorated_heading')
      .map((group) => ({ group, loading: true }))
    if (!template) return
    const pending = editorMarkers.value
    void (async () => {
      for (let index = 0; index < pending.length && active; index += 4) {
        await Promise.all(
          pending.slice(index, index + 4).map(async (marker) => {
            try {
              const blob = marker.group.imageDocumentId
                ? await api.downloadDocument(marker.group.imageDocumentId)
                : await downloadTemplateMarker(
                    template.id,
                    marker.group.id,
                    template.versionNo ?? 1,
                  )
              if (!active) return
              if (!['image/png', 'image/jpeg'].includes(blob.type) || blob.size >= 1_000_000)
                throw new Error('序号图片格式无效')
              marker.url = URL.createObjectURL(blob)
              urls.push(marker.url)
            } catch {
              // The decoration displays the template's text fallback or an unavailable notice.
            } finally {
              if (active) {
                marker.loading = false
                editorMarkers.value = [...pending]
              }
            }
          }),
        )
      }
    })()
  },
  { immediate: true },
)
const editFixedContent = (position?: 'before_body' | 'after_body') => {
  const template = fixedContent.template.value
  if (!template || props.readOnly || props.interactionLocked || saving.value) return
  const ids = new Set(
    template.lockedBlocks
      ?.filter((group) => !position || group.position === position)
      .flatMap((group) => group.blockIds),
  )
  editingBlocks.value = template.contentBlocks?.filter((block) => ids.has(block.id)) ?? []
  editingFixed.value = true
}
const applyFixedContent = async (blocks: NonNullable<LayoutTemplate['contentBlocks']>) => {
  const template = fixedContent.template.value
  if (!template || props.readOnly || props.interactionLocked || saving.value) return
  const articleId = props.article.id
  editingBlocks.value = blocks
  const changes = new Map(blocks.map((block) => [block.id, block]))
  saving.value = true
  try {
    const saved = await api.saveTemplate({
      ...template,
      contentBlocks: template.contentBlocks?.map((block) => changes.get(block.id) ?? block),
    })
    if (articleId === props.article.id && template.id === activeTemplate.value?.id) {
      editedTemplate.value = saved
      markDirty()
    }
    $q.notify({ type: 'positive', message: '固定内容已保存到模板，请保存文章以应用新版。' })
    void queryClient.invalidateQueries({ queryKey: ['templates'], refetchType: 'none' })
  } catch (error) {
    $q.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '固定内容保存失败。',
    })
    if (articleId === props.article.id && template.id === activeTemplate.value?.id)
      editingFixed.value = true
  } finally {
    saving.value = false
  }
}
watch(
  () => [props.article.id, props.accountId, props.template?.id, props.template?.versionId],
  () => {
    editedTemplate.value = null
    editingFixed.value = false
  },
)
const hasFixedContent = computed(() =>
  Boolean(fixedContent.beforeHtml.value || fixedContent.afterHtml.value),
)
let previewRequest = 0
let editRevision = 0
const savedTemplateVersionId = ref(props.article.layoutTemplate?.versionId)
const layoutDirty = computed(() =>
  Boolean(
    activeTemplate.value?.versionId &&
    activeTemplate.value.versionId !== savedTemplateVersionId.value,
  ),
)
const canSave = computed(() => (dirty.value || layoutDirty.value) && !saving.value)
const invalidateFullPreview = () => {
  previewRequest += 1
  fullPreviewHtml.value = ''
  fullPreviewError.value = ''
}
const markDirty = () => {
  if (props.readOnly) return
  invalidateFullPreview()
  editRevision += 1
  dirty.value = true
  saveState.value = 'failed'
}

const editor = useEditor({
  editable: !props.readOnly,
  extensions: [
    ...tableExtensions,
    StarterKit.configure({ paragraph: false }),
    moduleParagraph,
    Link.configure({ openOnClick: false }),
    Image.configure({ inline: false }),
  ],
  content: props.article.contentJson ?? props.article.contentHtml,
  editorProps: { attributes: { class: 'tiptap-body', 'aria-label': '文章预览富文本编辑器' } },
  onCreate: ({ editor: instance }) => {
    instance.registerPlugin(headingMarkers(() => editorMarkers.value))
    const separated = separateArticleTitle(instance.getJSON(), props.article.title)
    title.value = separated.title
    if (separated.separated) {
      instance.commands.setContent(separated.content, false)
      markDirty()
    }
    editorReady.value = true
  },
  onUpdate: markDirty,
})
watch(editorMarkers, () => {
  const instance = editor.value
  if (instance && !instance.isDestroyed)
    instance.view.dispatch(instance.state.tr.setMeta(headingMarkerKey, true))
})

const hydrateArticle = () => {
  invalidateFullPreview()
  versionNo.value = props.article.versionNo
  savedTemplateVersionId.value = props.article.layoutTemplate?.versionId
  dirty.value = false
  saveState.value = 'saved'
  editor.value?.commands.setContent(props.article.contentJson ?? props.article.contentHtml, false)
  title.value = props.article.title
  if (editor.value) {
    const separated = separateArticleTitle(editor.value.getJSON(), props.article.title)
    title.value = separated.title
    if (separated.separated) {
      editor.value.commands.setContent(separated.content, false)
      markDirty()
    }
  }
}

watch(() => props.article.id, hydrateArticle)
watch(
  () => props.article.versionNo,
  () => {
    invalidateFullPreview()
    if (!dirty.value && !saving.value && props.article.versionNo !== versionNo.value)
      hydrateArticle()
  },
)

watch(
  () => [props.accountId, activeTemplate.value?.id, activeTemplate.value?.versionId],
  () => {
    invalidateFullPreview()
    view.value = 'layout'
    if (layoutDirty.value) markDirty()
  },
)

const saveNow = async () => {
  if (props.readOnly || !editor.value || saving.value) return null
  if (!dirty.value && !layoutDirty.value)
    return { ...props.article, versionNo: versionNo.value, title: title.value }
  if (!title.value.trim() || title.value.trim().length > 120) {
    $q.notify({ type: 'negative', message: '请填写 1—120 字的文章标题。' })
    return null
  }
  invalidateFullPreview()
  saving.value = true
  saveState.value = 'saving'
  const revision = editRevision
  const templateVersionId = activeTemplate.value?.versionId
  try {
    const saved = await api.saveArticle({
      id: props.article.id,
      title: title.value.trim(),
      summary: props.article.summary,
      contentHtml: editor.value.getHTML(),
      contentJson: editor.value.getJSON(),
      baseVersionNo: versionNo.value,
      reason: 'preview_edit',
      templateVersionId,
    })
    versionNo.value = saved.versionNo
    savedTemplateVersionId.value = saved.layoutTemplate?.versionId
    dirty.value = revision !== editRevision || activeTemplate.value?.versionId !== templateVersionId
    saveState.value = dirty.value ? 'failed' : 'saved'
    queryClient.setQueryData(['article', props.article.id], saved)
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['article-versions', props.article.id] }),
      queryClient.invalidateQueries({ queryKey: ['library'] }),
      queryClient.invalidateQueries({ queryKey: ['task', props.article.taskId] }),
    ])
    if (dirty.value) {
      $q.notify({ type: 'warning', message: '保存期间内容有修改，请再次保存。' })
      return null
    }
    $q.notify({ type: 'positive', message: '文章修改已保存。' })
    return saved
  } catch (error) {
    saveState.value = 'failed'
    $q.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '文章修改保存失败。',
    })
    return null
  } finally {
    saving.value = false
  }
}

const chooseTitle = async (value: string) => {
  if (props.readOnly || saving.value || value === title.value) return
  title.value = value
  markDirty()
  await saveNow()
}

const loadFullPreview = async () => {
  if (saving.value || fullPreviewLoading.value || !editorReady.value) return
  invalidateFullPreview()
  fullPreviewLoading.value = true
  const articleId = props.article.id
  const articleVersionNo = props.article.versionNo
  const templateId = activeTemplate.value?.id ?? null
  const templateVersionId = activeTemplate.value?.versionId
  const accountId = props.accountId ?? activeTemplate.value?.accountId ?? props.article.accountId
  const revision = editRevision
  let request: number | undefined
  try {
    const saved = props.readOnly ? props.article : await saveNow()
    if (
      !editorReady.value ||
      articleId !== props.article.id ||
      accountId !==
        (props.accountId ?? activeTemplate.value?.accountId ?? props.article.accountId) ||
      templateId !== (activeTemplate.value?.id ?? null) ||
      templateVersionId !== activeTemplate.value?.versionId ||
      revision !== editRevision
    )
      return
    if (!saved) {
      fullPreviewError.value = '正文尚未保存，请保存后重新预览。'
      return
    }
    if (props.article.versionNo !== articleVersionNo && props.article.versionNo !== saved.versionNo)
      return
    request = ++previewRequest
    const render = await api.prepareArticleRender(
      articleId,
      accountId,
      templateId,
      null,
      saved.versionNo,
    )
    if (request === previewRequest) fullPreviewHtml.value = render.html
  } catch (error) {
    if (request === previewRequest)
      fullPreviewError.value = error instanceof Error ? error.message : '完整排版加载失败。'
  } finally {
    fullPreviewLoading.value = false
    if (
      editorReady.value &&
      view.value === 'layout' &&
      (accountId !==
        (props.accountId ?? activeTemplate.value?.accountId ?? props.article.accountId) ||
        templateVersionId !== activeTemplate.value?.versionId)
    )
      void loadFullPreview()
  }
}

const selectView = (value: 'edit' | 'layout') => {
  view.value = value
  if (value === 'layout' && !fullPreviewHtml.value) void loadFullPreview()
}

watch(
  () => [props.article.id, props.accountId, activeTemplate.value?.versionId, editorReady.value],
  () => {
    if (editorReady.value && view.value === 'layout') selectView('layout')
  },
  { immediate: true, flush: 'post' },
)

const fullPreviewDocument = computed(
  () => `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer"><style>
    *{box-sizing:border-box}html,body{margin:0;min-width:0}body{padding:1.5rem;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;overflow-wrap:anywhere}body>section{max-width:100%}img{max-width:100%;height:auto}table{max-width:100%;table-layout:fixed}pre{white-space:pre-wrap;overflow-wrap:anywhere}
  [data-template-locked=true]{position:relative}
    .fixed-edit-button{position:absolute;top:0;right:0;padding:8px 12px;border:1px solid currentColor;border-radius:4px;background:Canvas;color:CanvasText;cursor:pointer;opacity:0;pointer-events:none}
    [data-template-locked=true]:hover>.fixed-edit-button,[data-template-locked=true]:focus-within>.fixed-edit-button{opacity:1;pointer-events:auto}
    @media(hover:none){.fixed-edit-button{opacity:1;pointer-events:auto}}
  </style></head><body>${fullPreviewHtml.value}</body></html>`,
)

const addFixedEditButtons = (event: Event) => {
  const document = (event.target as HTMLIFrameElement).contentDocument
  if (!document || props.readOnly || props.interactionLocked) return
  for (const section of document.querySelectorAll<HTMLElement>('[data-template-locked="true"]')) {
    const button = document.createElement('button')
    button.type = 'button'
    button.className = 'fixed-edit-button'
    button.textContent = '修改固定内容'
    button.addEventListener('click', () => editFixedContent())
    section.append(button)
  }
}

const setLink = () => {
  if (!editor.value) return
  const url = window.prompt('请输入链接地址', 'https://')
  if (!url) return
  try {
    const parsed = new URL(url)
    if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error()
    editor.value.chain().focus().extendMarkRange('link').setLink({ href: parsed.href }).run()
  } catch {
    $q.notify({ type: 'warning', message: '链接必须是有效的 http 或 https 地址。' })
  }
}

defineExpose({ canSave, dirty, saveNow, saving, saveState, versionNo })
onBeforeUnmount(() => {
  editorReady.value = false
  invalidateFullPreview()
  editor.value?.destroy()
})
</script>

<template>
  <LockedContentEditor
    v-model="editingFixed"
    :blocks="editingBlocks"
    apply-label="保存到模板"
    @apply="applyFixedContent"
  />
  <section
    class="article-panel"
    aria-label="文章预览编辑区"
    :inert="interactionLocked || undefined"
  >
    <div class="article-panel__toolbar" role="toolbar" aria-label="文章预览编辑工具栏">
      <q-select
        v-if="!readOnly"
        class="article-panel__template-select"
        :model-value="accountId"
        :options="accounts.map((item) => ({ label: item.name, value: item.id }))"
        :loading="accountsLoading"
        :disable="saving || accountsLoading || !accounts.length"
        emit-value
        map-options
        dense
        outlined
        options-dense
        label="公众号"
        aria-label="选择预览公众号"
        @update:model-value="$emit('select-account', $event)"
      />
      <q-select
        v-if="!readOnly"
        class="article-panel__template-select"
        :model-value="template?.id ?? null"
        :options="templates.map((item) => ({ label: item.name, value: item.id }))"
        :loading="templatesLoading"
        :disable="saving || templatesLoading || !templates.length"
        emit-value
        map-options
        dense
        outlined
        options-dense
        label="预览排版模板"
        aria-label="选择文章预览排版模板"
        @update:model-value="$emit('select-template', $event)"
      >
        <template #prepend><q-icon name="auto_awesome" /></template>
      </q-select>
      <span v-if="template" class="article-panel__template-status">
        {{ view === 'layout' && fullPreviewHtml ? '已应用' : '已选模板' }}：{{ template.name }}
      </span>
      <span
        v-if="accountsError || templatesError"
        class="article-panel__template-status"
        role="alert"
      >
        {{ accountsError || templatesError }}
      </span>
      <slot name="cover" />
      <q-btn-toggle
        :model-value="view"
        class="article-panel__view-toggle"
        :options="[
          { label: readOnly ? '正文阅读' : '正文编辑', value: 'edit' },
          { label: '完整排版', value: 'layout' },
        ]"
        dense
        no-caps
        unelevated
        toggle-color="primary"
        aria-label="切换文章预览方式"
        @update:model-value="selectView"
      />
      <template v-if="!readOnly && view === 'edit'">
        <q-separator vertical />
        <q-btn
          flat
          round
          dense
          icon="undo"
          aria-label="撤销"
          :disable="!editor?.can().undo()"
          @click="editor?.chain().focus().undo().run()"
        />
        <q-btn
          flat
          round
          dense
          icon="redo"
          aria-label="重做"
          :disable="!editor?.can().redo()"
          @click="editor?.chain().focus().redo().run()"
        />
        <q-separator vertical />
        <q-btn flat dense no-caps label="正文" aria-label="正文样式">
          <q-menu>
            <q-list>
              <q-item
                clickable
                v-close-popup
                @click="editor?.chain().focus().setNode('paragraph', { module: 'body' }).run()"
                ><q-item-section>正文</q-item-section></q-item
              >
              <q-item
                clickable
                v-close-popup
                @click="editor?.chain().focus().setNode('paragraph', { module: 'lead' }).run()"
                ><q-item-section>导语</q-item-section></q-item
              >
              <q-item
                clickable
                v-close-popup
                @click="editor?.chain().focus().setNode('paragraph', { module: 'highlight' }).run()"
                ><q-item-section>重点论点</q-item-section></q-item
              >
              <q-item
                clickable
                v-close-popup
                @click="editor?.chain().focus().setNode('paragraph', { module: 'caption' }).run()"
                ><q-item-section>图片说明</q-item-section></q-item
              >
              <q-separator />
              <q-item
                clickable
                v-close-popup
                @click="editor?.chain().focus().toggleHeading({ level: 2 }).run()"
                ><q-item-section>一级标题</q-item-section></q-item
              >
              <q-item
                clickable
                v-close-popup
                @click="editor?.chain().focus().toggleHeading({ level: 3 }).run()"
                ><q-item-section>二级标题</q-item-section></q-item
              >
            </q-list>
          </q-menu>
        </q-btn>
        <q-separator vertical />
        <q-btn
          flat
          round
          dense
          icon="format_bold"
          aria-label="加粗"
          :class="{ active: editor?.isActive('bold') }"
          @click="editor?.chain().focus().toggleBold().run()"
        />
        <q-btn
          flat
          round
          dense
          icon="format_italic"
          aria-label="斜体"
          :class="{ active: editor?.isActive('italic') }"
          @click="editor?.chain().focus().toggleItalic().run()"
        />
        <q-btn flat round dense icon="format_underlined" aria-label="下划线" disable />
        <q-btn
          flat
          round
          dense
          icon="strikethrough_s"
          aria-label="删除线"
          :class="{ active: editor?.isActive('strike') }"
          @click="editor?.chain().focus().toggleStrike().run()"
        />
        <q-btn
          flat
          round
          dense
          icon="format_list_bulleted"
          aria-label="无序列表"
          @click="editor?.chain().focus().toggleBulletList().run()"
        />
        <q-btn
          flat
          round
          dense
          icon="format_list_numbered"
          aria-label="有序列表"
          @click="editor?.chain().focus().toggleOrderedList().run()"
        />
        <q-btn
          flat
          round
          dense
          icon="format_quote"
          aria-label="引用"
          @click="editor?.chain().focus().toggleBlockquote().run()"
        />
        <q-btn
          flat
          round
          dense
          icon="horizontal_rule"
          aria-label="分割线"
          @click="editor?.chain().focus().setHorizontalRule().run()"
        />
        <q-separator vertical />
        <q-btn flat round dense icon="link" aria-label="添加链接" @click="setLink" />
        <q-btn flat round dense icon="image" aria-label="图片占位" disable />
        <ArticleTableMenu :editor="editor" />
        <q-btn
          flat
          round
          dense
          icon="code"
          aria-label="代码块"
          @click="editor?.chain().focus().toggleCodeBlock().run()"
        />
        <q-btn flat round dense icon="sentiment_satisfied" aria-label="表情占位" disable />
      </template>
    </div>
    <div
      v-show="view === 'edit'"
      class="article-panel__body"
      :class="{ 'article-panel__body--readonly': readOnly }"
    >
      <ArticleTitleChoices
        v-if="!readOnly"
        :article="{ ...article, versionNo }"
        :title="title"
        :disabled="saving"
        @choose="chooseTitle"
      />
      <div class="article-panel__scroll">
        <div
          :style="previewCssVariables"
          :class="[
            'article-panel__document',
            {
              'article-panel__document--with-marker': hasHeadingMarker,
              'article-panel__document--with-fixed': hasFixedContent,
            },
          ]"
        >
          <header class="article-panel__heading">
            <q-input
              v-model="title"
              class="article-panel__title"
              type="textarea"
              rows="1"
              autogrow
              borderless
              stack-label
              label="文章标题"
              aria-label="文章标题"
              maxlength="120"
              :disable="saving"
              :readonly="readOnly"
              @update:model-value="markDirty"
            />
          </header>
          <div
            v-if="fixedContent.loading.value || fixedContent.error.value"
            class="article-panel__fixed-state"
            role="status"
          >
            <q-spinner v-if="fixedContent.loading.value" color="primary" size="20px" />
            <span>{{ fixedContent.error.value || '正在加载固定内容…' }}</span>
            <q-btn
              v-if="fixedContent.error.value"
              flat
              dense
              color="primary"
              label="重试"
              @click="fixedContent.retry"
            />
          </div>
          <ArticleFixedContent
            :source-url="fixedContent.sourceUrl.value"
            v-if="fixedContent.beforeHtml.value"
            :html="fixedContent.beforeHtml.value"
            label="正文固定开头"
            :editable="!readOnly && !interactionLocked && !saving"
            @edit="editFixedContent('before_body')"
          />
          <EditorContent :editor="editor" />
          <ArticleFixedContent
            :source-url="fixedContent.sourceUrl.value"
            v-if="fixedContent.afterHtml.value"
            :html="fixedContent.afterHtml.value"
            label="正文固定结尾"
            :editable="!readOnly && !interactionLocked && !saving"
            @edit="editFixedContent('after_body')"
          />
        </div>
      </div>
    </div>
    <div v-if="view === 'layout'" class="article-panel__full-preview">
      <h2 class="article-panel__full-title text-h6">{{ title }}</h2>
      <div
        v-if="fullPreviewLoading"
        class="article-panel__preview-state"
        role="status"
        aria-live="polite"
      >
        <q-spinner color="primary" size="32px" aria-hidden="true" />
        <span>{{ saving ? '正在保存正文…' : '正在加载完整排版…' }}</span>
      </div>
      <iframe
        v-else-if="fullPreviewHtml"
        class="article-panel__full-frame"
        :srcdoc="fullPreviewDocument"
        sandbox="allow-same-origin"
        @load="addFixedEditButtons"
        referrerpolicy="no-referrer"
        :title="`${title}完整排版预览`"
      />
      <div v-else class="article-panel__preview-state" aria-live="polite">
        <span>{{ fullPreviewError || '内容已更新，请重新预览。' }}</span>
        <q-btn
          outline
          color="primary"
          label="重新预览"
          :disable="saving || !editorReady"
          @click="loadFullPreview"
        />
      </div>
    </div>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/mixins/article-content' as *;
@use '@/styles/tokens/primitive' as space;

:deep(.article-heading-image) {
  min-width: 0;
  max-width: 100%;
  overflow-wrap: anywhere;
}

:deep(.article-heading-image--text) {
  @include preview-module('heading-marker');
}

.article-panel {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  min-width: 0;
  min-height: 0;
  height: min(72vh, 760px);

  &__body {
    display: grid;
    grid-template-columns: minmax(180px, 260px) minmax(0, 1fr);
    min-width: 0;
    min-height: 0;
  }

  &__body--readonly {
    grid-template-columns: minmax(0, 1fr);
  }

  &__toolbar {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 2px;
    min-width: 0;
    padding: 8px clamp(10px, 2vw, 20px);
    overflow-x: auto;
    background: var(--app-bg-surface);
    border-bottom: 1px solid var(--app-border-default);
  }

  &__toolbar .active {
    color: var(--app-action-primary);
    background: var(--app-action-soft);
  }

  &__template-select {
    flex: 0 1 260px;
    width: 260px;
    min-width: min(210px, 100%);
    max-width: 100%;
  }

  &__template-status {
    min-width: 0;
    max-width: min(320px, 100%);
    color: var(--app-text-secondary);
    font-size: 13px;
    overflow-wrap: anywhere;
  }

  &__view-toggle {
    min-width: 0;
    max-width: 100%;
    margin-left: auto;
  }

  &__full-preview {
    display: flex;
    flex-direction: column;
    gap: space.$space-3;
    min-width: 0;
    min-height: 0;
    padding: space.$space-4;
    background: var(--app-bg-subtle);
  }

  &__full-title {
    min-width: 0;
    max-height: 25%;
    margin: 0;
    overflow-y: auto;
    overflow-wrap: anywhere;
  }

  &__full-frame {
    flex: 1 1 auto;
    width: 100%;
    min-width: 0;
    min-height: 0;
    border: 1px solid var(--app-border-default);
    background: var(--app-bg-surface);
  }

  &__preview-state {
    display: flex;
    flex: 1 1 auto;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: space.$space-3;
    min-width: 0;
    min-height: 0;
    overflow-y: auto;
    overflow-wrap: anywhere;
    text-align: center;
  }

  &__preview-state > * {
    min-width: 0;
    max-width: 100%;
  }

  &__scroll {
    min-width: 0;
    min-height: 0;
    padding: clamp(14px, 3vw, 32px);
    overflow-y: auto;
    background: var(--app-bg-subtle);
  }

  &__document {
    @include article-content;

    width: min(100%, 820px);
    min-width: 0;
    max-width: 100%;
    min-height: 100%;
    margin-inline: auto;
    padding: clamp(24px, 5vw, 64px);
    color: var(--app-text-primary);
    background: var(--app-bg-surface);
    border: 1px solid var(--app-border-default);
    border-radius: 10px;
    box-shadow: var(--app-shadow-sm);
  }

  &__heading {
    min-width: 0;
    margin-bottom: min(var(--article-title-margin-bottom), #{space.$space-3});
    padding-bottom: min(var(--article-title-margin-bottom), #{space.$space-3});
    border-bottom: 1px solid var(--app-border-default);
  }

  &__document--with-fixed :deep(.tiptap-body) {
    min-height: 0;
  }

  &__fixed-state {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: space.$space-2;
    min-width: 0;
    color: var(--app-text-secondary);
    overflow-wrap: anywhere;

    > span {
      flex: 1 1 auto;
      min-width: 0;
    }
  }

  &__title,
  &__title :deep(.q-field__control),
  &__title :deep(.q-field__control-container),
  &__title :deep(textarea.q-field__native) {
    box-sizing: border-box;
    width: 100%;
    min-width: 0;
    max-width: 100%;
  }

  &__title :deep(textarea.q-field__native) {
    color: var(--app-text-primary);
    font-size: var(--article-title-font-size);
    font-weight: var(--article-title-font-weight);
    line-height: var(--article-title-line-height);
    overflow-wrap: anywhere;
  }
}

@media (max-width: 599px) {
  .article-panel {
    height: min(74vh, 720px);

    &__body:not(.article-panel__body--readonly) {
      grid-template-columns: minmax(0, 1fr);
      grid-template-rows: minmax(0, 0.45fr) minmax(0, 1fr);
    }

    &__document {
      padding: 24px 18px;
      border-radius: 0;
    }

    &__template-select {
      flex-basis: 100%;
      width: 100%;
    }
  }
}
</style>

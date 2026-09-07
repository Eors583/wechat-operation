<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { EditorContent, useEditor } from '@tiptap/vue-3'
import StarterKit from '@tiptap/starter-kit'
import Link from '@tiptap/extension-link'
import Image from '@tiptap/extension-image'
import { useQuasar } from 'quasar'
import type { Article, LayoutTemplate } from '@/api/types'
import { api } from '@/api/client'
import { createDefaultStyles } from '@/api/styleDefaults'
import { queryClient } from '@/boot/query'
import { moduleParagraph } from '@/editor/moduleParagraph'
import { templatePreviewCssVariables } from '@/utils/templatePreviewStyles'
import { separateArticleTitle } from '@/utils/articleTitle'
import { tableExtensions } from '@/editor/tableExtensions'
import ArticleTableMenu from './ArticleTableMenu.vue'

const props = withDefaults(
  defineProps<{
    article: Article
    readOnly?: boolean
    template?: LayoutTemplate | null
    templates?: LayoutTemplate[]
    templatesLoading?: boolean
    templatesError?: string
  }>(),
  {
    template: null,
    readOnly: false,
    templates: () => [],
    templatesLoading: false,
    templatesError: '',
  },
)
defineEmits<{ 'select-template': [templateId: string | null] }>()
const $q = useQuasar()
const fallbackStyles = createDefaultStyles()
const previewCssVariables = computed(() =>
  templatePreviewCssVariables(props.template?.styles ?? fallbackStyles),
)
const hasHeadingMarker = computed(() => props.template?.styles.heading_marker.enabled === true)
const dirty = ref(false)
const saving = ref(false)
const saveState = ref<'saved' | 'saving' | 'failed'>('saved')
const versionNo = ref(props.article.versionNo)
const title = ref(props.article.title)
const canSave = computed(() => dirty.value && !saving.value)
const markDirty = () => {
  if (props.readOnly) return
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
    const separated = separateArticleTitle(instance.getJSON(), props.article.title)
    title.value = separated.title
    if (separated.separated) {
      instance.commands.setContent(separated.content, false)
      markDirty()
    }
  },
  onUpdate: markDirty,
})

watch(
  () => props.article.id,
  () => {
    versionNo.value = props.article.versionNo
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
  },
)

const saveNow = async () => {
  if (props.readOnly || !editor.value || !dirty.value || saving.value) return
  if (!title.value.trim() || title.value.trim().length > 120) {
    $q.notify({ type: 'negative', message: '请填写 1—120 字的文章标题。' })
    return
  }
  saving.value = true
  saveState.value = 'saving'
  try {
    const saved = await api.saveArticle({
      id: props.article.id,
      title: title.value.trim(),
      summary: props.article.summary,
      contentHtml: editor.value.getHTML(),
      contentJson: editor.value.getJSON(),
      baseVersionNo: versionNo.value,
      reason: 'preview_edit',
    })
    versionNo.value = saved.versionNo
    dirty.value = false
    saveState.value = 'saved'
    queryClient.setQueryData(['article', props.article.id], saved)
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['article-versions', props.article.id] }),
      queryClient.invalidateQueries({ queryKey: ['library'] }),
      queryClient.invalidateQueries({ queryKey: ['task', props.article.taskId] }),
    ])
    $q.notify({ type: 'positive', message: '文章修改已保存。' })
  } catch (error) {
    saveState.value = 'failed'
    $q.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '文章修改保存失败。',
    })
  } finally {
    saving.value = false
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
onBeforeUnmount(() => editor.value?.destroy())
</script>

<template>
  <section class="article-panel" aria-label="文章预览编辑区">
    <div
      v-if="!readOnly"
      class="article-panel__toolbar"
      role="toolbar"
      aria-label="文章预览编辑工具栏"
    >
      <q-select
        class="article-panel__template-select"
        :model-value="template?.id ?? null"
        :options="templates.map((item) => ({ label: item.name, value: item.id }))"
        :loading="templatesLoading"
        :disable="templatesLoading || !templates.length"
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
        已应用：{{ template.name }}
      </span>
      <span v-else-if="!templatesLoading" class="article-panel__template-status">
        {{ templatesError || '暂无可用排版模板，当前使用基础样式' }}
      </span>
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
    </div>
    <div class="article-panel__scroll">
      <div
        :style="previewCssVariables"
        :class="[
          'article-panel__document',
          { 'article-panel__document--with-marker': hasHeadingMarker },
        ]"
      >
        <header class="article-panel__heading">
          <q-input
            v-model="title"
            class="article-panel__title"
            type="textarea"
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
        <EditorContent :editor="editor" />
      </div>
    </div>
  </section>
</template>

<style scoped lang="scss">
@mixin preview-module($name) {
  margin-top: var(--article-#{$name}-margin-top);
  margin-bottom: var(--article-#{$name}-margin-bottom);
  padding: var(--article-#{$name}-padding);
  color: var(--article-#{$name}-color);
  background: var(--article-#{$name}-background);
  border-left: var(--article-#{$name}-border-left);
  font-size: var(--article-#{$name}-font-size);
  font-weight: var(--article-#{$name}-font-weight);
  line-height: var(--article-#{$name}-line-height);
  text-align: var(--article-#{$name}-text-align);
  text-indent: var(--article-#{$name}-text-indent);
}

.article-panel {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  min-width: 0;
  min-height: 0;
  height: min(72vh, 760px);

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

  &__scroll {
    min-width: 0;
    min-height: 0;
    padding: clamp(14px, 3vw, 32px);
    overflow-y: auto;
    background: var(--app-bg-subtle);
  }

  &__document {
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
    margin-bottom: var(--article-title-margin-bottom);
    padding-bottom: var(--article-title-margin-bottom);
    border-bottom: 1px solid var(--app-border-default);
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

  &__document :deep(.tiptap-body) {
    min-width: 0;
    min-height: 560px;
    outline: none;
    overflow-wrap: anywhere;
    counter-reset: article-heading-marker;
  }

  &__document :deep(.tiptap-body h1) {
    @include preview-module('title');

    overflow-wrap: anywhere;
  }
  &__document :deep(.tiptap-body h2) {
    @include preview-module('heading1');

    overflow-wrap: anywhere;
  }
  &__document :deep(.tiptap-body h3) {
    @include preview-module('heading2');

    overflow-wrap: anywhere;
  }
  &__document--with-marker :deep(.tiptap-body h2::before) {
    @include preview-module('heading-marker');

    display: block;
    content: counter(article-heading-marker, decimal-leading-zero);
    counter-increment: article-heading-marker;
    overflow-wrap: anywhere;
  }
  &__document :deep(.tiptap-body p) {
    @include preview-module('body');

    overflow-wrap: anywhere;
  }
  &__document :deep(.tiptap-body blockquote) {
    @include preview-module('quote');

    overflow-wrap: anywhere;
  }
  &__document :deep(.tiptap-body blockquote p) {
    margin: 0;
    padding: 0;
    color: inherit;
    background: transparent;
    border: 0;
    font: inherit;
    text-align: inherit;
    text-indent: inherit;
  }
  &__document :deep(.tiptap-body [data-module='lead']) {
    @include preview-module('lead');
  }
  &__document :deep(.tiptap-body [data-module='highlight']) {
    @include preview-module('highlight');
  }
  &__document :deep(.tiptap-body [data-module='caption']) {
    @include preview-module('caption');
  }
  &__document :deep(.tiptap-body ul),
  &__document :deep(.tiptap-body ol) {
    @include preview-module('list');

    padding-left: max(var(--article-list-padding), 24px);
    overflow-wrap: anywhere;
  }
  &__document :deep(.tiptap-body hr) {
    @include preview-module('divider');

    min-height: 1px;
    border-top: 1px solid var(--article-divider-color);
  }
  &__document :deep(.tiptap-body img) {
    display: block;
    max-width: 100%;
    height: auto;
    margin-inline: auto;
  }
}

@media (max-width: 599px) {
  .article-panel {
    height: min(74vh, 720px);

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

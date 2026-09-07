<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { api } from '@/api/client'
import type { LibraryItem } from '@/api/types'
import { platform } from '@/platform'
import AppButton from '@/components/base/AppButton.vue'
import AppDialog from '@/components/base/AppDialog.vue'
import PdfPreview from '@/components/business/PdfPreview.vue'

const props = defineProps<{
  modelValue: boolean
  item: LibraryItem | null
  loading?: boolean
  reparsing?: boolean
}>()
defineEmits<{ 'update:modelValue': [value: boolean]; retry: [item: LibraryItem] }>()

type PreviewKind = 'pptx' | 'pdf' | 'download'
type PptxViewerInstance = { destroy(): void }

const PPTX_MIME = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
const PDF_MIME = 'application/pdf'
const canvasContainer = ref<HTMLElement | null>(null)
const rendererContainer = ref<HTMLElement | null>(null)
const sourceFile = ref<Blob | null>(null)
const previewKind = ref<PreviewKind>('download')
const previewLoading = ref(false)
const previewError = ref('')
const downloading = ref(false)
let viewer: PptxViewerInstance | null = null
let loadVersion = 0

const fileLabel = computed(() => {
  const extension = props.item?.title.match(/\.([a-z0-9]+)$/i)?.[1]
  return extension?.toUpperCase() ?? props.item?.fileType ?? '资料'
})

const clearViewer = () => {
  viewer?.destroy()
  viewer = null
  rendererContainer.value?.replaceChildren()
}

const loadPreview = async () => {
  const version = ++loadVersion
  clearViewer()
  sourceFile.value = null
  previewError.value = ''
  previewKind.value = 'download'
  if (!props.modelValue || props.item?.type !== 'reference') return

  previewLoading.value = true
  try {
    const file = await api.downloadDocument(props.item.sourceId)
    if (version !== loadVersion) return
    sourceFile.value = file
    const isPdf = file.type === PDF_MIME || /\.pdf$/i.test(props.item.title)
    if (isPdf) {
      previewKind.value = 'pdf'
      return
    }
    const isPptx = file.type === PPTX_MIME || /\.pptx$/i.test(props.item.title)
    if (!isPptx) return

    previewKind.value = 'pptx'
    await nextTick()
    const container = rendererContainer.value
    if (!container || version !== loadVersion) return
    const { PptxViewer, RECOMMENDED_ZIP_LIMITS } = await import('@aiden0z/pptx-renderer/browser')
    const nextViewer = await PptxViewer.open(await file.arrayBuffer(), container, {
      fitMode: 'contain',
      scrollContainer: canvasContainer.value ?? container,
      zipLimits: RECOMMENDED_ZIP_LIMITS,
      lazySlides: true,
      lazyMedia: true,
      pdfjs: false,
      listOptions: {
        windowed: true,
        initialSlides: 4,
        batchSize: 4,
        showSlideLabels: true,
      },
    })
    if (version !== loadVersion) nextViewer.destroy()
    else viewer = nextViewer
  } catch (error) {
    if (version === loadVersion)
      previewError.value = error instanceof Error ? error.message : '原文件预览加载失败。'
  } finally {
    if (version === loadVersion) previewLoading.value = false
  }
}

const downloadOriginal = async () => {
  const item = props.item
  if (!item || downloading.value) return
  downloading.value = true
  try {
    const file = sourceFile.value ?? (await api.downloadDocument(item.sourceId))
    sourceFile.value = file
    await platform.downloadFile(new File([file], item.title, { type: file.type }))
  } finally {
    downloading.value = false
  }
}

watch(
  () => [props.modelValue, props.item?.sourceId] as const,
  () => void loadPreview(),
  { immediate: true },
)
onBeforeUnmount(() => {
  loadVersion += 1
  clearViewer()
})
</script>

<template>
  <AppDialog
    :model-value="modelValue"
    :title="item?.title ?? '文件预览'"
    width="1100px"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <div v-if="item" class="file-preview">
      <header class="file-preview__toolbar">
        <span>{{ fileLabel }}</span>
        <span v-if="item.pageCount">{{ item.pageCount }} 页</span>
        <span>原文件预览</span>
      </header>
      <main
        ref="canvasContainer"
        class="file-preview__canvas"
        :class="{ 'file-preview__canvas--pdf': previewKind === 'pdf' }"
      >
        <PdfPreview
          v-if="previewKind === 'pdf' && sourceFile && !previewError"
          :file="sourceFile"
          @error="previewError = $event"
        />
        <div v-show="previewKind === 'pptx' && !previewError" class="file-preview__stage">
          <div
            ref="rendererContainer"
            class="file-preview__renderer"
            aria-label="PowerPoint 幻灯片预览"
          />
          <div v-if="previewLoading" class="file-preview__loading-overlay" role="status">
            <q-spinner color="primary" size="38px" />
            <span>正在还原幻灯片版式…</span>
          </div>
        </div>
        <div
          v-if="loading || (previewLoading && previewKind !== 'pptx')"
          class="file-preview__loading"
          role="status"
        >
          <q-spinner color="primary" size="38px" />
          <span>正在打开原文件…</span>
        </div>
        <section v-else-if="previewError" class="file-preview__message" role="alert">
          <q-icon name="error_outline" size="42px" color="negative" />
          <h3>暂时无法预览原文件</h3>
          <p>{{ previewError }}</p>
          <AppButton icon="download" label="下载原文件" @click="downloadOriginal" />
        </section>
        <section v-else-if="previewKind === 'download'" class="file-preview__message">
          <q-icon name="description" size="48px" color="primary" />
          <h3>{{ item.title }}</h3>
          <p>此格式暂不支持站内还原展示，请下载原文件后查看。</p>
          <AppButton icon="download" label="下载原文件" @click="downloadOriginal" />
        </section>
      </main>
    </div>
    <template v-if="item?.type === 'reference'" #actions>
      <AppButton variant="outline" label="关闭" @click="$emit('update:modelValue', false)" />
      <AppButton
        variant="outline"
        icon="download"
        label="下载原文件"
        :loading="downloading"
        @click="downloadOriginal"
      />
      <AppButton
        v-if="item.status === 'failed'"
        icon="refresh"
        label="重试解析"
        :loading="reparsing"
        @click="$emit('retry', item)"
      />
    </template>
  </AppDialog>
</template>

<style scoped lang="scss">
.file-preview {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  min-width: 0;
  min-height: 0;
  height: min(76vh, 820px);

  &__toolbar {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 12px;
    min-width: 0;
    padding: 10px 18px;
    color: var(--app-text-secondary);
    border-bottom: 1px solid var(--app-border-default);

    span {
      overflow-wrap: anywhere;
    }
  }

  &__canvas {
    min-width: 0;
    min-height: 0;
    padding: clamp(16px, 3vw, 32px);
    overflow: auto;
    background: var(--app-bg-subtle);

    &--pdf {
      padding: 0;
      overflow: hidden;
    }
  }

  &__renderer {
    width: 100%;
    max-width: 100%;
    min-width: 0;
    min-height: 100%;
    box-sizing: border-box;
  }

  &__stage {
    position: relative;
    width: 100%;
    max-width: 100%;
    min-width: 0;
    min-height: 100%;
  }

  &__loading-overlay {
    position: absolute;
    inset: 0;
    display: grid;
    place-items: center;
    align-content: center;
    gap: 12px;
    min-height: 320px;
    color: var(--app-text-secondary);
    background: color-mix(in srgb, var(--app-bg-subtle) 90%, transparent);
  }

  &__message {
    display: grid;
    place-items: center;
    align-content: center;
    gap: 12px;
    width: min(100%, 620px);
    min-height: 420px;
    margin-inline: auto;
    padding: clamp(24px, 6vw, 56px);
    box-sizing: border-box;
    overflow-wrap: anywhere;
    text-align: center;
    background: var(--app-bg-surface);
    box-shadow: var(--app-shadow-sm);

    h3,
    p {
      max-width: 100%;
      margin: 0;
    }

    p {
      color: var(--app-text-secondary);
      line-height: 1.7;
    }
  }

  &__loading {
    display: grid;
    place-items: center;
    align-content: center;
    gap: 12px;
    min-height: 320px;
    color: var(--app-text-secondary);
  }
}

@media (max-width: 599px) {
  .file-preview {
    height: calc(100vh - 69px);
  }

  .file-preview__canvas {
    padding: 12px;
  }

  .file-preview__message {
    min-height: 360px;
  }
}
</style>

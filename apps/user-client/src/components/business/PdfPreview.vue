<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import type { PDFDocumentLoadingTask, PDFDocumentProxy } from 'pdfjs-dist'

const props = defineProps<{ file: Blob }>()
const emit = defineEmits<{ error: [message: string] }>()

const scrollContainer = ref<HTMLElement | null>(null)
const pages = ref<number[]>([])
const loading = ref(false)
let document: PDFDocumentProxy | null = null
let loadingTask: PDFDocumentLoadingTask | null = null
let observer: IntersectionObserver | null = null
let loadVersion = 0

const reset = () => {
  observer?.disconnect()
  observer = null
  void loadingTask?.destroy()
  loadingTask = null
  document = null
  pages.value = []
}

const renderPage = async (canvas: HTMLCanvasElement, pageNumber: number, version: number) => {
  const pdf = document
  if (!pdf) return
  try {
    const page = await pdf.getPage(pageNumber)
    if (version !== loadVersion) return
    const natural = page.getViewport({ scale: 1 })
    const availableWidth = Math.min((scrollContainer.value?.clientWidth ?? 960) - 32, 960)
    const viewport = page.getViewport({ scale: Math.max(availableWidth / natural.width, 0.1) })
    const outputScale = Math.min(window.devicePixelRatio || 1, 2)
    const context = canvas.getContext('2d')
    if (!context) throw new Error('浏览器无法创建 PDF 画布。')
    canvas.width = Math.floor(viewport.width * outputScale)
    canvas.height = Math.floor(viewport.height * outputScale)
    await page.render({
      canvas,
      canvasContext: context,
      viewport,
      transform: outputScale === 1 ? undefined : [outputScale, 0, 0, outputScale, 0, 0],
    }).promise
    canvas.dataset.rendered = 'true'
  } catch (error) {
    if (version === loadVersion)
      emit('error', error instanceof Error ? error.message : 'PDF 页面渲染失败。')
  }
}

const observePages = (version: number) => {
  const root = scrollContainer.value
  if (!root) return
  observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue
        observer?.unobserve(entry.target)
        const canvas = entry.target as HTMLCanvasElement
        void renderPage(canvas, Number(canvas.dataset.page), version)
      }
    },
    { root, rootMargin: '1000px 0px' },
  )
  root
    .querySelectorAll<HTMLCanvasElement>('canvas[data-page]')
    .forEach((canvas) => observer?.observe(canvas))
}

const loadPdf = async () => {
  const version = ++loadVersion
  reset()
  loading.value = true
  try {
    const pdfjs = await import('pdfjs-dist')
    pdfjs.GlobalWorkerOptions.workerSrc = workerUrl
    const bytes = new Uint8Array(await props.file.arrayBuffer())
    if (version !== loadVersion) return
    const task = pdfjs.getDocument({ data: bytes })
    loadingTask = task
    const nextDocument = await task.promise
    if (version !== loadVersion) {
      await task.destroy()
      return
    }
    document = nextDocument
    pages.value = Array.from({ length: nextDocument.numPages }, (_, index) => index + 1)
    await nextTick()
    observePages(version)
  } catch (error) {
    if (version === loadVersion)
      emit('error', error instanceof Error ? error.message : 'PDF 原文件加载失败。')
  } finally {
    if (version === loadVersion) loading.value = false
  }
}

watch(
  () => props.file,
  () => void loadPdf(),
  { immediate: true },
)
onBeforeUnmount(() => {
  loadVersion += 1
  reset()
})
</script>

<template>
  <div ref="scrollContainer" class="pdf-preview" aria-label="PDF 页面预览">
    <figure v-for="page in pages" :key="page" class="pdf-preview__page">
      <canvas :data-page="page" :aria-label="`PDF 第 ${page} 页`" />
      <figcaption>{{ page }} / {{ pages.length }}</figcaption>
    </figure>
    <div v-if="loading" class="pdf-preview__loading" role="status">
      <q-spinner color="primary" size="38px" />
      <span>正在还原 PDF 页面…</span>
    </div>
  </div>
</template>

<style scoped lang="scss">
.pdf-preview {
  position: relative;
  display: grid;
  align-content: start;
  gap: 20px;
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  padding: clamp(12px, 2.5vw, 28px);
  box-sizing: border-box;
  overflow: auto;
  background: var(--app-bg-subtle);

  &__page {
    display: grid;
    justify-items: center;
    gap: 8px;
    width: 100%;
    min-width: 0;
    margin: 0;

    canvas {
      display: block;
      width: min(100%, 960px);
      max-width: 100%;
      height: auto;
      aspect-ratio: 210 / 297;
      background: white;
      box-shadow: var(--app-shadow-sm);
    }

    figcaption {
      color: var(--app-text-secondary);
      font-size: 12px;
    }
  }

  &__loading {
    position: absolute;
    inset: 0;
    display: grid;
    place-items: center;
    align-content: center;
    gap: 12px;
    color: var(--app-text-secondary);
    background: var(--app-bg-subtle);
  }
}
</style>

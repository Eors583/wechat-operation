<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { playTemplateVideo, prepareTemplateVideos, releaseTemplateVideos } from '@/utils/templateMedia'

const props = defineProps<{ html: string; label: string; sourceUrl?: string }>()
const frame = ref<HTMLIFrameElement | null>(null)
const height = ref(1)
let cleanup = () => {}

// Only server-sanitized template fragments enter this script-free document.
// Keep them outside the editor so saving the body never duplicates fixed content.
const sourceDocument = computed(
  () => `<!doctype html><html lang="zh-CN"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src https: http: data:; style-src 'unsafe-inline'; script-src 'none'; media-src blob:; form-action 'none'; base-uri 'none'">
<style>
*{box-sizing:border-box}html,body{margin:0;min-width:0}
body{font-family:system-ui,'Microsoft YaHei',sans-serif;color:CanvasText;color-scheme:light;overflow-wrap:anywhere}
main{display:flow-root;min-width:0;max-width:100%;overflow-wrap:anywhere}
main *{max-width:100%;overflow-wrap:anywhere}img{max-width:100%!important;height:auto!important}
table{max-width:100%;table-layout:fixed}pre{white-space:pre-wrap;overflow-wrap:anywhere}
</style></head><body><main>${props.html}</main></body></html>`,
)

const onLoad = () => {
  cleanup()
  const document = frame.value?.contentDocument
  const content = document?.querySelector('main')
  if (!document || !content) return
  prepareTemplateVideos(document)
  const resize = () => {
    height.value = Math.max(
      1,
      Math.ceil(content.getBoundingClientRect().height),
      content.scrollHeight,
    )
  }
  const observer = new ResizeObserver(resize)
  observer.observe(content)
  const preventNavigation = (event: MouseEvent) => {
    const target = event.target as Element | null
    if (target?.closest('a')) event.preventDefault()
    playTemplateVideo(target, props.sourceUrl)
  }
  document.addEventListener('click', preventNavigation)
  cleanup = () => {
    releaseTemplateVideos(document)
    observer.disconnect()
    document.removeEventListener('click', preventNavigation)
  }
  resize()
}

onBeforeUnmount(() => cleanup())
</script>

<template>
  <iframe
    ref="frame"
    class="article-fixed-content"
    :style="{ height: `${height}px` }"
    :srcdoc="sourceDocument"
    :title="label"
    sandbox="allow-same-origin"
    allow="autoplay; fullscreen"
    referrerpolicy="no-referrer"
    @load="onLoad"
  />
</template>

<style scoped lang="scss">
.article-fixed-content {
  display: block;
  width: 100%;
  min-width: 0;
  max-width: 100%;
  border: 0;
}
</style>

<script setup lang="ts">
import { computed } from 'vue'
import type { Article, LayoutTemplate } from '@/api/types'

const props = defineProps<{
  article: Article
  template?: LayoutTemplate | null
  compact?: boolean
}>()

const sourceDocument = computed(() => {
  const styles = props.template?.styles
  const titleSize = styles?.title.fontSize ?? 30
  const titleColor = styles?.title.color ?? '#17211b'
  const headingSize = styles?.heading1.fontSize ?? 22
  const headingColor = styles?.heading1.color ?? '#17211b'
  const bodySize = styles?.body.fontSize ?? 16
  const bodyColor = styles?.body.color ?? '#17211b'
  const bodyLine = styles?.body.lineHeight ?? 1.8
  const quoteBackground = styles?.quote.background ?? '#f4f7f5'
  const quoteColor = styles?.quote.color ?? '#526057'
  const marker = styles?.heading_marker
  const markerCss =
    marker?.enabled === true
      ? `body{counter-reset:heading-marker}h2::before{content:counter(heading-marker, decimal-leading-zero);counter-increment:heading-marker;display:block;margin:${marker.marginTop ?? 0}px 0 ${marker.spacing}px;color:${marker.color};background:${marker.background};font-size:${marker.fontSize}px;font-weight:${marker.fontWeight};line-height:${marker.lineHeight};text-align:${marker.align};padding:${marker.padding}px;overflow-wrap:anywhere}`
      : ''
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>
    *{box-sizing:border-box}html,body{margin:0;min-width:0;background:#fff;color:${bodyColor};font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}body{padding:${props.compact ? 24 : 48}px;overflow-wrap:anywhere}h1{margin:0 0 24px;color:${titleColor};font-size:${titleSize}px;line-height:1.3;overflow-wrap:anywhere}h2{margin:30px 0 14px;color:${headingColor};font-size:${headingSize}px;line-height:1.4;overflow-wrap:anywhere}p,li{color:${bodyColor};font-size:${bodySize}px;line-height:${bodyLine};overflow-wrap:anywhere}blockquote{margin:20px 0;padding:14px 18px;color:${quoteColor};background:${quoteBackground};border-left:4px solid #079455;overflow-wrap:anywhere}img{display:block;max-width:100%;height:auto;margin:18px auto;border-radius:10px}a{color:#087443;overflow-wrap:anywhere}
    ${markerCss}
  </style></head><body>${props.article.contentHtml}</body></html>`
})
</script>

<template>
  <article
    :class="['article-render', { 'article-render--compact': compact }]"
    aria-label="文章内容预览"
  >
    <iframe :srcdoc="sourceDocument" sandbox="" :title="`${article.title}内容预览`" />
  </article>
</template>

<style scoped lang="scss">
.article-render {
  width: min(100%, 720px);
  height: 100%;
  min-width: 0;
  min-height: 0;
  margin-inline: auto;
  background: var(--app-bg-surface);

  iframe {
    display: block;
    width: 100%;
    height: 100%;
    min-height: 720px;
    border: 0;
  }

  &--compact {
    width: 100%;
    iframe {
      min-height: 100%;
    }
  }
}
</style>

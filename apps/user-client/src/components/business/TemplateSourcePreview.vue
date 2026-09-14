<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { LayoutTemplate, ModuleKey, ModuleStyle } from '@/api/types'

const props = defineProps<{
  blocks: NonNullable<LayoutTemplate['contentBlocks']>
  title?: string
  selectedIds: string[]
  lockedGroups: NonNullable<LayoutTemplate['lockedBlocks']>
  editedStyles: Partial<Record<ModuleKey, ModuleStyle>>
}>()
const emit = defineEmits<{ toggle: [id: string, extend: boolean] }>()
const frame = ref<HTMLIFrameElement | null>(null)
let originalStyles = new Map<HTMLElement, string | null>()

// Only server-sanitized source fragments enter this script-free sandbox. Parent
// event listeners provide selection; source links cannot navigate the preview.
const sourceDocument = computed(
  () => `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src https: http: data:; style-src 'unsafe-inline'; script-src 'none'; form-action 'none'; base-uri 'none'">
<meta name="referrer" content="no-referrer"><style>
*{box-sizing:border-box}html,body{margin:0;min-width:0;font-family:system-ui,'Microsoft YaHei',sans-serif}
body{padding:16px;color:CanvasText;background:Canvas;color-scheme:light;overflow-wrap:anywhere}
main{max-width:680px;margin:auto;min-width:0}
.source-title{margin:0 0 24px;font-size:24px;line-height:1.4}
.source-block{display:grid;grid-template-columns:28px minmax(0,1fr);gap:8px;min-width:0;border:1px solid transparent;border-radius:6px}
.source-block[data-selected=true]{border-color:var(--app-action-primary);background:var(--app-action-soft)}
.source-block[data-locked=true]{border-color:var(--app-border-strong)}
.source-select{align-self:start;min-width:0;min-height:28px;padding:2px;border:1px solid var(--app-border-default);border-radius:6px;background:var(--app-bg-surface);color:var(--app-text-secondary);cursor:pointer;font:inherit;font-size:12px}
.source-select[aria-pressed=true]{background:var(--app-action-primary);color:var(--app-action-primary-text)}
.source-select:disabled{cursor:default;color:var(--app-action-primary)}
.source-select:focus-visible{outline:3px solid var(--app-focus);outline-offset:2px}
.source-content{min-width:0;max-width:100%;overflow-x:auto;overflow-wrap:anywhere}
.source-content *{max-width:100%;overflow-wrap:anywhere}
.source-content img{max-width:100%!important;height:auto!important}
.source-content table{max-width:100%;border-collapse:collapse}
.source-content pre{white-space:pre-wrap}
.source-content a{cursor:default}
</style></head><body><main><h1 class="source-title"></h1>${props.blocks
    .map(
      (block, index) =>
        `<section class="source-block" data-index="${index}"><button type="button" class="source-select" aria-label="选择第 ${index + 1} 部分" aria-pressed="false">${index + 1}</button><div class="source-content">${block.html}</div></section>`,
    )
    .join('')}</main></body></html>`,
)

const applyModuleStyle = (element: HTMLElement, style: ModuleStyle) => {
  if (!originalStyles.has(element)) originalStyles.set(element, element.getAttribute('style'))
  const css = element.style
  css.setProperty('font-size', `${style.fontSize}px`, 'important')
  css.setProperty('font-weight', style.fontWeight, 'important')
  css.setProperty('color', style.color, 'important')
  css.setProperty('background', style.background, 'important')
  css.setProperty('text-align', style.align, 'important')
  css.setProperty('line-height', String(style.lineHeight), 'important')
  css.setProperty('margin-top', `${style.marginTop ?? 0}px`, 'important')
  css.setProperty('margin-bottom', `${style.spacing}px`, 'important')
  css.setProperty('text-indent', `${style.textIndent ?? 0}px`, 'important')
  css.setProperty('padding', `${style.padding}px`, 'important')
  css.setProperty('border', style.borderAll ?? 'none', 'important')
  css.setProperty(
    'border-left',
    style.borderLeft || (style.border === 'left' ? '4px solid var(--app-action-primary)' : 'none'),
    'important',
  )
}

const syncState = () => {
  const document = frame.value?.contentDocument
  if (!document) return
  const selected = new Set(props.selectedIds)
  const locked = new Set(props.lockedGroups.flatMap((group) => group.blockIds))
  for (const [element, style] of originalStyles) {
    if (style === null) element.removeAttribute('style')
    else element.setAttribute('style', style)
  }
  const title = document.querySelector<HTMLElement>('.source-title')
  if (title) {
    title.textContent = props.title ?? ''
    title.hidden = !props.title
    if (props.editedStyles.title) applyModuleStyle(title, props.editedStyles.title)
  }
  const rows = document.querySelectorAll<HTMLElement>('main > .source-block')
  rows.forEach((row, index) => {
    const block = props.blocks[index]
    if (!block) return
    const isLocked = locked.has(block.id)
    row.dataset.selected = String(selected.has(block.id))
    row.dataset.locked = String(isLocked)
    const button = row.querySelector<HTMLButtonElement>(':scope > .source-select')
    if (button) {
      button.disabled = isLocked
      button.textContent = isLocked ? '锁' : selected.has(block.id) ? '✓' : String(index + 1)
      button.setAttribute('aria-pressed', String(selected.has(block.id)))
      button.setAttribute('aria-label', `${isLocked ? '已锁定' : '选择'}第 ${index + 1} 部分`)
      button.title = isLocked ? '在固定部分列表中解锁' : `选择第 ${index + 1} 部分`
    }
    const content = row.querySelector<HTMLElement>(':scope > .source-content')
    if (!content) return
    const module = block.module as ModuleKey
    const style = props.editedStyles[module]
    content.hidden = !isLocked && module === 'heading_marker' && style?.enabled === false
    if (isLocked) return
    if (style && !module.startsWith('table_')) {
      const selectors: Partial<Record<ModuleKey, string>> = {
        title: 'h1',
        heading1: 'h2',
        heading2: 'h3, h4, h5, h6',
        body: 'p',
        lead: 'p',
        quote: 'blockquote',
        list: 'ul, ol',
        caption: 'figcaption, p',
        divider: 'hr',
        highlight: 'p',
        heading_marker: 'p',
      }
      const matches = content.querySelectorAll<HTMLElement>(selectors[module] ?? ':scope > *')
      const elements = matches.length
        ? matches
        : content.querySelectorAll<HTMLElement>(':scope > *')
      elements.forEach((element) => applyModuleStyle(element, style))
      content.querySelectorAll<HTMLElement>('span, strong, em, a').forEach((element) => {
        if (!originalStyles.has(element)) originalStyles.set(element, element.getAttribute('style'))
        for (const property of ['font-size', 'color', 'line-height', 'font-weight']) {
          element.style.setProperty(property, 'inherit', 'important')
        }
      })
    }
    for (const [key, selector] of [
      ['table_header', 'th'],
      ['table_cell', 'td'],
    ] as const) {
      const tableStyle = props.editedStyles[key]
      if (tableStyle)
        content
          .querySelectorAll<HTMLElement>(selector)
          .forEach((element) => applyModuleStyle(element, tableStyle))
    }
  })
}

const onLoad = () => {
  const document = frame.value?.contentDocument
  if (!document || !frame.value) return
  originalStyles = new Map()
  const palette = getComputedStyle(frame.value)
  for (const token of [
    '--app-text-primary',
    '--app-text-secondary',
    '--app-bg-surface',
    '--app-border-default',
    '--app-border-strong',
    '--app-action-primary',
    '--app-action-soft',
    '--app-action-primary-text',
    '--app-focus',
  ]) {
    document.documentElement.style.setProperty(token, palette.getPropertyValue(token))
  }
  document.addEventListener('click', (event) => {
    const target = event.target as Element | null
    if (target?.closest('a')) event.preventDefault()
    const button = target?.closest<HTMLButtonElement>('.source-select')
    if (!button || button.disabled) return
    const index = Number(button.parentElement?.dataset.index)
    const block = props.blocks[index]
    if (block) emit('toggle', block.id, event.shiftKey)
  })
  syncState()
}
watch(() => [props.selectedIds, props.lockedGroups, props.editedStyles, props.title], syncState, {
  deep: true,
})
</script>

<template>
  <iframe
    ref="frame"
    class="template-source-preview"
    :srcdoc="sourceDocument"
    sandbox="allow-same-origin"
    referrerpolicy="no-referrer"
    title="完整文章预览，使用每部分左侧按钮选择固定内容"
    @load="onLoad"
  />
</template>

<style scoped lang="scss">
.template-source-preview {
  display: block;
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  background: var(--app-bg-surface);
  border: 1px solid var(--app-border-default);
  border-radius: 10px;
}
</style>

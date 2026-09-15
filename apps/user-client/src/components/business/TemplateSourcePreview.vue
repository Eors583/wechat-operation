<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type { LayoutTemplate, ModuleKey, ModuleStyle } from '@/api/types'
import AppButton from '@/components/base/AppButton.vue'
import {
  playTemplateVideo,
  prepareTemplateVideos,
  releaseTemplateVideos,
} from '@/utils/templateMedia'

const props = defineProps<{
  blocks: NonNullable<LayoutTemplate['contentBlocks']>
  title?: string
  sourceUrl?: string
  selectedIds: string[]
  lockedGroups: NonNullable<LayoutTemplate['lockedBlocks']>
  editedStyles: Partial<Record<ModuleKey, ModuleStyle>>
  canLock: boolean
  busy: boolean
}>()
const emit = defineEmits<{
  toggle: [id: string, extend: boolean]
  select: [ids: string[], endId: string]
  lock: [position: 'before_body' | 'after_body']
  unlock: [blockId: string]
  edit: [blockId: string]
  clear: []
}>()
const frame = ref<HTMLIFrameElement | null>(null)
const selecting = ref(false)
let originalStyles = new Map<HTMLElement, string | null>()
let cleanupSelection = () => {}

// Imported content is script-free; parent listeners provide native video playback and selection. Parent
// event listeners provide selection; source links cannot navigate the preview.
const sourceDocument = computed(
  () => `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src https: http: data:; style-src 'unsafe-inline'; script-src 'none'; media-src blob:; form-action 'none'; base-uri 'none'">
<meta name="referrer" content="no-referrer"><style>
*{box-sizing:border-box}html,body{margin:0;min-width:0;font-family:system-ui,'Microsoft YaHei',sans-serif}
body{padding:16px;color:CanvasText;background:Canvas;color-scheme:light;overflow-wrap:anywhere}
main{max-width:680px;margin:auto;min-width:0}
.source-title{margin:0 0 24px;font-size:24px;line-height:1.4}
.source-block{display:grid;grid-template-columns:28px minmax(0,1fr);gap:8px;min-width:0;border:1px solid transparent;border-radius:6px}
.source-block[data-selected=true]{border-color:var(--app-action-primary);background:var(--app-action-soft)}
.source-block[data-locked=true]{border-color:var(--app-action-primary);background:var(--app-action-soft);border-radius:0}
.source-block[data-lock-start=true]{border-top-left-radius:6px;border-top-right-radius:6px}
.source-block[data-lock-end=true]{border-bottom-left-radius:6px;border-bottom-right-radius:6px}
.source-block,.source-block *{user-select:none!important;-webkit-user-select:none!important;-webkit-touch-callout:none}
.source-block[data-locked=false]{cursor:crosshair}
html[data-selecting=true],html[data-selecting=true] *{cursor:crosshair!important}
.source-unlock{grid-column:1/-1;min-width:0;min-height:36px;padding:6px 10px;border:0;text-align:left;overflow-wrap:anywhere;background:var(--app-action-soft);color:var(--app-action-primary);font:inherit;font-size:12px;cursor:pointer}
.source-unlock[hidden]{display:none}
.source-edit:not([hidden]){opacity:0;pointer-events:none}
.source-block:hover>.source-edit,.source-block:focus-within>.source-edit{opacity:1;pointer-events:auto}
@media(hover:none){.source-edit:not([hidden]){opacity:1;pointer-events:auto}}
.source-select{align-self:start;min-width:0;min-height:28px;padding:2px;border:1px solid var(--app-border-default);border-radius:6px;background:var(--app-bg-surface);color:var(--app-text-secondary);cursor:pointer;font:inherit;font-size:12px}
.source-select[aria-pressed=false]:not(:focus-visible){opacity:0}
.source-select[aria-pressed=true]{background:var(--app-action-primary);color:var(--app-action-primary-text)}
.source-select:disabled{cursor:default;color:var(--app-action-primary)}
.source-select:focus-visible,.source-unlock:focus-visible{outline:3px solid var(--app-focus);outline-offset:2px}
.source-content{min-width:0;max-width:100%;overflow-x:auto;overflow-wrap:anywhere}
.source-content *{max-width:100%;overflow-wrap:anywhere}
.source-content img{max-width:100%!important;height:auto!important}
.source-content table{max-width:100%;border-collapse:collapse}
.source-content pre{white-space:pre-wrap}
.source-content a{cursor:default}.source-content a>span{cursor:pointer}
</style></head><body><main><h1 class="source-title"></h1>${props.blocks
    .map(
      (block, index) =>
        `<section class="source-block" data-index="${index}"><button type="button" class="source-edit source-unlock" hidden>修改固定内容</button><button type="button" class="source-unlock" hidden></button><button type="button" class="source-select" aria-label="选择第 ${index + 1} 部分" aria-pressed="false"></button><div class="source-content">${block.html}</div></section>`,
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

const syncSelection = () => {
  const document = frame.value?.contentDocument
  if (!document) return
  const selected = new Set(props.selectedIds)
  const groups = new Map(
    props.lockedGroups.flatMap((group) => group.blockIds.map((id) => [id, group] as const)),
  )
  document.querySelectorAll<HTMLElement>('main > .source-block').forEach((row, index) => {
    const block = props.blocks[index]
    if (!block) return
    const group = groups.get(block.id)
    row.dataset.selected = String(selected.has(block.id))
    row.dataset.locked = String(!!group)
    const startsGroup = !!group && groups.get(props.blocks[index - 1]?.id ?? '') !== group
    row.dataset.lockStart = String(startsGroup)
    row.dataset.lockEnd = String(!!group && groups.get(props.blocks[index + 1]?.id ?? '') !== group)
    const button = row.querySelector<HTMLButtonElement>(':scope > .source-select')
    if (button) {
      button.disabled = !!group || props.busy
      button.style.visibility = group ? 'hidden' : 'visible'
      button.textContent = selected.has(block.id) ? '✓' : ''
      button.setAttribute('aria-pressed', String(selected.has(block.id)))
      button.setAttribute('aria-label', `选择第 ${index + 1} 部分`)
      button.title = `选择第 ${index + 1} 部分`
    }
    const edit = row.querySelector<HTMLButtonElement>(':scope > .source-edit')
    if (edit) {
      edit.hidden = !group
      edit.disabled = props.busy
    }
    const unlock = row.querySelector<HTMLButtonElement>(':scope > .source-unlock:not(.source-edit)')
    if (unlock) {
      unlock.hidden = !startsGroup
      unlock.disabled = props.busy
      if (group) {
        const placement =
          group.position === 'before_body'
            ? '开头'
            : group.position === 'after_body'
              ? '结尾'
              : `第 ${group.paragraphIndex} 段后`
        unlock.textContent = `已固定到${placement} · 解锁`
        unlock.setAttribute('aria-label', `解锁固定到${placement}的这一组内容`)
      }
    }
  })
}

const syncStyles = () => {
  const document = frame.value?.contentDocument
  if (!document) return
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
  cleanupSelection()
  const document = frame.value?.contentDocument
  const previewWindow = document?.defaultView
  if (!document || !previewWindow || !frame.value) return
  prepareTemplateVideos(document)
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
  const listeners = new AbortController()
  const options = { signal: listeners.signal }
  const rows = Array.from(document.querySelectorAll<HTMLElement>('main > .source-block'))
  let press: {
    index: number
    x: number
    y: number
    currentY: number
    baseline: string[]
    pointerId?: number
    touchId?: number
    active: boolean
    moved: boolean
    end: number
  } | null = null
  let holdTimer = 0
  let scrollFrame = 0
  let suppressClickUntil = 0

  const finish = () => {
    window.clearTimeout(holdTimer)
    window.cancelAnimationFrame(scrollFrame)
    const previous = press
    press = null
    selecting.value = false
    delete document.documentElement.dataset.selecting
    if (previous?.active) suppressClickUntil = Date.now() + 500
    if (
      previous?.pointerId !== undefined &&
      document.documentElement.hasPointerCapture(previous.pointerId)
    )
      document.documentElement.releasePointerCapture(previous.pointerId)
  }
  const selectTo = (end: number) => {
    if (!press?.active || end === press.end) return
    press.end = end
    const locked = new Set(props.lockedGroups.flatMap((group) => group.blockIds))
    const range = props.blocks
      .slice(Math.min(press.index, end), Math.max(press.index, end) + 1)
      .map((block) => block.id)
      .filter((id) => !locked.has(id))
    emit('select', [...new Set([...press.baseline, ...range])], props.blocks[end]?.id ?? '')
  }
  const selectAtPointer = () => {
    if (!press?.active || !rows.length) return
    // Rows stay in article order; find the range endpoint without scanning a long article.
    const y = Math.max(0, Math.min(previewWindow.innerHeight - 1, press.currentY))
    let low = 0
    let high = rows.length - 1
    while (low < high) {
      const middle = Math.floor((low + high) / 2)
      if (rows[middle]!.getBoundingClientRect().bottom < y) low = middle + 1
      else high = middle
    }
    selectTo(low)
  }
  let previousScrollTime = 0
  const autoScroll = (time: number) => {
    if (!press?.active) return
    const edge = Math.min(56, previewWindow.innerHeight / 4)
    const y = press.currentY
    const speed =
      y < edge
        ? -Math.min(1, (edge - y) / edge)
        : y > previewWindow.innerHeight - edge
          ? Math.min(1, (y - previewWindow.innerHeight + edge) / edge)
          : 0
    if (press.moved && speed) {
      previewWindow.scrollBy(0, speed * Math.min(32, time - previousScrollTime) * 0.6)
      selectAtPointer()
    }
    previousScrollTime = time
    scrollFrame = window.requestAnimationFrame(autoScroll)
  }
  const activate = () => {
    if (!press || press.active) return
    window.clearTimeout(holdTimer)
    press.active = true
    selecting.value = true
    document.documentElement.dataset.selecting = 'true'
    document.getSelection()?.removeAllRanges()
    if (press.pointerId !== undefined) document.documentElement.setPointerCapture(press.pointerId)
    selectTo(press.index)
    previousScrollTime = performance.now()
    scrollFrame = window.requestAnimationFrame(autoScroll)
  }
  const begin = (
    target: EventTarget | null,
    x: number,
    y: number,
    pointerId?: number,
    touchId?: number,
  ) => {
    finish()
    suppressClickUntil = 0
    if (
      props.busy ||
      (target as Element | null)?.closest(
        '.source-unlock, [data-video-play], [data-template-video], video',
      )
    )
      return
    const row = (target as Element | null)?.closest<HTMLElement>('main > .source-block')
    if (!row || row.dataset.locked === 'true') return
    press = {
      index: Number(row.dataset.index),
      x,
      y,
      currentY: y,
      baseline: [...props.selectedIds],
      pointerId,
      touchId,
      active: false,
      moved: false,
      end: -1,
    }
    holdTimer = window.setTimeout(activate, 350)
  }
  const move = (x: number, y: number) => {
    if (!press) return
    const moved = Math.hypot(x - press.x, y - press.y) > 5
    if (!press.active) {
      if (!moved) return
      if (press.pointerId === undefined) {
        finish()
        return
      }
      activate()
    }
    press.currentY = y
    press.moved ||= moved
    selectAtPointer()
  }
  document.addEventListener(
    'pointerdown',
    (event) => {
      if (event.pointerType === 'touch') return
      if (!event.isPrimary || event.button !== 0) {
        finish()
        return
      }
      begin(event.target, event.clientX, event.clientY, event.pointerId)
    },
    options,
  )
  document.addEventListener(
    'pointermove',
    (event) => {
      if (press?.pointerId !== event.pointerId) return
      if (!(event.buttons & 1)) {
        finish()
        return
      }
      move(event.clientX, event.clientY)
    },
    options,
  )
  const finishPointer = (event: PointerEvent) => {
    if (press?.pointerId === event.pointerId) finish()
  }
  document.addEventListener('pointerup', finishPointer, options)
  document.addEventListener('pointercancel', finishPointer, options)
  document.addEventListener('lostpointercapture', finishPointer, options)
  window.addEventListener('pointerup', finishPointer, options)
  document.addEventListener(
    'pointerleave',
    () => {
      if (!press?.active) finish()
    },
    options,
  )
  // Cancel native scrolling only after the hold, so an ordinary swipe still scrolls.
  document.addEventListener(
    'touchstart',
    (event) => {
      if (event.touches.length !== 1) {
        finish()
        return
      }
      const touch = event.touches[0]!
      begin(event.target, touch.clientX, touch.clientY, undefined, touch.identifier)
    },
    { ...options, passive: true },
  )
  document.addEventListener(
    'touchmove',
    (event) => {
      const touch = Array.from(event.touches).find((item) => item.identifier === press?.touchId)
      if (!touch) return
      if (press?.active) event.preventDefault()
      move(touch.clientX, touch.clientY)
    },
    { ...options, passive: false },
  )
  document.addEventListener('touchend', finish, options)
  document.addEventListener('touchcancel', finish, options)
  document.addEventListener('dragstart', (event) => event.preventDefault(), options)
  document.addEventListener(
    'contextmenu',
    (event) => {
      if (press) event.preventDefault()
    },
    options,
  )
  document.addEventListener(
    'keydown',
    (event) => {
      if (event.key === 'Escape') finish()
    },
    options,
  )
  previewWindow.addEventListener('blur', finish, options)
  previewWindow.addEventListener(
    'scroll',
    () => {
      if (press?.active) selectAtPointer()
      else finish()
    },
    options,
  )
  document.addEventListener(
    'visibilitychange',
    () => {
      if (document.hidden) finish()
    },
    options,
  )
  document.addEventListener(
    'click',
    (event) => {
      const target = event.target as Element | null
      if (target?.closest('a')) event.preventDefault()
      if (props.busy || target?.closest('video')) return
      if (target?.closest('[data-video-play]') && playTemplateVideo(target, props.sourceUrl)) return
      if (target?.closest('[data-template-video]')) return
      if (event.detail !== 0 && Date.now() < suppressClickUntil) {
        event.preventDefault()
        return
      }
      const row = target?.closest<HTMLElement>('main > .source-block')
      if (!row) return
      const index = Number(row.dataset.index)
      const block = props.blocks[index]
      if (target?.closest('.source-edit')) {
        if (block) emit('edit', block.id)
        return
      }
      if (target?.closest('.source-unlock')) {
        if (block) emit('unlock', block.id)
        return
      }
      if (row.dataset.locked === 'true') return
      if (block) emit('toggle', block.id, event.shiftKey)
    },
    options,
  )
  cleanupSelection = () => {
    releaseTemplateVideos(document)
    finish()
    listeners.abort()
  }
  syncSelection()
  syncStyles()
}
onBeforeUnmount(() => cleanupSelection())
watch(sourceDocument, () => cleanupSelection(), { flush: 'sync' })
watch(() => [props.selectedIds, props.lockedGroups, props.busy], syncSelection, { deep: true })
watch(() => [props.lockedGroups, props.editedStyles, props.title], syncStyles, {
  deep: true,
})
</script>

<template>
  <div class="template-source-preview">
    <iframe
      ref="frame"
      class="template-source-preview__frame"
      :srcdoc="sourceDocument"
      sandbox="allow-same-origin"
      allow="autoplay; fullscreen"
      referrerpolicy="no-referrer"
      title="完整文章预览，拖动或点击内容选择固定部分，触屏可长按拖动"
      @load="onLoad"
    />
    <div class="template-source-preview__actions">
      <span aria-live="polite">{{
        selectedIds.length ? `已选 ${selectedIds.length} 部分` : '点击内容或拖动选择'
      }}</span>
      <AppButton
        variant="ghost"
        label="取消选择"
        :disabled="!selectedIds.length || busy || selecting"
        @click="emit('clear')"
      />
      <div class="template-source-preview__placements">
        <AppButton
          label="固定到开头"
          icon="vertical_align_top"
          :disabled="!selectedIds.length || !canLock || selecting"
          @click="emit('lock', 'before_body')"
        />
        <AppButton
          label="固定到结尾"
          icon="vertical_align_bottom"
          :disabled="!selectedIds.length || !canLock || selecting"
          @click="emit('lock', 'after_body')"
        />
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.template-source-preview {
  display: flex;
  flex-direction: column;
  width: 100%;
  min-width: 0;
  min-height: 0;
  background: var(--app-bg-surface);
  border: 1px solid var(--app-border-default);
  border-radius: 10px;

  &__frame {
    display: block;
    flex: 1 1 auto;
    width: 100%;
    min-width: 0;
    min-height: 0;
    border: 0;
    border-radius: inherit;
  }

  &__actions {
    display: flex;
    flex: 0 0 auto;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    min-width: 0;
    padding: 8px 12px;
    border-top: 1px solid var(--app-border-default);

    > span {
      flex: 1 1 auto;
      min-width: 0;
      color: var(--app-text-secondary);
      font-size: 12px;
      overflow-wrap: anywhere;
    }
  }

  &__placements {
    display: grid;
    flex: 1 1 100%;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
    min-width: 0;
  }

  .app-button {
    min-width: 0;
    padding-inline: 8px;
    overflow-wrap: anywhere;
  }
}
</style>

<script setup lang="ts">
import { ref, watch } from 'vue'
import type { LayoutContentBlock } from '@/api/types'
import AppDialog from '@/components/base/AppDialog.vue'
import AppButton from '@/components/base/AppButton.vue'

const props = withDefaults(
  defineProps<{ modelValue: boolean; blocks: LayoutContentBlock[]; applyLabel?: string }>(),
  { applyLabel: '确认修改' },
)
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  apply: [blocks: LayoutContentBlock[]]
}>()
type Field = { node: Text | Element; value: string; kind: 'text' | 'image' | 'video' }
const fields = ref<Field[]>([])
let drafts: { block: LayoutContentBlock; document: Document }[] = []
const error = ref('')
watch(
  () => props.modelValue,
  (open) => {
    if (!open) return
    error.value = ''
    const entries: Field[] = []
    drafts = props.blocks.map((block) => {
      const document = new DOMParser().parseFromString(block.html, 'text/html')
      const walker = document.createTreeWalker(
        document.body,
        NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT,
      )
      while (walker.nextNode()) {
        const node = walker.currentNode
        const parent = node.nodeType === Node.TEXT_NODE ? node.parentElement : (node as Element)
        const video = parent?.closest('a[data-mpvid], a[href*="action=mpvideo"]')
        if (video === node)
          entries.push({ node: video, value: video.getAttribute('href') ?? '', kind: 'video' })
        if (parent?.closest('[data-profile-card]') || video) continue
        if (node.nodeType === Node.TEXT_NODE && node.textContent?.trim()) {
          entries.push({ node: node as Text, value: node.textContent, kind: 'text' })
        } else if (node.nodeName === 'IMG') {
          entries.push({
            node: node as HTMLImageElement,
            value: (node as HTMLImageElement).getAttribute('src') ?? '',
            kind: 'image',
          })
        }
      }
      return { block, document }
    })
    fields.value = entries
  },
)
const apply = () => {
  error.value = ''
  for (const field of fields.value) {
    if (field.kind === 'text') continue
    try {
      const url = new URL(field.value.trim())
      if (url.protocol !== 'https:' || url.username || url.password) throw new Error()
      if (
        field.kind === 'video' &&
        (url.origin !== 'https://mp.weixin.qq.com' ||
          url.pathname !== '/mp/readtemplate' ||
          url.searchParams.get('action') !== 'mpvideo' ||
          !/^wxv_[0-9]+$/.test(url.searchParams.get('vid') ?? ''))
      )
        throw new Error()
    } catch {
      error.value =
        field.kind === 'video' ? '请填写有效的微信视频播放链接。' : '请填写有效的 HTTPS 图片链接。'
      return
    }
  }
  for (const field of fields.value) {
    if (field.kind === 'text') field.node.textContent = field.value
    else if (field.kind === 'video') {
      const video = field.node as Element
      const url = new URL(field.value.trim())
      video.setAttribute('href', url.href)
      video.setAttribute('data-src', url.href)
      video.setAttribute('data-mpvid', url.searchParams.get('vid')!)
    } else {
      const image = field.node as HTMLImageElement
      image.setAttribute('src', field.value.trim())
      image.removeAttribute('srcset')
      image.removeAttribute('data-src')
    }
  }
  emit(
    'apply',
    drafts.map(({ block, document }) => ({
      ...block,
      html: document.body.innerHTML,
      text: document.body.textContent ?? '',
    })),
  )
  emit('update:modelValue', false)
}
</script>

<template>
  <AppDialog
    :model-value="modelValue"
    title="修改固定内容"
    width="760px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="locked-editor">
      <div v-for="(field, index) in fields" :key="index" class="locked-editor__field">
        <q-input
          v-if="field.kind === 'text'"
          v-model="field.value"
          outlined
          type="textarea"
          label="文字"
          :rows="3"
        />
        <q-input
          v-else-if="field.kind === 'video'"
          v-model="field.value"
          outlined
          label="替换微信视频链接"
        />
        <template v-else>
          <img
            :src="/^https:\/\//.test(field.value) ? field.value : undefined"
            alt="待替换图片"
            referrerpolicy="no-referrer"
          />
          <q-input v-model="field.value" outlined label="替换图片链接" placeholder="https://…" />
        </template>
      </div>
      <p v-if="!fields.length">这一组没有可修改的文字、图片或视频。</p>
      <p v-if="error" role="alert" class="text-negative">{{ error }}</p>
    </div>
    <template #actions>
      <AppButton flat label="取消" @click="emit('update:modelValue', false)" />
      <AppButton color="primary" :label="applyLabel" :disable="!fields.length" @click="apply" />
    </template>
  </AppDialog>
</template>

<style scoped lang="scss">
.locked-editor {
  display: grid;
  gap: 16px;
  min-width: 0;
  padding: 20px;

  &__field {
    display: grid;
    gap: 8px;
    min-width: 0;
  }

  img {
    max-width: 100%;
    max-height: 240px;
    object-fit: contain;
  }

  :deep(textarea) {
    min-width: 0;
    max-width: 100%;
    overflow-y: auto;
    overflow-wrap: anywhere;
  }
}
</style>

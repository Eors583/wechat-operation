<script setup lang="ts">
import type { LibraryItem } from '@/api/types'
import AppButton from '@/components/base/AppButton.vue'
import AppDialog from '@/components/base/AppDialog.vue'

defineProps<{
  modelValue: boolean
  item: LibraryItem | null
  loading?: boolean
  reparsing?: boolean
}>()
defineEmits<{ 'update:modelValue': [value: boolean]; retry: [item: LibraryItem] }>()
</script>

<template>
  <AppDialog
    :model-value="modelValue"
    :title="item?.title ?? '文件预览'"
    width="980px"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <div v-if="item" class="file-preview">
      <header class="file-preview__toolbar">
        <span>{{ item.fileType ?? '资料' }}</span>
        <span v-if="item.pageCount">{{ item.pageCount }} 页</span>
        <span v-if="item.parserVersion">解析器 {{ item.parserVersion }}</span>
      </header>
      <main class="file-preview__canvas">
        <div v-if="loading" class="file-preview__loading">
          <q-spinner color="primary" size="38px" />
          <span>正在读取解析结果…</span>
        </div>
        <article v-else>
          <q-icon name="description" size="38px" color="primary" />
          <h1>{{ item.title }}</h1>
          <p>{{ item.summary }}</p>
          <h2>解析文字</h2>
          <pre v-if="item.extractedText">{{ item.extractedText }}</pre>
          <q-banner v-else rounded
            >服务端尚未提供可预览的解析文字。这里只显示真实解析结果，不生成模拟页码或正文。</q-banner
          >
          <q-banner rounded>
            资料状态：{{
              item.status === 'ready'
                ? '已读取，可以用于 AI 创作'
                : item.status === 'failed'
                  ? '解析失败，不会用于 AI 创作'
                  : '正在读取，完成前不会用于 AI 创作'
            }}
          </q-banner>
        </article>
      </main>
    </div>
    <template v-if="item?.type === 'reference' && item.status === 'failed'" #actions>
      <AppButton variant="outline" label="关闭" @click="$emit('update:modelValue', false)" />
      <AppButton
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
  height: min(72vh, 780px);

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
    padding: clamp(16px, 4vw, 44px);
    overflow: auto;
    background: var(--app-bg-subtle);

    article {
      width: min(100%, 760px);
      min-height: 560px;
      margin-inline: auto;
      padding: clamp(24px, 6vw, 64px);
      overflow-wrap: anywhere;
      background: var(--app-bg-surface);
      box-shadow: var(--app-shadow-sm);
    }

    h1 {
      margin: 18px 0 8px;
      font-size: clamp(24px, 4vw, 34px);
    }
    h2 {
      margin-top: 36px;
    }
    p {
      line-height: 1.8;
    }
    pre {
      margin: 0 0 24px;
      font: inherit;
      line-height: 1.8;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
    .q-banner {
      margin-top: 18px;
      background: var(--app-bg-subtle);
      overflow-wrap: anywhere;
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
  .file-preview__canvas article {
    min-height: 520px;
  }
}
</style>

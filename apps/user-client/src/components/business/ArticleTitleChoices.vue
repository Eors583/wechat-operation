<script setup lang="ts">
import { computed } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { api } from '@/api/client'
import type { Article } from '@/api/types'
import AppButton from '@/components/base/AppButton.vue'

const props = defineProps<{
  article: Article
  title: string
  disabled?: boolean
}>()
defineEmits<{ choose: [title: string] }>()
const titleOptionsQuery = useQuery({
  queryKey: computed(() => [
    'article-title-options',
    props.article.id,
    props.article.taskId,
    props.article.versionNo,
  ]),
  enabled: computed(() => Boolean(props.article.taskId)),
  refetchInterval: (query) => (query.state.data?.activeRun ? 3000 : false),
  queryFn: async () => {
    const current = props.article
    const bundle = await api.getTask(current.taskId)
    let messages = bundle.messages
    let cursor = bundle.messagesNextCursor
    const visited = new Set<string>()
    const state = {
      activeRun: ['accepted', 'running'].includes(bundle.latestAiRun?.status ?? ''),
    }
    while (true) {
      const match = messages
        .filter(
          (message) =>
            message.titleArticleId === current.id &&
            message.titleCandidates !== undefined &&
            (message.articleVersionNo ?? 0) <= current.versionNo,
        )
        .sort(
          (left, right) =>
            (right.articleVersionNo ?? 0) - (left.articleVersionNo ?? 0) ||
            right.createdAt.localeCompare(left.createdAt),
        )[0]
      if (match) return { ...state, titles: match.titleCandidates ?? [] }
      if (!cursor || visited.has(cursor)) return { ...state, titles: [] as string[] }
      visited.add(cursor)
      const page = await api.listTaskMessages(current.taskId, cursor)
      messages = page.items
      cursor = page.nextCursor
    }
  },
})
const titleOptions = computed(() => {
  const titles = titleOptionsQuery.data.value?.titles ?? []
  return [...new Set((titles.length ? titles : [props.article.title]).filter(Boolean))]
})
</script>
<template>
  <aside class="article-title-options q-pa-md" aria-label="备选标题">
    <h2 class="text-subtitle1 q-ma-none q-mb-sm">备选标题</h2>
    <q-spinner
      v-if="titleOptionsQuery.isPending.value && article.taskId"
      color="primary"
      aria-label="加载备选标题"
    />
    <q-list class="article-title-options__list" role="group" aria-label="选择文章标题">
      <q-item
        v-for="(option, index) in titleOptions"
        :key="option"
        clickable
        tag="button"
        type="button"
        :active="option === title"
        :aria-pressed="option === title"
        :disable="disabled"
        class="article-title-options__item q-mb-sm"
        active-class="article-title-options__item--selected"
        @click="$emit('choose', option)"
      >
        <q-item-section side>{{ index + 1 }}</q-item-section>
        <q-item-section class="article-title-options__label">{{ option }}</q-item-section>
        <q-item-section v-if="option === title" side
          ><q-icon name="check" color="primary" size="18px"
        /></q-item-section>
      </q-item>
    </q-list>
    <AppButton
      v-if="titleOptionsQuery.isError.value"
      variant="outline"
      label="重新加载"
      :loading="titleOptionsQuery.isFetching.value"
      full-width
      @click="titleOptionsQuery.refetch()"
    />
  </aside>
</template>
<style scoped lang="scss">
.article-title-options {
  min-width: 0;
  min-height: 0;
  overflow-y: auto;
  background: var(--app-bg-surface);
  border-right: 1px solid var(--app-border-default);
}
.article-title-options__list,
.article-title-options__label {
  min-width: 0;
  overflow-wrap: anywhere;
}
.article-title-options__item {
  width: 100%;
  min-width: 0;
  border: 1px solid var(--app-border-default);
  border-radius: $generic-border-radius;
  color: var(--app-text-primary);
  background: var(--app-bg-surface);
  text-align: left;
  font: inherit;
}
.article-title-options__item--selected {
  border-color: var(--app-action-primary);
  background: var(--app-action-soft);
}
</style>

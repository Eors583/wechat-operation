import { computed, toValue, type MaybeRefOrGetter } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { api } from '@/api/client'
import type { LayoutTemplate } from '@/api/types'

export const useArticleFixedContent = (
  template: MaybeRefOrGetter<LayoutTemplate | null | undefined>,
) => {
  const selected = computed(() => toValue(template))
  const hasContent = computed(
    () =>
      Array.isArray(selected.value?.contentBlocks) && Array.isArray(selected.value?.lockedBlocks),
  )
  const needsVersion = computed(() =>
    Boolean(selected.value?.id && selected.value.versionId && !hasContent.value),
  )
  const query = useQuery({
    queryKey: computed(
      () =>
        [
          'layout-template-version',
          selected.value?.id ?? '',
          selected.value?.versionId ?? '',
        ] as const,
    ),
    queryFn: ({ queryKey }) => api.getTemplateVersion(queryKey[1], queryKey[2]),
    enabled: needsVersion,
    staleTime: Infinity,
    retry: false,
  })
  const resolved = computed(() => {
    if (hasContent.value) return selected.value
    const loaded = query.data.value
    return needsVersion.value &&
      loaded?.id === selected.value?.id &&
      loaded?.versionId === selected.value?.versionId
      ? loaded
      : undefined
  })
  const fragments = computed(() => {
    const result = { beforeHtml: '', afterHtml: '' }
    const blocks = new Map(resolved.value?.contentBlocks?.map((block) => [block.id, block.html]))
    for (const group of resolved.value?.lockedBlocks ?? []) {
      if (group.position !== 'before_body' && group.position !== 'after_body') continue
      const html = group.blockIds.map((id) => blocks.get(id) ?? '').join('')
      const key = group.position === 'before_body' ? 'beforeHtml' : 'afterHtml'
      result[key] += `<section data-template-locked="true">${html}</section>`
    }
    return result
  })
  const error = computed(() => {
    if (!needsVersion.value || !query.error.value) return ''
    return query.error.value instanceof Error
      ? query.error.value.message
      : '固定内容加载失败，请重试。'
  })
  const retry = () => {
    if (needsVersion.value) void query.refetch()
  }
  return {
    sourceUrl: computed(() => resolved.value?.sourceUrl),
    beforeHtml: computed(() => fragments.value.beforeHtml),
    afterHtml: computed(() => fragments.value.afterHtml),
    loading: computed(() => needsVersion.value && query.isFetching.value),
    error,
    retry,
  }
}

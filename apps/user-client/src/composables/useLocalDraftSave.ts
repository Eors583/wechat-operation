import { onScopeDispose, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useQuasar } from 'quasar'
import { api } from '@/api/client'
import type { Article, Project } from '@/api/types'
import { queryClient } from '@/boot/query'

export function useLocalDraftSave() {
  const $q = useQuasar()
  const router = useRouter()
  const saving = ref(false)
  let active = true
  let confirmation: ReturnType<typeof $q.dialog> | undefined
  onScopeDispose(() => {
    active = false
    confirmation?.hide()
  })

  const projectLabel = async (id: string | null) => {
    if (!id) return '未分类'
    const cached = queryClient
      .getQueriesData<{ pages: { items: Project[] }[] }>({ queryKey: ['projects'] })
      .flatMap(([, data]) => data?.pages.flatMap((page) => page.items) ?? [])
      .find((project) => project.id === id)
    if (cached) return cached.name
    try {
      let cursor: string | undefined
      const visited = new Set<string>()
      do {
        const page = await api.listProjectsPage(cursor)
        const project = page.items.find((item) => item.id === id)
        if (project) return project.name
        cursor = page.nextCursor
        if (cursor && visited.has(cursor)) break
        if (cursor) visited.add(cursor)
      } while (cursor)
    } catch {
      // Resolving a label must not turn a successful save into a reported failure.
    }
    return '所属项目'
  }

  const save = async (prepare: () => Promise<Article | null>) => {
    if (saving.value) return
    saving.value = true
    try {
      const article = await prepare()
      if (!article) return
      const saved = await api.setArticleOutcome({
        id: article.id,
        outcome: 'local_draft',
        idempotencyKey: crypto.randomUUID(),
      })
      queryClient.setQueryData(['article', saved.id], saved)
      await queryClient.invalidateQueries({ queryKey: ['library'] })
      const project = await projectLabel(saved.projectId)
      if (!active) return
      confirmation?.hide()
      confirmation = $q
        .dialog({
          title: '本地草稿保存成功',
          message: `已保存到：文章库 → ${project} → 文章（本地草稿）。`,
          html: false,
          cardStyle: { overflowWrap: 'anywhere' },
          ok: { label: '跳转到草稿箱', color: 'primary', noCaps: true },
          cancel: { label: '返回', flat: true, color: 'primary', noCaps: true },
        })
        .onOk(() => {
          void router.push({
            name: 'library',
            query: {
              project: saved.projectId ?? 'unclassified',
              type: 'article',
              status: 'local_draft',
            },
          })
        })
    } catch (error) {
      $q.notify({
        type: 'negative',
        message: error instanceof Error ? error.message : '本地草稿没有保存完成。',
      })
    } finally {
      saving.value = false
    }
  }

  return { saving, save }
}

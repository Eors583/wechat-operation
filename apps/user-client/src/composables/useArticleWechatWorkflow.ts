import { computed, onScopeDispose, ref, shallowRef, watch } from 'vue'
import { useQuasar } from 'quasar'
import { api } from '@/api/client'
import type {
  Article,
  ArticleRenderPreview,
  LayoutTemplate,
  OfficialAccount,
  PendingArticleOutcome,
} from '@/api/types'
import { queryClient } from '@/boot/query'
import { platform } from '@/platform'

export function useArticleWechatWorkflow(options: {
  article: () => Article | null
  account: () => OfficialAccount | null
  template: () => LayoutTemplate | null
  save: () => Promise<Article | null>
  blocked: () => boolean
}) {
  const $q = useQuasar()
  const coverAssetId = ref<string | null>(null)
  const coverName = ref('')
  const coverUploading = ref(false)
  const preparing = ref(false)
  const submitting = ref(false)
  const actionLabel = ref('正在存入草稿箱…')
  const loadingGroup = `wechat-outcome-${crypto.randomUUID()}`
  watch([preparing, submitting], ([prepare, submit]) => {
    if (prepare || submit)
      $q.loading.show({ group: loadingGroup, message: actionLabel.value, delay: 0 })
    else $q.loading.hide(loadingGroup)
  }, { flush: 'sync' })
  const visible = ref(false)
  const pending = ref<PendingArticleOutcome | null>(null)
  const locked = shallowRef<{
    article: Article
    account: OfficialAccount
    template: LayoutTemplate
    render: ArticleRenderPreview
    action: 'draft' | 'publish'
    key: string
    coverName: string
  } | null>(null)
  const busy = computed(() => coverUploading.value || preparing.value || submitting.value)
  let active = true
  onScopeDispose(() => {
    active = false
    $q.loading.hide(loadingGroup)
  })
  const current = (id: string) => active && options.article()?.id === id
  const notifyError = (error: unknown, fallback: string) => {
    if (active)
      $q.notify({ type: 'negative', message: error instanceof Error ? error.message : fallback })
  }
  watch(
    () => options.article()?.id,
    (id) => {
      coverAssetId.value = null
      coverName.value = ''
      visible.value = false
      locked.value = null
      pending.value = id ? api.getPendingArticleOutcome(id) : null
      if (id)
        void api
          .refreshPendingArticleOutcome(id)
          .then((value) => {
            if (current(id)) pending.value = value
          })
          .catch(() => undefined)
    },
    { immediate: true },
  )

  const chooseCover = async () => {
    const article = options.article()
    if (!article || busy.value || options.blocked() || pending.value) return
    coverUploading.value = true
    try {
      const [file] = await platform.pickFiles('.png,.jpg,.jpeg')
      if (!file || !current(article.id)) return
      const uploaded = await api.uploadFile(file, {
        projectId: article.projectId,
        taskId: article.taskId,
        saveToLibrary: false,
        waitForReady: false,
      })
      if (!uploaded.assetId) throw new Error('封面上传未返回可用的资源编号。')
      if (!current(article.id)) return
      coverAssetId.value = uploaded.assetId
      coverName.value = uploaded.name
      locked.value = null
      $q.notify({ type: 'positive', message: '封面已上传。' })
    } catch (error) {
      if (current(article.id)) notifyError(error, '封面上传失败。')
    } finally {
      coverUploading.value = false
    }
  }

  const openFinal = async (action: 'draft' | 'publish') => {
    const article = options.article()
    const account = options.account()
    const template = options.template()
    if (!article || busy.value || options.blocked()) return
    if (pending.value) {
      await resume()
      return
    }
    if (!account || !template?.versionId) {
      $q.notify({ type: 'warning', message: '请先选择目标公众号和可用的排版模板。' })
      return
    }
    if (account.status !== 'connected' || !account.capabilities.includes(action)) {
      $q.notify({
        type: 'warning',
        message:
          action === 'draft'
            ? '该公众号暂不能写入草稿箱，请检查授权。'
            : '该公众号暂不能发布，请检查授权。',
      })
      return
    }
    const cover = coverAssetId.value
    const unchanged = () =>
      current(article.id) &&
      options.account()?.id === account.id &&
      options.template()?.versionId === template.versionId &&
      coverAssetId.value === cover
    actionLabel.value = action === 'publish' ? '正在发布…' : '正在存入草稿箱…'
    preparing.value = true
    try {
      // A failed status lookup must not permit a second WeChat submission.
      const existing = await api.refreshPendingArticleOutcome(article.id)
      if (!unchanged()) return
      pending.value = existing
      if (existing) {
        preparing.value = false
        await resume()
        return
      }
      const saved = await options.save()
      if (!saved || !unchanged()) return
      const render = await api.prepareArticleRender(
        saved.id,
        account.id,
        template.id,
        cover,
        saved.versionNo,
      )
      if (!unchanged()) return
      locked.value = {
        article: saved,
        account,
        template,
        render,
        action,
        key: crypto.randomUUID(),
        coverName: coverName.value,
      }
      visible.value = true
    } catch (error) {
      if (current(article.id)) notifyError(error, '最终预览生成失败。')
    } finally {
      preparing.value = false
    }
  }

  const refreshPending = async (id: string) => {
    const value = await api
      .refreshPendingArticleOutcome(id)
      .catch(() => api.getPendingArticleOutcome(id))
    if (current(id)) pending.value = value
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['article', id] }),
      queryClient.invalidateQueries({ queryKey: ['library'] }),
    ])
  }
  const confirm = async () => {
    const snapshot = locked.value
    if (!snapshot || !visible.value || submitting.value || !current(snapshot.article.id)) return
    actionLabel.value = snapshot.action === 'publish' ? '正在发布…' : '正在存入草稿箱…'
    submitting.value = true
    try {
      const result = await api.setArticleOutcome({
        id: snapshot.article.id,
        outcome: snapshot.action === 'publish' ? 'publish' : 'wechat_draft',
        accountId: snapshot.account.id,
        templateId: snapshot.template.id,
        renderId: snapshot.render.renderId,
        idempotencyKey: snapshot.key,
      })
      queryClient.setQueryData(['article', result.id], result)
      if (current(result.id)) {
        visible.value = false
        locked.value = null
        $q.notify({
          type: 'positive',
          message:
            snapshot.action === 'publish'
              ? '微信已确认文章发布成功。'
              : '微信已确认文章进入公众号草稿箱。',
        })
      }
    } catch (error) {
      notifyError(error, '公众号操作没有完成。')
    } finally {
      await refreshPending(snapshot.article.id)
      if (pending.value) visible.value = false
      submitting.value = false
    }
  }
  const resume = async () => {
    const article = options.article()
    if (!article || busy.value) return
    // An unresolved request without an operation id must not be resent by a query button.
    if (pending.value && !pending.value.operationId) {
      const approved = await new Promise<boolean>((resolve) => {
        $q.dialog({
          title: '继续原提交',
          message: '原请求尚未取得微信操作编号。是否使用原请求编号继续提交？',
          cancel: true,
        })
          .onOk(() => resolve(true))
          .onCancel(() => resolve(false))
          .onDismiss(() => resolve(false))
      })
      if (!approved || !current(article.id) || busy.value) return
    }
    actionLabel.value = pending.value?.outcome === 'publish' ? '正在发布…' : '正在存入草稿箱…'
    submitting.value = true
    try {
      const result = await api.resumePendingArticleOutcome(article.id)
      if (result) queryClient.setQueryData(['article', result.id], result)
      if (current(article.id))
        $q.notify({
          type: 'positive',
          message: result ? '微信操作结果已确认。' : '当前没有待处理的微信操作。',
        })
    } catch (error) {
      notifyError(error, '原微信操作仍未确认。')
    } finally {
      await refreshPending(article.id)
      submitting.value = false
    }
  }
  watch(
    () => pending.value?.operationId,
    (id) => {
      // Only resume status reads automatically; an unacknowledged write needs explicit continuation.
      if (id && !busy.value) void resume()
    },
    { immediate: true, flush: 'post' },
  )
  return {
    coverAssetId,
    coverName,
    coverUploading,
    preparing,
    submitting,
    busy,
    pending,
    visible,
    locked,
    chooseCover,
    openFinal,
    confirm,
    resume,
  }
}

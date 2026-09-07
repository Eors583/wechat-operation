<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute } from 'vue-router'
import { useInfiniteQuery, useQuery } from '@tanstack/vue-query'
import { useQuasar } from 'quasar'
import { EditorContent, useEditor } from '@tiptap/vue-3'
import StarterKit from '@tiptap/starter-kit'
import { templatePreviewCssVariables } from '@/utils/templatePreviewStyles'
import { createDefaultStyles } from '@/api/styleDefaults'
import { tableExtensions } from '@/editor/tableExtensions'
import ArticleTableMenu from '@/components/business/ArticleTableMenu.vue'
import Link from '@tiptap/extension-link'
import Image from '@tiptap/extension-image'
import { moduleParagraph } from '@/editor/moduleParagraph'
import { ApiError, api } from '@/api/client'
import { articleStatusLabel } from '@/api/articleStatus'
import { queryClient } from '@/boot/query'
import type {
  Article,
  ArticleRenderPreview,
  ArticleVersion,
  PendingArticleOutcome,
} from '@/api/types'
import { platform } from '@/platform'
import { useAuthStore } from '@/stores/auth'
import AppButton from '@/components/base/AppButton.vue'
import AppDialog from '@/components/base/AppDialog.vue'
import AsyncStatePanel from '@/components/composite/AsyncStatePanel.vue'
import WechatFinalPreview from '@/components/business/WechatFinalPreview.vue'
import { usePublicSettings } from '@/composables/usePublicSettings'

const route = useRoute()
const $q = useQuasar()
const auth = useAuthStore()
const { settings: publicSettings } = usePublicSettings()
const articleId = computed(() => String(route.params.id))
const articleQuery = useQuery({
  queryKey: computed(() => ['article', articleId.value]),
  queryFn: () => api.getArticle(articleId.value),
})
const versionsQuery = useInfiniteQuery({
  queryKey: computed(() => ['article-versions', articleId.value]),
  queryFn: ({ pageParam }) => api.getArticleVersionsPage(articleId.value, pageParam),
  initialPageParam: undefined as string | undefined,
  getNextPageParam: (lastPage) => lastPage.nextCursor,
})
const accountsQuery = useInfiniteQuery({
  queryKey: ['accounts'],
  queryFn: ({ pageParam }) => api.listOfficialAccountsPage(pageParam),
  initialPageParam: undefined as string | undefined,
  getNextPageParam: (lastPage) => lastPage.nextCursor,
})

const title = ref('')
const versionNo = ref(0)
const selectedAccountId = ref<string | null>(null)
const selectedTemplateId = ref<string | null>(null)
const view = ref(route.query.view === 'layout' ? 'layout' : 'edit')
const saveState = ref<'saved' | 'saving' | 'failed'>('saved')
const saveConflict = ref(false)
const saveErrorMessage = ref('')
const dirty = ref(false)
const historyDialog = ref(false)
const revisionDialog = ref(false)
const revisionInstruction = ref('')
const revisionProposal = ref('')
const revisionSimulated = ref(false)
const revisionLoading = ref(false)
const revisionSelection = ref<{ from: number; to: number; text: string } | null>(null)
const finalDialog = ref(false)
const finalAction = ref<'draft' | 'publish'>('draft')
const finalRender = ref<ArticleRenderPreview | null>(null)
const finalPreparing = ref(false)
const renderError = ref('')
const outcomeLoading = ref(false)
const localSaving = ref(false)
const coverAssetId = ref<string | null>(null)
const coverName = ref('')
const coverUploading = ref(false)
const finalIdempotencyKey = ref('')
const pendingOutcome = ref<PendingArticleOutcome | null>(
  api.getPendingArticleOutcome(articleId.value),
)
let saveTimer: ReturnType<typeof setTimeout> | null = null
let editRevision = 0
let hydratedArticleId = ''
let checkedDraftArticleId = ''
let checkedRevisionArticleId = ''
let saveInFlight: Promise<Article | null> | null = null

interface LocalArticleDraft {
  articleId: string
  ownerId: string
  title: string
  contentHtml: string
  contentJson: Record<string, unknown>
  baseVersionNo: number
  updatedAt: string
}

const apiErrorCode = (error: unknown) => {
  if (error instanceof ApiError) return error.code
  if (typeof error !== 'object' || error === null || !('code' in error)) return ''
  return typeof error.code === 'string' ? error.code : ''
}

const localDraftKey = () =>
  `wechat-ai-article-draft:${auth.user?.id ?? 'anonymous'}:${articleId.value}`
const readLocalDraft = (): LocalArticleDraft | null => {
  try {
    const value = JSON.parse(
      sessionStorage.getItem(localDraftKey()) ?? 'null',
    ) as LocalArticleDraft | null
    return value?.articleId === articleId.value && value.ownerId === auth.user?.id ? value : null
  } catch {
    return null
  }
}
const clearLocalDraft = () => sessionStorage.removeItem(localDraftKey())
const persistLocalDraft = () => {
  if (!article.value || !editor.value || !auth.user) return
  const draft: LocalArticleDraft = {
    articleId: article.value.id,
    ownerId: auth.user.id,
    title: title.value,
    contentHtml: editor.value.getHTML(),
    contentJson: editor.value.getJSON(),
    baseVersionNo: versionNo.value,
    updatedAt: new Date().toISOString(),
  }
  try {
    sessionStorage.setItem(localDraftKey(), JSON.stringify(draft))
  } catch {
    /* Keep editing even when storage is unavailable. */
  }
}

const article = computed(() => articleQuery.data.value ?? null)
const pendingOutcomeText = computed(() => {
  const pending = pendingOutcome.value
  if (!pending) return ''
  const action = pending.outcome === 'publish' ? '发布' : '写入公众号草稿箱'
  const stage = {
    queued: '排队中',
    submitting: '提交中',
    reconciling: '结果核对中',
    unknown: '结果未知',
  }[pending.operationStatus]
  return `${action}${stage}`
})
const versions = computed(() => [
  ...new Map(
    (versionsQuery.data.value?.pages.flatMap((page) => page.items) ?? []).map((version) => [
      version.id,
      version,
    ]),
  ).values(),
])
const accounts = computed(() => [
  ...new Map(
    (accountsQuery.data.value?.pages.flatMap((page) => page.items) ?? []).map((account) => [
      account.id,
      account,
    ]),
  ).values(),
])
const selectedAccount = computed(
  () => accounts.value.find((item) => item.id === selectedAccountId.value) ?? null,
)
const canDraft = computed(
  () =>
    selectedAccount.value?.status === 'connected' &&
    selectedAccount.value.capabilities.includes('draft'),
)
const canPublish = computed(
  () =>
    selectedAccount.value?.status === 'connected' &&
    selectedAccount.value.capabilities.includes('publish'),
)
const templatesQuery = useInfiniteQuery({
  queryKey: computed(() => ['templates', selectedAccountId.value]),
  queryFn: ({ pageParam }) => api.listTemplatesPage(selectedAccountId.value!, pageParam),
  initialPageParam: undefined as string | undefined,
  getNextPageParam: (lastPage) => lastPage.nextCursor,
  enabled: computed(() => Boolean(selectedAccountId.value)),
})
const templates = computed(() =>
  [
    ...new Map(
      (templatesQuery.data.value?.pages.flatMap((page) => page.items) ?? []).map((template) => [
        template.id,
        template,
      ]),
    ).values(),
  ].filter((template) => template.enabled),
)
const selectedTemplate = computed(
  () => templates.value.find((item) => item.id === selectedTemplateId.value) ?? null,
)
const selectedText = computed(() => {
  if (!editor.value) return ''
  const { from, to } = editor.value.state.selection
  return from === to ? '' : editor.value.state.doc.textBetween(from, to, ' ')
})

const scheduleSave = () => {
  editRevision += 1
  dirty.value = true
  finalRender.value = null
  if (view.value === 'layout') view.value = 'edit'
  if (saveTimer) clearTimeout(saveTimer)
  persistLocalDraft()
  if (saveConflict.value) {
    saveState.value = 'failed'
    return
  }
  saveState.value = 'saving'
  saveTimer = setTimeout(() => {
    void saveContent().catch(() => undefined)
  }, publicSettings.value.articles.autosaveSeconds * 1000)
}

const editor = useEditor({
  extensions: [
    ...tableExtensions,
    StarterKit.configure({ paragraph: false }),
    moduleParagraph,
    Link.configure({ openOnClick: false }),
    Image.configure({ inline: false }),
  ],
  content: '',
  editorProps: { attributes: { class: 'tiptap-body', 'aria-label': '文章正文编辑器' } },
  onUpdate: scheduleSave,
})

watch(
  article,
  async (value) => {
    if (!value) return
    if (versionNo.value && versionNo.value !== value.versionNo) finalRender.value = null
    const initialLoad = hydratedArticleId !== value.id
    if (!initialLoad && (dirty.value || saveInFlight)) return
    versionNo.value = value.versionNo
    hydratedArticleId = value.id
    title.value = value.title
    selectedAccountId.value =
      value.accountId ?? accounts.value.find((item) => item.status === 'connected')?.id ?? null
    await nextTick()
    if (editor.value?.getHTML() !== value.contentHtml)
      editor.value?.commands.setContent(value.contentJson ?? value.contentHtml, false)
    dirty.value = false
    saveState.value = 'saved'
    saveConflict.value = false
    saveErrorMessage.value = ''
    if (initialLoad && checkedDraftArticleId !== value.id) {
      checkedDraftArticleId = value.id
      const draft = readLocalDraft()
      const differs =
        draft &&
        (draft.title !== value.title ||
          JSON.stringify(draft.contentJson) !== JSON.stringify(value.contentJson))
      if (draft && differs) {
        $q.dialog({
          title: '发现未保存的本地修改',
          message:
            draft.baseVersionNo === value.versionNo
              ? '上次页面关闭前还有未保存内容。要恢复后继续保存吗？'
              : '服务端文章已产生新版本。本地修改仍被保留，恢复后需要选择冲突处理方式。',
          ok: { label: '恢复本地修改' },
          cancel: { label: '放弃本地副本', flat: true },
          persistent: true,
        })
          .onOk(() => {
            title.value = draft.title
            editor.value?.commands.setContent(draft.contentJson, false)
            dirty.value = true
            editRevision += 1
            saveConflict.value = draft.baseVersionNo !== value.versionNo
            saveState.value = 'failed'
            saveErrorMessage.value = saveConflict.value
              ? '服务端已有新版本，请选择如何处理本地修改。'
              : '本地修改尚未保存，请手动重试。'
          })
          .onCancel(clearLocalDraft)
      } else if (draft) clearLocalDraft()
    }
  },
  { immediate: true },
)

watch(
  articleId,
  (value) => {
    pendingOutcome.value = api.getPendingArticleOutcome(value)
    void api
      .refreshPendingArticleOutcome(value)
      .then((pending) => {
        if (articleId.value === value) pendingOutcome.value = pending
      })
      .catch(() => undefined)
  },
  { immediate: true },
)

watch(
  accounts,
  (value) => {
    if (!selectedAccountId.value)
      selectedAccountId.value = value.find((item) => item.status === 'connected')?.id ?? null
  },
  { immediate: true },
)

watch(
  templates,
  (value) => {
    if (!value.some((item) => item.id === selectedTemplateId.value))
      selectedTemplateId.value =
        article.value?.templateId && value.some((item) => item.id === article.value?.templateId)
          ? article.value.templateId
          : (value[0]?.id ?? null)
  },
  { immediate: true },
)

watch(
  [
    selectedAccountId,
    selectedTemplateId,
    () => selectedTemplate.value?.updatedAt,
    () => selectedAccount.value?.lastSyncedAt,
  ],
  () => {
    finalRender.value = null
    finalIdempotencyKey.value = ''
    renderError.value = ''
  },
)

const saveContent = async (): Promise<Article | null> => {
  if (saveInFlight) {
    await saveInFlight
    return dirty.value ? saveContent() : article.value
  }
  if (!article.value || !editor.value || !dirty.value) return article.value
  if (saveTimer) {
    clearTimeout(saveTimer)
    saveTimer = null
  }
  saveState.value = 'saving'
  const revision = editRevision
  const targetId = article.value.id
  const targetTaskId = article.value.taskId
  const operation = api.saveArticle({
    id: targetId,
    title: title.value,
    summary: article.value.summary,
    contentHtml: editor.value.getHTML(),
    contentJson: editor.value.getJSON(),
    baseVersionNo: versionNo.value,
  })
  saveInFlight = operation
  let saved: Article | null = null
  try {
    saved = await operation
    versionNo.value = saved.versionNo
    if (editRevision === revision) {
      dirty.value = false
      saveState.value = 'saved'
      saveConflict.value = false
      saveErrorMessage.value = ''
      clearLocalDraft()
    }
    queryClient.setQueryData(['article', targetId], saved)
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['article-versions', targetId] }),
      queryClient.invalidateQueries({ queryKey: ['library'] }),
      queryClient.invalidateQueries({ queryKey: ['task', targetTaskId] }),
    ])
  } catch (error) {
    saveState.value = 'failed'
    saveConflict.value = apiErrorCode(error) === 'ARTICLE_VERSION_CONFLICT'
    saveErrorMessage.value = saveConflict.value
      ? '服务端已有新版本。本地修改已保留，请选择冲突处理方式。'
      : error instanceof Error
        ? error.message
        : '当前修改暂未保存，请手动重试。'
    persistLocalDraft()
    $q.notify({
      type: saveConflict.value ? 'warning' : 'negative',
      message: saveErrorMessage.value,
    })
    throw error
  } finally {
    if (saveInFlight === operation) saveInFlight = null
  }
  return dirty.value && editRevision !== revision ? saveContent() : saved
}

const retrySave = () => {
  if (!saveConflict.value) void saveContent().catch(() => undefined)
}

const copyLocalContent = async () => {
  if (!editor.value) return
  try {
    await navigator.clipboard.writeText(`${title.value}\n\n${editor.value.getText()}`)
    $q.notify({ type: 'positive', message: '本地标题和正文已复制。' })
  } catch {
    $q.notify({ type: 'negative', message: '浏览器不允许复制，请先保持页面打开。' })
  }
}

const loadLatestArticle = async () => {
  const latest = await api.getArticle(articleId.value)
  queryClient.setQueryData(['article', articleId.value], latest)
  title.value = latest.title
  editor.value?.commands.setContent(latest.contentJson ?? latest.contentHtml, false)
  versionNo.value = latest.versionNo
  dirty.value = false
  saveConflict.value = false
  saveErrorMessage.value = ''
  saveState.value = 'saved'
  clearLocalDraft()
}

const discardLocalAndReload = () => {
  $q.dialog({
    title: '放弃本地修改？',
    message: '将加载服务端最新版本。本地未保存内容会被清除；如需备份，请先复制本地内容。',
    ok: { label: '放弃并加载最新版', color: 'negative' },
    cancel: true,
    persistent: true,
  }).onOk(async () => {
    try {
      await loadLatestArticle()
    } catch (error) {
      $q.notify({
        type: 'negative',
        message: error instanceof Error ? error.message : '最新版加载失败，本地内容仍保留。',
      })
    }
  })
}

const keepLocalAsNewVersion = () => {
  if (!article.value || !editor.value) return
  $q.dialog({
    title: '用本地修改创建新版本？',
    message:
      '系统会先取得服务端最新版本，再把当前本地全文保存为下一个版本。服务端现有内容仍保留在历史版本中，不会静默消失。',
    ok: { label: '创建新版本' },
    cancel: true,
    persistent: true,
  }).onOk(async () => {
    if (!article.value || !editor.value) return
    saveState.value = 'saving'
    const revision = editRevision
    const local = {
      title: title.value,
      contentHtml: editor.value.getHTML(),
      contentJson: editor.value.getJSON(),
    }
    try {
      const latest = await api.getArticle(article.value.id)
      const saved = await api.saveArticle({
        id: latest.id,
        title: local.title,
        summary: latest.summary,
        contentHtml: local.contentHtml,
        contentJson: local.contentJson,
        baseVersionNo: latest.versionNo,
      })
      versionNo.value = saved.versionNo
      queryClient.setQueryData(['article', saved.id], saved)
      saveConflict.value = false
      saveErrorMessage.value = ''
      if (editRevision === revision) {
        dirty.value = false
        saveState.value = 'saved'
        clearLocalDraft()
      } else {
        saveState.value = 'failed'
        persistLocalDraft()
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['article-versions', saved.id] }),
        queryClient.invalidateQueries({ queryKey: ['library'] }),
        queryClient.invalidateQueries({ queryKey: ['task', saved.taskId] }),
      ])
      $q.notify({ type: 'positive', message: '本地修改已作为新的文章版本保存。' })
    } catch (error) {
      saveState.value = 'failed'
      saveConflict.value = apiErrorCode(error) === 'ARTICLE_VERSION_CONFLICT'
      saveErrorMessage.value =
        error instanceof Error ? error.message : '冲突处理没有完成，本地内容仍保留。'
      persistLocalDraft()
      $q.notify({ type: 'negative', message: saveErrorMessage.value })
    }
  })
}

const restore = async (version: ArticleVersion) => {
  const restored = await api.restoreArticleVersion(articleId.value, version)
  queryClient.setQueryData(['article', articleId.value], restored)
  editor.value?.commands.setContent(restored.contentJson ?? restored.contentHtml, false)
  title.value = restored.title
  versionNo.value = restored.versionNo
  dirty.value = false
  saveConflict.value = false
  saveErrorMessage.value = ''
  saveState.value = 'saved'
  clearLocalDraft()
  historyDialog.value = false
  await versionsQuery.refetch()
  $q.notify({
    type: 'positive',
    message: `已恢复版本 ${version.versionNo}，并创建了新的当前版本。`,
  })
}

const openRevision = () => {
  if (!selectedText.value) return
  revisionInstruction.value = ''
  revisionProposal.value = ''
  revisionSelection.value = null
  revisionDialog.value = true
}

const generateRevision = async () => {
  if (!article.value || !editor.value || !selectedText.value || !revisionInstruction.value.trim())
    return
  const { from, to } = editor.value.state.selection
  const text = selectedText.value
  revisionLoading.value = true
  try {
    await saveContent()
    if (!editor.value || editor.value.state.doc.textBetween(from, to, ' ') !== text) {
      throw new Error('选中文字已经变化，请重新选择后再生成建议。')
    }
    const proposal = await api.proposeArticleRevision({
      articleId: article.value.id,
      baseVersionNo: versionNo.value,
      selectedText: text,
      instruction: revisionInstruction.value.trim(),
      selectionFrom: from,
      selectionTo: to,
    })
    revisionProposal.value = proposal.replacementText
    revisionSimulated.value = proposal.simulated
    revisionSelection.value = { from, to, text }
  } catch (error) {
    $q.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : 'AI 修改建议没有生成完成。',
    })
  } finally {
    await auth.refreshUser().catch(() => undefined)
    revisionLoading.value = false
  }
}

const resumePendingRevision = async () => {
  const pending = api.getPendingArticleRevision(articleId.value)
  if (!pending || !editor.value) return
  revisionInstruction.value = pending.instruction
  revisionSelection.value = {
    from: pending.selectionFrom,
    to: pending.selectionTo,
    text: pending.selectedText,
  }
  revisionProposal.value = ''
  revisionDialog.value = true
  revisionLoading.value = true
  try {
    const proposal = await api.resumePendingArticleRevision(articleId.value)
    if (!proposal) return
    revisionProposal.value = proposal.replacementText
    revisionSimulated.value = proposal.simulated
    $q.notify({ type: 'positive', message: '已找回上次的 AI 修改建议，未重复创建扣费任务。' })
  } catch (error) {
    $q.notify({
      type: 'warning',
      timeout: 8000,
      message: error instanceof Error ? error.message : '原 AI 修改任务仍在处理。',
    })
  } finally {
    await auth.refreshUser().catch(() => undefined)
    revisionLoading.value = false
  }
}

watch(
  article,
  (value) => {
    if (!value || checkedRevisionArticleId === value.id) return
    checkedRevisionArticleId = value.id
    void nextTick().then(resumePendingRevision)
  },
  { immediate: true },
)

const applyRevision = () => {
  const selection = revisionSelection.value
  if (!editor.value || !selection || !revisionProposal.value) return
  if (editor.value.state.doc.textBetween(selection.from, selection.to, ' ') !== selection.text) {
    $q.notify({ type: 'warning', message: '选中文字已经变化，建议未应用。请重新选择后再试。' })
    return
  }
  editor.value
    .chain()
    .focus()
    .insertContentAt({ from: selection.from, to: selection.to }, revisionProposal.value)
    .run()
  revisionDialog.value = false
  revisionInstruction.value = ''
  revisionProposal.value = ''
  revisionSelection.value = null
}

const setLink = () => {
  if (!editor.value) return
  const url = window.prompt('请输入链接地址', 'https://')
  if (!url) return
  try {
    const parsed = new URL(url)
    if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error()
    editor.value.chain().focus().extendMarkRange('link').setLink({ href: parsed.href }).run()
  } catch {
    $q.notify({ type: 'warning', message: '链接必须是有效的 http 或 https 地址。' })
  }
}

const setParagraphModule = (module: 'lead' | 'body' | 'highlight' | 'caption') => {
  editor.value?.chain().focus().setNode('paragraph', { module }).run()
}

const chooseCover = async () => {
  if (!article.value) return
  const [file] = await platform.pickFiles('.png,.jpg,.jpeg')
  if (!file) return
  coverUploading.value = true
  try {
    const uploaded = await api.uploadFile(file, {
      projectId: article.value.projectId,
      taskId: article.value.taskId,
      saveToLibrary: false,
      waitForReady: true,
    })
    if (!uploaded.assetId) throw new Error('封面上传成功，但没有返回可用的资源编号。')
    coverAssetId.value = uploaded.assetId
    coverName.value = uploaded.name
    finalRender.value = null
    $q.notify({ type: 'positive', message: '封面已上传，将随最终排版版本一并冻结。' })
  } catch (error) {
    $q.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '封面上传失败。',
    })
  } finally {
    coverUploading.value = false
  }
}

const saveLocal = async () => {
  localSaving.value = true
  try {
    const saved = (await saveContent()) ?? article.value
    if (!saved) return
    const result = await api.setArticleOutcome({
      id: saved.id,
      outcome: 'local_draft',
      idempotencyKey: crypto.randomUUID(),
    })
    queryClient.setQueryData(['article', saved.id], result)
    await queryClient.invalidateQueries({ queryKey: ['library'] })
    $q.notify({ type: 'positive', message: '文章已存入本地草稿箱，并出现在文章库。' })
  } catch (error) {
    $q.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '本地草稿没有保存完成。',
    })
  } finally {
    localSaving.value = false
  }
}

let renderRequestToken = 0
const prepareCurrentRender = async () => {
  if (pendingOutcome.value) return null
  if (!selectedAccount.value || !selectedTemplate.value) return null
  const token = ++renderRequestToken
  finalPreparing.value = true
  renderError.value = ''
  try {
    const saved = (await saveContent()) ?? article.value
    if (!saved || token !== renderRequestToken) return null
    const rendered = await api.prepareArticleRender(
      saved.id,
      selectedAccount.value.id,
      selectedTemplate.value.id,
      coverAssetId.value,
    )
    if (token !== renderRequestToken) return null
    finalRender.value = rendered
    return rendered
  } catch (error) {
    if (token === renderRequestToken)
      renderError.value = error instanceof Error ? error.message : '排版预览生成失败。'
    return null
  } finally {
    if (token === renderRequestToken) finalPreparing.value = false
  }
}

watch(
  view,
  (value) => {
    if (value === 'layout') void prepareCurrentRender()
  },
  { immediate: true },
)
watch(
  [
    selectedAccountId,
    selectedTemplateId,
    coverAssetId,
    () => selectedTemplate.value?.updatedAt,
    () => selectedAccount.value?.lastSyncedAt,
  ],
  () => {
    if (view.value === 'layout') void prepareCurrentRender()
  },
)

const openFinal = async (action: 'draft' | 'publish') => {
  pendingOutcome.value = await api
    .refreshPendingArticleOutcome(articleId.value)
    .catch(() => api.getPendingArticleOutcome(articleId.value))
  if (pendingOutcome.value) {
    $q.notify({
      type: 'warning',
      message: '该文章已有微信操作待确认，请先查询原操作，不能创建新的提交。',
    })
    return
  }
  if (!selectedAccount.value || !selectedTemplate.value) {
    $q.notify({ type: 'warning', message: '请先选择目标公众号和已启用的排版模板。' })
    return
  }
  if (selectedAccount.value.status !== 'connected') {
    $q.notify({ type: 'warning', message: '该公众号需要重新授权后才能写入或发布。' })
    return
  }
  if ((action === 'draft' && !canDraft.value) || (action === 'publish' && !canPublish.value)) {
    $q.notify({
      type: 'warning',
      message:
        action === 'draft' ? '该公众号没有写入草稿箱的能力。' : '该公众号没有发布文章的能力。',
    })
    return
  }
  try {
    const rendered = await prepareCurrentRender()
    if (!rendered) {
      if (renderError.value) $q.notify({ type: 'negative', message: renderError.value })
      return
    }
    finalIdempotencyKey.value = crypto.randomUUID()
    finalAction.value = action
    finalDialog.value = true
  } catch (error) {
    $q.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '最终预览生成失败，请稍后重试。',
    })
  }
}

const confirmOutcome = async () => {
  if (!article.value || !selectedAccount.value || !selectedTemplate.value) return
  outcomeLoading.value = true
  try {
    const result = await api.setArticleOutcome({
      id: article.value.id,
      outcome: finalAction.value === 'publish' ? 'publish' : 'wechat_draft',
      accountId: selectedAccount.value.id,
      templateId: selectedTemplate.value.id,
      renderId: finalRender.value?.renderId,
      idempotencyKey:
        finalIdempotencyKey.value || (finalIdempotencyKey.value = crypto.randomUUID()),
    })
    queryClient.setQueryData(['article', article.value.id], result)
    await queryClient.invalidateQueries({ queryKey: ['library'] })
    finalDialog.value = false
    $q.notify({
      type: 'positive',
      message:
        finalAction.value === 'publish'
          ? '微信已确认文章发布成功。'
          : '微信已确认文章进入公众号草稿箱。',
    })
    finalIdempotencyKey.value = ''
  } catch (error) {
    $q.notify({
      type: 'negative',
      timeout: 8000,
      message: error instanceof Error ? error.message : '公众号操作没有完成。',
    })
  } finally {
    pendingOutcome.value = await api
      .refreshPendingArticleOutcome(articleId.value)
      .catch(() => api.getPendingArticleOutcome(articleId.value))
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['article', articleId.value] }),
      queryClient.invalidateQueries({ queryKey: ['library'] }),
    ])
    outcomeLoading.value = false
  }
}

const resumePendingOutcome = async () => {
  outcomeLoading.value = true
  try {
    const result = await api.resumePendingArticleOutcome(articleId.value)
    if (result) {
      queryClient.setQueryData(['article', articleId.value], result)
      $q.notify({
        color: 'positive',
        icon: 'check_circle',
        message: '微信操作结果已确认。',
      })
    }
  } catch (error) {
    $q.notify({
      type: 'negative',
      timeout: 8000,
      message: error instanceof Error ? error.message : '原微信操作仍未确认。',
    })
  } finally {
    pendingOutcome.value = await api
      .refreshPendingArticleOutcome(articleId.value)
      .catch(() => api.getPendingArticleOutcome(articleId.value))
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['article', articleId.value] }),
      queryClient.invalidateQueries({ queryKey: ['library'] }),
    ])
    outcomeLoading.value = false
  }
}

const confirmLeaveWithUnsavedChanges = () =>
  new Promise<boolean>((resolve) => {
    $q.dialog({
      title: '还有未保存的修改',
      message: '离开后仍可在本标签页恢复会话副本，但建议先解决冲突或重试保存。确定离开吗？',
      ok: { label: '仍然离开', color: 'negative' },
      cancel: { label: '继续编辑', flat: true },
      persistent: true,
    })
      .onOk(() => resolve(true))
      .onCancel(() => resolve(false))
  })

const handleBeforeUnload = (event: BeforeUnloadEvent) => {
  if (!dirty.value) return
  event.preventDefault()
  event.returnValue = ''
}

onBeforeRouteLeave(async () => {
  if (!dirty.value) return true
  if (!saveConflict.value && saveState.value !== 'failed') {
    try {
      await saveContent()
      if (!dirty.value) return true
    } catch {
      // The persistent failure state below gives the user an explicit choice.
    }
  }
  return confirmLeaveWithUnsavedChanges()
})
onMounted(() => window.addEventListener('beforeunload', handleBeforeUnload))
onBeforeUnmount(() => {
  if (saveTimer) clearTimeout(saveTimer)
  window.removeEventListener('beforeunload', handleBeforeUnload)
})
</script>

<template>
  <q-page class="article-page">
    <AsyncStatePanel
      :loading="articleQuery.isPending.value"
      :error="articleQuery.error.value instanceof Error ? articleQuery.error.value.message : null"
      @retry="articleQuery.refetch()"
    >
      <div v-if="article" class="article-workbench">
        <header class="article-workbench__header">
          <div class="article-title">
            <q-btn flat round dense icon="arrow_back" aria-label="返回" @click="$router.back()" />
            <q-input
              v-model="title"
              borderless
              dense
              aria-label="文章标题"
              maxlength="120"
              @update:model-value="scheduleSave"
            />
          </div>
          <div class="save-indicator" :class="`save-indicator--${saveState}`">
            <q-spinner v-if="saveState === 'saving'" size="18px" /><q-icon
              v-else
              :name="saveState === 'saved' ? 'cloud_done' : 'cloud_off'"
            />
            <span>{{
              saveState === 'saved'
                ? '已保存'
                : saveState === 'saving'
                  ? '正在保存'
                  : saveConflict
                    ? '版本冲突，尚未保存'
                    : '保存失败，尚未重试'
            }}</span>
            <q-btn
              v-if="saveState === 'failed' && !saveConflict"
              flat
              dense
              no-caps
              color="negative"
              label="重试保存"
              @click="retrySave"
            />
          </div>
          <q-tabs v-model="view" dense active-color="primary" indicator-color="primary"
            ><q-tab name="edit" icon="edit" label="编辑视图" /><q-tab
              name="layout"
              icon="visibility"
              label="公众号排版预览"
          /></q-tabs>
          <AppButton
            variant="outline"
            icon="history"
            label="历史版本"
            @click="historyDialog = true"
          />
          <q-banner v-if="saveConflict" rounded class="article-conflict-banner">
            <template #avatar><q-icon name="sync_problem" color="warning" size="28px" /></template>
            <strong>检测到服务端新版本</strong>
            <p>{{ saveErrorMessage }} 当前编辑内容已保留在本标签页，会话恢复时也会再次提示。</p>
            <template #action>
              <q-btn flat dense no-caps label="复制本地内容" @click="copyLocalContent" />
              <q-btn
                flat
                dense
                no-caps
                label="放弃本地并加载最新版"
                @click="discardLocalAndReload"
              />
              <q-btn
                unelevated
                dense
                no-caps
                color="primary"
                label="本地内容创建新版本"
                @click="keepLocalAsNewVersion"
              />
            </template>
          </q-banner>
        </header>

        <main class="article-workbench__main">
          <section v-show="view === 'edit'" class="editor-pane">
            <div class="editor-toolbar" role="toolbar" aria-label="文章编辑工具栏">
              <ArticleTableMenu :editor="editor" />
              <q-btn
                flat
                round
                dense
                icon="undo"
                aria-label="撤销"
                :disable="!editor?.can().undo()"
                @click="editor?.chain().focus().undo().run()"
              />
              <q-btn
                flat
                round
                dense
                icon="redo"
                aria-label="重做"
                :disable="!editor?.can().redo()"
                @click="editor?.chain().focus().redo().run()"
              />
              <q-separator vertical />
              <q-btn flat dense no-caps label="正文" aria-label="正文样式"
                ><q-menu
                  ><q-list
                    ><q-item clickable v-close-popup @click="setParagraphModule('body')"
                      ><q-item-section>正文</q-item-section></q-item
                    ><q-item clickable v-close-popup @click="setParagraphModule('lead')"
                      ><q-item-section>导语</q-item-section></q-item
                    ><q-item clickable v-close-popup @click="setParagraphModule('highlight')"
                      ><q-item-section>重点论点</q-item-section></q-item
                    ><q-item clickable v-close-popup @click="setParagraphModule('caption')"
                      ><q-item-section>图片说明</q-item-section></q-item
                    ><q-separator /><q-item
                      clickable
                      v-close-popup
                      @click="editor?.chain().focus().toggleHeading({ level: 2 }).run()"
                      ><q-item-section>一级标题</q-item-section></q-item
                    ><q-item
                      clickable
                      v-close-popup
                      @click="editor?.chain().focus().toggleHeading({ level: 3 }).run()"
                      ><q-item-section>二级标题</q-item-section></q-item
                    ></q-list
                  ></q-menu
                ></q-btn
              >
              <q-btn
                flat
                round
                dense
                icon="format_bold"
                aria-label="加粗"
                :class="{ active: editor?.isActive('bold') }"
                @click="editor?.chain().focus().toggleBold().run()"
              />
              <q-btn
                flat
                round
                dense
                icon="format_italic"
                aria-label="斜体"
                :class="{ active: editor?.isActive('italic') }"
                @click="editor?.chain().focus().toggleItalic().run()"
              />
              <q-btn
                flat
                round
                dense
                icon="format_list_bulleted"
                aria-label="无序列表"
                @click="editor?.chain().focus().toggleBulletList().run()"
              />
              <q-btn
                flat
                round
                dense
                icon="format_list_numbered"
                aria-label="有序列表"
                @click="editor?.chain().focus().toggleOrderedList().run()"
              />
              <q-btn
                flat
                round
                dense
                icon="format_quote"
                aria-label="引用"
                @click="editor?.chain().focus().toggleBlockquote().run()"
              />
              <q-btn flat round dense icon="link" aria-label="添加链接" @click="setLink" />
              <q-separator vertical />
              <AppButton
                variant="ghost"
                icon="auto_awesome"
                label="让 AI 修改选中内容"
                :disabled="!selectedText"
                @click="openRevision"
              />
            </div>
            <div class="editor-scroll">
              <EditorContent
                :editor="editor"
                class="editor-document"
                :style="
                  templatePreviewCssVariables(selectedTemplate?.styles ?? createDefaultStyles())
                "
              />
            </div>
          </section>

          <section v-show="view === 'layout'" class="layout-preview-pane">
            <div class="layout-preview-pane__label">
              <q-icon name="verified" color="positive" />此处加载服务端生成的不可变
              Render；最终确认将复用同一排版版本。
            </div>
            <div class="layout-preview-pane__scroll">
              <div v-if="!selectedAccount || !selectedTemplate" class="render-message">
                <q-icon name="info_outline" size="28px" /><span
                  >选择目标公众号和已启用模板后生成排版预览。</span
                >
              </div>
              <div v-else-if="finalPreparing" class="render-message">
                <q-spinner color="primary" size="30px" /><span
                  >正在锁定文章、模板、封面与公众号版本…</span
                >
              </div>
              <div v-else-if="renderError" class="render-message render-message--error">
                <q-icon name="error_outline" size="28px" /><span>{{ renderError }}</span
                ><AppButton variant="outline" label="重新生成" @click="prepareCurrentRender" />
              </div>
              <iframe
                v-else-if="finalRender"
                :srcdoc="finalRender.html"
                sandbox=""
                title="公众号服务端排版预览"
              />
            </div>
          </section>

          <aside class="article-meta">
            <h2>公众号排版</h2>
            <q-select
              v-model="selectedAccountId"
              :options="
                accounts.map((item) => ({ label: item.name, value: item.id, status: item.status }))
              "
              emit-value
              map-options
              outlined
              label="目标公众号"
              :disable="Boolean(pendingOutcome)"
            >
              <template #after-options>
                <q-item v-if="accountsQuery.hasNextPage.value">
                  <q-item-section
                    ><AppButton
                      variant="ghost"
                      label="加载更多公众号"
                      :loading="accountsQuery.isFetchingNextPage.value"
                      full-width
                      @click.stop="accountsQuery.fetchNextPage()"
                  /></q-item-section>
                </q-item>
              </template>
            </q-select>
            <q-banner v-if="pendingOutcome" rounded class="article-meta__warning">
              <strong>{{ pendingOutcomeText }}</strong>
              <div>操作编号：{{ pendingOutcome.operationId || '尚未取得（将重用原幂等键）' }}</div>
              <div>已锁定原排版版本；在结果确认前禁止新建微信提交。</div>
              <template #action
                ><AppButton
                  variant="outline"
                  label="查询原操作"
                  :loading="outcomeLoading"
                  @click="resumePendingOutcome"
              /></template>
            </q-banner>
            <q-banner
              v-if="selectedAccount?.status === 'reconnect'"
              rounded
              class="article-meta__warning"
              >公众号连接已失效。仍可编辑与预览，存草稿或发布前需要重新连接。</q-banner
            >
            <q-banner
              v-else-if="selectedAccount && (!canDraft || !canPublish)"
              rounded
              class="article-meta__warning"
              >当前公众号能力受限：{{ canDraft ? '可写入草稿箱' : '不可写入草稿箱' }}，{{
                canPublish ? '可发布' : '不可发布'
              }}。</q-banner
            >
            <q-select
              v-model="selectedTemplateId"
              :options="templates.map((item) => ({ label: item.name, value: item.id }))"
              emit-value
              map-options
              outlined
              label="已启用模板"
              :loading="templatesQuery.isPending.value"
              :disable="Boolean(pendingOutcome)"
            >
              <template #no-option>
                <q-item v-if="templatesQuery.hasNextPage.value">
                  <q-item-section
                    ><AppButton
                      variant="ghost"
                      label="当前页没有已启用模板，加载更多"
                      :loading="templatesQuery.isFetchingNextPage.value"
                      full-width
                      @click.stop="templatesQuery.fetchNextPage()"
                  /></q-item-section>
                </q-item>
                <q-item v-else
                  ><q-item-section class="text-muted"
                    >该公众号暂无已启用模板</q-item-section
                  ></q-item
                >
              </template>
              <template #after-options>
                <q-item v-if="templatesQuery.hasNextPage.value">
                  <q-item-section
                    ><AppButton
                      variant="ghost"
                      label="加载更多模板"
                      :loading="templatesQuery.isFetchingNextPage.value"
                      full-width
                      @click.stop="templatesQuery.fetchNextPage()"
                  /></q-item-section>
                </q-item>
              </template>
            </q-select>
            <div class="cover-card">
              <q-icon name="image" size="32px" />
              <span
                ><strong>文章封面</strong
                ><small>{{
                  coverAssetId ? coverName : article.coverState === 'ready' ? '已设置' : '尚未设置'
                }}</small></span
              >
              <AppButton
                variant="ghost"
                :label="coverAssetId || article.coverState === 'ready' ? '更换' : '选择封面'"
                :loading="coverUploading"
                :disabled="Boolean(pendingOutcome)"
                @click="chooseCover"
              />
            </div>
            <q-list bordered separator class="article-meta__details">
              <q-item
                ><q-item-section
                  ><q-item-label caption>当前版本</q-item-label
                  ><q-item-label>版本 {{ versionNo }}</q-item-label></q-item-section
                ></q-item
              >
              <q-item
                ><q-item-section
                  ><q-item-label caption>文章状态</q-item-label
                  ><q-item-label>{{
                    articleStatusLabel(article.status)
                  }}</q-item-label></q-item-section
                ></q-item
              >
              <q-item
                ><q-item-section
                  ><q-item-label caption>排版版本</q-item-label
                  ><q-item-label>{{
                    finalRender ? '已锁定；内容或目标变化后失效' : '等待生成'
                  }}</q-item-label></q-item-section
                ></q-item
              >
            </q-list>
          </aside>
        </main>

        <footer class="article-workbench__footer safe-bottom">
          <span>本地草稿不调用微信；公众号草稿和发布都将先打开同一排版版本的只读最终预览。</span>
          <div>
            <AppButton
              variant="outline"
              label="存本地草稿箱"
              :loading="localSaving"
              @click="saveLocal"
            /><AppButton
              v-if="publicSettings.wechat.wechatDraftEnabled"
              variant="outline"
              label="存公众号草稿箱"
              :loading="finalPreparing"
              :disabled="Boolean(pendingOutcome) || Boolean(selectedAccount && !canDraft)"
              @click="openFinal('draft')"
            /><AppButton
              v-if="publicSettings.wechat.wechatPublishEnabled"
              label="直接发布"
              :loading="finalPreparing"
              :disabled="Boolean(pendingOutcome) || Boolean(selectedAccount && !canPublish)"
              @click="openFinal('publish')"
            />
          </div>
        </footer>
      </div>
    </AsyncStatePanel>

    <AppDialog v-model="historyDialog" title="历史版本" width="720px">
      <AsyncStatePanel
        :loading="versionsQuery.isPending.value"
        :error="
          versionsQuery.error.value instanceof Error ? versionsQuery.error.value.message : null
        "
        :empty="!versions.length"
        @retry="versionsQuery.refetch()"
      >
        <q-list separator class="history-list">
          <q-item v-for="version in versions" :key="version.id">
            <q-item-section avatar
              ><q-avatar color="primary" text-color="white">{{
                version.versionNo
              }}</q-avatar></q-item-section
            >
            <q-item-section
              ><q-item-label>{{ version.reason }}</q-item-label
              ><q-item-label caption
                >{{ new Date(version.createdAt).toLocaleString('zh-CN') }} ·
                {{ version.title }}</q-item-label
              ></q-item-section
            >
            <q-item-section side
              ><AppButton variant="ghost" label="恢复此版本" @click="restore(version)"
            /></q-item-section>
          </q-item>
        </q-list>
      </AsyncStatePanel>
      <div v-if="versionsQuery.hasNextPage.value" class="history-load-more">
        <AppButton
          variant="outline"
          label="加载更多历史版本"
          :loading="versionsQuery.isFetchingNextPage.value"
          @click="versionsQuery.fetchNextPage()"
        />
      </div>
    </AppDialog>

    <AppDialog v-model="revisionDialog" title="让 AI 修改选中内容" width="620px">
      <div class="revision-dialog">
        <q-banner rounded
          >原文：<span>{{ revisionSelection?.text ?? selectedText }}</span></q-banner
        >
        <q-input
          v-model="revisionInstruction"
          outlined
          type="textarea"
          label="修改要求"
          placeholder="例如：把这段写得更简洁、更有案例感"
          autogrow
          autofocus
          :disable="revisionLoading"
        />
        <q-banner v-if="revisionProposal" rounded class="revision-dialog__proposal">
          <strong>AI 修改建议</strong>
          <p>{{ revisionProposal }}</p>
          <small v-if="revisionSimulated">真实模型服务未配置，当前建议不可作为生成结果使用。</small>
        </q-banner>
      </div>
      <template #actions>
        <AppButton
          variant="ghost"
          label="取消"
          :disabled="revisionLoading"
          @click="revisionDialog = false"
        />
        <AppButton
          v-if="revisionProposal"
          variant="outline"
          label="重新生成建议"
          :loading="revisionLoading"
          :disabled="!revisionInstruction.trim()"
          @click="generateRevision"
        />
        <AppButton v-if="revisionProposal" label="确认应用建议" @click="applyRevision" />
        <AppButton
          v-else
          label="生成修改建议"
          :loading="revisionLoading"
          :disabled="!revisionInstruction.trim()"
          @click="generateRevision"
        />
      </template>
    </AppDialog>

    <WechatFinalPreview
      v-if="article && selectedAccount && selectedTemplate"
      v-model="finalDialog"
      :article="article"
      :account="selectedAccount"
      :template="selectedTemplate"
      :action="finalAction"
      :render-html="finalRender?.html"
      :cover-name="coverName"
      :loading="outcomeLoading"
      @confirm="confirmOutcome"
    />
  </q-page>
</template>

<style scoped lang="scss">
.article-page {
  min-width: 0;
  min-height: 0 !important;
  height: 100dvh;
  overflow: clip;
}

.article-workbench {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  min-width: 0;
  min-height: 0;
  height: 100%;
  background: var(--app-bg-page);

  &__header {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 12px;
    min-width: 0;
    padding: 10px clamp(12px, 2vw, 24px);
    background: var(--app-bg-surface);
    border-bottom: 1px solid var(--app-border-default);
  }
  &__main {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(260px, 320px);
    min-width: 0;
    min-height: 0;
  }
  &__footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    min-width: 0;
    padding: 12px clamp(12px, 2vw, 24px);
    background: var(--app-bg-surface);
    border-top: 1px solid var(--app-border-default);
  }
  &__footer > span {
    min-width: 0;
    color: var(--app-text-secondary);
    overflow-wrap: anywhere;
  }
  &__footer > div {
    display: flex;
    flex: 0 0 auto;
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: 10px;
  }
}

.article-title {
  display: flex;
  align-items: center;
  flex: 1 1 300px;
  min-width: 0;
}
.article-title .q-input {
  flex: 1 1 auto;
  min-width: 0;
  font-size: 18px;
  font-weight: 700;
}
.save-indicator {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  color: var(--app-text-secondary);
  font-size: 13px;
  overflow-wrap: anywhere;
}
.save-indicator--saved {
  color: var(--app-action-primary);
}
.save-indicator--failed {
  color: var(--app-danger);
}
.article-conflict-banner {
  flex: 1 0 100%;
  order: 5;
  min-width: 0;
  color: var(--app-text-primary);
  background: color-mix(in srgb, var(--app-warning) 12%, var(--app-bg-surface));
  overflow-wrap: anywhere;
}
.article-conflict-banner p {
  margin: 4px 0 0;
  overflow-wrap: anywhere;
}
.article-conflict-banner :deep(.q-banner__actions) {
  flex-wrap: wrap;
  gap: 6px;
  min-width: 0;
}

.editor-pane,
.layout-preview-pane {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  min-width: 0;
  min-height: 0;
  overflow: clip;
}

.editor-toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 2px;
  min-width: 0;
  padding: 8px clamp(10px, 2vw, 20px);
  overflow-x: auto;
  background: var(--app-bg-surface);
  border-bottom: 1px solid var(--app-border-default);
}
.editor-toolbar .active {
  color: var(--app-action-primary);
  background: var(--app-action-soft);
}
.editor-scroll {
  min-width: 0;
  min-height: 0;
  padding: clamp(14px, 3vw, 32px);
  overflow-y: auto;
}
.editor-document {
  width: min(100%, 820px);
  min-height: 100%;
  margin-inline: auto;
  padding: clamp(24px, 5vw, 64px);
  color: var(--app-text-primary);
  background: var(--app-bg-surface);
  border: 1px solid var(--app-border-default);
  border-radius: 12px;
  box-shadow: var(--app-shadow-sm);
}
.editor-document :deep(.tiptap-body) {
  min-width: 0;
  min-height: 640px;
  outline: none;
  overflow-wrap: anywhere;
}
.editor-document :deep(.tiptap-body h1) {
  font-size: clamp(27px, 4vw, 38px);
  line-height: 1.3;
  overflow-wrap: anywhere;
}
.editor-document :deep(.tiptap-body h2) {
  margin-top: 30px;
  font-size: 24px;
  overflow-wrap: anywhere;
}
.editor-document :deep(.tiptap-body h3) {
  margin-top: 24px;
  font-size: 20px;
  overflow-wrap: anywhere;
}
.editor-document :deep(.tiptap-body p),
.editor-document :deep(.tiptap-body li) {
  font-size: 16px;
  line-height: 1.85;
  overflow-wrap: anywhere;
}
.editor-document :deep(.tiptap-body blockquote) {
  margin-inline: 0;
  padding: 12px 16px;
  color: var(--app-text-secondary);
  background: var(--app-bg-subtle);
  border-left: 4px solid var(--app-action-primary);
}
.editor-document :deep(.tiptap-body [data-module='lead']) {
  color: var(--app-text-secondary);
  font-size: 18px;
}
.editor-document :deep(.tiptap-body [data-module='highlight']) {
  padding: 10px 12px;
  background: var(--app-action-soft);
  border-radius: 6px;
}
.editor-document :deep(.tiptap-body [data-module='caption']) {
  color: var(--app-text-secondary);
  font-size: 13px;
  text-align: center;
}
.editor-document :deep(.tiptap-body img) {
  max-width: 100%;
  height: auto;
}

.layout-preview-pane {
  background: var(--app-bg-subtle);
}
.layout-preview-pane__label {
  padding: 10px 18px;
  color: var(--app-text-secondary);
  background: var(--app-bg-surface);
  border-bottom: 1px solid var(--app-border-default);
  overflow-wrap: anywhere;
}
.layout-preview-pane__scroll {
  min-width: 0;
  min-height: 0;
  padding: clamp(16px, 3vw, 34px);
  overflow-y: auto;
}
.layout-preview-pane__scroll > iframe {
  display: block;
  width: min(100%, 820px);
  min-height: max(100%, 760px);
  margin-inline: auto;
  background: #fff;
  border: 1px solid var(--app-border-default);
  border-radius: 12px;
  box-shadow: var(--app-shadow-sm);
}
.render-message {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  width: min(100%, 720px);
  min-width: 0;
  min-height: 240px;
  margin: 40px auto;
  padding: 24px;
  color: var(--app-text-secondary);
  text-align: center;
  background: var(--app-bg-surface);
  border: 1px solid var(--app-border-default);
  border-radius: 12px;
  overflow-wrap: anywhere;
}
.render-message--error {
  flex-wrap: wrap;
  color: var(--app-danger);
}

.article-meta {
  min-width: 0;
  min-height: 0;
  padding: 20px;
  overflow-y: auto;
  background: var(--app-bg-surface);
  border-left: 1px solid var(--app-border-default);
}
.article-meta h2 {
  margin: 0 0 18px;
  font-size: 19px;
}
.article-meta > .q-field {
  margin-bottom: 14px;
}
.article-meta__warning {
  margin: 0 0 14px;
  color: var(--app-warning);
  background: color-mix(in srgb, var(--app-warning) 10%, var(--app-bg-surface));
  overflow-wrap: anywhere;
}
.cover-card {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  min-width: 0;
  margin: 4px 0 18px;
  padding: 12px;
  background: var(--app-bg-subtle);
  border: 1px solid var(--app-border-default);
  border-radius: 10px;
}
.cover-card span {
  display: grid;
  min-width: 0;
}
.cover-card small {
  color: var(--app-text-secondary);
}
.article-meta__details {
  border-color: var(--app-border-default);
  border-radius: 10px;
}

.history-list {
  min-width: 0;
}
.history-list .q-item {
  min-width: 0;
  padding: 14px 20px;
}
.history-list :deep(.q-item__label) {
  overflow-wrap: anywhere;
  white-space: normal;
}
.history-load-more {
  display: flex;
  justify-content: center;
  min-width: 0;
  padding: 14px 20px;
  border-top: 1px solid var(--app-border-default);
}
.revision-dialog {
  display: grid;
  gap: 16px;
  min-width: 0;
  padding: 20px;
}
.revision-dialog .q-banner {
  min-width: 0;
  background: var(--app-bg-subtle);
}
.revision-dialog .q-banner span {
  overflow-wrap: anywhere;
}
.revision-dialog__proposal p {
  margin: 8px 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.revision-dialog__proposal small {
  color: var(--app-text-secondary);
  overflow-wrap: anywhere;
}

@media (max-width: 1023px) {
  .article-page {
    height: calc(100dvh - 50px);
  }
  .article-workbench__header .q-tabs {
    order: 4;
    width: 100%;
  }
  .article-workbench__main {
    grid-template-columns: minmax(0, 1fr) minmax(220px, 280px);
  }
  .article-workbench__footer {
    align-items: stretch;
    flex-direction: column;
  }
}

@media (max-width: 767px) {
  .article-workbench__main {
    display: block;
    overflow-y: auto;
  }
  .editor-pane,
  .layout-preview-pane {
    min-height: 70vh;
    overflow: visible;
  }
  .editor-scroll,
  .layout-preview-pane__scroll {
    overflow: visible;
  }
  .editor-toolbar {
    position: sticky;
    top: 0;
    z-index: 2;
  }
  .editor-document {
    min-height: 70vh;
    padding: 24px 18px;
    border-radius: 0;
  }
  .article-meta {
    overflow: visible;
    border-top: 1px solid var(--app-border-default);
    border-left: 0;
  }
  .article-workbench__footer > div {
    display: grid;
    grid-template-columns: 1fr;
    width: 100%;
  }
}
</style>

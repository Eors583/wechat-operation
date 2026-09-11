<script setup lang="ts">
import {
  computed,
  defineAsyncComponent,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useInfiniteQuery, useQuery } from '@tanstack/vue-query'
import { useQuasar } from 'quasar'
import { ApiError, api } from '@/api/client'
import type {
  Article,
  Attachment,
  AttachmentUploadProgress,
  LayoutTemplate,
  Message,
  RunStage,
  TaskBundle,
} from '@/api/types'
import { queryClient } from '@/boot/query'
import { useAuthStore } from '@/stores/auth'
import AppButton from '@/components/base/AppButton.vue'
import AppDialog from '@/components/base/AppDialog.vue'
import AsyncStatePanel from '@/components/composite/AsyncStatePanel.vue'
import PromptComposer from '@/components/composite/PromptComposer.vue'
import GenerationProgress from '@/components/business/GenerationProgress.vue'
import MessageArticleCard from '@/components/business/MessageArticleCard.vue'
import PreferenceConfirmationCard from '@/components/business/PreferenceConfirmationCard.vue'
import { usePublicSettings } from '@/composables/usePublicSettings'
import { useLocalDraftSave } from '@/composables/useLocalDraftSave'
import { renderSafeMarkdown } from '@/utils/safeMarkdown'
import { defaultArticleTemplate } from '@/utils/articleDownload'

const route = useRoute()
const router = useRouter()
const $q = useQuasar()
const auth = useAuthStore()
const { settings: publicSettings } = usePublicSettings()
const taskId = computed(() => (typeof route.params.id === 'string' ? route.params.id : ''))
const uploadProgress = ref<AttachmentUploadProgress[]>([])
const activeUploadMessageId = ref('')
const ArticlePreviewPanel = defineAsyncComponent(
  () => import('@/components/business/ArticlePreviewPanel.vue'),
)

const taskQuery = useQuery({
  queryKey: computed(() => ['task', taskId.value]),
  queryFn: async () => {
    const id = taskId.value
    const result = await api.getTask(id)
    const cached = queryClient.getQueryData<TaskBundle>(['task', id])
    if (!cached) return result
    const latestIds = new Set(result.messages.map((message) => message.id))
    return {
      ...result,
      messages: [
        ...cached.messages.filter((message) => !latestIds.has(message.id)),
        ...result.messages,
      ],
      messagesNextCursor: cached.messagesNextCursor,
    }
  },
  enabled: computed(() => Boolean(taskId.value)),
  refetchInterval: (query) =>
    query.state.data?.messages.some(
      (message) =>
        message.preferenceReview === 'pending' &&
        Date.now() - Date.parse(message.preferenceReviewRequestedAt ?? message.createdAt) < 300_000,
    )
      ? 3000
      : false,
})
const skillSearch = ref('')
const skillsQuery = useInfiniteQuery({
  queryKey: computed(() => ['skills', 'composer', skillSearch.value]),
  queryFn: ({ pageParam }) => api.listSkillsPage(pageParam, 50, skillSearch.value || undefined),
  initialPageParam: undefined as string | undefined,
  getNextPageParam: (lastPage) => lastPage.nextCursor,
})
const modelOptionsQuery = useQuery({
  queryKey: ['model-options'],
  queryFn: api.listModelOptions,
})

type PromptComposerInstance = {
  acknowledgeDraft: (draftId: string) => void
  restoreDraft: (draftId: string) => void
}

const bundle = computed(() => taskQuery.data.value ?? null)
const task = computed(() => bundle.value?.task ?? null)
const messages = computed(() => bundle.value?.messages ?? [])
const decidingPreferences = ref(new Set<string>())
const decidePreference = async (message: Message, decision: 'confirmed' | 'dismissed') => {
  const sourceId = message.sourceMessageId
  const id = taskId.value
  if (!sourceId || decidingPreferences.value.has(sourceId)) return
  decidingPreferences.value.add(sourceId)
  try {
    await api.decidePreference(id, sourceId, decision)
    queryClient.setQueryData<TaskBundle>(['task', id], (current) =>
      current
        ? {
            ...current,
            messages: current.messages.map((source) =>
              source.id === sourceId && source.preferenceProposal
                ? {
                    ...source,
                    preferenceProposal: { ...source.preferenceProposal, status: decision },
                  }
                : source,
            ),
          }
        : current,
    )
    await queryClient.invalidateQueries({ queryKey: ['task', id] })
  } catch (error) {
    $q.notify({ type: 'negative', message: error instanceof Error ? error.message : '操作失败' })
  } finally {
    decidingPreferences.value.delete(sourceId)
  }
}
const preferenceForReply = (message: Message) => {
  if (
    message.role !== 'assistant' ||
    !message.sourceMessageId ||
    message.responseKind === 'retry_loading'
  )
    return undefined
  const proposal = messages.value.find(
    (source) => source.id === message.sourceMessageId,
  )?.preferenceProposal
  return proposal?.status === 'pending' && Date.parse(proposal.expiresAt) > Date.now()
    ? proposal
    : undefined
}
const retrySourceId = ref('')
const rawVisibleMessages = computed(() => [
  ...messages.value,
  ...pendingMessages.value.filter(
    (pending) =>
      !messages.value.some(
        (message) =>
          message.id === pending.id ||
          (pending.clientMessageId && message.clientMessageId === pending.clientMessageId),
      ),
  ),
])
const visibleMessages = computed(() => {
  const latestReplies = new Map<string, Message>()
  for (const message of rawVisibleMessages.value) {
    if (message.role === 'assistant' && message.sourceMessageId)
      latestReplies.set(message.sourceMessageId, message)
  }
  const rendered = new Set<string>()
  return rawVisibleMessages.value.flatMap((message): Message[] => {
    if (message.role !== 'assistant' || !message.sourceMessageId) return [message]
    const sourceId = message.sourceMessageId
    if (rendered.has(sourceId)) return []
    rendered.add(sourceId)
    const reply = latestReplies.get(sourceId) ?? message
    if (sourceId === retrySourceId.value && generating.value)
      return [{ ...reply, id: message.id, responseKind: 'retry_loading', content: '' }]
    if (sourceId === retrySourceId.value && runError.value)
      return [
        {
          ...reply,
          id: message.id,
          responseKind: 'ai_error',
          content: runError.value,
          errorCode: runErrorCode.value,
          aiRunId: runErrorRunId.value || reply.aiRunId,
        },
      ]
    return [{ ...reply, id: message.id }]
  })
})
const inlineRetry = computed(() =>
  Boolean(
    retrySourceId.value &&
    rawVisibleMessages.value.some(
      (message) => message.role === 'assistant' && message.sourceMessageId === retrySourceId.value,
    ),
  ),
)
const latestAiRun = computed(() => bundle.value?.latestAiRun ?? null)
const lastUserMessage = computed(() =>
  [...visibleMessages.value].reverse().find((message) => message.role === 'user'),
)
const selectedModelName = computed(
  () =>
    (modelOptionsQuery.data.value ?? []).find((model) => model.id === selectedModelId.value)
      ?.name ?? '自动（稳定优先）',
)
const article = computed(() => bundle.value?.article ?? null)
const fileSize = (bytes: number) =>
  bytes < 1024
    ? `${bytes} B`
    : bytes < 1024 * 1024
      ? `${(bytes / 1024).toFixed(1)} KB`
      : `${(bytes / 1024 / 1024).toFixed(2)} MB`
const attachmentProgress = (messageId: string, attachmentId: string) =>
  messageId === activeUploadMessageId.value
    ? uploadProgress.value.find((item) => item.id === attachmentId)
    : undefined
const attachmentProgressLabel = (item: AttachmentUploadProgress) =>
  `${fileSize(item.loaded)} / ${fileSize(item.total)} · ${
    item.phase === 'uploading'
      ? item.loaded === item.total
        ? '确认上传中'
        : '上传中'
      : item.phase === 'processing'
        ? '解析中'
        : '已就绪'
  }`
const loadedSkills = computed(() => [
  ...new Map(
    (skillsQuery.data.value?.pages.flatMap((page) => page.items) ?? []).map((skill) => [
      skill.id,
      skill,
    ]),
  ).values(),
])
const articleVisible = ref(false)
const selectedArticle = ref<Article | null>(null)
let previewRequest = 0
const previewTemplateId = ref<string | null>(null)
const previewTemplatesQuery = useQuery({
  queryKey: ['templates', 'article-preview'],
  queryFn: () => api.listTemplatesPage(undefined, undefined, 100),
  enabled: computed(() => articleVisible.value && Boolean(article.value)),
})
const previewTemplates = computed<LayoutTemplate[]>(() =>
  [
    ...(selectedArticle.value?.layoutTemplate ? [selectedArticle.value.layoutTemplate] : []),
    ...(previewTemplatesQuery.data.value?.items ?? []).filter(
      (template) => template.id !== selectedArticle.value?.layoutTemplate?.id,
    ),
  ].filter(
    (template) =>
      template.enabled &&
      template.status === 'ready' &&
      (!selectedArticle.value?.accountId ||
        template.accountId === null ||
        template.accountId === selectedArticle.value.accountId),
  ),
)
const previewTemplate = computed(
  () => previewTemplates.value.find((template) => template.id === previewTemplateId.value) ?? null,
)
const selectedProjectId = ref<string | null>(null)
const selectedSkillIds = ref<string[]>([])
const missingSkillIds = computed(() =>
  selectedSkillIds.value.filter((id) => !loadedSkills.value.some((skill) => skill.id === id)),
)
const selectedSkillsQuery = useQuery({
  queryKey: computed(() => ['selected-skills', missingSkillIds.value]),
  enabled: computed(() => missingSkillIds.value.length > 0),
  queryFn: () =>
    Promise.all(
      missingSkillIds.value.map((id) =>
        api.getSkill(id).catch((error: unknown) => {
          if (error instanceof ApiError && error.status === 404) return null
          throw error
        }),
      ),
    ),
})
const skills = computed(() => [
  ...new Map(
    [...(selectedSkillsQuery.data.value ?? []), ...loadedSkills.value]
      .filter((skill) => skill !== null)
      .map((skill) => [skill.id, skill]),
  ).values(),
])
const selectedModelId = ref<string | null>(null)
const selectedModelAvailable = computed(
  () =>
    selectedModelId.value === null ||
    (modelOptionsQuery.data.value ?? []).some((model) => model.id === selectedModelId.value),
)
const pendingMessages = ref<Message[]>([])
const generating = ref(false)
const runStage = ref<RunStage | null>(null)
const runStageHistory = ref<RunStage[]>([])
const recordRunStage = (stage: RunStage) => {
  runStage.value = stage
  if (
    !['reconnecting', 'failed', 'cancelled'].includes(stage) &&
    !runStageHistory.value.includes(stage)
  )
    runStageHistory.value.push(stage)
}
const runError = ref('')
const runErrorCode = ref('')
const awaitingConfirmation = computed(() =>
  ['AI_RUN_REQUEST_PENDING', 'AI_RUN_STREAM_UNAVAILABLE'].includes(runErrorCode.value),
)
const runErrorRunId = ref('')
const streamingText = ref('')
const conversation = ref<HTMLElement | null>(null)
const articlePreviewPanel = ref<{
  canSave: boolean
  dirty: boolean
  saveNow: () => Promise<Article | null>
  saving: boolean
  versionNo: number
} | null>(null)
const { saving: localSaving, save: saveLocalDraft } = useLocalDraftSave()
const saveLocal = () =>
  saveLocalDraft(async () => {
    const panel = articlePreviewPanel.value
    if (!panel || panel.saving) return null
    const saved = await panel.saveNow()
    return panel.dirty ? null : saved
  })
const currentRunId = ref('')
const activeGenerationTaskId = ref('')
const loadingEarlier = ref(false)
const taskComposer = ref<PromptComposerInstance | null>(null)
const blankComposer = ref<PromptComposerInstance | null>(null)
let generationToken = 0
let generationController: AbortController | null = null
let initializedTaskSettings = ''
let initializedModelOwnerId = ''
let pageActive = true
let prependingMessages = false

const friendlyRunError = (code?: string, message?: string) => {
  if (code === 'ModelRouteExhausted' || code === 'ProviderUnavailable')
    return selectedModelId.value
      ? '所选模型和备用模型本次均未能完成生成。你可以切回“自动（稳定优先）”后重新生成。'
      : '主模型和备用模型本次均未能完成生成。系统已保留消息和附件，请稍后重新生成。'
  if (code === 'AI_RUN_STREAM_UNAVAILABLE')
    return '生成仍在后台执行，但实时连接暂时中断。请稍后刷新任务查看结果。'
  return message?.trim() || '内容生成没有完成，你可以直接重试，已上传的资料不会丢失。'
}

const persistedFailureRunIds = computed(
  () =>
    new Set(
      messages.value
        .filter((message) => message.responseKind === 'ai_error' && message.aiRunId)
        .map((message) => message.aiRunId as string),
    ),
)

const displayedRunFailure = computed(() => {
  if (generating.value) return null
  if (inlineRetry.value && runError.value) return null
  if (
    runError.value &&
    (!runErrorRunId.value || !persistedFailureRunIds.value.has(runErrorRunId.value))
  ) {
    return {
      message: runError.value,
      errorCode: runErrorCode.value,
      runId: runErrorRunId.value,
    }
  }
  const latest = latestAiRun.value
  if (latest?.status === 'failed' && !persistedFailureRunIds.value.has(latest.id)) {
    return {
      message: friendlyRunError(latest.errorCode, latest.errorMessage),
      errorCode: latest.errorCode ?? '',
      runId: latest.id,
    }
  }
  return null
})

const alternativeModel = computed(() =>
  (modelOptionsQuery.data.value ?? []).find((model) => model.id !== selectedModelId.value),
)

const examples = computed(() =>
  publicSettings.value.home.examplePrompts.map((text, index) => ({
    icon: ['description', 'edit_note', 'lightbulb_outline', 'title'][index % 4],
    text,
  })),
)

watch(
  task,
  (value) => {
    if (!value || initializedTaskSettings === value.id) return
    const latestUserMessage = [...messages.value].reverse().find((item) => item.role === 'user')
    selectedSkillIds.value =
      latestUserMessage?.skillIds ?? (value.currentSkillId ? [value.currentSkillId] : [])
    initializedTaskSettings = value.id
  },
  { immediate: true },
)
watch(
  [selectedArticle, previewTemplates],
  ([currentArticle, templates], [previousArticle]) => {
    if (
      currentArticle?.id === previousArticle?.id &&
      templates.some((template) => template.id === previewTemplateId.value)
    )
      return
    previewTemplateId.value = currentArticle
      ? (defaultArticleTemplate(currentArticle, templates)?.id ?? null)
      : null
  },
  { immediate: true },
)
watch(taskId, (value) => {
  articleVisible.value = false
  if (!value || value !== activeGenerationTaskId.value) pendingMessages.value = []
  runError.value = ''
  runErrorCode.value = ''
  runErrorRunId.value = ''
  if (value) return
  initializedTaskSettings = ''
  selectedProjectId.value = null
  selectedSkillIds.value = []
})
const modelPreferenceKey = (ownerId: string) => `wechat-ai-selected-model:${ownerId}`
const selectModel = (modelId: string | null) => {
  if (modelId && !(modelOptionsQuery.data.value ?? []).some((model) => model.id === modelId)) return
  selectedModelId.value = modelId
  const ownerId = auth.user?.id
  if (!ownerId) return
  if (modelId) localStorage.setItem(modelPreferenceKey(ownerId), modelId)
  else localStorage.removeItem(modelPreferenceKey(ownerId))
}
watch(
  [() => auth.user?.id ?? '', () => modelOptionsQuery.data.value ?? []],
  ([ownerId, models]) => {
    if (!ownerId || !models.length || initializedModelOwnerId === ownerId) return
    const storedModelId = localStorage.getItem(modelPreferenceKey(ownerId))
    selectedModelId.value =
      storedModelId && models.some((model) => model.id === storedModelId) ? storedModelId : null
    initializedModelOwnerId = ownerId
  },
  { immediate: true },
)
const nearConversationEnd = () => {
  const element = conversation.value
  return !element || element.scrollHeight - element.scrollTop - element.clientHeight < 160
}

watch(visibleMessages, async (_next, previous) => {
  if (prependingMessages) return
  const follow = !previous.length || nearConversationEnd()
  await nextTick()
  if (follow)
    conversation.value?.scrollTo({ top: conversation.value.scrollHeight, behavior: 'smooth' })
})
watch([streamingText, runStage], async () => {
  const follow = nearConversationEnd()
  await nextTick()
  if (follow)
    conversation.value?.scrollTo({ top: conversation.value.scrollHeight, behavior: 'smooth' })
})

const cacheTaskResult = (result: TaskBundle) => {
  queryClient.setQueryData<TaskBundle>(['task', result.task.id], (cached) => {
    if (!cached) return result
    const latestIds = new Set(result.messages.map((message) => message.id))
    return {
      ...result,
      messages: [
        ...cached.messages.filter((message) => !latestIds.has(message.id)),
        ...result.messages,
      ],
      messagesNextCursor: cached.messagesNextCursor,
    }
  })
}

const refreshCurrentTask = async () => {
  if (!taskId.value) return
  cacheTaskResult(await api.getTask(taskId.value))
}

const loadEarlierMessages = async () => {
  const current = bundle.value
  const element = conversation.value
  if (!current?.messagesNextCursor || !element || loadingEarlier.value) return
  loadingEarlier.value = true
  prependingMessages = true
  const previousHeight = element.scrollHeight
  const previousTop = element.scrollTop
  try {
    const page = await api.listTaskMessages(current.task.id, current.messagesNextCursor)
    queryClient.setQueryData<TaskBundle>(['task', current.task.id], (cached) => {
      if (!cached) return cached
      const known = new Set(cached.messages.map((message) => message.id))
      return {
        ...cached,
        messages: [...page.items.filter((message) => !known.has(message.id)), ...cached.messages],
        messagesNextCursor: page.nextCursor,
      }
    })
    await nextTick()
    element.scrollTop = previousTop + element.scrollHeight - previousHeight
  } catch (error) {
    $q.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '更早消息加载失败，请重试。',
    })
  } finally {
    prependingMessages = false
    loadingEarlier.value = false
  }
}

const send = async (payload: {
  text: string
  attachments: Attachment[]
  draftId?: string
  retryMessage?: Message
  retryOfRunId?: string
}) => {
  if (generating.value) return
  retrySourceId.value = payload.retryMessage?.id ?? ''
  generationController?.abort()
  generationController = new AbortController()
  const controller = generationController
  const token = ++generationToken
  uploadProgress.value = []
  const pendingMessage: Message = payload.retryMessage ?? {
    id: `pending_${payload.draftId ?? crypto.randomUUID()}`,
    clientMessageId: `message_${crypto.randomUUID()}`,
    taskId: taskId.value || 'pending',
    role: 'user',
    content: payload.text,
    createdAt: new Date().toISOString(),
    attachments: payload.attachments,
    skillIds: [...selectedSkillIds.value],
  }
  activeUploadMessageId.value = pendingMessage.id
  const originRoute = route.fullPath
  activeGenerationTaskId.value = taskId.value
  const visibleForRun = () =>
    pageActive &&
    (activeGenerationTaskId.value
      ? taskId.value === activeGenerationTaskId.value
      : route.fullPath === originRoute)
  if (!payload.retryMessage) pendingMessages.value = [...pendingMessages.value, pendingMessage]
  generating.value = true
  runError.value = ''
  runErrorCode.value = ''
  runErrorRunId.value = ''
  streamingText.value = ''
  runStage.value = 'submitting'
  runStageHistory.value = ['submitting']
  try {
    const pending = api.sendMessage({
      clientMessageId: pendingMessage.clientMessageId,
      retryOfRunId: payload.retryOfRunId,
      taskId: taskId.value || undefined,
      projectId: taskId.value ? (task.value?.projectId ?? null) : selectedProjectId.value,
      text: payload.text,
      skillIds: pendingMessage.skillIds ?? selectedSkillIds.value,
      modelDeploymentId: selectedModelId.value,
      usePreferences: true,
      attachments: payload.attachments,
      signal: controller.signal,
      onRunAccepted: async (runId, acceptedTaskId, clientMessageId) => {
        // Acceptance persists the task; sidebar discovery must not wait for generation.
        void queryClient.invalidateQueries({ queryKey: ['tasks'] })
        if (token !== generationToken) void api.cancelRun(runId)
        else {
          uploadProgress.value = []
          pendingMessages.value = pendingMessages.value.map((message) =>
            message.id === pendingMessage.id
              ? { ...message, clientMessageId: clientMessageId ?? message.clientMessageId }
              : message,
          )
          activeGenerationTaskId.value = acceptedTaskId
          if (!taskId.value) {
            // Warm the conversation cache before replacing the optimistic new-chat view.
            await api
              .getTask(acceptedTaskId)
              .then(cacheTaskResult)
              .catch(() => undefined)
            if (token === generationToken && pageActive && route.fullPath === originRoute)
              await router.replace(`/tasks/${acceptedTaskId}`)
          }
          if (visibleForRun()) currentRunId.value = runId
        }
      },
      onRunStage: (stage) => {
        if (token === generationToken && visibleForRun()) recordRunStage(stage)
      },
      onTextDelta: (text) => {
        if (token === generationToken && visibleForRun()) streamingText.value += text
      },
      onArticleReady: () => {
        if (token === generationToken && visibleForRun()) {
          streamingText.value = ''
          void refreshCurrentTask()
        }
      },
      onAttachmentUploaded: () => {
        void queryClient.invalidateQueries({ queryKey: ['library'] })
      },
      onAttachmentProgress: (progress) => {
        if (token !== generationToken || !visibleForRun()) return
        const index = uploadProgress.value.findIndex((item) => item.id === progress.id)
        if (index < 0) uploadProgress.value.push(progress)
        else uploadProgress.value[index] = progress
      },
    })
    const result = await pending
    if (token !== generationToken) return
    if (visibleForRun()) {
      runStage.value = 'completed'
      streamingText.value = ''
    }
    pendingMessages.value = pendingMessages.value.filter(
      (message) => message.id !== pendingMessage.id,
    )
    cacheTaskResult(result)
    if (payload.draftId) {
      taskComposer.value?.acknowledgeDraft(payload.draftId)
      blankComposer.value?.acknowledgeDraft(payload.draftId)
    }
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['tasks'] }),
      queryClient.invalidateQueries({ queryKey: ['library'] }),
      queryClient.invalidateQueries({ queryKey: ['preferences'] }),
      queryClient.invalidateQueries({ queryKey: ['skills'] }),
    ])
    if (visibleForRun() && !taskId.value) await router.replace(`/tasks/${result.task.id}`)
  } catch (error) {
    if (token !== generationToken) return
    if (visibleForRun()) {
      runStage.value = 'failed'
      runErrorCode.value = error instanceof ApiError ? error.code : 'CLIENT_GENERATION_ERROR'
      runErrorRunId.value = currentRunId.value
      runError.value = friendlyRunError(
        runErrorCode.value,
        error instanceof Error ? error.message : undefined,
      )
      const saved = api.getPendingMessage(taskId.value)
      if (saved)
        pendingMessages.value = pendingMessages.value.map((message) =>
          message.id === pendingMessage.id ? saved.message : message,
        )
      await refreshCurrentTask().catch(() => undefined)
    }
  } finally {
    if (token === generationToken) {
      uploadProgress.value = []
      activeUploadMessageId.value = ''
      if (visibleForRun()) {
        generating.value = false
        currentRunId.value = ''
      }
      if (generationController === controller) {
        generationController = null
        activeGenerationTaskId.value = ''
      }
      await auth.refreshUser().catch(() => undefined)
    }
  }
}

const failedMessageSource = (failure?: Message) => {
  if (!failure) return lastUserMessage.value
  if (failure.sourceMessageId) {
    const source = messages.value.find((message) => message.id === failure.sourceMessageId)
    if (source?.role === 'user') return source
  }
  const failureIndex = messages.value.findIndex((message) => message.id === failure.id)
  return messages.value
    .slice(0, failureIndex < 0 ? undefined : failureIndex)
    .reverse()
    .find((message) => message.role === 'user')
}

const retryLastRun = async (failure?: Message) => {
  if (awaitingConfirmation.value && (!failure || failure.sourceMessageId === retrySourceId.value)) {
    resumeOriginalRequest()
    return
  }
  const message = failedMessageSource(failure)
  if (!message || generating.value || !selectedModelAvailable.value) return
  const retryOfRunId = failure?.aiRunId || displayedRunFailure.value?.runId
  if (retryOfRunId && message.clientMessageId) {
    await send({
      text: message.content,
      attachments: message.attachments ?? [],
      retryMessage: message,
      retryOfRunId,
    })
  } else {
    resumeOriginalRequest()
  }
}

const isFailureMessage = (message: Message) => message.responseKind === 'ai_error'

const switchModel = () => {
  const model = alternativeModel.value
  if (!model) return
  selectModel(model.id)
  $q.notify({
    type: 'info',
    message: `已切换到 ${model.name}，可以重新生成。`,
    position: 'top',
  })
}

const chooseSuggestion = async (message: TaskBundle['messages'][number], suggestion: string) => {
  if (message.responseKind !== 'article_conflict_confirmation') {
    await send({ text: suggestion, attachments: [] })
    return
  }
  const messageIndex = messages.value.findIndex((item) => item.id === message.id)
  const originalRequest = messages.value
    .slice(0, messageIndex)
    .reverse()
    .find((item) => item.role === 'user')
  if (!originalRequest) {
    if (suggestion === '新建任务') await router.push('/create')
    else await send({ text: suggestion, attachments: [] })
    return
  }
  if (suggestion === '覆盖当前文章') {
    await send({
      text: `覆盖当前文章。${originalRequest.content}`,
      attachments: originalRequest.attachments ?? [],
    })
    return
  }
  await router.push('/create')
  await nextTick()
  await send({
    text: originalRequest.content,
    attachments: originalRequest.attachments ?? [],
  })
}

const stop = () => {
  const runId = currentRunId.value
  generationController?.abort()
  generationController = null
  generationToken += 1
  currentRunId.value = ''
  generating.value = false
  runStage.value = 'cancelled'
  if (runId) void api.cancelRun(runId).finally(() => auth.refreshUser().catch(() => undefined))
  $q.notify({ message: '生成已经停止，现有内容和资料都已保留。', color: 'info' })
}

const resumeOriginalRequest = () => {
  if (generating.value) return
  const saved = api.getPendingMessage(taskId.value)
  if (!saved) return
  const original = messages.value.find(
    (message) =>
      message.role === 'user' && message.clientMessageId === saved.message.clientMessageId,
  )
  if (original && messages.value.some((message) => message.sourceMessageId === original.id))
    retrySourceId.value = original.id
  if (!pendingMessages.value.some((message) => message.id === saved.message.id))
    pendingMessages.value.push(saved.message)
  const token = ++generationToken
  const controller = new AbortController()
  const originRoute = route.fullPath
  const visibleForRun = () =>
    pageActive &&
    (activeGenerationTaskId.value
      ? taskId.value === activeGenerationTaskId.value
      : route.fullPath === originRoute)
  generationController = controller
  generating.value = true
  runStage.value = 'reconnecting'
  runStageHistory.value = []
  runError.value = ''
  runErrorCode.value = ''
  runErrorRunId.value = ''
  streamingText.value = ''
  void api
    .resumePendingMessage({
      pendingKey: saved.key,
      signal: controller.signal,
      onRunAccepted: async (runId, acceptedTaskId) => {
        void queryClient.invalidateQueries({ queryKey: ['tasks'] })
        if (token !== generationToken) return
        activeGenerationTaskId.value = acceptedTaskId
        if (!taskId.value) await router.replace(`/tasks/${acceptedTaskId}`)
        if (visibleForRun()) currentRunId.value = runId
      },
      onRunStage: (stage) => {
        if (token === generationToken && visibleForRun()) recordRunStage(stage)
      },
      onTextDelta: (text) => {
        if (token === generationToken && visibleForRun()) streamingText.value += text
      },
      onArticleReady: () => {
        if (token === generationToken && visibleForRun()) {
          streamingText.value = ''
          void refreshCurrentTask()
        }
      },
    })
    .then(async (result) => {
      if (!result || token !== generationToken) return
      if (visibleForRun()) {
        runStage.value = 'completed'
        streamingText.value = ''
      }
      cacheTaskResult(result)
      pendingMessages.value = pendingMessages.value.filter(
        (message) => message.id !== saved.message.id,
      )
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['tasks'] }),
        queryClient.invalidateQueries({ queryKey: ['library'] }),
        queryClient.invalidateQueries({ queryKey: ['preferences'] }),
        queryClient.invalidateQueries({ queryKey: ['skills'] }),
      ])
      if (visibleForRun() && taskId.value !== result.task.id)
        await router.replace(`/tasks/${result.task.id}`)
    })
    .catch((error: unknown) => {
      if (token !== generationToken || controller.signal.aborted || !visibleForRun()) return
      runStage.value = 'failed'
      runErrorCode.value = error instanceof ApiError ? error.code : 'CLIENT_GENERATION_ERROR'
      runErrorRunId.value = currentRunId.value
      runError.value = friendlyRunError(
        runErrorCode.value,
        error instanceof Error ? error.message : undefined,
      )
      void refreshCurrentTask().catch(() => undefined)
    })
    .finally(() => {
      if (token !== generationToken) return
      if (visibleForRun()) {
        generating.value = false
        currentRunId.value = ''
      }
      if (generationController === controller) {
        generationController = null
        activeGenerationTaskId.value = ''
      }
      void auth.refreshUser().catch(() => undefined)
    })
}
onMounted(resumeOriginalRequest)

watch(
  () => route.fullPath,
  () => {
    if (!generationController) return
    if (activeGenerationTaskId.value && taskId.value === activeGenerationTaskId.value) return
    generating.value = false
    currentRunId.value = ''
    runStage.value = null
    streamingText.value = ''
  },
)
onBeforeUnmount(() => {
  pageActive = false
})

const openArticle = async (message: Message) => {
  const request = ++previewRequest
  try {
    if (!message.articleId) throw new Error('这条消息没有关联文章。')
    const resolved = await api.getArticle(message.articleId)
    if (request !== previewRequest) return
    previewTemplateId.value = resolved.templateId
    selectedArticle.value = resolved
    articleVisible.value = true
  } catch (error) {
    if (request === previewRequest)
      $q.notify({
        type: 'negative',
        message: error instanceof Error ? error.message : '预览加载失败。',
      })
  }
}

const editArticle = async () => {
  await articlePreviewPanel.value?.saveNow()
  if (articlePreviewPanel.value?.dirty || articlePreviewPanel.value?.saving) return
  if (selectedArticle.value) void router.push(`/articles/${selectedArticle.value.id}/edit`)
}
const layoutArticle = async () => {
  await articlePreviewPanel.value?.saveNow()
  if (articlePreviewPanel.value?.dirty || articlePreviewPanel.value?.saving) return
  if (selectedArticle.value)
    void router.push({
      path: `/articles/${selectedArticle.value.id}/edit`,
      query: { view: 'layout' },
    })
}
</script>

<template>
  <q-page class="create-page">
    <AsyncStatePanel
      v-if="taskId || pendingMessages.length || generating"
      :loading="Boolean(taskId) && taskQuery.isPending.value && !pendingMessages.length"
      :error="
        taskId && !pendingMessages.length && taskQuery.error.value instanceof Error
          ? taskQuery.error.value.message
          : null
      "
      @retry="taskQuery.refetch()"
    >
      <div class="workspace">
        <section class="workspace__chat">
          <header class="task-header">
            <div class="task-header__title">
              <h1>{{ task?.title || '新对话' }}</h1>
            </div>
          </header>

          <div ref="conversation" class="conversation" aria-live="polite">
            <div v-if="bundle?.messagesNextCursor" class="conversation__earlier">
              <AppButton
                label="加载更早消息"
                icon="history"
                variant="ghost"
                :loading="loadingEarlier"
                @click="loadEarlierMessages"
              />
            </div>
            <div
              v-for="message in visibleMessages"
              :key="message.id"
              :class="['message', `message--${message.role}`]"
            >
              <q-avatar
                v-if="message.role === 'assistant'"
                color="primary"
                text-color="white"
                icon="auto_awesome"
              />
              <div class="message__bubble">
                <template v-if="message.responseKind === 'retry_loading'">
                  <GenerationProgress
                    :stage="runStage"
                    :history="runStageHistory"
                    :model-name="selectedModelName"
                  />
                  <div
                    v-if="streamingText"
                    class="message__rich-text"
                    v-html="renderSafeMarkdown(streamingText)"
                  />
                </template>
                <div v-else-if="isFailureMessage(message)" class="message__failure" role="alert">
                  <strong><q-icon name="error_outline" />本次生成没有完成</strong>
                  <p>{{ message.content }}</p>
                  <div class="message__failure-meta">
                    <span v-if="message.errorCode">错误代码：{{ message.errorCode }}</span>
                    <span v-if="message.aiRunId">运行编号：{{ message.aiRunId }}</span>
                  </div>
                  <div class="message__failure-actions">
                    <AppButton
                      v-if="alternativeModel"
                      variant="ghost"
                      label="切换模型"
                      icon="swap_horiz"
                      :disabled="generating"
                      @click="switchModel"
                    />
                    <AppButton
                      :label="
                        awaitingConfirmation && message.sourceMessageId === retrySourceId
                          ? '继续原请求'
                          : '重新生成'
                      "
                      icon="refresh"
                      :loading="generating"
                      :disabled="
                        generating || !failedMessageSource(message) || !selectedModelAvailable
                      "
                      @click="retryLastRun(message)"
                    />
                  </div>
                </div>
                <div
                  v-else-if="message.role === 'assistant'"
                  class="message__rich-text"
                  v-html="renderSafeMarkdown(message.content)"
                />
                <p v-else>{{ message.content }}</p>
                <div v-if="message.attachments?.length" class="message__attachments">
                  <div
                    v-for="attachment in message.attachments"
                    :key="attachment.id"
                    class="message__attachment"
                  >
                    <q-icon :name="attachment.kind === 'link' ? 'link' : 'attach_file'" />
                    <span class="message__attachment-content">
                      <span class="message__attachment-name" :title="attachment.name">{{
                        attachment.name
                      }}</span>
                      <small
                        v-if="attachmentProgress(message.id, attachment.id)"
                        class="message__attachment-progress"
                        role="status"
                        >{{
                          attachmentProgressLabel(attachmentProgress(message.id, attachment.id)!)
                        }}</small
                      >
                    </span>
                  </div>
                </div>
                <MessageArticleCard
                  v-if="message.articleId && message.responseKind !== 'retry_loading'"
                  :message="message"
                  @preview="openArticle(message)"
                />
                <PreferenceConfirmationCard
                  v-if="preferenceForReply(message)"
                  :proposal="preferenceForReply(message)!"
                  :disabled="decidingPreferences.has(message.sourceMessageId!)"
                  @decide="(decision) => decidePreference(message, decision)"
                />
                <div
                  v-if="message.suggestions?.length && message.responseKind !== 'retry_loading'"
                  class="message__suggestions"
                >
                  <button
                    v-for="suggestion in message.suggestions"
                    :key="suggestion"
                    @click="chooseSuggestion(message, suggestion)"
                  >
                    {{ suggestion }}<q-icon name="chevron_right" />
                  </button>
                </div>
              </div>
              <q-avatar v-if="message.role === 'user'" color="primary" text-color="white">{{
                $q.screen.lt.sm ? '我' : '陈'
              }}</q-avatar>
            </div>

            <div
              v-if="generating && !inlineRetry"
              class="message message--assistant message--thinking"
            >
              <q-avatar color="primary" text-color="white" icon="auto_awesome" />
              <div class="message__bubble">
                <GenerationProgress
                  :stage="runStage"
                  :history="runStageHistory"
                  :model-name="selectedModelName"
                />
              </div>
            </div>

            <div
              v-if="streamingText && !inlineRetry"
              class="message message--assistant message--streaming"
            >
              <q-avatar color="primary" text-color="white" icon="auto_awesome" />
              <div class="message__bubble">
                <div class="message__rich-text" v-html="renderSafeMarkdown(streamingText)" />
                <q-spinner-dots v-if="generating" color="primary" size="22px" />
              </div>
            </div>

            <div v-if="displayedRunFailure" class="message message--assistant message--failure">
              <q-avatar color="primary" text-color="white" icon="auto_awesome" />
              <div class="message__bubble">
                <div class="message__failure" role="alert">
                  <strong
                    ><q-icon :name="awaitingConfirmation ? 'info_outline' : 'error_outline'" />{{
                      awaitingConfirmation ? '发送结果待确认' : '本次生成没有完成'
                    }}</strong
                  >
                  <p>{{ displayedRunFailure.message }}</p>
                  <div class="message__failure-meta">
                    <span v-if="displayedRunFailure.errorCode"
                      >错误代码：{{ displayedRunFailure.errorCode }}</span
                    >
                    <span v-if="displayedRunFailure.runId"
                      >运行编号：{{ displayedRunFailure.runId }}</span
                    >
                  </div>
                  <div class="message__failure-actions">
                    <AppButton
                      v-if="alternativeModel && !awaitingConfirmation"
                      variant="ghost"
                      label="切换模型"
                      icon="swap_horiz"
                      :disabled="generating"
                      @click="switchModel"
                    />
                    <AppButton
                      :label="awaitingConfirmation ? '继续原请求' : '重新生成'"
                      icon="refresh"
                      :loading="generating"
                      :disabled="
                        !lastUserMessage || (!awaitingConfirmation && !selectedModelAvailable)
                      "
                      @click="retryLastRun()"
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div class="workspace__composer safe-bottom">
            <PromptComposer
              ref="taskComposer"
              v-model:selected-skill-ids="selectedSkillIds"
              :selected-model-id="selectedModelId"
              :skills="skills"
              :skill-search="skillSearch"
              :models="modelOptionsQuery.data.value ?? []"
              :models-loading="modelOptionsQuery.isFetching.value"
              :skills-has-more="skillsQuery.hasNextPage.value"
              :skills-loading-more="skillsQuery.isFetchingNextPage.value"
              :loading="generating"
              :send-disabled="
                awaitingConfirmation ||
                !selectedModelAvailable ||
                modelOptionsQuery.isFetching.value
              "
              :allowed-extensions="publicSettings.files.allowedExtensions"
              :max-file-mb="publicSettings.files.maxFileMb"
              :link-fetch-enabled="publicSettings.files.linkFetchEnabled"
              :skills-enabled="publicSettings.features.featureFlags.personal_skills !== false"
              :visual-understanding-enabled="
                publicSettings.features.featureFlags.visual_understanding !== false
              "
              @load-more-skills="skillsQuery.fetchNextPage()"
              @search-skills="skillSearch = $event"
              @update:selected-model-id="selectModel"
              @send="send"
              @stop="stop"
            />
          </div>
        </section>
      </div>
    </AsyncStatePanel>

    <section v-else class="blank-create">
      <div class="blank-create__content">
        <q-icon name="auto_awesome" color="primary" size="52px" />
        <h1>{{ publicSettings.home.welcomeMessage }}</h1>
        <p>描述你的需求，内容助手会帮你整理资料并完成文章</p>
        <PromptComposer
          ref="blankComposer"
          v-model:selected-skill-ids="selectedSkillIds"
          :selected-model-id="selectedModelId"
          :skills="skills"
          :skill-search="skillSearch"
          :models="modelOptionsQuery.data.value ?? []"
          :models-loading="modelOptionsQuery.isFetching.value"
          :skills-has-more="skillsQuery.hasNextPage.value"
          :skills-loading-more="skillsQuery.isFetchingNextPage.value"
          :loading="generating"
          :send-disabled="
            awaitingConfirmation || !selectedModelAvailable || modelOptionsQuery.isFetching.value
          "
          :allowed-extensions="publicSettings.files.allowedExtensions"
          :max-file-mb="publicSettings.files.maxFileMb"
          :link-fetch-enabled="publicSettings.files.linkFetchEnabled"
          :skills-enabled="publicSettings.features.featureFlags.personal_skills !== false"
          :visual-understanding-enabled="
            publicSettings.features.featureFlags.visual_understanding !== false
          "
          @load-more-skills="skillsQuery.fetchNextPage()"
          @search-skills="skillSearch = $event"
          @update:selected-model-id="selectModel"
          @send="send"
          @stop="stop"
        />
        <GenerationProgress
          v-if="generating"
          :stage="runStage"
          :history="runStageHistory"
          :model-name="selectedModelName"
        />
        <div class="blank-create__examples" aria-label="示例指令">
          <span>你可以试试</span>
          <button
            v-for="example in examples"
            :key="example.text"
            :disabled="generating"
            @click="send({ text: example.text, attachments: [] })"
          >
            <q-icon :name="example.icon" />{{ example.text }}<q-icon name="chevron_right" />
          </button>
        </div>
        <div
          v-if="streamingText"
          class="blank-create__streaming"
          v-html="renderSafeMarkdown(streamingText)"
        />
        <div v-if="displayedRunFailure" class="message message--assistant message--failure">
          <q-avatar color="primary" text-color="white" icon="auto_awesome" />
          <div class="message__bubble">
            <div class="message__failure" role="alert">
              <strong><q-icon name="error_outline" />本次生成没有完成</strong>
              <p>{{ displayedRunFailure.message }}</p>
              <div class="message__failure-meta">
                <span v-if="displayedRunFailure.errorCode"
                  >错误代码：{{ displayedRunFailure.errorCode }}</span
                >
                <span v-if="displayedRunFailure.runId"
                  >运行编号：{{ displayedRunFailure.runId }}</span
                >
              </div>
              <div v-if="alternativeModel" class="message__failure-actions">
                <AppButton
                  variant="ghost"
                  label="切换模型"
                  icon="swap_horiz"
                  :disabled="generating"
                  @click="switchModel"
                />
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <AppDialog
      v-if="selectedArticle"
      v-model="articleVisible"
      title="文章预览"
      width="1480px"
      :full-screen-mobile="false"
    >
      <ArticlePreviewPanel
        v-if="articleVisible"
        ref="articlePreviewPanel"
        :key="`${selectedArticle.id}:${selectedArticle.versionNo}`"
        :article="selectedArticle"
        :template="previewTemplate"
        :templates="previewTemplates"
        :templates-loading="previewTemplatesQuery.isPending.value"
        :templates-error="
          previewTemplatesQuery.error.value instanceof Error
            ? previewTemplatesQuery.error.value.message
            : ''
        "
        @select-template="previewTemplateId = $event"
      />
      <template #actions>
        <AppButton
          class="article-preview-dialog__button article-preview-dialog__local"
          variant="outline"
          label="存本地草稿箱"
          :loading="localSaving || articlePreviewPanel?.saving"
          :disabled="!articlePreviewPanel"
          @click="saveLocal"
        />
        <AppButton
          class="article-preview-dialog__button"
          variant="outline"
          label="存公众号草稿箱"
          @click="layoutArticle"
        />
        <AppButton class="article-preview-dialog__button" label="直接发布" @click="editArticle" />
      </template>
    </AppDialog>
  </q-page>
</template>

<style scoped lang="scss">
.create-page {
  min-width: 0;
  min-height: 0 !important;
  height: 100dvh;
  overflow: clip;
}

.workspace {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  min-width: 0;
  min-height: 0;
  height: 100%;
  padding: 0;
  gap: 0;
  &__chat {
    display: grid;
    grid-template-rows: auto minmax(0, 1fr) auto;
    min-width: 0;
    min-height: 0;
    overflow: clip;
    background: var(--app-bg-surface);
    border: 0;
    border-radius: 0;
  }

  &__composer {
    min-width: 0;
    padding: 10px clamp(10px, 2.5vw, 28px) 12px;
    background: var(--app-bg-surface);
    border-top: 1px solid var(--app-border-default);
  }
}

.task-header {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  padding: 12px 18px;
  border-bottom: 1px solid var(--app-border-default);

  &__title {
    display: flex;
    align-items: center;
    flex: 1 1 auto;
    min-width: 0;
  }
  h1 {
    min-width: 0;
    margin: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 19px;
  }
}

.conversation {
  min-width: 0;
  min-height: 0;
  padding: clamp(18px, 3vw, 34px);
  overflow-y: auto;
  overscroll-behavior: contain;

  &__earlier {
    display: flex;
    justify-content: center;
    min-width: 0;
    margin: 0 0 20px;
  }
}

.message {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  min-width: 0;
  margin-bottom: 26px;

  &--user {
    justify-content: flex-end;
  }
  &--user .message__bubble {
    flex: 0 1 auto;
    width: fit-content;
    max-width: min(78%, 780px);
    padding: 14px 16px;
    background: var(--app-action-soft);
    border: 1px solid color-mix(in srgb, var(--app-action-primary) 18%, transparent);
    border-radius: 14px 4px 14px 14px;
  }
  &--assistant .message__bubble {
    flex: 1 1 auto;
    max-width: 880px;
  }

  &__bubble {
    min-width: 0;
  }
  &__bubble > p {
    margin: 0;
    line-height: 1.75;
    overflow-wrap: anywhere;
  }
  &__rich-text {
    line-height: 1.75;
    overflow-wrap: anywhere;

    :deep(p),
    :deep(ul),
    :deep(ol),
    :deep(pre) {
      margin: 0 0 10px;
    }

    :deep(p:last-child),
    :deep(ul:last-child),
    :deep(ol:last-child),
    :deep(pre:last-child) {
      margin-bottom: 0;
    }

    :deep(ul),
    :deep(ol) {
      padding-left: 20px;
    }

    :deep(code) {
      padding: 1px 5px;
      background: var(--app-bg-subtle);
      border-radius: 4px;
      font-family: ui-monospace, SFMono-Regular, Consolas, 'Liberation Mono', monospace;
      font-size: 0.92em;
    }

    :deep(pre) {
      max-width: 100%;
      padding: 10px 12px;
      overflow-x: auto;
      background: var(--app-bg-subtle);
      border: 1px solid var(--app-border-default);
      border-radius: 8px;
    }

    :deep(pre code) {
      padding: 0;
      background: transparent;
      border-radius: 0;
      white-space: pre;
    }

    :deep(a) {
      color: var(--app-action-primary);
      text-decoration: none;
      overflow-wrap: anywhere;
    }
  }
  &--streaming .message__bubble {
    display: grid;
    gap: 8px;
  }
  &--thinking .message__bubble {
    flex: 0 1 auto;
  }
  &__failure {
    display: grid;
    gap: 8px;
    width: min(100%, 760px);
    min-width: 0;
    padding: 14px 16px;
    color: var(--app-text-primary);
    background: color-mix(in srgb, var(--q-negative) 9%, var(--app-bg-surface));
    border: 1px solid color-mix(in srgb, var(--q-negative) 28%, var(--app-border-default));
    border-radius: 10px;
    overflow-wrap: anywhere;
  }
  &__failure strong {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
  }
  &__failure strong .q-icon {
    flex: 0 0 auto;
    color: var(--q-negative);
    font-size: 20px;
  }
  &__failure p {
    margin: 0;
    color: var(--app-text-secondary);
    line-height: 1.6;
    overflow-wrap: anywhere;
  }
  &__failure-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 14px;
    min-width: 0;
    color: var(--app-text-secondary);
    font-family: ui-monospace, SFMono-Regular, Consolas, 'Liberation Mono', monospace;
    font-size: 12px;
  }
  &__failure-meta span {
    min-width: 0;
    overflow-wrap: anywhere;
  }
  &__failure-actions {
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: 8px;
    min-width: 0;
    margin-top: 2px;
  }
  &__attachments {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    min-width: 0;
    margin-top: 10px;
  }
  &__attachment {
    display: flex;
    align-items: center;
    gap: 6px;
    max-width: min(420px, 64vw);
    min-width: 0;
    padding: 4px 10px;
    border: 1px solid currentcolor;
    border-radius: 999px;
  }
  &__attachment > .q-icon {
    flex: 0 0 auto;
  }
  &__attachment-content {
    display: grid;
    min-width: 0;
  }
  &__attachment-name {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  &__attachment-progress {
    color: var(--app-text-secondary);
    font-size: 11px;
    font-variant-numeric: tabular-nums;
    overflow-wrap: anywhere;
  }

  &__article-card {
    width: 100%;
    max-width: 760px;
    margin-top: 16px;
    color: var(--app-text-primary);
    background: var(--app-bg-surface);
    border: 1px solid var(--app-border-default);
    border-radius: 8px;
  }
  &__article-card .q-card__section {
    display: grid;
    gap: 12px;
    min-width: 0;
    padding: 18px;
  }
  &__article-card header {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr) auto;
    align-items: center;
    gap: 10px;
    min-width: 0;
  }
  &__article-card header .q-icon {
    font-size: 24px;
  }
  &__article-card strong {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  &__article-card p,
  &__article-card small {
    margin: 0;
    color: var(--app-text-secondary);
    line-height: 1.65;
    overflow-wrap: anywhere;
  }
  &__article-excerpt {
    display: -webkit-box;
    overflow: hidden;
    color: var(--app-text-primary);
    line-height: 1.8;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    -webkit-line-clamp: 5;
    -webkit-box-orient: vertical;
  }

  &__suggestions {
    display: grid;
    gap: 6px;
    width: 100%;
    max-width: 760px;
    margin-top: 14px;
  }
  &__suggestions button {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    min-width: 0;
    padding: 10px 12px;
    color: var(--app-text-primary);
    text-align: left;
    background: var(--app-bg-surface);
    border: 1px solid var(--app-border-default);
    border-radius: 8px;
    cursor: pointer;
    overflow-wrap: anywhere;
  }
}

.message__rich-text,
.blank-create__streaming {
  min-width: 0;
  max-width: 100%;

  :deep(h1),
  :deep(h2),
  :deep(h3),
  :deep(h4),
  :deep(h5),
  :deep(h6) {
    margin: 18px 0 8px;
    color: var(--app-text-primary);
    font-weight: 650;
    line-height: 1.4;
    overflow-wrap: anywhere;
  }

  :deep(h1:first-child),
  :deep(h2:first-child),
  :deep(h3:first-child),
  :deep(h4:first-child),
  :deep(h5:first-child),
  :deep(h6:first-child) {
    margin-top: 0;
  }

  :deep(h1) {
    font-size: 1.45rem;
  }
  :deep(h2) {
    font-size: 1.3rem;
  }
  :deep(h3) {
    font-size: 1.16rem;
  }
  :deep(h4),
  :deep(h5),
  :deep(h6) {
    font-size: 1rem;
  }

  :deep(blockquote) {
    margin: 12px 0;
    padding: 10px 14px;
    color: var(--app-text-secondary);
    background: var(--app-bg-subtle);
    border-left: 3px solid var(--app-action-primary);
    border-radius: 0 8px 8px 0;
    overflow-wrap: anywhere;
  }

  :deep(hr) {
    margin: 18px 0;
    border: 0;
    border-top: 1px solid var(--app-border-default);
  }

  :deep(.markdown-table-wrap) {
    width: 100%;
    max-width: 100%;
    margin: 12px 0;
    overflow-x: auto;
    border: 1px solid var(--app-border-default);
    border-radius: 8px;
    overscroll-behavior-inline: contain;
  }

  :deep(.markdown-table-wrap:focus-visible) {
    outline: 2px solid var(--app-action-primary);
    outline-offset: 2px;
  }

  :deep(table) {
    width: max-content;
    min-width: 100%;
    border-collapse: collapse;
    color: var(--app-text-primary);
    font-size: 14px;
    line-height: 1.6;
  }

  :deep(th),
  :deep(td) {
    min-width: 120px;
    max-width: 360px;
    padding: 10px 12px;
    text-align: left;
    vertical-align: top;
    border-right: 1px solid var(--app-border-default);
    border-bottom: 1px solid var(--app-border-default);
    overflow-wrap: anywhere;
  }

  :deep(th:last-child),
  :deep(td:last-child) {
    border-right: 0;
  }

  :deep(tbody tr:last-child td) {
    border-bottom: 0;
  }

  :deep(th) {
    font-weight: 650;
    background: var(--app-bg-subtle);
  }

  :deep(.markdown-table__cell--center) {
    text-align: center;
  }

  :deep(.markdown-table__cell--right) {
    text-align: right;
  }
}

.article-preview-dialog {
  :deep(.article-preview-dialog__button) {
    min-width: 128px;
    border-radius: 6px;
  }

  :deep(.article-preview-dialog__local) {
    color: var(--app-text-primary);

    .q-btn__content {
      color: inherit;
    }

    &::before {
      border-color: var(--app-border-strong);
    }
  }
}

.blank-create {
  display: grid;
  place-items: center;
  width: 100%;
  min-width: 0;
  min-height: 100%;
  padding: clamp(24px, 5vw, 68px);
  overflow-y: auto;

  &__content {
    width: min(100%, 900px);
    min-width: 0;
    text-align: center;
  }
  h1 {
    margin: 18px 0 8px;
    font-size: clamp(34px, 4vw, 48px);
    font-weight: 650;
    letter-spacing: -0.025em;
  }
  p {
    margin: 0 auto 32px;
    color: var(--app-text-secondary);
    font-size: 17px;
    overflow-wrap: anywhere;
  }
  .prompt-composer {
    text-align: left;
  }
  &__examples {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 12px;
    min-width: 0;
    margin-top: 28px;
    text-align: left;
  }
  &__examples > span {
    grid-column: 1 / -1;
    color: var(--app-text-secondary);
  }
  &__examples button {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr) auto;
    align-items: center;
    gap: 8px;
    min-width: 0;
    padding: 13px 14px;
    color: var(--app-text-primary);
    text-align: left;
    background: var(--app-bg-surface);
    border: 1px solid var(--app-border-default);
    border-radius: 10px;
    cursor: pointer;
    overflow-wrap: anywhere;
  }
  &__examples button:hover {
    border-color: var(--app-action-primary);
  }
  &__streaming {
    width: min(100%, 760px);
    margin-top: 18px !important;
    padding: 14px;
    text-align: left;
    background: var(--app-bg-subtle);
    border-radius: 10px;
    overflow-wrap: anywhere;

    :deep(p),
    :deep(ul),
    :deep(pre) {
      margin: 0 0 10px;
    }

    :deep(p:last-child),
    :deep(ul:last-child),
    :deep(pre:last-child) {
      margin-bottom: 0;
    }

    :deep(pre) {
      max-width: 100%;
      overflow-x: auto;
    }
  }
  .message--failure {
    width: min(100%, 760px);
    margin: 18px auto 0;
    text-align: left;
  }
}

@media (max-width: 1199px) {
  .blank-create__examples {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 1023px) {
  .create-page {
    height: calc(100dvh - 50px);
  }
  .workspace {
    padding: 0;
  }
  .workspace__chat {
    border: 0;
    border-radius: 0;
  }
  .task-header {
    padding-inline: 12px;
  }
}

@media (max-width: 599px) {
  .task-header {
    &__title {
      flex-basis: 100%;
    }
  }

  .conversation {
    padding: 16px 12px;
  }
  .message {
    gap: 8px;
  }
  .message > .q-avatar {
    width: 32px;
    height: 32px;
    font-size: 13px;
  }
  .message--user .message__bubble {
    max-width: 84%;
  }
  .message__article-card header {
    grid-template-columns: auto minmax(0, 1fr);
  }
  .message__article-card .app-button {
    grid-column: 1 / -1;
    width: 100%;
  }
  .article-preview-dialog__button {
    flex: 1 1 100%;
    min-width: 0;
  }
  .message__failure-actions,
  .message__failure-actions .app-button {
    width: 100%;
  }
  .blank-create {
    place-items: start center;
    padding: 32px 12px;
  }
  .blank-create__examples {
    grid-template-columns: 1fr;
  }
}
</style>

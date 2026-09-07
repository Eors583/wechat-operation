import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { remoteApi, visibleRunStage } from './client'

const timestamp = '2026-08-31T08:00:00.000Z'
const user = {
  id: 'user-1',
  name: '测试用户',
  role: '内容运营',
  phone: '13800000000',
  email: '',
  points: 100,
  themePreference: 'system' as const,
}

const jsonResponse = (payload: unknown, status = 200, headers?: HeadersInit) =>
  new Response(status === 204 ? null : JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json', ...Object.fromEntries(new Headers(headers)) },
  })

const apiErrorResponse = (status: number, code: string, retryable = false) =>
  jsonResponse(
    {
      code,
      message: code,
      details: {},
      retryable,
      request_id: `request-${code}`,
    },
    status,
  )

const observedRequest = async (input: RequestInfo | URL, init?: RequestInit) => {
  if (!(input instanceof Request)) return { url: String(input), init: init ?? {} }
  const body =
    input.method === 'GET' || input.method === 'HEAD' ? undefined : await input.clone().text()
  return {
    url: input.url,
    init: {
      method: input.method,
      headers: input.headers,
      body: body || undefined,
    } satisfies RequestInit,
  }
}
const requestHeaders = (init?: RequestInit) => new Headers(init?.headers)

const articleEnvelope = (status = 'local_draft') => ({
  article: {
    id: 'article-1',
    title: '文章',
    summary: '',
    source_task_id: 'task-1',
    project_id: null,
    status,
    current_version_no: 1,
    updated_at: timestamp,
  },
  version: {
    id: 'version-1',
    article_id: 'article-1',
    version_no: 1,
    created_at: timestamp,
    content_json: {
      type: 'doc',
      content: [{ type: 'paragraph', content: [{ type: 'text', text: '正文' }] }],
    },
  },
})

const taskResource = (messages: unknown[] = []) => ({
  id: 'task-1',
  title: '任务',
  project_id: null,
  current_article_id: null,
  current_skill_id: null,
  use_preferences: true,
  status: 'active',
  last_message_at: timestamp,
  updated_at: timestamp,
  created_at: timestamp,
  deleted_at: null,
  owner_id: user.id,
  owner_type: 'user',
  messages,
  messages_next_cursor: null,
  latest_ai_run: null,
})

describe('remote API transport invariants', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    sessionStorage.setItem(
      'wechat-ai-user-client-auth',
      JSON.stringify({ user, accessToken: 'access-old', refreshToken: 'refresh-old' }),
    )
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('recovers pending message content only for the current owner and conversation', () => {
    const command = {
      ownerId: user.id,
      path: '/tasks/task-1/messages',
      idempotencyKey: 'original',
      intentSignature: 'intent',
      createdAt: new Date().toISOString(),
      body: {
        text: '保留消息',
        clientMessageId: 'client-1',
        content: {
          attachments: [{ id: 'doc', documentId: 'doc', name: '参考.pdf', kind: 'file' }],
        },
      },
    }
    localStorage.setItem(
      'wechat-ai-pending-message',
      JSON.stringify({
        original: command,
        foreign: {
          ...command,
          ownerId: 'someone-else',
          idempotencyKey: 'foreign',
          path: '/tasks/other/messages',
        },
      }),
    )
    expect(remoteApi.getPendingMessage('task-1')).toMatchObject({
      key: 'original',
      message: {
        content: '保留消息',
        clientMessageId: 'client-1',
        attachments: [{ documentId: 'doc', name: '参考.pdf' }],
      },
    })
    expect(remoteApi.getPendingMessage('other')).toBeNull()
    expect(remoteApi.getPendingMessage('')).toBeNull()
  })

  it('keeps the latest failed AI run when loading a task', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse({
          ...taskResource(),
          latest_ai_run: {
            id: 'run-failed',
            status: 'failed',
            run_type: 'article_generation',
            error_code: 'ModelRouteExhausted',
            error_message: 'All frozen model-route deployments failed',
            created_at: timestamp,
            completed_at: timestamp,
          },
        }),
      ),
    )

    await expect(remoteApi.getTask('task-1')).resolves.toMatchObject({
      latestAiRun: {
        id: 'run-failed',
        status: 'failed',
        errorCode: 'ModelRouteExhausted',
      },
    })
  })

  it('keeps a failed run as a persistent assistant message with diagnostics', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(
          taskResource([
            {
              id: 'message-failed',
              task_id: 'task-1',
              role: 'assistant',
              plain_text: '所选模型本次未能完成生成，请重试。',
              content_json: {
                response_kind: 'ai_error',
                ai_run_id: 'run-failed',
                error_code: 'ModelRouteExhausted',
                retryable: true,
                source_message_id: 'message-user',
              },
              created_at: timestamp,
            },
          ]),
        ),
      ),
    )

    await expect(remoteApi.getTask('task-1')).resolves.toMatchObject({
      messages: [
        {
          id: 'message-failed',
          role: 'assistant',
          responseKind: 'ai_error',
          aiRunId: 'run-failed',
          errorCode: 'ModelRouteExhausted',
          retryable: true,
          sourceMessageId: 'message-user',
        },
      ],
    })
  })

  it('maps the camelized heading marker token into the frontend layout module', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse({
          items: [
            {
              id: 'template-1',
              name: '序号标题模板',
              enabled: false,
              official_account_id: null,
              source_url: 'https://mp.weixin.qq.com/s/example',
              extraction_status: 'completed',
              updated_at: timestamp,
              version: {
                created_at: timestamp,
                style_tokens: {
                  heading_marker: {
                    enabled: true,
                    font_size: 24,
                    font_weight: 700,
                    color: '#ff4c00',
                    align: 'center',
                  },
                },
                source_snapshot: {},
              },
            },
          ],
          next_cursor: null,
        }),
      ),
    )

    const page = await remoteApi.listTemplatesPage(null)

    expect(page.items[0]?.styles.heading_marker).toMatchObject({
      enabled: true,
      fontSize: 24,
      fontWeight: '700',
      color: '#ff4c00',
      align: 'center',
    })
  })

  it('refreshes a definite 401 without automatically replaying a high-risk write', async () => {
    const saveRequests: RequestInit[] = []
    let saveAttempts = 0
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const observed = await observedRequest(input, init)
        const { url } = observed
        if (url.endsWith('/articles/article-1/save-local')) {
          saveAttempts += 1
          saveRequests.push(observed.init)
          return saveAttempts === 1
            ? apiErrorResponse(401, 'ACCESS_TOKEN_EXPIRED')
            : jsonResponse(null, 204)
        }
        if (url.endsWith('/auth/refresh')) {
          return jsonResponse({
            access_token: 'access-fresh',
            refresh_token: 'refresh-rotated',
            user: {
              id: user.id,
              display_name: user.name,
              phone: user.phone,
              email: '',
              quota_balance: 100,
              theme_preference: 'system',
            },
          })
        }
        if (url.endsWith('/articles/article-1')) return jsonResponse(articleEnvelope())
        throw new Error(`Unexpected request: ${observed.init.method ?? 'GET'} ${url}`)
      }),
    )

    await expect(
      remoteApi.setArticleOutcome({
        id: 'article-1',
        outcome: 'local_draft',
        idempotencyKey: 'save-key-original',
      }),
    ).rejects.toMatchObject({ code: 'AUTH_REFRESHED_RETRY_REQUIRED', retryable: true })

    expect(saveRequests).toHaveLength(1)
    expect(JSON.parse(localStorage.getItem('wechat-ai-user-client-auth') ?? '{}').accessToken).toBe(
      'access-fresh',
    )

    await expect(
      remoteApi.setArticleOutcome({
        id: 'article-1',
        outcome: 'local_draft',
        idempotencyKey: 'save-key-new-click',
      }),
    ).resolves.toMatchObject({ id: 'article-1', status: 'local_draft' })

    expect(saveRequests).toHaveLength(2)
    expect(saveRequests.map((init) => requestHeaders(init).get('Idempotency-Key'))).toEqual([
      'save-key-original',
      'save-key-original',
    ])
    expect(requestHeaders(saveRequests[1]).get('Authorization')).toBe('Bearer access-fresh')
  })

  it('resumes multipart finalization with the server part size, exact ETags and fixed keys', async () => {
    const file = new File([new Uint8Array([1, 2, 3, 4, 5])], 'data.csv', {
      type: 'application/vnd.ms-excel',
    })
    if (!file.arrayBuffer)
      Object.defineProperty(file, 'arrayBuffer', {
        value: async () => new Uint8Array([1, 2, 3, 4, 5]).buffer,
      })
    const creates: RequestInit[] = []
    const completes: RequestInit[] = []
    const uploadedPartSizes: number[] = []
    let completeAttempts = 0

    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const observed = await observedRequest(input, init)
        const { url } = observed
        if (url.endsWith('/uploads') && observed.init.method === 'POST') {
          creates.push(observed.init)
          return jsonResponse(
            {
              asset: { id: 'asset-1' },
              upload: { id: 'upload-1' },
              part_urls: ['https://upload.example/part-1', 'https://upload.example/part-2'],
              part_size_bytes: 3,
              provider_mode: 'mock',
            },
            201,
          )
        }
        if (url.startsWith('https://upload.example/part-')) {
          const partNumber = Number(url.at(-1))
          uploadedPartSizes.push((init?.body as Blob).size)
          return new Response(null, { status: 200, headers: { ETag: `"etag-${partNumber}"` } })
        }
        if (url.endsWith('/uploads/upload-1/complete')) {
          completes.push(observed.init)
          completeAttempts += 1
          if (completeAttempts === 1) return apiErrorResponse(503, 'STORAGE_TEMPORARY', true)
          return jsonResponse({
            asset: { id: 'asset-1' },
            document: { id: 'document-1' },
            library_item: null,
          })
        }
        if (url.endsWith('/documents/document-1'))
          return jsonResponse({ id: 'document-1', status: 'completed' })
        throw new Error(`Unexpected request: ${observed.init.method ?? 'GET'} ${url}`)
      }),
    )

    await expect(remoteApi.uploadFile(file)).rejects.toMatchObject({ code: 'STORAGE_TEMPORARY' })
    await expect(remoteApi.uploadFile(file)).resolves.toMatchObject({
      id: 'document-1',
      assetId: 'asset-1',
      mimeType: 'text/csv',
      status: 'reading',
    })

    expect(uploadedPartSizes).toEqual([3, 2])
    expect(creates).toHaveLength(2)
    expect(completes).toHaveLength(2)
    expect(requestHeaders(creates[0]).get('Idempotency-Key')).toBe(
      requestHeaders(creates[1]).get('Idempotency-Key'),
    )
    expect(requestHeaders(completes[0]).get('Idempotency-Key')).toBe(
      requestHeaders(completes[1]).get('Idempotency-Key'),
    )
    expect(completes[0]?.body).toBe(completes[1]?.body)
    expect(JSON.parse(String(completes[0]?.body))).toMatchObject({
      size_bytes: 5,
      completed_parts: [
        { part_number: 1, etag: '"etag-1"' },
        { part_number: 2, etag: '"etag-2"' },
      ],
    })
  })

  it('reuses a message key after retryable 409 and reconnects SSE with Last-Event-ID', async () => {
    const messageRequests: RequestInit[] = []
    const streamHeaders: Headers[] = []
    const deltas: string[] = []
    const stages: string[] = []
    const readyArticles: string[] = []
    const warnings: string[] = []
    const acceptedRuns: Array<[string, string]> = []
    let messageAttempts = 0
    let streamAttempts = 0

    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const observed = await observedRequest(input, init)
        const { url } = observed
        if (url.endsWith('/tasks/task-1') && observed.init.method === 'PATCH')
          return jsonResponse(taskResource())
        if (url.endsWith('/tasks/task-1/messages') && observed.init.method === 'POST') {
          messageRequests.push(observed.init)
          messageAttempts += 1
          if (messageAttempts === 1) return apiErrorResponse(409, 'IDEMPOTENCY_IN_PROGRESS', true)
          return jsonResponse(
            { task: taskResource(), message: { id: 'message-1' }, ai_run: { id: 'run-1' } },
            202,
          )
        }
        if (url.endsWith('/ai-runs/run-1/events')) {
          expect(acceptedRuns).toEqual([['run-1', 'task-1']])
          streamHeaders.push(requestHeaders(init))
          streamAttempts += 1
          const body =
            streamAttempts === 1
              ? 'id: event-1\nevent: stage.changed\ndata: {"stage":"retrieving"}\n\n'
              : 'id: event-2\nevent: stage.changed\ndata: {"stage":"planning"}\n\nid: event-3\nevent: text.delta\ndata: {"text":"第一段"}\n\nid: event-4\nevent: text.delta\ndata: {"text":"{\\"type\\":\\"doc\\",\\"content\\":[]}"}\n\nid: event-5\nevent: article.ready\ndata: {"article_id":"article-1"}\n\nid: event-6\nevent: run.completed\ndata: {}\n\n'
          const warningEvents =
            streamAttempts === 2
              ? 'event: warning\ndata: {"code":"AI_CONTENT_CHECK_WARNING","message":"文章已生成，但自动校验发现可能不准确的表述"}\n\nevent: warning\ndata: {"code":"MODEL_FALLBACK_USED","message":"主模型不可用，已切换备用模型"}\n\n'
              : ''
          return new Response(warningEvents + body, {
            status: 200,
            headers: { 'Content-Type': 'text/event-stream' },
          })
        }
        if (url.endsWith('/ai-runs/run-1')) return jsonResponse({ id: 'run-1', status: 'accepted' })
        if (url.endsWith('/tasks/task-1') && (observed.init.method ?? 'GET') === 'GET')
          return jsonResponse(taskResource())
        throw new Error(`Unexpected request: ${observed.init.method ?? 'GET'} ${url}`)
      }),
    )

    const result = await remoteApi.sendMessage({
      clientMessageId: 'message-from-ui',
      taskId: 'task-1',
      projectId: null,
      text: '继续写作',
      skillId: null,
      usePreferences: true,
      attachments: [],
      onRunAccepted: (runId, taskId, clientMessageId) => {
        expect(clientMessageId).toBe('message-from-ui')
        acceptedRuns.push([runId, taskId])
      },
      onTextDelta: (text) => deltas.push(text),
      onArticleReady: (articleId) => readyArticles.push(articleId),
      onRunStage: (stage) => stages.push(stage),
      onWarning: (message) => warnings.push(message),
    })

    expect(result.runId).toBe('run-1')
    expect(acceptedRuns).toEqual([['run-1', 'task-1']])
    expect(messageRequests).toHaveLength(2)
    expect(requestHeaders(messageRequests[0]).get('Idempotency-Key')).toBe(
      requestHeaders(messageRequests[1]).get('Idempotency-Key'),
    )
    expect(streamHeaders).toHaveLength(2)
    expect(streamHeaders[0]?.get('Last-Event-ID')).toBeNull()
    expect(streamHeaders[1]?.get('Last-Event-ID')).toBe('event-1')
    expect(deltas).toEqual(['第一段'])
    expect(readyArticles).toEqual(['article-1'])
    expect(warnings).toEqual(['主模型不可用，已切换备用模型'])
    expect([...new Set(stages.filter((stage) => stage !== 'reconnecting'))]).toEqual([
      'reading',
      'planning',
      'ready',
      'completed',
    ])
    expect(remoteApi.hasPendingMessage()).toBe(false)
  })

  it.each([
    ['accepted', 'queued'],
    ['validating', 'validating'],
    ['retrieving', 'reading'],
    ['planning', 'planning'],
    ['generating', 'generating'],
    ['validating_output', 'checking'],
    ['saving_version', 'saving'],
    ['ready_for_formatting', 'ready'],
    ['unrecognized', null],
  ])('preserves the real progress stage %s', (backend, visible) => {
    expect(visibleRunStage(backend as string)).toBe(visible)
  })

  it('preserves retryability metadata from the unified error response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => apiErrorResponse(503, 'UPSTREAM_BUSY', true)),
    )
    await expect(remoteApi.getMe()).rejects.toEqual(
      expect.objectContaining({
        code: 'UPSTREAM_BUSY',
        retryable: true,
        requestId: 'request-UPSTREAM_BUSY',
      }),
    )
  })

  it('removes pending commands and owner article drafts even when logout revocation fails', async () => {
    localStorage.setItem(
      'wechat-ai-pending-message',
      JSON.stringify({
        mine: { ownerId: user.id, secret: 'prompt' },
        theirs: { ownerId: 'user-2', secret: 'other prompt' },
      }),
    )
    localStorage.setItem(
      'wechat-ai-pending-uploads',
      JSON.stringify({ mine: { ownerId: user.id, secret: 'file' } }),
    )
    localStorage.setItem(
      'wechat-ai-pending-article-save',
      JSON.stringify({ mine: { ownerId: user.id, secret: 'article' } }),
    )
    sessionStorage.setItem(`wechat-ai-article-draft:${user.id}:article-1`, '{"secret":"draft"}')
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => apiErrorResponse(503, 'LOGOUT_UNAVAILABLE', true)),
    )

    await expect(remoteApi.logout()).rejects.toMatchObject({ code: 'LOGOUT_UNAVAILABLE' })

    expect(JSON.parse(localStorage.getItem('wechat-ai-pending-message') ?? '{}')).toEqual({
      theirs: { ownerId: 'user-2', secret: 'other prompt' },
    })
    expect(localStorage.getItem('wechat-ai-pending-uploads')).toBeNull()
    expect(localStorage.getItem('wechat-ai-pending-article-save')).toBeNull()
    expect(sessionStorage.getItem(`wechat-ai-article-draft:${user.id}:article-1`)).toBeNull()
    expect(localStorage.getItem('wechat-ai-user-client-auth')).toBeNull()
    expect(sessionStorage.getItem('wechat-ai-user-client-auth')).toBeNull()
  })
})

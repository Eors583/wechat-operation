import { Capacitor } from '@capacitor/core'
import createClient from 'openapi-fetch'
import { uploadPart } from './uploadPart'
import { createDefaultStyles } from './styleDefaults'
import type {
  Camelized,
  ArticleContentUpdateDto,
  ArticleRestoreDto,
  ArticleRestoreResultDto,
  ArticleRevisionCreateDto,
  ArticleRevisionResourceDto,
  ArticleUpdateResultDto,
  CurrentWechatOperationDto,
  LayoutTemplateCreateDto,
  LayoutTemplatePatchDto,
  MePatchDto,
  MeResponseDto,
  TaskCreateDto,
  TaskDetailDto,
  UploadCreateResponseDto,
  UploadCreateDto,
  UploadCompleteDto,
  UploadCompleteResponseDto,
} from './contract'
import type { components, paths } from './generated/schema'
import { platform } from '@/platform'
import { safeHttpUrl } from '@/utils/safeUrl'
import type {
  AccountStatus,
  AccountDeletionReceipt,
  Article,
  ArticleOutcomeInput,
  ArticleRevisionInput,
  ArticleSaveInput,
  ArticleStatus,
  ArticleVersion,
  Attachment,
  FileReadStatus,
  LayoutTemplate,
  LibraryFilters,
  LibraryItem,
  LibraryPage,
  ModelOption,
  ModuleKey,
  ModuleStyle,
  OfficialAccount,
  OfficialAccountAuthorization,
  PendingArticleRevision,
  PendingArticleOutcome,
  Preference,
  Project,
  PublicSettings,
  RunStage,
  SendMessageInput,
  SendMessageResult,
  Session,
  Skill,
  SkillInput,
  Task,
  TaskAIRunSummary,
  TaskPage,
  ThemePreference,
  User,
  UserApi,
  VerificationChallenge,
} from './types'
import { createDefaultPublicSettings } from './types'

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code = 'REQUEST_FAILED',
    readonly details?: unknown,
    readonly retryable = false,
    readonly requestId?: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

type JsonRecord = Record<string, unknown>
type AuthPlatform = 'web' | 'windows' | 'ios' | 'android'
type MessageCreateDto = Camelized<components['schemas']['MessageCreate']>
interface PendingMessageCommand {
  ownerId: string
  path: '/tasks' | `/tasks/${string}/messages`
  body: TaskCreateDto | MessageCreateDto
  intentSignature: string
  idempotencyKey: string
  createdAt: string
  taskId?: string
  runId?: string
  cancelRequested?: boolean
}
interface PendingArticleSaveCommand {
  ownerId: string
  articleId: string
  idempotencyKey: string
  body: ArticleContentUpdateDto
  createdAt: string
}
interface PendingArticleRestoreCommand {
  ownerId: string
  articleId: string
  versionId: string
  idempotencyKey: string
  body: ArticleRestoreDto
  createdAt: string
}
interface PendingArticleLocalSaveCommand {
  ownerId: string
  articleId: string
  idempotencyKey: string
  createdAt: string
}
interface PendingUploadCommand {
  ownerId: string
  fingerprint: string
  createIdempotencyKey: string
  completeIdempotencyKey: string
  createBody: UploadCreateDto
  completedParts: Array<{ partNumber: number; etag: string }>
  assetId?: string
  documentId?: string
  createdAt: string
}

const runtimeApiUrl = window.desktopBridge
  ? import.meta.env.VITE_API_BASE_URL_ELECTRON || import.meta.env.VITE_API_BASE_URL
  : Capacitor.isNativePlatform()
    ? import.meta.env.VITE_API_BASE_URL_NATIVE || import.meta.env.VITE_API_BASE_URL
    : import.meta.env.VITE_API_BASE_URL
const baseUrl = (runtimeApiUrl || '/api/v1').replace(/\/$/, '')
const openApiBaseUrl = baseUrl.endsWith('/api/v1') ? baseUrl.slice(0, -'/api/v1'.length) : baseUrl
if (platform.native && !/^https:\/\//.test(baseUrl) && import.meta.env.PROD) {
  throw new Error('原生生产包必须配置 HTTPS 绝对 API 地址。')
}
const sessionCacheKey = 'wechat-ai-user-client-auth'
const sessionCacheTtlMs = 7 * 24 * 60 * 60 * 1000
type CachedSession = Session & { expiresAt?: number }
const pendingMessageKey = 'wechat-ai-pending-message'
const pendingArticleSaveKey = 'wechat-ai-pending-article-save'
const pendingArticleRestoreKey = 'wechat-ai-pending-article-restore'
const pendingArticleLocalSaveKey = 'wechat-ai-pending-article-local-save'
const pendingArticleRevisionKey = 'wechat-ai-pending-article-revision'
const pendingUploadsKey = 'wechat-ai-pending-uploads'
const pendingArticleOutcomesKey = 'wechat-ai-pending-article-outcomes'
const ownerBusinessStorageKeys = [
  pendingMessageKey,
  pendingArticleSaveKey,
  pendingArticleRestoreKey,
  pendingArticleLocalSaveKey,
  pendingArticleRevisionKey,
  pendingUploadsKey,
  pendingArticleOutcomesKey,
]
const moduleKeys: ModuleKey[] = [
  'table_header',
  'table_cell',
  'title',
  'lead',
  'heading_marker',
  'heading1',
  'heading2',
  'body',
  'highlight',
  'quote',
  'list',
  'caption',
  'divider',
]
const backendModule: Record<ModuleKey, string> = {
  table_header: 'table_header',
  table_cell: 'table_cell',
  title: 'title',
  lead: 'lead',
  heading_marker: 'heading_marker',
  heading1: 'heading1',
  heading2: 'heading2',
  body: 'body',
  highlight: 'highlight',
  quote: 'quote',
  list: 'list',
  caption: 'caption',
  divider: 'divider',
}
const frontendModule = Object.fromEntries(
  Object.entries(backendModule).map(([frontend, backend]) => [backend, frontend]),
) as Record<string, ModuleKey>
frontendModule.headingMarker = 'heading_marker'
frontendModule.tableHeader = 'table_header'
frontendModule.tableCell = 'table_cell'

let refreshRequest: Promise<Session> | null = null

export const clearUserClientData = (ownerId?: string) => {
  if (!ownerId) return
  ownerBusinessStorageKeys.forEach((key) => {
    try {
      const entries = record(JSON.parse(localStorage.getItem(key) ?? '{}'))
      const retained = Object.fromEntries(
        Object.entries(entries).filter(([, value]) => record(value).ownerId !== ownerId),
      )
      if (Object.keys(retained).length) localStorage.setItem(key, JSON.stringify(retained))
      else localStorage.removeItem(key)
    } catch {
      // Malformed owner-bound state cannot be replayed safely.
      localStorage.removeItem(key)
    }
  })
  const draftPrefix = `wechat-ai-article-draft:${ownerId}:`
  for (let index = sessionStorage.length - 1; index >= 0; index -= 1) {
    const key = sessionStorage.key(index)
    if (key?.startsWith(draftPrefix)) sessionStorage.removeItem(key)
  }
}

const isRecord = (value: unknown): value is JsonRecord =>
  typeof value === 'object' && value !== null && !Array.isArray(value)
const record = (value: unknown): JsonRecord => (isRecord(value) ? value : {})
const textValue = (value: unknown, fallback = '') => (typeof value === 'string' ? value : fallback)
const optionalText = (value: unknown) => (typeof value === 'string' && value ? value : undefined)
const numberValue = (value: unknown, fallback = 0) =>
  typeof value === 'number' && Number.isFinite(value) ? value : fallback
const booleanValue = (value: unknown, fallback = false) =>
  typeof value === 'boolean' ? value : fallback
const stringList = (value: unknown) =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
const itemList = (value: unknown) =>
  Array.isArray(record(value).items) ? (record(value).items as unknown[]) : []
const nextPageCursor = (value: unknown, current?: string) => {
  const next = optionalText(record(value).nextCursor)
  if (next && next === current)
    throw new ApiError('列表游标没有前进，请刷新后重试。', 502, 'CURSOR_STALLED')
  return next
}
const now = () => new Date().toISOString()
const sleep = (milliseconds: number) => new Promise((resolve) => setTimeout(resolve, milliseconds))
const requestId = (prefix: string) =>
  `${prefix}_${globalThis.crypto?.randomUUID?.() ?? Math.random().toString(36).slice(2)}`
const resolveApiResourceUrl = (url: string) =>
  new URL(url, new URL(`${baseUrl}/`, window.location.origin)).toString()

const readPendingArticleOutcomes = (): Record<string, PendingArticleOutcome> => {
  try {
    const value = JSON.parse(localStorage.getItem(pendingArticleOutcomesKey) ?? '{}') as unknown
    if (!isRecord(value)) return {}
    return Object.fromEntries(Object.entries(value).filter(([, item]) => isRecord(item))) as Record<
      string,
      PendingArticleOutcome
    >
  } catch {
    return {}
  }
}

const readPendingArticleOutcome = (articleId: string): PendingArticleOutcome | null => {
  const pending = readPendingArticleOutcomes()[articleId]
  return pending?.ownerId === readCachedSession()?.user.id ? (pending ?? null) : null
}

const writePendingArticleOutcome = (
  pending: PendingArticleOutcome | null,
  articleId = pending?.articleId,
) => {
  if (!articleId) return
  const outcomes = readPendingArticleOutcomes()
  if (pending) outcomes[articleId] = pending
  else delete outcomes[articleId]
  try {
    if (Object.keys(outcomes).length)
      localStorage.setItem(pendingArticleOutcomesKey, JSON.stringify(outcomes))
    else localStorage.removeItem(pendingArticleOutcomesKey)
  } catch {
    // Browsers may deny persistent storage; server-side idempotency remains the safety net.
  }
}

const readPersistentCommand = <
  Command extends { ownerId: string; articleId: string; createdAt: string },
>(
  key: string,
  articleId: string,
): Command | null => {
  try {
    const commands = record(JSON.parse(localStorage.getItem(key) ?? '{}'))
    const value = commands[articleId] as Command | undefined
    if (!value || value.articleId !== articleId || value.ownerId !== readCachedSession()?.user.id)
      return null
    if (Date.now() - new Date(value.createdAt).getTime() > 24 * 60 * 60 * 1000) {
      delete commands[articleId]
      if (Object.keys(commands).length) localStorage.setItem(key, JSON.stringify(commands))
      else localStorage.removeItem(key)
      return null
    }
    return value
  } catch {
    return null
  }
}

const writePersistentCommand = (key: string, articleId: string, command: unknown | null) => {
  try {
    const commands = record(JSON.parse(localStorage.getItem(key) ?? '{}'))
    if (command) commands[articleId] = command
    else delete commands[articleId]
    if (Object.keys(commands).length) localStorage.setItem(key, JSON.stringify(commands))
    else localStorage.removeItem(key)
  } catch {
    // Server-side idempotency still protects the active request when storage is denied.
  }
}

const readPendingArticleSave = (articleId: string) =>
  readPersistentCommand<PendingArticleSaveCommand>(pendingArticleSaveKey, articleId)
const writePendingArticleSave = (
  command: PendingArticleSaveCommand | null,
  articleId = command?.articleId ?? '',
) => {
  if (articleId) writePersistentCommand(pendingArticleSaveKey, articleId, command)
}
const readPendingArticleRestore = (articleId: string) =>
  readPersistentCommand<PendingArticleRestoreCommand>(pendingArticleRestoreKey, articleId)
const writePendingArticleRestore = (
  command: PendingArticleRestoreCommand | null,
  articleId = command?.articleId ?? '',
) => {
  if (articleId) writePersistentCommand(pendingArticleRestoreKey, articleId, command)
}
const readPendingArticleLocalSave = (articleId: string) =>
  readPersistentCommand<PendingArticleLocalSaveCommand>(pendingArticleLocalSaveKey, articleId)
const writePendingArticleLocalSave = (
  command: PendingArticleLocalSaveCommand | null,
  articleId = command?.articleId ?? '',
) => {
  if (articleId) writePersistentCommand(pendingArticleLocalSaveKey, articleId, command)
}
const readPendingArticleRevision = (articleId: string) =>
  readPersistentCommand<PendingArticleRevision>(pendingArticleRevisionKey, articleId)
const writePendingArticleRevision = (
  command: PendingArticleRevision | null,
  articleId = command?.articleId ?? '',
) => {
  if (articleId) writePersistentCommand(pendingArticleRevisionKey, articleId, command)
}

const readPendingUpload = (fingerprint: string): PendingUploadCommand | null => {
  try {
    const command = record(JSON.parse(localStorage.getItem(pendingUploadsKey) ?? '{}'))[
      fingerprint
    ] as PendingUploadCommand | undefined
    if (
      !command ||
      command.fingerprint !== fingerprint ||
      command.ownerId !== readCachedSession()?.user.id
    )
      return null
    if (Date.now() - new Date(command.createdAt).getTime() <= 24 * 60 * 60 * 1000) return command
    writePendingUpload(null, fingerprint)
    return null
  } catch {
    return null
  }
}

const writePendingUpload = (
  command: PendingUploadCommand | null,
  fingerprint = command?.fingerprint ?? '',
) => {
  if (!fingerprint) return
  try {
    const commands = record(JSON.parse(localStorage.getItem(pendingUploadsKey) ?? '{}'))
    if (command) commands[fingerprint] = command
    else delete commands[fingerprint]
    if (Object.keys(commands).length)
      localStorage.setItem(pendingUploadsKey, JSON.stringify(commands))
    else localStorage.removeItem(pendingUploadsKey)
  } catch {
    // The fixed server idempotency keys still protect the current invocation.
  }
}

const withCommandLock = <Value>(name: string, operation: () => Value | Promise<Value>) =>
  navigator.locks
    ? navigator.locks.request(`wechat-ai:${name}`, operation)
    : Promise.resolve(operation())

const camelKey = (key: string) =>
  key.replace(/_([a-z])/g, (_, letter: string) => letter.toUpperCase())
const snakeKey = (key: string) => key.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`)
const convertKeys = (value: unknown, keyConverter: (key: string) => string): unknown => {
  if (Array.isArray(value)) return value.map((item) => convertKeys(item, keyConverter))
  if (!isRecord(value)) return value
  return Object.fromEntries(
    Object.entries(value).map(([key, item]) => [
      keyConverter(key),
      convertKeys(item, keyConverter),
    ]),
  )
}
const camelize = (value: unknown) => convertKeys(value, camelKey)
const snakeize = (value: unknown) => convertKeys(value, snakeKey)

const authPlatform = (): AuthPlatform => {
  if (window.desktopBridge) return 'windows'
  if (Capacitor.isNativePlatform()) return Capacitor.getPlatform() === 'ios' ? 'ios' : 'android'
  return 'web'
}

const readCachedSession = (): Session | null => {
  try {
    const raw = localStorage.getItem(sessionCacheKey) ?? sessionStorage.getItem(sessionCacheKey)
    if (!raw) return null
    const session = JSON.parse(raw) as CachedSession
    if (session.expiresAt && session.expiresAt <= Date.now()) {
      writeCachedSession(null)
      return null
    }
    if (platform.native && session.refreshToken) {
      delete session.refreshToken
      writeCachedSession(session)
    }
    return {
      user: session.user,
      accessToken: session.accessToken,
      refreshToken: session.refreshToken,
    }
  } catch {
    return null
  }
}

const writeCachedSession = (session: Session | null) => {
  if (session) {
    const cached: CachedSession = {
      ...(platform.native ? { ...session, refreshToken: undefined } : session),
      expiresAt: Date.now() + sessionCacheTtlMs,
    }
    localStorage.setItem(sessionCacheKey, JSON.stringify(cached))
    sessionStorage.removeItem(sessionCacheKey)
  } else {
    localStorage.removeItem(sessionCacheKey)
    sessionStorage.removeItem(sessionCacheKey)
  }
}

const csrfToken = () =>
  document.cookie
    .split('; ')
    .find((entry) => entry.startsWith('ua_csrf='))
    ?.slice('ua_csrf='.length)

const responseError = async (response: Response) => {
  const payload = (await response.json().catch(() => ({}))) as JsonRecord
  const requestId = textValue(payload.request_id, response.headers.get('X-Request-ID') ?? '')
  const message = textValue(payload.message, '请求没有完成，请稍后重试。')
  return new ApiError(
    requestId ? `${message}\n请求编号：${requestId}` : message,
    response.status,
    textValue(payload.code, 'REQUEST_FAILED'),
    camelize(payload.details),
    booleanValue(payload.retryable),
    requestId || undefined,
  )
}

const nativeAuthPayload = (response: { status: number; payload: Record<string, unknown> }) => {
  const payload = record(camelize(response.payload))
  if (response.status >= 200 && response.status < 300) return payload
  const requestId = textValue(payload.requestId)
  const message = textValue(payload.message, '请求没有完成，请稍后重试。')
  throw new ApiError(
    requestId ? `${message}\n请求编号：${requestId}` : message,
    response.status,
    textValue(payload.code, 'REQUEST_FAILED'),
    payload.details,
    booleanValue(payload.retryable),
    requestId || undefined,
  )
}

const refreshAccessToken = async () => {
  const cached = readCachedSession()
  const native = authPlatform() !== 'web'
  let payload: JsonRecord
  try {
    if (native) {
      payload = nativeAuthPayload(await platform.refreshSession())
    } else {
      const headers = new Headers({
        Accept: 'application/json',
        'Content-Type': 'application/json',
      })
      const csrf = csrfToken()
      if (csrf) headers.set('X-CSRF-Token', decodeURIComponent(csrf))
      const response = await fetch(`${baseUrl}/auth/refresh`, {
        method: 'POST',
        credentials: 'include',
        headers,
        body: JSON.stringify({}),
      })
      if (!response.ok) throw await responseError(response)
      payload = record(camelize(await response.json()))
    }
  } catch (error) {
    writeCachedSession(null)
    throw error
  }
  const nextRefreshToken = optionalText(payload.refreshToken)
  const refreshed: Session = {
    ...(cached ?? { user: mapUser(payload.user), accessToken: '' }),
    user: isRecord(payload.user) ? mapUser(payload.user) : (cached?.user ?? mapUser({})),
    accessToken: textValue(payload.accessToken),
    refreshToken: native ? undefined : (nextRefreshToken ?? cached?.refreshToken),
  }
  writeCachedSession(refreshed)
  return refreshed
}

const isManualReplayOperation = (request: Request) => {
  if (request.method === 'GET' || request.method === 'HEAD') return false
  const pathname = new URL(request.url, location.origin).pathname
  return (
    request.headers.has('Idempotency-Key') ||
    /\/api\/v1\/article-renders\/[^/]+\/confirm$/.test(pathname)
  )
}

const authenticatedFetch = async (input: Request): Promise<Response> => {
  const headers = new Headers(input.headers)
  const cached = readCachedSession()
  if (cached?.accessToken) headers.set('Authorization', `Bearer ${cached.accessToken}`)
  const pathname = new URL(input.url, location.origin).pathname
  if (pathname.endsWith('/api/v1/auth/logout') && authPlatform() === 'web') {
    const csrf = csrfToken()
    if (csrf) headers.set('X-CSRF-Token', decodeURIComponent(csrf))
  }
  const request = new Request(input, { headers, credentials: 'include' })
  const response = await fetch(request)
  const isRefreshable =
    !pathname.includes('/api/v1/auth/') || pathname.endsWith('/api/v1/auth/logout')
  if (response.status !== 401 || !isRefreshable) return response

  const originalError = await responseError(response.clone())
  refreshRequest ??= refreshAccessToken().finally(() => {
    refreshRequest = null
  })
  await refreshRequest
  if (isManualReplayOperation(request)) {
    throw new ApiError(
      '登录凭据已刷新。为避免重复执行高风险写操作，请继续原任务或手动重试。',
      401,
      'AUTH_REFRESHED_RETRY_REQUIRED',
      originalError.details,
      true,
      originalError.requestId,
    )
  }
  const refreshed = readCachedSession()
  if (refreshed?.accessToken) headers.set('Authorization', `Bearer ${refreshed.accessToken}`)
  return fetch(new Request(input, { headers, credentials: 'include' }))
}

const openApi = createClient<paths, 'application/json'>({
  baseUrl: openApiBaseUrl || globalThis.location?.origin || 'http://localhost',
  credentials: 'include',
  fetch: authenticatedFetch,
})

type OpenApiResult<T> = {
  data?: T
  error?: unknown
  response: Response
}

const openApiData = async <T>(operation: Promise<OpenApiResult<T>>): Promise<Camelized<T>> => {
  const { data, error, response } = await operation
  if (error !== undefined) {
    const payload = record(error)
    const requestId = textValue(payload.request_id, response.headers.get('X-Request-ID') ?? '')
    const message = textValue(payload.message, '请求没有完成，请稍后重试。')
    throw new ApiError(
      requestId ? `${message}\n请求编号：${requestId}` : message,
      response.status,
      textValue(payload.code, 'REQUEST_FAILED'),
      camelize(payload.details),
      booleanValue(payload.retryable),
      requestId || undefined,
    )
  }
  return camelize(data) as Camelized<T>
}

type ApiSchemas = components['schemas']
const apiBody = <Name extends keyof ApiSchemas>(
  value: Camelized<ApiSchemas[Name]>,
): ApiSchemas[Name] => snakeize(value) as ApiSchemas[Name]

const streamRunEvents = async (
  runId: string,
  lastEventId?: string,
  signal?: AbortSignal,
  retryAuth = true,
): Promise<Response> => {
  const headers = new Headers({ Accept: 'text/event-stream' })
  const cached = readCachedSession()
  if (cached?.accessToken) headers.set('Authorization', `Bearer ${cached.accessToken}`)
  if (lastEventId) headers.set('Last-Event-ID', lastEventId)
  const response = await fetch(`${baseUrl}/ai-runs/${encodeURIComponent(runId)}/events`, {
    credentials: 'include',
    headers,
    signal,
  })
  if (response.status === 401 && retryAuth && cached) {
    refreshRequest ??= refreshAccessToken().finally(() => {
      refreshRequest = null
    })
    await refreshRequest
    return streamRunEvents(runId, lastEventId, signal, false)
  }
  if (!response.ok) throw await responseError(response)
  return response
}

const mimeByExtension: Record<string, string> = {
  pdf: 'application/pdf',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  pptx: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  txt: 'text/plain',
  md: 'text/markdown',
  csv: 'text/csv',
  html: 'text/html',
  htm: 'text/html',
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  png: 'image/png',
  mp3: 'audio/mpeg',
  m4a: 'audio/mp4',
  mp4: 'video/mp4',
}

const allowedUploadMimeTypes = new Set(Object.values(mimeByExtension))

export const normalizedFileMimeType = (file: Pick<File, 'name' | 'type'>) => {
  const extensionMime = mimeByExtension[file.name.split('.').pop()?.toLowerCase() ?? '']
  if (extensionMime) return extensionMime
  return allowedUploadMimeTypes.has(file.type) ? file.type : ''
}

const sha256 = async (file: File) => {
  const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer())
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('')
}

const mapTheme = (value: unknown): ThemePreference =>
  value === 'light' || value === 'dark' ? value : 'system'
const mapUser = (value: unknown): User => {
  const source = record(value)
  return {
    id: textValue(source.id),
    name: textValue(source.displayName, '内容运营用户'),
    role: '内容运营',
    phone: textValue(source.phone),
    email: textValue(source.email),
    points: numberValue(source.quotaBalance),
    themePreference: mapTheme(source.themePreference),
  }
}

const mapProject = (value: unknown): Project => {
  const source = record(value)
  return {
    id: textValue(source.id),
    name: textValue(source.name, '未命名项目'),
    description: textValue(source.description),
    writingRequirements: textValue(source.writingRequirements),
    updatedAt: textValue(source.updatedAt, textValue(source.createdAt, now())),
  }
}

const mapPublicSettings = (value: unknown): PublicSettings => {
  const defaults = createDefaultPublicSettings()
  const root = record(value)
  const home = record(root.home)
  const files = record(root.files)
  const ai = record(root.ai)
  const articles = record(root.articles)
  const wechat = record(root.wechat)
  const features = record(root.features)
  const flags = record(features.featureFlags)
  return {
    home: {
      welcomeMessage: textValue(home.welcomeMessage, defaults.home.welcomeMessage),
      examplePrompts: stringList(home.examplePrompts).length
        ? stringList(home.examplePrompts)
        : defaults.home.examplePrompts,
    },
    files: {
      allowedExtensions: stringList(files.allowedExtensions).length
        ? stringList(files.allowedExtensions)
        : defaults.files.allowedExtensions,
      maxFileMb: numberValue(files.maxFileMb, defaults.files.maxFileMb),
      linkFetchEnabled: booleanValue(files.linkFetchEnabled, defaults.files.linkFetchEnabled),
    },
    ai: {
      maxClarificationRounds: numberValue(
        ai.maxClarificationRounds,
        defaults.ai.maxClarificationRounds,
      ),
      minArticleLength: numberValue(ai.minArticleLength, defaults.ai.minArticleLength),
      maxArticleLength: numberValue(ai.maxArticleLength, defaults.ai.maxArticleLength),
      preferenceEnabledByDefault: booleanValue(
        ai.preferenceEnabledByDefault,
        defaults.ai.preferenceEnabledByDefault,
      ),
    },
    articles: {
      autosaveSeconds: numberValue(articles.autosaveSeconds, defaults.articles.autosaveSeconds),
      historyVersions: numberValue(articles.historyVersions, defaults.articles.historyVersions),
    },
    wechat: {
      wechatDraftEnabled: booleanValue(
        wechat.wechatDraftEnabled,
        defaults.wechat.wechatDraftEnabled,
      ),
      wechatPublishEnabled: booleanValue(
        wechat.wechatPublishEnabled,
        defaults.wechat.wechatPublishEnabled,
      ),
      maxArticleImages: numberValue(wechat.maxArticleImages, defaults.wechat.maxArticleImages),
    },
    features: {
      featureFlags: Object.keys(flags).length
        ? Object.fromEntries(
            Object.entries(flags).map(([key, enabled]) => [key, booleanValue(enabled)]),
          )
        : defaults.features.featureFlags,
    },
  }
}

const mapTask = (value: unknown): Task => {
  const source = record(value)
  return {
    id: textValue(source.id),
    title: textValue(source.title, '新创作任务'),
    projectId: optionalText(source.projectId) ?? null,
    currentArticleId: optionalText(source.currentArticleId) ?? null,
    currentSkillId: optionalText(source.currentSkillId) ?? null,
    usePreferences: booleanValue(source.usePreferences, true),
    updatedAt: textValue(source.lastMessageAt, textValue(source.updatedAt, now())),
    status: source.status === 'archived' ? 'archived' : 'active',
  }
}

const mapModelOption = (value: unknown): ModelOption => {
  const source = record(value)
  return {
    id: textValue(source.id),
    name: textValue(source.name, textValue(source.modelId, '未命名模型')),
    providerName: textValue(source.providerName),
    modelId: textValue(source.modelId),
    modelType: source.modelType === 'vision' ? 'vision' : 'chat',
    contextWindow: numberValue(source.contextWindow),
    maxOutputTokens: numberValue(source.maxOutputTokens),
  }
}

const mapAttachment = (value: unknown): Attachment => {
  const source = record(value)
  const kind = source.kind === 'image' || source.kind === 'link' ? source.kind : 'file'
  const status = source.status === 'ready' || source.status === 'failed' ? source.status : 'reading'
  return {
    id: textValue(source.id, requestId('attachment')),
    name: textValue(source.name, '未命名附件'),
    kind,
    size: typeof source.size === 'number' ? source.size : undefined,
    mimeType: optionalText(source.mimeType),
    url: optionalText(source.url),
    status,
    saveToLibrary: booleanValue(source.saveToLibrary),
    assetId: optionalText(source.assetId),
    documentId: optionalText(source.documentId),
  }
}

const mapMessage = (value: unknown) => {
  const source = record(value)
  const content = record(source.contentJson)
  const proposal = record(content.preferenceProposal ?? content.preference_proposal)
  return {
    id: textValue(source.id),
    clientMessageId: optionalText(source.clientMessageId),
    taskId: textValue(source.taskId),
    role: source.role === 'assistant' ? ('assistant' as const) : ('user' as const),
    content: textValue(source.plainText),
    createdAt: textValue(source.createdAt, now()),
    attachments: Array.isArray(content.attachments)
      ? content.attachments.map(mapAttachment)
      : undefined,
    skillIds: Array.isArray(content.skillIds) ? stringList(content.skillIds) : undefined,
    articleId: optionalText(content.articleId),
    articleVersionNo: typeof content.versionNo === 'number' ? content.versionNo : undefined,
    titleCandidates: Array.isArray(content.titleCandidates)
      ? stringList(content.titleCandidates)
      : undefined,
    titleArticleId: optionalText(content.titleArticleId ?? content.articleId),
    suggestions: stringList(content.suggestions),
    responseKind: optionalText(content.responseKind ?? content.response_kind),
    aiRunId: optionalText(content.aiRunId ?? content.ai_run_id),
    errorCode: optionalText(content.errorCode ?? content.error_code),
    retryable: typeof content.retryable === 'boolean' ? content.retryable : undefined,
    sourceMessageId: optionalText(content.sourceMessageId ?? content.source_message_id),
    preferenceReview: optionalText(content.preferenceReview ?? content.preference_review),
    preferenceProposal:
      typeof proposal.value === 'string' && typeof proposal.status === 'string'
        ? {
            value: proposal.value,
            status: proposal.status,
            previousValue: optionalText(proposal.previousValue ?? proposal.previous_value),
            expiresAt: textValue(proposal.expiresAt ?? proposal.expires_at),
          }
        : undefined,
  }
}

const mapTaskAIRunSummary = (value: unknown): TaskAIRunSummary | null => {
  const source = record(value)
  const id = textValue(source.id)
  if (!id) return null
  return {
    id,
    status: textValue(source.status, 'failed') as TaskAIRunSummary['status'],
    runType: textValue(source.runType),
    errorCode: optionalText(source.errorCode),
    errorMessage: optionalText(source.errorMessage),
    createdAt: textValue(source.createdAt, now()),
    completedAt: optionalText(source.completedAt),
  }
}

const escapeHtml = (value: string) =>
  value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')

const safeLinkHref = (value: unknown) => safeHttpUrl(value)

const supportedTiptapNodes = new Set([
  'table',
  'tableRow',
  'tableCell',
  'tableHeader',
  'doc',
  'text',
  'paragraph',
  'heading',
  'blockquote',
  'bulletList',
  'orderedList',
  'listItem',
  'image',
  'horizontalRule',
  'hardBreak',
  'codeBlock',
])
const supportedTiptapMarks = new Set(['bold', 'italic', 'strike', 'code', 'link'])
const tiptapAlias: Record<string, string> = {
  title: 'heading',
  heading1: 'heading',
  heading2: 'heading',
  body: 'paragraph',
  quote: 'blockquote',
  divider: 'horizontalRule',
  intro: 'paragraph',
  list: 'bulletList',
}
const legacyParagraphModule: Record<string, 'lead' | 'body' | 'highlight' | 'caption'> = {
  lead: 'lead',
  intro: 'lead',
  body: 'body',
  highlight: 'highlight',
  caption: 'caption',
}
const nestedText = (value: unknown): string => {
  const source = record(value)
  if (source.type === 'text') return textValue(source.text)
  return Array.isArray(source.content)
    ? source.content.map(nestedText).join('')
    : textValue(source.text)
}

const normalizeTiptapNode = (value: unknown): JsonRecord | undefined => {
  const source = record(value)
  const originalType = textValue(source.type)
  if (!originalType) return undefined
  const legacyModule = legacyParagraphModule[originalType]
  const type = legacyModule ? 'paragraph' : (tiptapAlias[originalType] ?? originalType)
  if (!supportedTiptapNodes.has(type)) {
    const text = nestedText(source)
    return { type: 'paragraph', content: text ? [{ type: 'text', text }] : [] }
  }
  const normalized: JsonRecord = { type }
  const sourceAttrs = record(source.attrs)
  const attrs: JsonRecord = {}
  if (type === 'paragraph') {
    const module = legacyModule ?? sourceAttrs.module
    if (module === 'lead' || module === 'body' || module === 'highlight' || module === 'caption')
      attrs.module = module
  } else if (type === 'heading') {
    const level =
      originalType === 'title'
        ? 1
        : originalType === 'heading1'
          ? 2
          : originalType === 'heading2'
            ? 3
            : numberValue(sourceAttrs.level, 2)
    attrs.level = Math.min(3, Math.max(1, Math.round(level)))
  } else if (type === 'orderedList' && numberValue(sourceAttrs.start) >= 1) {
    attrs.start = Math.min(1_000_000, Math.round(numberValue(sourceAttrs.start)))
  } else if (type === 'codeBlock' && optionalText(sourceAttrs.language)) {
    attrs.language = textValue(sourceAttrs.language).slice(0, 80)
  } else if (type === 'tableCell' || type === 'tableHeader') {
    for (const key of ['colspan', 'rowspan', 'colwidth'])
      if (sourceAttrs[key] !== undefined && sourceAttrs[key] !== null) attrs[key] = sourceAttrs[key]
  } else if (type === 'image') {
    const src = safeHttpUrl(sourceAttrs.src, { httpsOnly: true })
    if (src) attrs.src = src.slice(0, 2048)
    if (optionalText(sourceAttrs.alt)) attrs.alt = textValue(sourceAttrs.alt).slice(0, 500)
    if (optionalText(sourceAttrs.title)) attrs.title = textValue(sourceAttrs.title).slice(0, 500)
    if (optionalText(sourceAttrs.assetId))
      attrs.assetId = textValue(sourceAttrs.assetId).slice(0, 64)
  }
  if (type === 'image' && !attrs.src) return { type: 'paragraph', content: [] }
  if (Object.keys(attrs).length) normalized.attrs = attrs
  if (type === 'text') {
    normalized.text = textValue(source.text)
    if (Array.isArray(source.marks)) {
      const marks = source.marks.flatMap((value) => {
        const mark = record(value)
        const markType = textValue(mark.type)
        if (!supportedTiptapMarks.has(markType)) return []
        if (markType !== 'link') return [{ type: markType }]
        const href = safeLinkHref(record(mark.attrs).href)
        return href ? [{ type: 'link', attrs: { href } }] : []
      })
      if (marks.length) normalized.marks = marks
    }
    return normalized
  }
  if (type === 'hardBreak' || type === 'horizontalRule' || type === 'image') return normalized
  if (Array.isArray(source.content)) {
    normalized.content = source.content
      .map(normalizeTiptapNode)
      .filter((item): item is JsonRecord => Boolean(item))
  } else if (typeof source.text === 'string') {
    normalized.content = [{ type: 'text', text: source.text }]
  } else if (type === 'doc') {
    normalized.content = []
  }
  return normalized
}

const tiptapDocumentBlocks = new Set([
  'table',
  'paragraph',
  'heading',
  'bulletList',
  'orderedList',
  'blockquote',
  'horizontalRule',
  'codeBlock',
  'image',
])
const inlineContent = (value: JsonRecord): JsonRecord[] => {
  const children = Array.isArray(value.content) ? (value.content as JsonRecord[]) : []
  return children.flatMap((child) => {
    if (child.type === 'text' || child.type === 'hardBreak') return [child]
    const text = nestedText(child)
    return text ? [{ type: 'text', text }] : []
  })
}

const paragraphFrom = (value?: JsonRecord): JsonRecord => {
  const text = value ? nestedText(value) : ''
  return { type: 'paragraph', content: text ? [{ type: 'text', text }] : [] }
}

const canonicalBlocks = (values: JsonRecord[]): JsonRecord[] =>
  values.flatMap((value): JsonRecord[] => {
    const type = textValue(value.type)
    if (type === 'text' || type === 'hardBreak') return [paragraphFrom(value)]
    if (type === 'listItem') {
      const children = Array.isArray(value.content) ? (value.content as JsonRecord[]) : []
      return canonicalBlocks(children)
    }
    if (!tiptapDocumentBlocks.has(type)) return [paragraphFrom(value)]
    if (type === 'table') return [value]
    if (type === 'paragraph' || type === 'heading')
      return [{ ...value, content: inlineContent(value) }]
    if (type === 'codeBlock') {
      const text = nestedText(value)
      return [{ ...value, ...(text ? { content: [{ type: 'text', text }] } : { content: [] }) }]
    }
    if (type === 'horizontalRule' || type === 'image') {
      return [value]
    }
    const children = Array.isArray(value.content) ? (value.content as JsonRecord[]) : []
    if (type === 'blockquote') {
      const blocks = canonicalBlocks(children)
      return blocks.length ? [{ ...value, content: blocks }] : [paragraphFrom()]
    }
    const items = children.map((child) => {
      const sourceChildren =
        child.type === 'listItem' && Array.isArray(child.content)
          ? (child.content as JsonRecord[])
          : [child]
      const blocks = canonicalBlocks(sourceChildren)
      if (!blocks.length || blocks[0]?.type !== 'paragraph') blocks.unshift(paragraphFrom())
      return { type: 'listItem', content: blocks }
    })
    return items.length ? [{ ...value, content: items }] : [paragraphFrom()]
  })

export const normalizeTiptapJson = (value: unknown): JsonRecord | undefined => {
  const normalized = normalizeTiptapNode(value)
  if (!normalized) return undefined
  if (normalized.type !== 'doc') return canonicalBlocks([normalized])[0]
  const children = Array.isArray(normalized.content) ? (normalized.content as JsonRecord[]) : []
  return { type: 'doc', content: canonicalBlocks(children) }
}

const nodeHtml = (value: unknown): string => {
  const node = record(value)
  const type = textValue(node.type)
  if (type === 'text') {
    let html = escapeHtml(textValue(node.text))
    const marks = Array.isArray(node.marks) ? node.marks : []
    marks.forEach((value) => {
      const mark = record(value)
      if (mark.type === 'bold') html = `<strong>${html}</strong>`
      else if (mark.type === 'italic') html = `<em>${html}</em>`
      else if (mark.type === 'strike') html = `<s>${html}</s>`
      else if (mark.type === 'code') html = `<code>${html}</code>`
      else if (mark.type === 'link') {
        const href = safeLinkHref(record(mark.attrs).href)
        if (href) html = `<a href="${escapeHtml(href)}" rel="noopener noreferrer">${html}</a>`
      }
    })
    return html
  }
  const children = Array.isArray(node.content)
    ? node.content.map(nodeHtml).join('')
    : escapeHtml(textValue(node.text))
  if (type === 'doc') return children
  if (type === 'table')
    return `<div class="tableWrapper"><table><tbody>${children}</tbody></table></div>`
  if (type === 'tableRow') return `<tr>${children}</tr>`
  if (type === 'tableCell') return `<td>${children}</td>`
  if (type === 'tableHeader') return `<th>${children}</th>`
  if (type === 'heading') {
    const level = Math.min(3, Math.max(1, numberValue(record(node.attrs).level, 2)))
    return `<h${level}>${children}</h${level}>`
  }
  if (type === 'blockquote') return `<blockquote>${children}</blockquote>`
  if (type === 'bulletList') return `<ul>${children}</ul>`
  if (type === 'orderedList') return `<ol>${children}</ol>`
  if (type === 'listItem') return `<li>${children}</li>`
  if (type === 'image') {
    const attrs = record(node.attrs)
    return `<img src="${escapeHtml(textValue(attrs.src))}" alt="${escapeHtml(textValue(attrs.alt))}">`
  }
  if (type === 'horizontalRule') return '<hr>'
  if (type === 'hardBreak') return '<br>'
  return `<p>${children}</p>`
}

const contentHtml = (value: unknown) => {
  const content = record(value)
  if (typeof content.html === 'string') return content.html
  if (content.type === 'doc') return nodeHtml(content)
  if (Array.isArray(content.content)) return content.content.map(nodeHtml).join('')
  return textValue(content.text) ? `<p>${escapeHtml(textValue(content.text))}</p>` : '<p></p>'
}

const mapArticleStatus = (value: unknown): ArticleStatus => {
  const statuses: ArticleStatus[] = [
    'editing',
    'local_draft',
    'wechat_draft',
    'published',
    'publishing',
    'wechat_draft_queued',
    'wechat_draft_submitting',
    'wechat_draft_reconciling',
    'wechat_draft_unknown',
    'wechat_draft_failed',
    'wechat_draft_cancelled',
    'publish_queued',
    'publish_submitting',
    'publish_reconciling',
    'publish_unknown',
    'publish_failed',
    'publish_cancelled',
  ]
  return statuses.includes(value as ArticleStatus) ? (value as ArticleStatus) : 'editing'
}

const mapArticle = (value: unknown): Article => {
  const envelope = record(value)
  const source = isRecord(envelope.article) ? envelope.article : envelope
  const version = record(envelope.version)
  const normalizedContent = normalizeTiptapJson(version.contentJson)
  return {
    id: textValue(source.id),
    title: textValue(source.title, '未命名文章'),
    summary: textValue(source.summary),
    taskId: textValue(source.sourceTaskId),
    projectId: optionalText(source.projectId) ?? null,
    status: mapArticleStatus(source.status),
    updatedAt: textValue(source.updatedAt, textValue(version.createdAt, now())),
    versionNo: numberValue(source.currentVersionNo, numberValue(version.versionNo, 1)),
    contentHtml: contentHtml(normalizedContent ?? version.contentJson),
    contentJson: normalizedContent,
    coverState: 'missing',
    renderId: null,
    accountId: null,
    templateId: null,
  }
}

const mapArticleVersion = (value: unknown, title = ''): ArticleVersion => {
  const source = record(value)
  const normalizedContent = normalizeTiptapJson(source.contentJson)
  return {
    id: textValue(source.id),
    articleId: textValue(source.articleId),
    versionNo: numberValue(source.versionNo),
    reason: textValue(source.source, '保存'),
    createdAt: textValue(source.createdAt, now()),
    contentHtml: contentHtml(normalizedContent ?? source.contentJson),
    title,
    contentJson: normalizedContent ?? undefined,
  }
}

const mapFileStatus = (value: unknown): FileReadStatus => {
  if (value === 'ready') return 'ready'
  if (value === 'failed') return 'failed'
  return 'reading'
}

const mapLibraryItem = (value: unknown): LibraryItem => {
  const source = record(value)
  const type = source.itemType === 'document' ? ('reference' as const) : ('article' as const)
  return {
    id: textValue(source.id),
    type,
    title: textValue(source.title, '未命名内容'),
    projectId: optionalText(source.projectId) ?? null,
    taskId: optionalText(source.sourceTaskId) ?? null,
    sourceTaskTitle: optionalText(source.sourceTaskTitle),
    status:
      type === 'article'
        ? mapArticleStatus(source.displayStatus)
        : mapFileStatus(source.displayStatus),
    updatedAt: textValue(source.updatedAt, now()),
    summary: textValue(source.summary),
    fileType:
      type === 'reference'
        ? textValue(source.filename, textValue(source.title)).split('.').pop()?.toUpperCase()
        : undefined,
    sourceId: textValue(source.sourceId),
  }
}

const mapLibraryItemDetail = (value: unknown): LibraryItem => {
  const envelope = record(value)
  const item = mapLibraryItem(envelope.item)
  const document = record(record(envelope.source).document)
  if (item.type !== 'reference' || !Object.keys(document).length) return item
  return {
    ...item,
    extractedText: optionalText(document.extractedText),
    pageCount: typeof document.pageCount === 'number' ? document.pageCount : undefined,
    parserVersion: optionalText(document.parserVersion),
  }
}

const mapSkill = (value: unknown): Skill => {
  const envelope = record(value)
  const source = isRecord(envelope.skill) ? envelope.skill : envelope
  const version = record(envelope.version)
  const schema = record(version.inputSchema)
  const example = textValue(schema.exampleArticle)
  return {
    id: textValue(source.id),
    scope: source.scope === 'personal' ? 'personal' : 'official',
    name: textValue(source.name, '未命名技能'),
    description: textValue(source.description),
    category: textValue(source.category, 'content'),
    enabled: booleanValue(
      envelope.enabled,
      booleanValue(source.enabled, source.scope === 'personal'),
    ),
    scenes: textValue(schema.scenario, textValue(source.description)),
    requirements: textValue(version.instructions),
    examples: example
      ? example
          .split(/\n{2,}/)
          .map((item) => item.trim())
          .filter(Boolean)
      : [],
  }
}

const templateStatus = (value: unknown): LayoutTemplate['status'] => {
  if (value === 'failed') return 'failed'
  if (value === 'queued' || value === 'extracting' || value === 'processing') return 'extracting'
  if (value === 'manual' || value === 'completed' || value === 'ready' || value === 'succeeded')
    return 'ready'
  return 'idle'
}

const styleFromToken = (fallback: ModuleStyle, value: unknown): ModuleStyle => {
  const source = record(value)
  const field = (camel: string, snake: string) => source[camel] ?? source[snake]
  const weight = numberValue(field('fontWeight', 'font_weight'), Number(fallback.fontWeight))
  return {
    enabled: booleanValue(field('enabled', 'enabled'), fallback.enabled ?? false),
    fontSize: numberValue(field('fontSize', 'font_size'), fallback.fontSize),
    fontWeight:
      weight === 500 || weight === 600 || weight === 700
        ? (String(weight) as ModuleStyle['fontWeight'])
        : '400',
    color: textValue(source.color, fallback.color),
    background: textValue(source.background, fallback.background),
    align:
      source.align === 'left' ||
      source.align === 'center' ||
      source.align === 'right' ||
      source.align === 'justify'
        ? source.align
        : fallback.align,
    lineHeight: numberValue(field('lineHeight', 'line_height'), fallback.lineHeight),
    spacing: numberValue(field('marginBottom', 'margin_bottom'), fallback.spacing),
    marginTop: numberValue(field('marginTop', 'margin_top'), fallback.marginTop ?? 0),
    textIndent: numberValue(field('textIndent', 'text_indent'), fallback.textIndent ?? 0),
    padding: numberValue(source.padding, fallback.padding),
    border: optionalText(field('borderLeft', 'border_left')) ? 'left' : 'none',
    borderLeft: optionalText(field('borderLeft', 'border_left')),
    borderAll: optionalText(field('borderAll', 'border_all')) ?? fallback.borderAll,
  }
}

const stylesFromTokens = (value: unknown) => {
  const defaults = createDefaultStyles()
  const tokens = record(value)
  const result = { ...defaults }
  Object.entries(tokens).forEach(([backend, token]) => {
    const module = frontendModule[backend]
    if (module) result[module] = styleFromToken(defaults[module], token)
  })
  return result
}

const sourcePreviewFromSnapshot = (value: unknown): string[] => {
  const snapshot = record(value)
  const samples = Array.isArray(snapshot.textSamples)
    ? snapshot.textSamples
    : Array.isArray(snapshot.text_samples)
      ? snapshot.text_samples
      : []
  const fromSamples = samples.map((item) => textValue(item).trim()).filter(Boolean)
  if (fromSamples.length) return fromSamples.slice(0, 12)
  return textValue(snapshot.textPreview ?? snapshot.text_preview)
    .split(/\n+/)
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, 12)
}

const stylesToTokens = (styles: Record<ModuleKey, ModuleStyle>) =>
  Object.fromEntries(
    moduleKeys.map((module) => {
      const style = styles[module]
      return [
        backendModule[module],
        {
          enabled: style.enabled,
          fontSize: style.fontSize,
          fontWeight: Number(style.fontWeight),
          color: style.color,
          background: style.background,
          align: style.align,
          lineHeight: style.lineHeight,
          marginTop: style.marginTop ?? 0,
          marginBottom: style.spacing,
          textIndent: style.textIndent ?? 0,
          padding: style.padding,
          ...(style.borderAll ? { borderAll: style.borderAll } : {}),
          ...(style.borderLeft || style.border === 'left'
            ? { borderLeft: style.borderLeft || '4px solid #059669' }
            : {}),
        },
      ]
    }),
  )

const mapTemplate = (value: unknown): LayoutTemplate => {
  const envelope = record(value)
  const source = isRecord(envelope.template) ? envelope.template : envelope
  const versions = Array.isArray(envelope.versions) ? envelope.versions : []
  const version = isRecord(envelope.version) ? envelope.version : record(versions[0])
  const sourceSnapshot = record(version.sourceSnapshot)
  const modelAssist = record(sourceSnapshot.modelAssist)
  const extractionMode =
    modelAssist.status === 'completed'
      ? 'agent'
      : modelAssist.status === 'deterministic_fallback'
        ? 'deterministic_fallback'
        : 'manual'
  return {
    id: textValue(source.id),
    accountId:
      typeof source.officialAccountId === 'string' && source.officialAccountId
        ? source.officialAccountId
        : null,
    name: textValue(source.name, '未命名模板'),
    enabled: booleanValue(source.enabled),
    sourceUrl: textValue(source.sourceUrl),
    status: templateStatus(source.extractionStatus),
    updatedAt: textValue(source.updatedAt, textValue(version.createdAt, now())),
    sourcePreview: sourcePreviewFromSnapshot(version.sourceSnapshot),
    extractionMode,
    styles: stylesFromTokens(version.styleTokens),
  }
}

const accountStatus = (value: unknown): AccountStatus => {
  if (value === 'reconnect_required') return 'reconnect'
  if (value === 'unsupported') return 'unsupported'
  return 'connected'
}

const avatarColor = (name: string) => {
  const palette = ['#0a8f52', '#7a5af8', '#3478f6', '#d97706', '#c2415d']
  const index =
    [...name].reduce((total, character) => total + (character.codePointAt(0) ?? 0), 0) %
    palette.length
  return palette[index] ?? palette[0]!
}

const mapCapabilities = (value: unknown) => [...new Set(stringList(value))]

const mapOfficialAccount = (value: unknown): OfficialAccount => {
  const source = record(value)
  const name = textValue(source.name, '未命名公众号')
  return {
    id: textValue(source.id),
    name,
    avatarText: [...name][0] ?? '号',
    avatarColor: avatarColor(name),
    status: accountStatus(source.uiStatus ?? source.status),
    authorizedAt: textValue(source.authorizedAt, textValue(source.createdAt, now())),
    lastSyncedAt: textValue(source.lastSyncedAt, textValue(source.updatedAt, now())),
    capabilities: mapCapabilities(source.capabilities),
  }
}

const mapPreference = (value: unknown): Preference => {
  const source = record(value)
  const sourceLabels: Record<string, string> = {
    explicit: '用户明确设置',
    article: '根据已确认文章总结',
    system: '系统建议',
    dialogue_feedback: '对话中的写作要求',
    final_preview: '最终预览确认',
  }
  const sourceType = textValue(source.sourceType, 'explicit')
  const valueText = textValue(source.value)
  // A readable heading preserves the existing text API and model-context consumers.
  const heading = /^# ([^\r\n]+)\r?\n\r?\n([\s\S]*)$/.exec(valueText)
  const titles: Record<string, string> = {
    article_length: '文章篇幅',
    tone: '语言风格',
    structure: '文章结构',
    audience: '目标读者',
    formatting: '排版习惯',
    direct_opening: '开头写法',
    direct_title: '标题写法',
    concise_expression: '表达方式',
    concrete_examples: '案例运用',
    avoid_jargon: '用词习惯',
  }
  return {
    id: textValue(source.id),
    title: heading?.[1] ?? titles[textValue(source.preferenceType)] ?? '写作风格',
    text: heading?.[2] ?? valueText,
    source: sourceLabels[sourceType] ?? '写作记录',
    status: source.status === 'candidate' ? 'candidate' : 'confirmed',
    updatedAt: textValue(source.updatedAt, now()),
  }
}

const uploadRemoteFile = async (
  file: File,
  context: {
    projectId?: string | null
    taskId?: string | null
    saveToLibrary?: boolean
    waitForReady?: boolean
    onProgress?: (loaded: number) => void
    onProcessing?: () => void
    signal?: AbortSignal
  } = {},
): Promise<Attachment> => {
  if (!file.size) throw new ApiError('不能上传空文件。', 422, 'EMPTY_FILE')
  const mimeType = normalizedFileMimeType(file)
  if (!mimeType) throw new ApiError('暂不支持这种文件格式。', 422, 'FILE_TYPE_NOT_ALLOWED')
  const hash = await sha256(file)
  const ownerId = readCachedSession()?.user.id
  if (!ownerId) throw new ApiError('登录状态已失效，请重新登录。', 401, 'SESSION_REQUIRED')
  const saveToLibrary = context.saveToLibrary ?? true
  const createBody = {
    filename: file.name,
    mimeType,
    sizeBytes: file.size,
    sha256: hash,
    projectId: context.projectId ?? null,
    taskId: context.taskId ?? null,
  } satisfies UploadCreateDto
  const fingerprint = JSON.stringify([
    ownerId,
    hash,
    file.name,
    file.size,
    mimeType,
    createBody.projectId,
    createBody.taskId,
    saveToLibrary,
  ])
  const command = await withCommandLock(`upload:${hash}`, () => {
    const existing = readPendingUpload(fingerprint)
    if (existing) return existing
    const created: PendingUploadCommand = {
      ownerId,
      fingerprint,
      createIdempotencyKey: requestId('upload-create'),
      completeIdempotencyKey: requestId('upload-complete'),
      createBody,
      completedParts: [],
      createdAt: now(),
    }
    writePendingUpload(created)
    return created
  })

  const attachment = async (documentId: string, assetId?: string): Promise<Attachment> => {
    if (context.waitForReady) {
      context.onProcessing?.()
      await waitForDocument(documentId, context.signal)
      writePendingUpload(null, fingerprint)
    } else {
      void waitForDocument(documentId)
        .then(() => writePendingUpload(null, fingerprint))
        .catch(() => undefined)
    }
    return {
      id: documentId,
      name: file.name,
      kind: mimeType.startsWith('image/') ? 'image' : 'file',
      size: file.size,
      mimeType,
      status: context.waitForReady ? 'ready' : 'reading',
      saveToLibrary,
      assetId,
      documentId,
    }
  }

  if (command.documentId) {
    context.onProgress?.(file.size)
    return attachment(command.documentId, command.assetId)
  }
  try {
    const created = (await openApiData(
      openApi.POST('/api/v1/uploads', {
        signal: context.signal,
        params: { header: { 'Idempotency-Key': command.createIdempotencyKey } },
        body: apiBody<'UploadCreate'>(command.createBody),
      }),
    )) as UploadCreateResponseDto
    const partUrls = [...created.partUrls]
    if (!partUrls.length)
      throw new ApiError('文件存储没有返回上传地址。', 502, 'UPLOAD_PARTS_MISSING')
    const partSize = created.partSizeBytes
    if (!Number.isSafeInteger(partSize) || partSize <= 0)
      throw new ApiError('文件存储返回了无效的分片大小。', 502, 'UPLOAD_PART_SIZE_INVALID')
    let loaded = command.completedParts.reduce(
      (sum, part) =>
        sum + Math.max(0, Math.min(partSize, file.size - (part.partNumber - 1) * partSize)),
      0,
    )
    context.onProgress?.(loaded)
    for (const [index, partUrl] of partUrls.entries()) {
      const partNumber = index + 1
      if (command.completedParts.some((part) => part.partNumber === partNumber)) continue
      const body = file.slice(index * partSize, Math.min(file.size, partNumber * partSize))
      const response = context.onProgress
        ? await uploadPart(resolveApiResourceUrl(partUrl), body, context.signal, (bytes) =>
            context.onProgress?.(Math.min(file.size, loaded + bytes)),
          )
        : await fetch(resolveApiResourceUrl(partUrl), {
            method: 'PUT',
            body,
            signal: context.signal,
          })
      if (!response.ok) {
        if ([401, 403, 404, 410].includes(response.status)) writePendingUpload(null, fingerprint)
        throw new ApiError(
          `文件第 ${partNumber} 段上传失败。`,
          response.status,
          'UPLOAD_PART_FAILED',
          undefined,
          response.status >= 500 || response.status === 429,
        )
      }
      const etag = response.headers.get('ETag')
      if (!etag)
        throw new ApiError(
          `文件第 ${partNumber} 段缺少 ETag，请检查存储 CORS 的 Access-Control-Expose-Headers 配置。`,
          502,
          'UPLOAD_PART_ETAG_MISSING',
        )
      command.completedParts.push({ partNumber, etag })
      loaded += body.size
      context.onProgress?.(Math.min(file.size, loaded))
      writePendingUpload(command)
    }
    const completeBody = {
      sizeBytes: file.size,
      sha256: hash,
      completedParts: [...command.completedParts].sort(
        (left, right) => left.partNumber - right.partNumber,
      ),
      saveToLibrary,
    } satisfies UploadCompleteDto
    const completed = (await openApiData(
      openApi.POST('/api/v1/uploads/{upload_id}/complete', {
        signal: context.signal,
        params: {
          path: { upload_id: created.upload.id },
          header: { 'Idempotency-Key': command.completeIdempotencyKey },
        },
        body: apiBody<'UploadComplete'>(completeBody),
      }),
    )) as UploadCompleteResponseDto
    command.assetId = completed.asset.id
    command.documentId = completed.document.id
    writePendingUpload(command)
    return attachment(command.documentId, command.assetId)
  } catch (error) {
    if (
      error instanceof ApiError &&
      !error.retryable &&
      error.status !== 408 &&
      error.status !== 429 &&
      error.status < 500
    )
      writePendingUpload(null, fingerprint)
    throw error
  }
}

const abortableDelay = (milliseconds: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException('操作已取消。', 'AbortError'))
      return
    }
    const onAbort = () => {
      clearTimeout(timer)
      reject(new DOMException('操作已取消。', 'AbortError'))
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort)
      resolve()
    }, milliseconds)
    signal?.addEventListener('abort', onAbort, { once: true })
  })

const waitForDocument = async (documentId: string, signal?: AbortSignal) => {
  for (let attempt = 0; attempt < 300; attempt += 1) {
    const document = record(
      await openApiData(
        openApi.GET('/api/v1/documents/{document_id}', {
          signal,
          params: { path: { document_id: documentId } },
        }),
      ),
    )
    const status = textValue(document.status)
    if (status === 'completed') return
    if (status === 'failed' || status === 'blocked_external' || status === 'deleted') {
      const errorCode = textValue(document.errorCode, 'DOCUMENT_PROCESSING_FAILED')
      throw new ApiError(
        errorCode === 'FILE_PROVIDER_NOT_CONFIGURED'
          ? '资料解析服务尚未配置，文件已保存但暂时不能用于 AI 创作。'
          : status === 'blocked_external'
            ? '资料包含需要人工确认的外部内容，暂不能用于生成。'
            : '资料解析没有完成，请删除后重新上传。',
        409,
        errorCode,
        { documentId, status },
      )
    }
    await abortableDelay(attempt < 10 ? 500 : 1000, signal)
  }
  throw new ApiError(
    '资料仍在安全扫描和解析中。文件已经保存，请稍后从资料库重新使用。',
    202,
    'DOCUMENT_PROCESSING_PENDING',
    { documentId },
  )
}

export const visibleRunStage = (stage: string): RunStage | null => {
  if (stage === 'accepted') return 'queued'
  if (stage === 'retrieving') return 'reading'
  if (stage === 'validating_output') return 'checking'
  if (stage === 'saving_version') return 'saving'
  if (stage === 'ready_for_formatting') return 'ready'
  if (
    stage === 'validating' ||
    stage === 'clarifying' ||
    stage === 'planning' ||
    stage === 'generating' ||
    stage === 'completed' ||
    stage === 'failed' ||
    stage === 'cancelled'
  )
    return stage
  return null
}

const runState = async (
  runId: string,
  onStage?: (stage: RunStage) => void,
  signal?: AbortSignal,
) => {
  const run = record(
    await openApiData(
      openApi.GET('/api/v1/ai-runs/{run_id}', {
        signal,
        params: { path: { run_id: runId } },
      }),
    ),
  )
  const status = textValue(run.status)
  const visibleStage = visibleRunStage(status)
  // A polling snapshot may still say accepted while SSE reports a later stage.
  if (visibleStage && ['completed', 'failed', 'cancelled'].includes(status)) onStage?.(visibleStage)
  if (status === 'completed') {
    return true
  }
  if (status === 'failed' || status === 'cancelled') {
    onStage?.(status)
    throw new ApiError(
      textValue(run.errorMessage, status === 'cancelled' ? '生成已经停止。' : '文章生成没有完成。'),
      409,
      textValue(run.errorCode, 'AI_RUN_FAILED'),
    )
  }
  return false
}

const retryableRunTransportError = (error: unknown) =>
  !(error instanceof ApiError) ||
  error.retryable ||
  error.status === 408 ||
  error.status === 429 ||
  error.status >= 500

const parseEventBlock = (block: string) => {
  let id: string | undefined
  let event = 'message'
  const data: string[] = []
  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith('id:')) id = line.slice(3).trim()
    else if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
  }
  return { id, event, data: record(camelize(JSON.parse(data.join('\n') || '{}'))) }
}

const userVisibleRunText = (text: string) => {
  const trimmed = text.trimStart()
  return !(
    trimmed.startsWith('{"type":"doc"') ||
    trimmed.startsWith('```json\n{"type":"doc"') ||
    trimmed.startsWith('```json\r\n{"type":"doc"')
  )
}

const waitForRun = async (
  runId: string,
  callbacks: Pick<SendMessageInput, 'onRunStage' | 'onTextDelta' | 'onArticleReady' | 'onWarning'>,
  signal?: AbortSignal,
) => {
  const { onRunStage: onStage, onTextDelta, onArticleReady, onWarning } = callbacks
  let lastEventId: string | undefined
  let reconnects = 0
  const reconnect = async () => {
    reconnects += 1
    if (reconnects > 12)
      throw new ApiError(
        '实时生成连接持续不可用，请检查网络后重试。',
        503,
        'AI_RUN_STREAM_UNAVAILABLE',
        undefined,
        true,
      )
    onStage?.('reconnecting')
    await abortableDelay(Math.min(500 * 2 ** (reconnects - 1), 5000), signal)
  }
  while (true) {
    try {
      const response = await streamRunEvents(runId, lastEventId, signal)
      if (!response.body) throw new Error('Event stream body missing')
      const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
      let buffer = ''
      let terminal = false
      while (!terminal) {
        const { done, value } = await reader.read()
        buffer += value ?? ''
        const blocks = buffer.split(/\r?\n\r?\n/)
        buffer = blocks.pop() ?? ''
        for (const block of blocks) {
          if (!block.trim() || block.trimStart().startsWith(':')) continue
          const event = parseEventBlock(block)
          lastEventId = event.id ?? lastEventId
          if (event.event === 'stage.changed') {
            const stage = textValue(event.data.stage)
            const visibleStage = visibleRunStage(stage)
            if (visibleStage) onStage?.(visibleStage)
          } else if (event.event === 'text.delta') {
            const text = textValue(event.data.text)
            if (text && userVisibleRunText(text)) onTextDelta?.(text)
          } else if (event.event === 'warning') {
            if (event.data.code === 'AI_CONTENT_CHECK_WARNING') continue
            const message = textValue(event.data.message)
            if (message) onWarning?.(message)
          } else if (event.event === 'article.ready') {
            const articleId = textValue(event.data.articleId)
            if (articleId) onArticleReady?.(articleId)
            onStage?.('ready')
          } else if (event.event === 'run.completed') {
            onStage?.('completed')
            terminal = true
          } else if (event.event === 'run.cancelled') {
            onStage?.('cancelled')
            throw new ApiError('生成已经停止。', 409, 'AI_RUN_CANCELLED')
          } else if (event.event === 'run.failed') {
            onStage?.('failed')
            throw new ApiError(
              textValue(event.data.message, '文章生成没有完成。'),
              409,
              textValue(event.data.code, 'AI_RUN_FAILED'),
            )
          }
        }
        if (done) break
      }
      if (terminal || (await runState(runId, onStage, signal))) return
      await reconnect()
    } catch (error) {
      if (error instanceof ApiError && ['AI_RUN_FAILED', 'AI_RUN_CANCELLED'].includes(error.code))
        throw error
      if (signal?.aborted || (error instanceof DOMException && error.name === 'AbortError'))
        throw error
      if (!retryableRunTransportError(error)) throw error
      try {
        if (await runState(runId, onStage, signal)) return
      } catch (stateError) {
        if (
          stateError instanceof ApiError &&
          ['AI_RUN_FAILED', 'AI_RUN_CANCELLED'].includes(stateError.code)
        )
          throw stateError
        if (
          signal?.aborted ||
          (stateError instanceof DOMException && stateError.name === 'AbortError')
        )
          throw stateError
        if (!retryableRunTransportError(stateError)) throw stateError
      }
      await reconnect()
    }
  }
}

const readPendingMessages = (): Record<string, PendingMessageCommand> => {
  try {
    const stored = record(JSON.parse(localStorage.getItem(pendingMessageKey) ?? '{}'))
    const commands: Record<string, PendingMessageCommand> = {}
    Object.values(stored).forEach((value) => {
      const source = record(value)
      const path = textValue(source.path)
      const ownerId = textValue(source.ownerId)
      const idempotencyKey = textValue(source.idempotencyKey)
      const createdAt = textValue(source.createdAt)
      const intentSignature = textValue(source.intentSignature)
      if (
        !ownerId ||
        !idempotencyKey ||
        !createdAt ||
        !intentSignature ||
        !/^\/tasks(?:\/[^/]+\/messages)?$/.test(path) ||
        !isRecord(source.body)
      )
        return
      if (Date.now() - new Date(createdAt).getTime() > 24 * 60 * 60 * 1000) return
      commands[idempotencyKey] = {
        ownerId,
        path: path as PendingMessageCommand['path'],
        body: source.body as PendingMessageCommand['body'],
        intentSignature,
        idempotencyKey,
        createdAt,
        taskId: optionalText(source.taskId),
        runId: optionalText(source.runId),
        cancelRequested: booleanValue(source.cancelRequested),
      }
    })
    if (Object.keys(commands).length)
      localStorage.setItem(pendingMessageKey, JSON.stringify(commands))
    else localStorage.removeItem(pendingMessageKey)
    return commands
  } catch {
    return {}
  }
}

const readPendingMessage = (intentSignature?: string): PendingMessageCommand | null => {
  const ownerId = readCachedSession()?.user.id
  return (
    Object.values(readPendingMessages())
      .filter(
        (command) =>
          command.ownerId === ownerId &&
          (!intentSignature || command.intentSignature === intentSignature),
      )
      .sort((left, right) => left.createdAt.localeCompare(right.createdAt))[0] ?? null
  )
}

const writePendingMessage = (
  command: PendingMessageCommand | null,
  idempotencyKey = command?.idempotencyKey,
) => {
  try {
    if (!command && !idempotencyKey) {
      localStorage.removeItem(pendingMessageKey)
      return
    }
    const commands = readPendingMessages()
    if (command) commands[command.idempotencyKey] = command
    else if (idempotencyKey) delete commands[idempotencyKey]
    if (Object.keys(commands).length)
      localStorage.setItem(pendingMessageKey, JSON.stringify(commands))
    else localStorage.removeItem(pendingMessageKey)
  } catch {
    // The server idempotency key still protects the active invocation.
  }
}

const resolvePendingMessage = async (
  command: PendingMessageCommand,
  input: Pick<
    SendMessageInput,
    'signal' | 'onRunAccepted' | 'onRunStage' | 'onTextDelta' | 'onArticleReady' | 'onWarning'
  >,
) => {
  writePendingMessage(command)
  let reconnects = 0
  while (!command.runId || !command.taskId) {
    try {
      const response = record(
        command.path === '/tasks'
          ? await openApiData(
              openApi.POST('/api/v1/tasks', {
                signal: input.signal,
                params: { header: { 'Idempotency-Key': command.idempotencyKey } },
                body: apiBody<'TaskCreate'>(command.body as TaskCreateDto),
              }),
            )
          : await openApiData(
              openApi.POST('/api/v1/tasks/{task_id}/messages', {
                signal: input.signal,
                params: {
                  path: {
                    task_id:
                      command.taskId ?? command.path.slice('/tasks/'.length, -'/messages'.length),
                  },
                  header: { 'Idempotency-Key': command.idempotencyKey },
                },
                body: apiBody<'MessageCreate'>(command.body as MessageCreateDto),
              }),
            ),
      )
      command.taskId = textValue(record(response.task).id, command.taskId)
      command.runId = textValue(record(response.aiRun).id, command.runId)
      if (!command.taskId || !command.runId) {
        writePendingMessage(null, command.idempotencyKey)
        throw new ApiError('服务端没有返回生成任务，请重试。', 502, 'AI_RUN_RESPONSE_INVALID')
      }
      writePendingMessage(command)
    } catch (error) {
      if (input.signal?.aborted || (error instanceof DOMException && error.name === 'AbortError'))
        throw error
      if (error instanceof ApiError && error.code === 'AUTH_REFRESHED_RETRY_REQUIRED') throw error
      if (
        error instanceof ApiError &&
        !error.retryable &&
        error.status !== 408 &&
        error.status !== 429 &&
        error.status < 500
      )
        throw error
      reconnects += 1
      if (reconnects >= 12)
        throw new ApiError(
          '暂未确认原请求的处理结果。消息和已上传资料已保留，请继续原请求确认结果，不要重复创建任务。',
          202,
          'AI_RUN_REQUEST_PENDING',
          { idempotencyKey: command.idempotencyKey },
          true,
        )
      input.onRunStage?.('reconnecting')
      await abortableDelay(Math.min(500 * 2 ** (reconnects - 1), 5000), input.signal)
    }
  }
  const acceptedMessage =
    command.path === '/tasks'
      ? (command.body as TaskCreateDto).firstMessage
      : (command.body as MessageCreateDto)
  await input.onRunAccepted?.(command.runId, command.taskId, acceptedMessage.clientMessageId)
  if (command.cancelRequested) {
    await openApiData(
      openApi.POST('/api/v1/ai-runs/{run_id}/cancel', {
        params: { path: { run_id: command.runId } },
      }),
    )
    writePendingMessage(null, command.idempotencyKey)
    throw new DOMException('操作已取消。', 'AbortError')
  }
  await waitForRun(command.runId, input, input.signal)
  return { taskId: command.taskId, runId: command.runId }
}

const articleRevisionBody = (input: ArticleRevisionInput): ArticleRevisionCreateDto => ({
  baseVersionNo: input.baseVersionNo,
  selectedText: input.selectedText,
  instruction: input.instruction,
  selectionFrom: input.selectionFrom,
  selectionTo: input.selectionTo,
})

const sameArticleRevision = (pending: PendingArticleRevision, input: ArticleRevisionInput) =>
  JSON.stringify(articleRevisionBody(pending)) === JSON.stringify(articleRevisionBody(input))

const settleArticleRevision = async (pending: PendingArticleRevision) => {
  writePendingArticleRevision(pending)
  let revision: ArticleRevisionResourceDto
  if (pending.revisionId) {
    revision = await openApiData(
      openApi.GET('/api/v1/article-revisions/{revision_id}', {
        params: { path: { revision_id: pending.revisionId } },
      }),
    )
  } else {
    try {
      revision = await openApiData(
        openApi.POST('/api/v1/articles/{article_id}/revisions', {
          params: {
            path: { article_id: pending.articleId },
            header: { 'Idempotency-Key': pending.idempotencyKey },
          },
          body: apiBody<'ArticleRevisionCreate'>(articleRevisionBody(pending)),
        }),
      )
      pending.revisionId = revision.id
      writePendingArticleRevision(pending)
    } catch (error) {
      if (
        error instanceof ApiError &&
        !error.retryable &&
        error.status !== 408 &&
        error.status !== 429 &&
        error.status < 500
      )
        writePendingArticleRevision(null, pending.articleId)
      throw error
    }
  }
  const revisionId = pending.revisionId || revision.id
  if (!revisionId)
    throw new ApiError('服务端没有返回文章修改任务。', 502, 'ARTICLE_REVISION_RESPONSE_INVALID')
  for (let attempt = 0; attempt < 300; attempt += 1) {
    const status = revision.status
    if (status === 'completed') {
      const replacementText = revision.replacementText ?? ''
      if (!replacementText)
        throw new ApiError('AI 没有返回可应用的修改建议。', 502, 'ARTICLE_REVISION_EMPTY')
      writePendingArticleRevision(null, pending.articleId)
      return { id: revisionId, replacementText }
    }
    if (status === 'failed' || status === 'cancelled') {
      writePendingArticleRevision(null, pending.articleId)
      throw new ApiError(
        revision.errorMessage || 'AI 修改建议没有生成完成。',
        409,
        revision.errorCode || 'ARTICLE_REVISION_FAILED',
      )
    }
    await abortableDelay(attempt < 10 ? 500 : 1000)
    revision = await openApiData(
      openApi.GET('/api/v1/article-revisions/{revision_id}', {
        params: { path: { revision_id: revisionId } },
      }),
    )
  }
  throw new ApiError('AI 修改建议仍在后台生成，请稍后再试。', 202, 'ARTICLE_REVISION_PENDING', {
    revisionId,
  })
}

const waitForArticleRevision = async (input: ArticleRevisionInput) => {
  const ownerId = readCachedSession()?.user.id
  if (!ownerId) throw new ApiError('登录状态已失效，请重新登录。', 401, 'SESSION_REQUIRED')
  const existing = await withCommandLock(`article-revision:${ownerId}:${input.articleId}`, () => {
    const pending = readPendingArticleRevision(input.articleId)
    if (pending) return pending
    const created: PendingArticleRevision = {
      ...input,
      ownerId,
      idempotencyKey: requestId('article-revision'),
      createdAt: now(),
    }
    writePendingArticleRevision(created)
    return created
  })
  if (existing && !sameArticleRevision(existing, input)) {
    throw new ApiError(
      '该文章还有一项 AI 修改建议正在生成，请先查询原任务，避免重复扣减积分。',
      202,
      'ARTICLE_REVISION_ALREADY_PENDING',
      { revisionId: existing.revisionId },
    )
  }
  return settleArticleRevision(existing)
}

const getDetailedSkill = async (id: string) =>
  mapSkill(
    await openApiData(
      openApi.GET('/api/v1/skills/{skill_id}', {
        params: { path: { skill_id: id } },
      }),
    ),
  )

const settleWechatOperation = async (
  pending: PendingArticleOutcome,
  initial?: JsonRecord,
): Promise<Article> => {
  if (!pending.operationId && !initial)
    throw new ApiError('微信操作没有返回可查询的编号。', 502, 'WECHAT_OPERATION_ID_MISSING')
  let operation =
    initial ??
    record(
      await openApiData(
        openApi.GET('/api/v1/wechat-operations/{operation_id}', {
          params: { path: { operation_id: pending.operationId! } },
        }),
      ),
    )
  const operationId = textValue(operation.id, pending.operationId)
  if (!operationId)
    throw new ApiError('微信操作没有返回可查询的编号。', 502, 'WECHAT_OPERATION_ID_MISSING')
  pending.operationId = operationId

  for (let attempt = 0; attempt < 45; attempt += 1) {
    const status = textValue(operation.status)
    if (status === 'succeeded') {
      const updated = mapArticle(
        await openApiData(
          openApi.GET('/api/v1/articles/{article_id}', {
            params: { path: { article_id: pending.articleId } },
          }),
        ),
      )
      const result = record(operation.result)
      writePendingArticleOutcome(null, pending.articleId)
      return {
        ...updated,
        renderId: pending.renderId,
        accountId: pending.accountId,
        templateId: pending.templateId,
        publishedUrl:
          pending.outcome === 'publish'
            ? (optionalText(result.url) ?? optionalText(result.articleUrl))
            : undefined,
        lastOperationStatus: 'succeeded',
      }
    }
    if (status === 'unknown') {
      pending.operationStatus = 'unknown'
      writePendingArticleOutcome(pending)
      throw new ApiError(
        '微信返回结果未知。为避免重复发布，已保留原操作并禁止新建提交；请查询原操作状态或凭操作编号对账。',
        409,
        'WECHAT_RESULT_UNKNOWN',
        { operationId, result: operation.result },
      )
    }
    if (status === 'failed' || status === 'cancelled') {
      writePendingArticleOutcome(null, pending.articleId)
      const result = record(operation.result)
      throw new ApiError(
        optionalText(result.message) ?? '公众号操作没有完成，请检查连接状态后重试。',
        409,
        textValue(operation.errorCode, 'WECHAT_OPERATION_FAILED'),
        { operationId, result: operation.result },
        booleanValue(operation.retryable),
      )
    }
    if (status === 'queued' || status === 'submitting' || status === 'reconciling')
      pending.operationStatus = status
    writePendingArticleOutcome(pending)
    await sleep(attempt < 8 ? 250 : 1000)
    operation = record(
      await openApiData(
        openApi.GET('/api/v1/wechat-operations/{operation_id}', {
          params: { path: { operation_id: operationId } },
        }),
      ),
    )
  }

  writePendingArticleOutcome(pending)
  throw new ApiError(
    '公众号仍在处理。已保留原操作，请稍后继续查询，不要重复提交。',
    202,
    'WECHAT_OPERATION_PENDING',
    { operationId },
  )
}

const establishSession = async (payload: JsonRecord): Promise<Session> => {
  const provisional: Session = {
    user: mapUser(payload.user),
    accessToken: textValue(payload.accessToken),
    refreshToken: platform.native ? undefined : optionalText(payload.refreshToken),
  }
  writeCachedSession(provisional)
  try {
    provisional.user = mapUser(await openApiData(openApi.GET('/api/v1/me')))
  } catch {
    // The auth response still contains enough safe identity data to enter the app.
  }
  writeCachedSession(provisional)
  return provisional
}

export const remoteApi: UserApi = {
  async login(identifier, password) {
    const deviceName = navigator.userAgent.slice(0, 120)
    const payload = platform.native
      ? nativeAuthPayload(await platform.loginSession({ identifier, password, deviceName }))
      : record(
          await openApiData(
            openApi.POST('/api/v1/auth/login', {
              body: apiBody<'LoginRequest'>({
                identifier,
                password,
                platform: authPlatform(),
                deviceName,
              }),
            }),
          ),
        )
    return establishSession(payload)
  },
  async loginWithCode(identifier, challengeId, code) {
    const verification = record(
      await openApiData(
        openApi.POST('/api/v1/auth/verification-codes/verify', {
          body: apiBody<'VerificationCheck'>({ challengeId, code }),
        }),
      ),
    )
    const verificationToken = textValue(verification.verificationToken)
    const deviceName = navigator.userAgent.slice(0, 120)
    const payload = platform.native
      ? nativeAuthPayload(
          await platform.loginCodeSession({ identifier, verificationToken, deviceName }),
        )
      : record(
          await openApiData(
            openApi.POST('/api/v1/auth/login-code', {
              body: apiBody<'CodeLoginRequest'>({
                identifier,
                verificationToken,
                platform: authPlatform(),
                deviceName,
              }),
            }),
          ),
        )
    return establishSession(payload)
  },
  async requestVerificationCode(destination, purpose): Promise<VerificationChallenge> {
    const payload = record(
      await openApiData(
        openApi.POST('/api/v1/auth/verification-codes', {
          body: apiBody<'VerificationRequest'>({ destination, purpose }),
        }),
      ),
    )
    return {
      challengeId: textValue(payload.challengeId),
      expiresAt: textValue(payload.expiresAt),
      deliveryStatus: textValue(payload.deliveryStatus),
      providerMode: 'configured',
    }
  },
  async register(phone, challengeId, code, password) {
    const verification = record(
      await openApiData(
        openApi.POST('/api/v1/auth/verification-codes/verify', {
          body: apiBody<'VerificationCheck'>({ challengeId, code }),
        }),
      ),
    )
    await openApiData(
      openApi.POST('/api/v1/auth/register', {
        body: apiBody<'RegisterRequest'>({
          phone,
          displayName: `运营用户${phone.slice(-4)}`,
          password,
          verificationToken: textValue(verification.verificationToken),
          acceptedTerms: true,
        }),
      }),
    )
    return remoteApi.login(phone, password)
  },
  async logout() {
    let revoked = false
    const ownerId = readCachedSession()?.user.id
    try {
      if (platform.native)
        nativeAuthPayload(await platform.logoutSession(readCachedSession()?.accessToken))
      else await openApiData(openApi.POST('/api/v1/auth/logout'))
      revoked = true
    } finally {
      if (platform.native && revoked) await platform.clearRefreshToken()
      clearUserClientData(ownerId)
      writeCachedSession(null)
    }
  },
  async deleteAccount(password, confirmation): Promise<AccountDeletionReceipt> {
    const ownerId = readCachedSession()?.user.id
    const payload = record(
      await openApiData(
        openApi.DELETE('/api/v1/me', {
          body: apiBody<'AccountDeletionCreate'>({ password, confirmation }),
        }),
      ),
    )
    if (platform.native) await platform.clearRefreshToken()
    clearUserClientData(ownerId)
    writeCachedSession(null)
    return {
      deletionRequestId: textValue(payload.deletionRequestId),
      status: 'scheduled',
      requestedAt: textValue(payload.requestedAt),
      purgeAfter: textValue(payload.purgeAfter),
    }
  },
  getMe: async () => mapUser((await openApiData(openApi.GET('/api/v1/me'))) as MeResponseDto),
  getPublicSettings: async () =>
    mapPublicSettings(await openApiData(openApi.GET('/api/v1/public-settings'))),
  async listProjectsPage(cursor, limit = 50) {
    const payload = await openApiData(
      openApi.GET('/api/v1/projects', { params: { query: { cursor, limit } } }),
    )
    return { items: itemList(payload).map(mapProject), nextCursor: nextPageCursor(payload, cursor) }
  },
  createProject: async (name) =>
    mapProject(
      await openApiData(
        openApi.POST('/api/v1/projects', { body: apiBody<'ProjectCreate'>({ name }) }),
      ),
    ),
  updateProject: async (id, patch) =>
    mapProject(
      await openApiData(
        openApi.PATCH('/api/v1/projects/{project_id}', {
          params: { path: { project_id: id } },
          body: apiBody<'ProjectPatch'>(patch),
        }),
      ),
    ),
  deleteProject: async (id) => {
    await openApiData(
      openApi.DELETE('/api/v1/projects/{project_id}', { params: { path: { project_id: id } } }),
    )
  },
  async listTasksPage(projectId, cursor, limit = 50): Promise<TaskPage> {
    const payload = await openApiData(
      openApi.GET('/api/v1/tasks', {
        params: {
          query: { project_id: projectId === null ? 'unclassified' : projectId, cursor, limit },
        },
      }),
    )
    return { items: itemList(payload).map(mapTask), nextCursor: nextPageCursor(payload, cursor) }
  },
  async getTask(id) {
    const source = (await openApiData(
      openApi.GET('/api/v1/tasks/{task_id}', {
        params: { path: { task_id: id } },
      }),
    )) as TaskDetailDto
    const task = mapTask(source)
    const messages = Array.isArray(source.messages) ? source.messages.map(mapMessage) : []
    let article: Article | null = null
    if (task.currentArticleId) {
      try {
        article = await remoteApi.getArticle(task.currentArticleId)
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 404) throw error
      }
    }
    return {
      task,
      messages,
      messagesNextCursor: source.messagesNextCursor ?? undefined,
      latestAiRun: mapTaskAIRunSummary(source.latestAiRun),
      article,
    }
  },
  async listTaskMessages(id, cursor, limit = 30) {
    const payload = await openApiData(
      openApi.GET('/api/v1/tasks/{task_id}/messages', {
        params: { path: { task_id: id }, query: { cursor, limit } },
      }),
    )
    return {
      items: itemList(payload).map(mapMessage),
      nextCursor: nextPageCursor(payload, cursor),
    }
  },
  uploadFile: uploadRemoteFile,
  async sendMessage(input: SendMessageInput): Promise<SendMessageResult> {
    if (input.attachments.some((attachment) => attachment.sourceFile)) input.onRunStage?.('reading')
    const attachments = await Promise.all(
      input.attachments.map(async (attachment) => {
        if (!attachment.sourceFile) return attachment
        const report = (loaded: number, phase: 'uploading' | 'processing' | 'ready') =>
          input.onAttachmentProgress?.({
            id: attachment.id,
            name: attachment.name,
            loaded,
            total: attachment.sourceFile!.size,
            phase,
          })
        report(0, 'uploading')
        return uploadRemoteFile(attachment.sourceFile, {
          projectId: input.projectId ?? null,
          taskId: input.taskId ?? null,
          saveToLibrary: attachment.saveToLibrary,
          waitForReady: true,
          signal: input.signal,
          onProgress: input.onAttachmentProgress
            ? (loaded) => report(loaded, 'uploading')
            : undefined,
          onProcessing: () => report(attachment.sourceFile!.size, 'processing'),
        }).then((uploaded) => {
          input.onAttachmentUploaded?.(uploaded)
          if (!uploaded.documentId)
            throw new ApiError('上传完成后没有返回资料编号。', 502, 'DOCUMENT_ID_MISSING')
          report(attachment.sourceFile!.size, 'ready')
          return { ...uploaded, status: 'ready' as const }
        })
      }),
    )
    const serializedAttachments = attachments.map((attachment) => ({
      id: attachment.id,
      name: attachment.name,
      kind: attachment.kind,
      size: attachment.size,
      url: attachment.url,
      status: attachment.status,
      saveToLibrary: attachment.saveToLibrary,
      assetId: attachment.assetId,
      documentId: attachment.documentId,
    }))
    const intentSignature = JSON.stringify({
      retryOfRunId: input.retryOfRunId ?? null,
      taskId: input.taskId ?? null,
      projectId: input.projectId ?? null,
      text: input.text,
      skillIds: input.skillIds ?? (input.skillId ? [input.skillId] : []),
      modelDeploymentId: input.modelDeploymentId ?? null,
      usePreferences: input.usePreferences,
      attachments: serializedAttachments,
    })
    const clientMessageId = input.clientMessageId ?? requestId('message')
    const runKey = requestId('run')
    const message = {
      text: input.text,
      content: {
        ...(input.retryOfRunId ? { retryOfRunId: input.retryOfRunId } : {}),
        skillIds: input.skillIds ?? (input.skillId ? [input.skillId] : []),
        attachments: serializedAttachments,
        documentIds: attachments
          .map((item) => item.documentId)
          .filter((id): id is string => Boolean(id)),
        links: attachments
          .filter((item) => item.kind === 'link' && item.url)
          .map((item) => item.url!),
      },
      clientMessageId,
      modelDeploymentId: input.modelDeploymentId ?? null,
    } satisfies MessageCreateDto
    let path: PendingMessageCommand['path']
    let body: PendingMessageCommand['body']
    if (input.taskId) {
      await openApiData(
        openApi.PATCH('/api/v1/tasks/{task_id}', {
          signal: input.signal,
          params: { path: { task_id: input.taskId } },
          body: apiBody<'TaskPatch'>({
            currentSkillId: input.skillIds?.[0] ?? input.skillId ?? null,
            usePreferences: input.usePreferences,
          }),
        }),
      )
      path = `/tasks/${input.taskId}/messages`
      body = message
    } else {
      path = '/tasks'
      body = {
        projectId: input.projectId ?? null,
        currentSkillId: input.skillIds?.[0] ?? input.skillId ?? null,
        modelDeploymentId: input.modelDeploymentId ?? null,
        usePreferences: input.usePreferences,
        firstMessage: message,
      } satisfies TaskCreateDto
    }
    const ownerId = readCachedSession()?.user.id
    if (!ownerId) throw new ApiError('登录状态已失效，请重新登录。', 401, 'SESSION_REQUIRED')
    const command = await withCommandLock(`message:${ownerId}`, () => {
      const existing = readPendingMessage(intentSignature)
      if (existing) return existing
      const created: PendingMessageCommand = {
        ownerId,
        path,
        body,
        intentSignature,
        idempotencyKey: runKey,
        createdAt: now(),
        taskId: input.taskId,
      }
      writePendingMessage(created)
      return created
    })
    try {
      const { taskId, runId } = await resolvePendingMessage(command, input)
      const result = { ...(await remoteApi.getTask(taskId)), runId }
      writePendingMessage(null, command.idempotencyKey)
      return result
    } catch (error) {
      if (input.signal?.aborted) {
        command.cancelRequested = true
        writePendingMessage(command)
        void remoteApi.resumePendingMessage().catch(() => undefined)
      } else if (
        error instanceof ApiError &&
        !error.retryable &&
        error.status !== 408 &&
        error.status !== 429 &&
        error.status < 500
      )
        writePendingMessage(null, command.idempotencyKey)
      throw error
    }
  },
  async resumePendingMessage(input = {}) {
    const command = input.pendingKey
      ? readPendingMessages()[input.pendingKey]
      : readPendingMessage()
    if (!command) return null
    if (command.ownerId !== readCachedSession()?.user.id) {
      writePendingMessage(null, command.idempotencyKey)
      return null
    }
    try {
      const { taskId, runId } = await resolvePendingMessage(command, input)
      const result = { ...(await remoteApi.getTask(taskId)), runId }
      writePendingMessage(null, command.idempotencyKey)
      return result
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError' && command.cancelRequested)
        return null
      if (input.signal?.aborted) {
        command.cancelRequested = true
        writePendingMessage(command)
      } else if (
        error instanceof ApiError &&
        !error.retryable &&
        error.status !== 408 &&
        error.status !== 429 &&
        error.status < 500
      )
        writePendingMessage(null, command.idempotencyKey)
      throw error
    }
  },
  hasPendingMessage: () => Boolean(readPendingMessage()),
  getPendingMessage(taskId) {
    const ownerId = readCachedSession()?.user.id
    const command = Object.values(readPendingMessages())
      .filter(
        (item) =>
          item.ownerId === ownerId &&
          !item.cancelRequested &&
          (item.taskId ?? (item.path === '/tasks' ? '' : item.path.slice(7, -9))) === taskId,
      )
      .sort((a, b) => a.createdAt.localeCompare(b.createdAt))[0]
    if (!command) return null
    const body = record(command.body)
    const message = command.path === '/tasks' ? record(body.firstMessage) : body
    const content = record(message.content)
    return {
      key: command.idempotencyKey,
      message: {
        id: `pending_${command.idempotencyKey}`,
        clientMessageId: optionalText(message.clientMessageId),
        taskId,
        role: 'user',
        content: textValue(message.text),
        createdAt: command.createdAt,
        attachments: Array.isArray(content.attachments)
          ? content.attachments.map(mapAttachment)
          : [],
      },
    }
  },
  async cancelRun(id) {
    await openApiData(
      openApi.POST('/api/v1/ai-runs/{run_id}/cancel', { params: { path: { run_id: id } } }),
    )
    const command = Object.values(readPendingMessages()).find((item) => item.runId === id)
    if (command) writePendingMessage(null, command.idempotencyKey)
  },
  updateTask: async (id, patch) =>
    mapTask(
      await openApiData(
        openApi.PATCH('/api/v1/tasks/{task_id}', {
          params: { path: { task_id: id } },
          body: apiBody<'TaskPatch'>(patch),
        }),
      ),
    ),
  deleteTask: async (id) => {
    await openApiData(
      openApi.DELETE('/api/v1/tasks/{task_id}', { params: { path: { task_id: id } } }),
    )
  },
  getArticle: async (id) =>
    mapArticle(
      await openApiData(
        openApi.GET('/api/v1/articles/{article_id}', {
          params: { path: { article_id: id } },
        }),
      ),
    ),
  async saveArticle(input: ArticleSaveInput) {
    if (!input.contentJson)
      throw new ApiError('文章编辑器没有可保存的结构化内容。', 422, 'ARTICLE_CONTENT_REQUIRED')
    const normalizedContent = normalizeTiptapJson(input.contentJson)
    if (!normalizedContent || normalizedContent.type !== 'doc')
      throw new ApiError('文章编辑器内容不是可保存的标准文档。', 422, 'ARTICLE_CONTENT_INVALID')
    // normalizeTiptapJson is the runtime boundary for legacy/editor content. Once it
    // has produced a doc root, serialize it through the generated API contract.
    const content = normalizedContent as ArticleContentUpdateDto['content']
    let body = {
      baseVersionNo: input.baseVersionNo,
      title: input.title,
      summary: input.summary,
      content,
      source: input.reason?.includes('AI') ? ('ai' as const) : ('autosave' as const),
    } satisfies ArticleContentUpdateDto
    const ownerId = readCachedSession()?.user.id
    if (!ownerId) throw new ApiError('登录状态已失效，请重新登录。', 401, 'SESSION_REQUIRED')
    const dispatch = async (command: PendingArticleSaveCommand) => {
      writePendingArticleSave(command)
      try {
        const response = (await openApiData(
          openApi.PUT('/api/v1/articles/{article_id}/content', {
            params: {
              path: { article_id: command.articleId },
              header: { 'Idempotency-Key': command.idempotencyKey },
            },
            body: apiBody<'ArticleContentUpdate'>(command.body),
          }),
        )) as ArticleUpdateResultDto
        writePendingArticleSave(null, command.articleId)
        return mapArticle(response)
      } catch (error) {
        if (
          error instanceof ApiError &&
          !error.retryable &&
          error.status !== 408 &&
          error.status !== 429 &&
          error.status < 500
        )
          writePendingArticleSave(null, command.articleId)
        throw error
      }
    }

    while (true) {
      const command = await withCommandLock(`article-save:${ownerId}:${input.id}`, () => {
        const pending = readPendingArticleSave(input.id)
        if (pending) return pending
        const created: PendingArticleSaveCommand = {
          ownerId,
          articleId: input.id,
          idempotencyKey: requestId('article-save'),
          body,
          createdAt: now(),
        }
        writePendingArticleSave(created)
        return created
      })
      if (JSON.stringify(command.body) === JSON.stringify(body)) return dispatch(command)
      const recovered = await dispatch(command)
      body = { ...body, baseVersionNo: recovered.versionNo }
    }
  },
  async getArticleVersionsPage(id, cursor, limit = 30) {
    const [article, payload] = await Promise.all([
      remoteApi.getArticle(id),
      openApiData(
        openApi.GET('/api/v1/articles/{article_id}/versions', {
          params: { path: { article_id: id }, query: { cursor, limit } },
        }),
      ),
    ])
    return {
      items: itemList(payload).map((version) => mapArticleVersion(version, article.title)),
      nextCursor: nextPageCursor(payload, cursor),
    }
  },
  async restoreArticleVersion(articleId, version) {
    const ownerId = readCachedSession()?.user.id
    if (!ownerId) throw new ApiError('登录状态已失效，请重新登录。', 401, 'SESSION_REQUIRED')
    const dispatch = async (command: PendingArticleRestoreCommand) => {
      writePendingArticleRestore(command)
      try {
        const response = (await openApiData(
          openApi.POST('/api/v1/articles/{article_id}/versions/restore', {
            params: {
              path: { article_id: command.articleId },
              header: { 'Idempotency-Key': command.idempotencyKey },
            },
            body: apiBody<'RestoreVersionRequest'>(command.body),
          }),
        )) as ArticleRestoreResultDto
        writePendingArticleRestore(null, command.articleId)
        return mapArticle(response)
      } catch (error) {
        if (
          error instanceof ApiError &&
          !error.retryable &&
          error.status !== 408 &&
          error.status !== 429 &&
          error.status < 500
        )
          writePendingArticleRestore(null, command.articleId)
        throw error
      }
    }

    const pending = await withCommandLock(`article-restore:${ownerId}:${articleId}`, () =>
      readPendingArticleRestore(articleId),
    )
    if (pending) {
      const recovered = await dispatch(pending)
      if (pending.versionId === version.id) return recovered
    }
    const article = await remoteApi.getArticle(articleId)
    const body = {
      versionNo: version.versionNo,
      baseVersionNo: article.versionNo,
    } satisfies ArticleRestoreDto
    const command = await withCommandLock(`article-restore:${ownerId}:${articleId}`, () => {
      const existing = readPendingArticleRestore(articleId)
      if (existing) return existing
      const created: PendingArticleRestoreCommand = {
        ownerId,
        articleId,
        versionId: version.id,
        idempotencyKey: requestId('article-restore'),
        body,
        createdAt: now(),
      }
      writePendingArticleRestore(created)
      return created
    })
    return dispatch(command)
  },
  proposeArticleRevision: waitForArticleRevision,
  getPendingArticleRevision: readPendingArticleRevision,
  async resumePendingArticleRevision(articleId) {
    const pending = readPendingArticleRevision(articleId)
    return pending ? settleArticleRevision(pending) : null
  },
  async prepareArticleRender(
    articleId,
    accountId,
    templateId,
    coverAssetId = null,
    articleVersionNo,
  ) {
    const versionNo = articleVersionNo ?? (await remoteApi.getArticle(articleId)).versionNo
    const render = record(
      await openApiData(
        openApi.POST('/api/v1/article-renders', {
          body: apiBody<'RenderCreate'>({
            articleId,
            articleVersionNo: versionNo,
            templateId,
            officialAccountId: accountId,
            coverAssetId,
          }),
        }),
      ),
    )
    const renderId = textValue(render.id)
    const html = textValue(render.html)
    if (!renderId || !html.trim())
      throw new ApiError('服务端没有返回可确认的排版版本。', 502, 'ARTICLE_RENDER_INVALID')
    return { renderId, html }
  },
  async downloadArticleRender(renderId, format) {
    const result = await openApi.GET('/api/v1/article-renders/{render_id}/download', {
      params: { path: { render_id: renderId }, query: { format } },
      parseAs: 'blob',
    })
    if (result.error || !result.data)
      throw new Error(textValue(record(result.error).message, '文章导出失败，请稍后重试。'))
    return result.data
  },
  async setArticleOutcome(input: ArticleOutcomeInput) {
    if (input.outcome === 'local_draft') {
      const ownerId = readCachedSession()?.user.id
      if (!ownerId) throw new ApiError('登录状态已失效，请重新登录。', 401, 'SESSION_REQUIRED')
      const command = await withCommandLock(`article-local-save:${ownerId}:${input.id}`, () => {
        const existing = readPendingArticleLocalSave(input.id)
        if (existing) return existing
        const created: PendingArticleLocalSaveCommand = {
          ownerId,
          articleId: input.id,
          idempotencyKey: input.idempotencyKey,
          createdAt: now(),
        }
        writePendingArticleLocalSave(created)
        return created
      })
      try {
        await openApiData(
          openApi.POST('/api/v1/articles/{article_id}/save-local', {
            params: {
              path: { article_id: input.id },
              header: { 'Idempotency-Key': command.idempotencyKey },
            },
          }),
        )
        const article = await remoteApi.getArticle(input.id)
        writePendingArticleLocalSave(null, command.articleId)
        return { ...article, status: 'local_draft', lastOperationStatus: 'succeeded' }
      } catch (error) {
        if (
          error instanceof ApiError &&
          !error.retryable &&
          error.status !== 408 &&
          error.status !== 429 &&
          error.status < 500
        )
          writePendingArticleLocalSave(null, command.articleId)
        throw error
      }
    }
    if (!input.accountId || !input.templateId)
      throw new ApiError('请选择目标公众号和排版模板。', 422, 'WECHAT_TARGET_REQUIRED')
    const existing = readPendingArticleOutcome(input.id)
    if (
      existing &&
      (existing.outcome !== input.outcome ||
        existing.accountId !== input.accountId ||
        existing.templateId !== input.templateId ||
        (input.renderId && existing.renderId !== input.renderId))
    ) {
      throw new ApiError(
        '该文章已有微信操作待确认。为避免重复发布，请先继续查询原操作。',
        409,
        'WECHAT_OPERATION_CONFLICT',
        { operationId: existing.operationId },
      )
    }
    if (existing?.operationId) return settleWechatOperation(existing)

    const ownerId = readCachedSession()?.user.id
    if (!ownerId) throw new ApiError('登录状态已失效，请重新登录。', 401, 'SESSION_REQUIRED')
    const prepared = input.renderId
      ? { renderId: input.renderId }
      : existing
        ? { renderId: existing.renderId }
        : await remoteApi.prepareArticleRender(input.id, input.accountId, input.templateId)
    const pending: PendingArticleOutcome = existing ?? {
      ownerId,
      articleId: input.id,
      outcome: input.outcome,
      accountId: input.accountId,
      templateId: input.templateId,
      renderId: prepared.renderId,
      idempotencyKey: input.idempotencyKey,
      operationStatus: 'queued',
      createdAt: now(),
    }
    writePendingArticleOutcome(pending)
    try {
      await openApiData(
        openApi.POST('/api/v1/article-renders/{render_id}/confirm', {
          params: { path: { render_id: pending.renderId } },
          body: apiBody<'RenderConfirmRequest'>({
            action: pending.outcome === 'publish' ? 'publish' : 'draft',
          }),
        }),
      )
      const operation = record(
        pending.outcome === 'publish'
          ? await openApiData(
              openApi.POST('/api/v1/wechat-publishes', {
                params: { header: { 'Idempotency-Key': pending.idempotencyKey } },
                body: apiBody<'WechatOperationRequest'>({ renderId: pending.renderId }),
              }),
            )
          : await openApiData(
              openApi.POST('/api/v1/wechat-drafts', {
                params: { header: { 'Idempotency-Key': pending.idempotencyKey } },
                body: apiBody<'WechatOperationRequest'>({ renderId: pending.renderId }),
              }),
            ),
      )
      pending.operationId = textValue(operation.id)
      if (!pending.operationId)
        throw new ApiError('微信操作没有返回可查询的编号。', 502, 'WECHAT_OPERATION_ID_MISSING')
      writePendingArticleOutcome(pending)
      return settleWechatOperation(pending, operation)
    } catch (error) {
      if (error instanceof ApiError && error.code === 'WECHAT_OPERATION_ALREADY_PENDING') {
        const details = record(error.details)
        const blockingOperationId = optionalText(details.operationId)
        const blockingStatus = details.status
        if (blockingOperationId) {
          pending.operationId = blockingOperationId
          if (
            blockingStatus === 'queued' ||
            blockingStatus === 'submitting' ||
            blockingStatus === 'reconciling' ||
            blockingStatus === 'unknown'
          )
            pending.operationStatus = blockingStatus
          writePendingArticleOutcome(pending)
        } else {
          await remoteApi.refreshPendingArticleOutcome(pending.articleId).catch(() => undefined)
        }
        throw new ApiError(
          '服务端已有同一篇文章的微信操作正在处理。已找回原操作，请查询原结果，不会重复提交。',
          409,
          error.code,
          error.details,
          true,
          error.requestId,
        )
      }
      if (
        error instanceof ApiError &&
        !error.retryable &&
        error.status !== 408 &&
        error.status !== 429 &&
        error.status < 500 &&
        !pending.operationId
      )
        writePendingArticleOutcome(null, pending.articleId)
      throw error
    }
  },
  getPendingArticleOutcome: readPendingArticleOutcome,
  async refreshPendingArticleOutcome(articleId) {
    const local = readPendingArticleOutcome(articleId)
    const operationType = local ? (local.outcome === 'publish' ? 'publish' : 'draft') : undefined
    const response = (await openApiData(
      openApi.GET('/api/v1/articles/{article_id}/wechat-operation', {
        params: { path: { article_id: articleId }, query: { operation_type: operationType } },
      }),
    )) as CurrentWechatOperationDto
    const operation = response.operation
    if (!operation) return local
    const status = operation.status
    if (
      status !== 'queued' &&
      status !== 'submitting' &&
      status !== 'reconciling' &&
      status !== 'unknown'
    )
      return local
    const ownerId = readCachedSession()?.user.id
    if (!ownerId) return null
    const pending: PendingArticleOutcome = {
      ownerId,
      articleId,
      outcome: operation.operationType === 'publish' ? 'publish' : 'wechat_draft',
      accountId: operation.officialAccountId,
      templateId: local?.templateId ?? '',
      renderId: operation.renderId,
      idempotencyKey: operation.idempotencyKey,
      operationId: operation.id,
      operationStatus: status,
      createdAt: operation.createdAt,
    }
    writePendingArticleOutcome(pending)
    return pending
  },
  async resumePendingArticleOutcome(articleId) {
    const pending = await remoteApi.refreshPendingArticleOutcome(articleId)
    if (!pending) return null
    if (pending.operationId) return settleWechatOperation(pending)
    return remoteApi.setArticleOutcome({
      id: pending.articleId,
      outcome: pending.outcome,
      accountId: pending.accountId,
      templateId: pending.templateId,
      renderId: pending.renderId,
      idempotencyKey: pending.idempotencyKey,
    })
  },
  async listLibraryItemsPage(
    filters: LibraryFilters = {},
    cursor?: string,
    limit = 50,
  ): Promise<LibraryPage> {
    const payload = await openApiData(
      openApi.GET('/api/v1/library-items', {
        params: {
          query: {
            query: filters.search?.trim() || undefined,
            project_id: filters.projectId === 'all' ? undefined : filters.projectId,
            item_type:
              filters.type === 'article'
                ? 'article'
                : filters.type === 'reference'
                  ? 'document'
                  : undefined,
            cursor,
            limit,
          },
        },
      }),
    )
    return {
      items: itemList(payload).map(mapLibraryItem),
      nextCursor: nextPageCursor(payload, cursor),
    }
  },
  getLibraryItem: async (id) =>
    mapLibraryItemDetail(
      await openApiData(
        openApi.GET('/api/v1/library-items/{item_id}', {
          params: { path: { item_id: id } },
        }),
      ),
    ),
  async downloadDocument(id) {
    const response = await authenticatedFetch(
      new Request(`${baseUrl}/documents/${encodeURIComponent(id)}/content`, {
        headers: { Accept: 'application/octet-stream' },
      }),
    )
    if (!response.ok) throw await responseError(response)
    return response.blob()
  },
  updateLibraryItemTitle: async (id, title) =>
    mapLibraryItem(
      await openApiData(
        openApi.PATCH('/api/v1/library-items/{item_id}', {
          params: { path: { item_id: id } },
          body: apiBody<'LibraryItemPatch'>({ title }),
        }),
      ),
    ),
  deleteLibraryItem: async (id) => {
    await openApiData(
      openApi.DELETE('/api/v1/library-items/{item_id}', { params: { path: { item_id: id } } }),
    )
  },
  async reparseDocument(id) {
    await openApiData(
      openApi.POST('/api/v1/documents/{document_id}/reparse', {
        params: { path: { document_id: id } },
      }),
    )
    await waitForDocument(id)
  },
  async listSkillsPage(cursor, limit = 50, query) {
    const payload = await openApiData(
      openApi.GET('/api/v1/skills', { params: { query: { cursor, limit, query } } }),
    )
    return { items: itemList(payload).map(mapSkill), nextCursor: nextPageCursor(payload, cursor) }
  },
  async getSkill(id) {
    return mapSkill(
      await openApiData(
        openApi.GET('/api/v1/skills/{skill_id}', { params: { path: { skill_id: id } } }),
      ),
    )
  },
  async saveSkill(input: SkillInput) {
    const payload = {
      name: input.name,
      description: input.scenes,
      category: 'content',
      scenario: input.scenes,
      instructions: input.requirements,
      exampleArticle: input.examples.join('\n\n') || null,
    }
    const response = input.id
      ? await openApiData(
          openApi.PATCH('/api/v1/skills/{skill_id}', {
            params: { path: { skill_id: input.id } },
            body: apiBody<'PersonalSkillPatch'>(payload),
          }),
        )
      : await openApiData(
          openApi.POST('/api/v1/skills', { body: apiBody<'PersonalSkillCreate'>(payload) }),
        )
    const mapped = mapSkill(response)
    return input.id ? { ...mapped, enabled: (await getDetailedSkill(input.id)).enabled } : mapped
  },
  async setSkillEnabled(id, enabled) {
    await openApiData(
      openApi.PATCH('/api/v1/skills/{skill_id}/setting', {
        params: { path: { skill_id: id } },
        body: apiBody<'SkillSettingPatch'>({ enabled }),
      }),
    )
    return { ...(await getDetailedSkill(id)), enabled }
  },
  deleteSkill: async (id) => {
    await openApiData(
      openApi.DELETE('/api/v1/skills/{skill_id}', { params: { path: { skill_id: id } } }),
    )
  },
  async listOfficialAccountsPage(cursor, limit = 50) {
    const payload = await openApiData(
      openApi.GET('/api/v1/official-accounts', { params: { query: { cursor, limit } } }),
    )
    return {
      items: itemList(payload).map(mapOfficialAccount),
      nextCursor: nextPageCursor(payload, cursor),
    }
  },
  getOfficialAccount: async (id) =>
    mapOfficialAccount(
      await openApiData(
        openApi.GET('/api/v1/official-accounts/{account_id}', {
          params: { path: { account_id: id } },
        }),
      ),
    ),
  async createOfficialAccountAuthorization(redirectUri): Promise<OfficialAccountAuthorization> {
    const response = record(
      await openApiData(
        openApi.POST('/api/v1/official-accounts/authorize-url', {
          body: apiBody<'AuthorizationUrlRequest'>({ redirectUri }),
        }),
      ),
    )
    return {
      authorizationUrl: textValue(response.authorizationUrl),
      expiresIn: numberValue(response.expiresIn, 300),
    }
  },
  async completeOfficialAccountAuthorization(accountId, previousAccountIds = []) {
    if (accountId) {
      try {
        const account = await remoteApi.getOfficialAccount(accountId)
        return account.status === 'connected' ? account : null
      } catch {
        return null
      }
    }
    const accounts = (await remoteApi.listOfficialAccountsPage(undefined, 100)).items
    return (
      accounts.find(
        (account) => account.status === 'connected' && !previousAccountIds.includes(account.id),
      ) ?? null
    )
  },
  disconnectOfficialAccount: async (id) => {
    await openApiData(
      openApi.DELETE('/api/v1/official-accounts/{account_id}', {
        params: { path: { account_id: id } },
      }),
    )
  },
  async listTemplatesPage(accountId, cursor, limit = 50) {
    const query =
      typeof accountId === 'string' && accountId
        ? { official_account_id: accountId, cursor, limit }
        : { cursor, limit }
    const payload = await openApiData(
      openApi.GET('/api/v1/layout-templates', {
        params: { query },
      }),
    )
    return {
      items: itemList(payload).map(mapTemplate),
      nextCursor: nextPageCursor(payload, cursor),
    }
  },
  async extractTemplate(accountId, url) {
    const response = await openApiData(
      openApi.POST('/api/v1/layout-templates/extract', {
        body: apiBody<'LayoutExtractRequest'>({
          sourceUrl: url,
          officialAccountId: accountId,
          name: '提取的新模板',
          saveTemplate: true,
        }),
      }),
    )
    const payload = record(response)
    const providerStatus = textValue(payload.providerStatus)
    if (providerStatus === 'failed') {
      throw new ApiError(
        textValue(payload.message, '模板提取失败，请检查链接。'),
        409,
        'LAYOUT_PROVIDER_FAILED',
      )
    }
    const template = mapTemplate(response)
    if (template.status === 'failed') {
      throw new ApiError(
        textValue(payload.message, '模板提取失败，请检查链接。'),
        409,
        'LAYOUT_PROVIDER_FAILED',
      )
    }
    return template
  },
  async saveTemplate(template: LayoutTemplate) {
    const creating = template.id.startsWith('template_')
    const shared = {
      name: template.name,
      enabled: template.enabled,
      styleTokens: stylesToTokens(template.styles),
    }
    const payload = creating
      ? ({ ...shared, officialAccountId: template.accountId } satisfies LayoutTemplateCreateDto)
      : (shared satisfies LayoutTemplatePatchDto)
    const response = creating
      ? await openApiData(
          openApi.POST('/api/v1/layout-templates', {
            body: apiBody<'LayoutTemplateCreate'>(payload as LayoutTemplateCreateDto),
          }),
        )
      : await openApiData(
          openApi.PATCH('/api/v1/layout-templates/{template_id}', {
            params: { path: { template_id: template.id } },
            body: apiBody<'LayoutTemplatePatch'>(payload as LayoutTemplatePatchDto),
          }),
        )
    return mapTemplate(response)
  },
  deleteTemplate: async (id) => {
    await openApiData(
      openApi.DELETE('/api/v1/layout-templates/{template_id}', {
        params: { path: { template_id: id } },
      }),
    )
  },
  async listPreferencesPage(cursor, limit = 50) {
    const payload = await openApiData(
      openApi.GET('/api/v1/preferences', { params: { query: { cursor, limit } } }),
    )
    return {
      items: itemList(payload).map(mapPreference),
      nextCursor: nextPageCursor(payload, cursor),
    }
  },
  async savePreference(value, id, status = 'confirmed') {
    return mapPreference(
      id
        ? await openApiData(
            openApi.PATCH('/api/v1/preferences/{preference_id}', {
              params: { path: { preference_id: id } },
              body: apiBody<'PreferencePatch'>({ value, status }),
            }),
          )
        : await openApiData(
            openApi.POST('/api/v1/preferences', {
              body: apiBody<'PreferenceCreate'>({
                preferenceType: 'writing_style',
                value,
                scope: 'personal',
                confidence: 1,
              }),
            }),
          ),
    )
  },
  confirmPreference: async (id) =>
    mapPreference(
      await openApiData(
        openApi.PATCH('/api/v1/preferences/{preference_id}', {
          params: { path: { preference_id: id } },
          body: apiBody<'PreferencePatch'>({ status: 'confirmed' }),
        }),
      ),
    ),
  deletePreference: async (id) => {
    await openApiData(
      openApi.DELETE('/api/v1/preferences/{preference_id}', {
        params: { path: { preference_id: id } },
      }),
    )
  },
  async updateThemePreference(themePreference: ThemePreference) {
    const body = { themePreference } satisfies MePatchDto
    await openApiData(openApi.PATCH('/api/v1/me', { body: apiBody<'MePatch'>(body) }))
    return remoteApi.getMe()
  },
  async listModelOptions() {
    const payload = await openApiData(openApi.GET('/api/v1/model-options'))
    return itemList(payload).map(mapModelOption)
  },
}

export const api: UserApi = remoteApi

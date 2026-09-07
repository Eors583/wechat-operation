import createClient from 'openapi-fetch'
import type { paths } from './generated/schema'
import type { ApiErrorBody } from './contracts'

export class AdminApiError extends Error {
  constructor(
    public readonly body: ApiErrorBody,
    public readonly status: number,
  ) {
    super(body.message)
    this.name = 'AdminApiError'
  }
}

const baseUrl = new URL(
  import.meta.env.VITE_ADMIN_API_BASE ?? '/admin-api/v1',
  window.location.origin,
).href
  .replace(/\/admin-api\/v1\/?$/, '')
  .replace(/\/$/, '')
const accessTokenKey = 'admin-access-token'

export const readAdminAccessToken = () => sessionStorage.getItem(accessTokenKey)
export const setAdminAccessToken = (token?: string | null) => {
  if (token) sessionStorage.setItem(accessTokenKey, token)
  else sessionStorage.removeItem(accessTokenKey)
}

const cookieValue = (name: string) =>
  document.cookie
    .split(';')
    .map((entry) => entry.trim())
    .find((entry) => entry.startsWith(`${name}=`))
    ?.slice(name.length + 1)

export const adminCsrfToken = () =>
  decodeURIComponent(cookieValue('admin_csrf') ?? sessionStorage.getItem('admin_csrf') ?? '')

let refreshPromise: Promise<boolean> | null = null
let sessionExpiredHandler: (() => void) | null = null

export const setAdminSessionExpiredHandler = (handler: (() => void) | null) => {
  sessionExpiredHandler = handler
}

const isAuthenticationRequest = (url: string) =>
  ['/admin-api/v1/auth/login', '/admin-api/v1/auth/refresh', '/admin-api/v1/auth/logout'].some(
    (path) => new URL(url, window.location.origin).pathname.endsWith(path),
  )

async function refreshAdminSession(): Promise<boolean> {
  if (refreshPromise) return refreshPromise
  refreshPromise = (async () => {
    const csrf = adminCsrfToken()
    if (!csrf) return false
    try {
      const refreshUrl = new URL(`${baseUrl}/admin-api/v1/auth/refresh`, window.location.origin)
      const response = await globalThis.fetch(refreshUrl, {
        method: 'POST',
        credentials: 'include',
        headers: { 'X-CSRF-Token': csrf },
      })
      if (!response.ok) return false
      const body = (await response.json()) as { access_token?: unknown }
      if (typeof body.access_token !== 'string' || !body.access_token) return false
      setAdminAccessToken(body.access_token)
      return true
    } catch {
      return false
    }
  })().finally(() => {
    refreshPromise = null
  })
  return refreshPromise
}

export async function adminSessionFetch(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  const request = new Request(input, { ...init, credentials: 'include' })
  const replay = request.clone()
  const response = await globalThis.fetch(request)
  if (response.status !== 401 || isAuthenticationRequest(request.url) || !readAdminAccessToken()) {
    return response
  }
  if (!(await refreshAdminSession())) {
    setAdminAccessToken(null)
    sessionExpiredHandler?.()
    return response
  }
  const headers = new Headers(replay.headers)
  headers.set('Authorization', `Bearer ${readAdminAccessToken() ?? ''}`)
  return globalThis.fetch(new Request(replay, { headers, credentials: 'include' }))
}

export const adminOpenApi = createClient<paths>({
  baseUrl,
  credentials: 'include',
  fetch: adminSessionFetch,
})

adminOpenApi.use({
  async onRequest({ request }) {
    const token = readAdminAccessToken()
    if (token) request.headers.set('Authorization', `Bearer ${token}`)
    if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method)) {
      const csrf = adminCsrfToken()
      if (csrf) request.headers.set('X-CSRF-Token', decodeURIComponent(csrf))
    }
    return request
  },
})

type OpenApiResult<T> = { data?: T; error?: unknown; response: Response }

const fallbackError = (response: Response): ApiErrorBody => ({
  code: 'HTTP_ERROR',
  message: `请求失败（${response.status}）`,
  request_id: response.headers.get('x-request-id') ?? 'unknown',
  retryable: response.status >= 500,
})

export async function adminOpenApiData<T>(request: Promise<OpenApiResult<T>>): Promise<T> {
  const result = await request
  if (result.error !== undefined || !result.response.ok) {
    const candidate =
      result.error && typeof result.error === 'object'
        ? (result.error as Partial<ApiErrorBody>)
        : {}
    const fallback = fallbackError(result.response)
    throw new AdminApiError(
      {
        code: candidate.code ?? fallback.code,
        message: candidate.message ?? fallback.message,
        request_id: candidate.request_id ?? fallback.request_id,
        retryable: candidate.retryable ?? fallback.retryable,
        ...(candidate.details ? { details: candidate.details } : {}),
      },
      result.response.status,
    )
  }
  return result.data as T
}

export const requestId = (prefix: string) => `${prefix}_${crypto.randomUUID()}`

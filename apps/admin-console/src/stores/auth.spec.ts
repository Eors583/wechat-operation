import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from './auth'

const loginResponse = () =>
  new Response(
    JSON.stringify({
      access_token: 'real-api-token',
      refresh_token: null,
      expires_in: 900,
      admin: { id: 'admin-1', username: 'admin', permissions: ['*'] },
    }),
    { status: 200, headers: { 'content-type': 'application/json' } },
  )

describe('admin authentication through the real API client', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    sessionStorage.clear()
    vi.restoreAllMocks()
  })

  it('stores the administrator returned by the login endpoint', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(loginResponse())
    const auth = useAuthStore()

    const result = await auth.submitPassword({ username: 'admin', password: 'server-password' })

    expect(result).toEqual({ ok: true })
    const request = fetchMock.mock.calls[0]?.[0] as Request
    expect(request.url).toBe(`${window.location.origin}/admin-api/v1/auth/login`)
    expect(auth.isAuthenticated).toBe(true)
    expect(JSON.parse(sessionStorage.getItem('admin-auth-session') ?? '{}').username).toBe('admin')
    expect(sessionStorage.getItem('admin-access-token')).toBe('real-api-token')
  })

  it('shows the structured error returned by the login endpoint', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          code: 'INVALID_ADMIN_CREDENTIALS',
          message: '管理员账号或密码不正确。',
          request_id: 'req-login-test',
          retryable: false,
        }),
        { status: 401, headers: { 'content-type': 'application/json' } },
      ),
    )
    const auth = useAuthStore()

    await expect(
      auth.submitPassword({ username: 'admin', password: 'wrong-password' }),
    ).resolves.toEqual({ ok: false, message: '管理员账号或密码不正确。' })
    expect(auth.isAuthenticated).toBe(false)
  })

  it('calls logout and clears the local management session', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(loginResponse())
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
    const auth = useAuthStore()
    await auth.submitPassword({ username: 'admin', password: 'server-password' })

    await auth.logout()

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(auth.isAuthenticated).toBe(false)
    expect(sessionStorage.getItem('admin-auth-session')).toBeNull()
    expect(sessionStorage.getItem('admin-access-token')).toBeNull()
  })
})

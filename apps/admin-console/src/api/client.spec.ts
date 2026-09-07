import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  adminCsrfToken,
  adminSessionFetch,
  readAdminAccessToken,
  setAdminAccessToken,
  setAdminSessionExpiredHandler,
} from './client'

describe('administrator access-token refresh', () => {
  beforeEach(() => {
    sessionStorage.clear()
    document.cookie = 'admin_csrf=csrf-test; path=/'
    setAdminSessionExpiredHandler(null)
    vi.restoreAllMocks()
  })

  it('coalesces concurrent refreshes and replays each request with the new token', async () => {
    setAdminAccessToken('expired-token')
    expect(adminCsrfToken()).toBe('csrf-test')
    expect(readAdminAccessToken()).toBe('expired-token')
    let refreshCount = 0
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const request = input instanceof Request ? input : new Request(input)
      if (request.url.endsWith('/admin-api/v1/auth/refresh')) {
        refreshCount += 1
        await Promise.resolve()
        return Response.json({ access_token: 'fresh-token' })
      }
      if (request.headers.get('Authorization') === 'Bearer fresh-token') {
        return Response.json({ ok: true })
      }
      return Response.json({ code: 'INVALID_ADMIN_SESSION' }, { status: 401 })
    })

    const responses = await Promise.all([
      adminSessionFetch(
        new Request('http://localhost/admin-api/v1/dashboard', {
          headers: { Authorization: 'Bearer expired-token' },
        }),
      ),
      adminSessionFetch(
        new Request('http://localhost/admin-api/v1/users', {
          headers: { Authorization: 'Bearer expired-token' },
        }),
      ),
    ])

    expect(refreshCount).toBe(1)
    expect(responses.map((response) => response.status)).toEqual([200, 200])
    expect(readAdminAccessToken()).toBe('fresh-token')
    expect(fetchMock).toHaveBeenCalledTimes(5)
  })

  it('clears local access and signals expiry when refresh fails', async () => {
    setAdminAccessToken('expired-token')
    const expired = vi.fn()
    setAdminSessionExpiredHandler(expired)
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      Response.json({ code: 'INVALID_ADMIN_SESSION' }, { status: 401 }),
    )

    const response = await adminSessionFetch(
      new Request('http://localhost/admin-api/v1/dashboard', {
        headers: { Authorization: 'Bearer expired-token' },
      }),
    )

    expect(response.status).toBe(401)
    expect(readAdminAccessToken()).toBeNull()
    expect(expired).toHaveBeenCalledOnce()
  })
})

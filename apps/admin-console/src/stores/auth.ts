import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  adminCsrfToken,
  adminOpenApi,
  adminOpenApiData,
  setAdminAccessToken,
  setAdminSessionExpiredHandler,
} from '@/api/client'
import type { AdminIdentity } from '@/api/contracts'

type LoginResult = { ok: true } | { ok: false; message: string }

const sessionKey = 'admin-auth-session'

function cachedAdminIdentity(): AdminIdentity | null {
  const cached = sessionStorage.getItem(sessionKey)
  if (!cached) return null
  try {
    const value = JSON.parse(cached) as Partial<AdminIdentity>
    if (
      typeof value.id === 'string' &&
      typeof value.username === 'string' &&
      Array.isArray(value.permissions)
    ) {
      return value as AdminIdentity
    }
  } catch {
    // Invalid or legacy production cache entries must never prevent the login page from loading.
  }
  sessionStorage.removeItem(sessionKey)
  return null
}

export const useAuthStore = defineStore('auth', () => {
  const identity = ref<AdminIdentity | null>(cachedAdminIdentity())
  const isAuthenticated = computed(() => identity.value !== null)

  function clearLocalSession(): void {
    identity.value = null
    sessionStorage.removeItem(sessionKey)
    sessionStorage.removeItem('admin_csrf')
    setAdminAccessToken(null)
  }

  setAdminSessionExpiredHandler(clearLocalSession)

  async function submitPassword(input: {
    username: string
    password: string
  }): Promise<LoginResult> {
    try {
      const response = await adminOpenApiData(
        adminOpenApi.POST('/admin-api/v1/auth/login', {
          body: {
            username: input.username,
            password: input.password,
            device_name: navigator.userAgent.slice(0, 120),
          },
        }),
      )
      setAdminAccessToken(response.access_token)
      identity.value = {
        id: response.admin.id,
        username: response.admin.username,
        display_name: response.admin.username,
        role: response.admin.permissions.includes('*') ? 'super_admin' : 'operations',
        permissions: [...response.admin.permissions],
        last_login_at: new Date().toISOString(),
      }
      sessionStorage.setItem(sessionKey, JSON.stringify(identity.value))
      return { ok: true }
    } catch (error) {
      return { ok: false, message: error instanceof Error ? error.message : '管理员登录失败。' }
    }
  }

  async function logout(): Promise<void> {
    if (identity.value) {
      try {
        await adminOpenApiData(
          adminOpenApi.POST('/admin-api/v1/auth/logout', {
            params: { header: { 'X-CSRF-Token': adminCsrfToken() } },
          }),
        )
      } catch {
        // The local administrator session must still be cleared.
      }
    }
    clearLocalSession()
  }

  async function hydrate(): Promise<void> {
    if (!identity.value) return
    try {
      const current = await adminOpenApiData(adminOpenApi.GET('/admin-api/v1/me'))
      identity.value = {
        ...identity.value,
        id: current.id,
        username: current.username,
        display_name: current.username,
        permissions: [...current.permissions],
        role: current.permissions.includes('*') ? 'super_admin' : 'operations',
      }
      sessionStorage.setItem(sessionKey, JSON.stringify(identity.value))
    } catch {
      await logout()
    }
  }

  return {
    identity,
    isAuthenticated,
    submitPassword,
    logout,
    hydrate,
  }
})

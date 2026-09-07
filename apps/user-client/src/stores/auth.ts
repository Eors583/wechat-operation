import { defineStore } from 'pinia'
import { api, clearUserClientData } from '@/api/client'
import type { Session } from '@/api/types'
import { queryClient } from '@/boot/query'
import { platform } from '@/platform'
import { useThemeStore } from '@/stores/theme'

const cacheKey = 'wechat-ai-user-client-auth'
const logoutPendingKey = 'wechat-ai-user-client-logout-pending'
const sessionCacheTtlMs = 7 * 24 * 60 * 60 * 1000
type CachedSession = Session & { expiresAt?: number }

const readSession = (): Session | null => {
  const raw = localStorage.getItem(cacheKey) ?? sessionStorage.getItem(cacheKey)
  if (!raw) return null
  const session = JSON.parse(raw) as CachedSession
  if (session.expiresAt && session.expiresAt <= Date.now()) {
    localStorage.removeItem(cacheKey)
    sessionStorage.removeItem(cacheKey)
    return null
  }
  return {
    user: session.user,
    accessToken: session.accessToken,
    refreshToken: session.refreshToken,
  }
}

export const useAuthStore = defineStore('auth', {
  state: () => ({ session: readSession() as Session | null, loading: false }),
  getters: {
    isAuthenticated: (state) => Boolean(state.session),
    user: (state) => state.session?.user ?? null,
  },
  actions: {
    persist() {
      if (this.session) {
        const cached: CachedSession = {
          ...(platform.native ? { ...this.session, refreshToken: undefined } : this.session),
          expiresAt: Date.now() + sessionCacheTtlMs,
        }
        localStorage.setItem(cacheKey, JSON.stringify(cached))
        sessionStorage.removeItem(cacheKey)
      } else {
        localStorage.removeItem(cacheKey)
        sessionStorage.removeItem(cacheKey)
      }
    },
    async login(identifier: string, password: string) {
      this.loading = true
      try {
        this.session = await api.login(identifier, password)
        useThemeStore().syncFromServer(this.session.user.themePreference)
        localStorage.removeItem(logoutPendingKey)
        this.persist()
      } finally {
        this.loading = false
      }
    },
    async loginWithCode(identifier: string, challengeId: string, code: string) {
      this.loading = true
      try {
        this.session = await api.loginWithCode(identifier, challengeId, code)
        useThemeStore().syncFromServer(this.session.user.themePreference)
        localStorage.removeItem(logoutPendingKey)
        this.persist()
      } finally {
        this.loading = false
      }
    },
    requestVerificationCode(destination: string, purpose: 'register' | 'login' | 'reset_password') {
      return api.requestVerificationCode(destination, purpose)
    },
    async register(phone: string, challengeId: string, code: string, password: string) {
      this.loading = true
      try {
        this.session = await api.register(phone, challengeId, code, password)
        useThemeStore().syncFromServer(this.session.user.themePreference)
        localStorage.removeItem(logoutPendingKey)
        this.persist()
      } finally {
        this.loading = false
      }
    },
    async hydrate() {
      if (localStorage.getItem(logoutPendingKey)) {
        this.session = null
        this.persist()
        try {
          await api.logout()
          localStorage.removeItem(logoutPendingKey)
        } catch {
          // Keep the tombstone and native credential for a later server revocation retry.
        }
        return
      }
      try {
        const user = await api.getMe()
        const refreshed = readSession()
        this.session = refreshed ? { ...refreshed, user } : { user, accessToken: '' }
        useThemeStore().syncFromServer(user.themePreference)
        this.persist()
      } catch {
        this.session = null
        this.persist()
      }
    },
    async refreshUser() {
      if (!this.session) return
      const user = await api.getMe()
      this.session = { ...this.session, user }
      this.persist()
      useThemeStore().syncFromServer(user.themePreference)
    },
    async logout() {
      let revoked = false
      const ownerId = this.session?.user.id
      try {
        await api.logout()
        revoked = true
      } finally {
        if (revoked) localStorage.removeItem(logoutPendingKey)
        else localStorage.setItem(logoutPendingKey, '1')
        clearUserClientData(ownerId)
        queryClient.clear()
        this.session = null
        this.persist()
      }
    },
    async deleteAccount(password: string) {
      const receipt = await api.deleteAccount(password, '注销账号')
      clearUserClientData(this.session?.user.id)
      queryClient.clear()
      this.session = null
      this.persist()
      return receipt
    },
  },
})

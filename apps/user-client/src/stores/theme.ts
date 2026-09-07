import { Dark } from 'quasar'
import { defineStore } from 'pinia'
import { api } from '@/api/client'
import type { ThemePreference } from '@/api/types'

const key = 'wechat-ai-theme-preference'

export const useThemeStore = defineStore('theme', {
  state: () => ({
    preference: (localStorage.getItem(key) as ThemePreference | null) ?? 'system',
    media: null as MediaQueryList | null,
  }),
  actions: {
    apply() {
      Dark.set(
        this.preference === 'system' ? (this.media?.matches ?? false) : this.preference === 'dark',
      )
      document.documentElement.dataset.theme = this.preference
    },
    initialize() {
      this.media = window.matchMedia('(prefers-color-scheme: dark)')
      this.media.addEventListener('change', () => {
        if (this.preference === 'system') this.apply()
      })
      this.apply()
    },
    syncFromServer(preference: ThemePreference) {
      this.preference = preference
      localStorage.setItem(key, preference)
      this.apply()
    },
    async setPreference(preference: ThemePreference) {
      const previous = this.preference
      this.preference = preference
      localStorage.setItem(key, preference)
      this.apply()
      try {
        await api.updateThemePreference(preference)
      } catch (error) {
        this.preference = previous
        localStorage.setItem(key, previous)
        this.apply()
        throw error
      }
    },
  },
})

import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { ThemePreference } from '@/api/contracts'

const storageKey = 'admin-theme'

export const usePreferencesStore = defineStore('preferences', () => {
  const theme = ref<ThemePreference>(
    (localStorage.getItem(storageKey) as ThemePreference | null) ?? 'system',
  )

  function applyTheme(): void {
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches
    const isDark = theme.value === 'dark' || (theme.value === 'system' && prefersDark)
    document.documentElement.dataset.theme = isDark ? 'dark' : 'light'
    document.documentElement.classList.toggle('dark', isDark)
    localStorage.setItem(storageKey, theme.value)
  }

  function setTheme(value: ThemePreference): void {
    theme.value = value
    applyTheme()
  }

  return { theme, applyTheme, setTheme }
})

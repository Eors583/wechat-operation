import { defineBoot } from '#q-app'
import { useThemeStore } from '@/stores/theme'

export default defineBoot(() => {
  useThemeStore().initialize()
})

import { computed } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { api } from '@/api/client'
import { createDefaultPublicSettings } from '@/api/types'

const defaults = createDefaultPublicSettings()

export const usePublicSettings = () => {
  const query = useQuery({ queryKey: ['public-settings'], queryFn: api.getPublicSettings })
  const settings = computed(() => query.data.value ?? defaults)
  return { query, settings }
}

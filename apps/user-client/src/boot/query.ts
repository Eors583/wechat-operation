import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { defineBoot } from '#q-app'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, retry: 1, refetchOnWindowFocus: false },
    mutations: { retry: false },
  },
})

export default defineBoot(({ app }) => {
  app.use(VueQueryPlugin, { queryClient })
})

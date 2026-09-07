import { createRouter, createWebHashHistory, createWebHistory } from 'vue-router'
import { defineRouter } from '#q-app'
import { useAuthStore } from '@/stores/auth'
import { routes } from './routes'

export default defineRouter(() => {
  const history =
    import.meta.env.QUASAR_VUE_ROUTER_MODE === 'hash' ? createWebHashHistory : createWebHistory
  const router = createRouter({
    history: history(import.meta.env.QUASAR_VUE_ROUTER_BASE),
    routes,
    scrollBehavior: () => ({ top: 0 }),
  })
  router.beforeEach(async (to) => {
    const auth = useAuthStore()
    if (!auth.isAuthenticated) await auth.hydrate()
    if (!to.meta.public && !auth.isAuthenticated)
      return { name: 'login', query: { redirect: to.fullPath } }
    if (to.meta.public && auth.isAuthenticated) return { name: 'create' }
    return true
  })
  return router
})

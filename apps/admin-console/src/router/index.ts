import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

export const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  scrollBehavior: () => ({ top: 0 }),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/pages/LoginPage.vue'),
      meta: { public: true },
    },
    {
      path: '/',
      component: () => import('@/layouts/AdminLayout.vue'),
      children: [
        { path: '', name: 'dashboard', component: () => import('@/pages/DashboardPage.vue') },
        {
          path: 'ai/config',
          name: 'ai-config',
          component: () => import('@/pages/ai/AiConfigPage.vue'),
        },
        {
          path: 'ai/prompts',
          name: 'prompts',
          component: () => import('@/pages/ai/PromptPage.vue'),
        },
        {
          path: 'skills',
          name: 'skills',
          component: () => import('@/pages/skills/SkillsPage.vue'),
        },
        { path: 'users', name: 'users', component: () => import('@/pages/users/UsersPage.vue') },
        {
          path: 'wechat/platform',
          name: 'wechat-platform',
          component: () => import('@/pages/wechat/WechatPlatformPage.vue'),
        },
        {
          path: 'wechat/accounts',
          name: 'wechat-accounts',
          component: () => import('@/pages/wechat/AccountsPage.vue'),
        },
        { path: 'tasks', name: 'tasks', component: () => import('@/pages/tasks/TasksPage.vue') },
        {
          path: 'settings',
          name: 'settings',
          component: () => import('@/pages/settings/SystemSettingsPage.vue'),
        },
        {
          path: 'settings/external-knowledge',
          name: 'external-knowledge',
          component: () => import('@/pages/settings/ExternalKnowledgePage.vue'),
        },
        {
          path: 'settings/wechat-article-apis',
          name: 'wechat-article-apis',
          component: () => import('@/pages/settings/WechatArticleApisPage.vue'),
        },
        {
          path: 'settings/admins',
          name: 'admins',
          component: () => import('@/pages/settings/AdminAccountsPage.vue'),
        },
        {
          path: 'settings/audit',
          name: 'audit',
          component: () => import('@/pages/settings/AuditPage.vue'),
        },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (!to.meta.public && !auth.isAuthenticated)
    return { name: 'login', query: { redirect: to.fullPath } }
  if (to.name === 'login' && auth.isAuthenticated) return { name: 'dashboard' }
  return true
})

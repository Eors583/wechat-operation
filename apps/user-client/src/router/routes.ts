import type { RouteRecordRaw } from 'vue-router'

export const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/pages/auth/LoginPage.vue'),
    meta: { public: true },
  },
  {
    path: '/register',
    name: 'register',
    component: () => import('@/pages/auth/RegisterPage.vue'),
    meta: { public: true },
  },
  {
    path: '/legal/:document(terms|privacy|ai)',
    name: 'legal',
    component: () => import('@/pages/LegalPage.vue'),
    meta: { public: true },
  },
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    children: [
      { path: '', redirect: '/create' },
      { path: 'create', name: 'create', component: () => import('@/pages/CreatePage.vue') },
      { path: 'tasks/:id', name: 'task', component: () => import('@/pages/CreatePage.vue') },
      { path: 'articles', name: 'library', component: () => import('@/pages/LibraryPage.vue') },
      {
        path: 'articles/:id/edit',
        name: 'article',
        component: () => import('@/pages/ArticlePage.vue'),
      },
      { path: 'skills', name: 'skills', component: () => import('@/pages/SkillsPage.vue') },
      {
        path: 'official-accounts',
        name: 'accounts',
        component: () => import('@/pages/AccountsPage.vue'),
      },
      { path: 'settings', name: 'settings', component: () => import('@/pages/SettingsPage.vue') },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/create' },
]

import { createRouter, createWebHashHistory } from 'vue-router'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/pages/LoginPage.vue'),
      meta: { public: true, layout: 'blank' },
    },
    { path: '/', redirect: '/dashboard' },
    {
      path: '/dashboard',
      name: 'dashboard',
      component: () => import('@/pages/DashboardPage.vue'),
    },
    {
      path: '/servers',
      name: 'servers',
      component: () => import('@/pages/ServersPage.vue'),
    },
    {
      path: '/users',
      name: 'users',
      component: () => import('@/pages/UsersPage.vue'),
    },
    {
      path: '/activity-logs',
      name: 'activity-logs',
      component: () => import('@/pages/ActivityLogsPage.vue'),
    },
    {
      path: '/email-templates',
      name: 'email-templates',
      component: () => import('@/pages/EmailTemplatesPage.vue'),
    },
    {
      path: '/automation',
      redirect: '/settings',
    },
    {
      path: '/settings',
      name: 'settings',
      component: () => import('@/pages/SettingsPage.vue'),
    },
  ],
})

/** Check auth status before each navigation */
router.beforeEach(async (to) => {
  if (to.meta.public) return true
  try {
    const res = await fetch('/api/me')
    if (!res.ok) return { name: 'login' }
  } catch {
    return { name: 'login' }
  }
  return true
})

export default router

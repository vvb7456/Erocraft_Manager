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
    {
      path: '/forgot-password',
      name: 'forgot-password',
      component: () => import('@/pages/ForgotPasswordPage.vue'),
      meta: { public: true, layout: 'blank' },
    },
    {
      path: '/reset-password',
      name: 'reset-password',
      component: () => import('@/pages/ResetPasswordPage.vue'),
      meta: { public: true, layout: 'blank' },
    },
    {
      path: '/confirm-email',
      name: 'confirm-email',
      component: () => import('@/pages/ConfirmEmailPage.vue'),
      meta: { public: true, layout: 'blank' },
    },
    { path: '/', redirect: '/servers' },

    // ── User routes ──
    {
      path: '/servers',
      name: 'user-servers',
      component: () => import('@/pages/user/UserServersPage.vue'),
      meta: { layout: 'user' },
    },
    {
      path: '/account',
      name: 'account',
      component: () => import('@/pages/user/AccountPage.vue'),
      meta: { layout: 'user' },
    },
    {
      path: '/servers/:id',
      component: () => import('@/pages/user/ServerDetailPage.vue'),
      meta: { layout: 'user' },
      children: [
        { path: '', redirect: (to) => ({ name: 'server-console', params: to.params }) },
        { path: 'console', name: 'server-console', component: () => import('@/pages/user/ServerConsolePage.vue') },
        { path: 'files', name: 'server-files', component: () => import('@/pages/user/ServerFilesPage.vue') },
        { path: 'settings', name: 'server-settings', component: () => import('@/pages/user/ServerSettingsPage.vue') },
        { path: 'activity', name: 'server-activity', component: () => import('@/pages/user/ServerActivityPage.vue') },
      ],
    },

    // ── Admin routes ──
    { path: '/admin', redirect: '/admin/dashboard' },
    {
      path: '/admin/dashboard',
      name: 'dashboard',
      component: () => import('@/pages/DashboardPage.vue'),
      meta: { admin: true },
    },
    {
      path: '/admin/servers',
      name: 'servers',
      component: () => import('@/pages/ServersPage.vue'),
      meta: { admin: true },
    },
    {
      path: '/admin/users',
      name: 'users',
      component: () => import('@/pages/UsersPage.vue'),
      meta: { admin: true },
    },
    {
      path: '/admin/activity-logs',
      name: 'activity-logs',
      component: () => import('@/pages/ActivityLogsPage.vue'),
      meta: { admin: true },
    },
    {
      path: '/admin/email-templates',
      name: 'email-templates',
      component: () => import('@/pages/EmailTemplatesPage.vue'),
      meta: { admin: true },
    },
    {
      path: '/admin/automation',
      redirect: '/admin/settings',
    },
    {
      path: '/admin/settings',
      name: 'settings',
      component: () => import('@/pages/SettingsPage.vue'),
      meta: { admin: true },
    },
  ],
})

/** Check auth status before each navigation */
router.beforeEach(async (to) => {
  if (to.meta.public) {
    if (to.name === 'login' || to.name === 'forgot-password') {
      try {
        const res = await fetch('/api/me')
        if (res.ok) {
          const data = await res.json()
          return data.is_admin ? { name: 'dashboard' } : { name: 'user-servers' }
        }
      } catch {
        return true
      }
    }
    return true
  }
  try {
    const res = await fetch('/api/me')
    if (!res.ok) return { name: 'login' }
    const data = await res.json()
    // Admin routes require admin role
    if (to.meta.admin && !data.is_admin) {
      return { name: 'user-servers' }
    }
  } catch {
    return { name: 'login' }
  }
  return true
})

export default router

import { createRouter, createWebHashHistory } from 'vue-router'
import { switchLanguage } from '@/i18n/vue-i18n'
import { backendToFrontendLocale } from '@/i18n/locale-map'
import { useAppStore } from '@/stores/app'

/** Sync the i18n locale with the user's saved server-side preference. */
function applyServerLanguage(value: unknown) {
  switchLanguage(backendToFrontendLocale(value))
}

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
    {
      path: '/register',
      name: 'register',
      component: () => import('@/pages/RegisterPage.vue'),
      meta: { public: true, layout: 'blank' },
    },
    {
      path: '/verify-email',
      name: 'verify-email',
      component: () => import('@/pages/VerifyEmailPage.vue'),
      meta: { public: true, layout: 'blank' },
    },
    { path: '/', name: 'home', meta: { layout: 'blank' }, component: () => import('@/pages/LoadingPage.vue') },

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
        { path: 'more', name: 'server-more', component: () => import('@/pages/user/ServerMorePage.vue') },
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
      path: '/admin/hosts',
      name: 'hosts',
      component: () => import('@/pages/HostsPage.vue'),
      meta: { admin: true },
    },
    {
      path: '/admin/hosts/:id',
      component: () => import('@/pages/HostDetailPage.vue'),
      meta: { admin: true },
      children: [
        {
          path: '',
          name: 'host-detail',
          redirect: (to) => ({ name: 'host-overview', params: to.params }),
        },
        {
          path: 'overview',
          name: 'host-overview',
          component: () => import('@/pages/host/HostOverviewPane.vue'),
          meta: { admin: true },
        },
        {
          path: 'setting',
          name: 'host-setting',
          component: () => import('@/pages/host/HostSettingPane.vue'),
          meta: { admin: true },
        },
        {
          path: 'wings',
          name: 'host-wings',
          component: () => import('@/pages/host/HostWingsPane.vue'),
          meta: { admin: true },
        },
        {
          path: 'allocations',
          name: 'host-allocations',
          component: () => import('@/pages/host/HostAllocationsPane.vue'),
          meta: { admin: true },
        },
        {
          path: 'activity',
          name: 'host-activity',
          component: () => import('@/pages/host/HostActivityPane.vue'),
          meta: { admin: true },
        },
      ],
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
  const app = useAppStore()
  if (to.meta.public) {
    if (to.name === 'login' || to.name === 'forgot-password') {
      try {
        const data = await app.fetchSessionUser()
        if (data) {
          applyServerLanguage(data?.language)
          app.setIsAdmin(!!data.is_admin)
          return data.is_admin ? { name: 'dashboard' } : { name: 'user-servers' }
        }
      } catch {
        return true
      }
    }
    return true
  }
  try {
    const data = await app.fetchSessionUser()
    if (!data) {
      app.setIsAdmin(false)
      return { name: 'login' }
    }
    applyServerLanguage(data?.language)
    app.setIsAdmin(!!data.is_admin)
    // Root path: pick destination by role
    if (to.name === 'home') {
      return data.is_admin ? { name: 'dashboard' } : { name: 'user-servers' }
    }
    // Admin routes require admin role
    if (to.meta.admin && !data.is_admin) {
      return { name: 'user-servers' }
    }
  } catch {
    app.setIsAdmin(false)
    return { name: 'login' }
  }
  return true
})

export default router

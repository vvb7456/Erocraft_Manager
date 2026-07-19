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
    {
      path: '/agreement/:slug',
      name: 'agreement-view',
      component: () => import('@/pages/AgreementViewPage.vue'),
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
      path: '/plans',
      name: 'user-plans',
      component: () => import('@/pages/user/UserPlansPage.vue'),
      meta: { layout: 'user' },
    },
    {
      path: '/orders',
      name: 'user-orders',
      component: () => import('@/pages/user/UserOrdersPage.vue'),
      meta: { layout: 'user' },
    },
    {
      path: '/promotions',
      name: 'user-promotions',
      component: () => import('@/pages/user/UserPromotionsPage.vue'),
      meta: { layout: 'user' },
    },
    {
      path: '/orders/:id',
      name: 'user-order-detail',
      component: () => import('@/pages/user/UserOrderDetailPage.vue'),
      meta: { layout: 'user' },
    },
    {
      path: '/pay/:id',
      name: 'user-pay',
      component: () => import('@/pages/user/UserPayPage.vue'),
      meta: { layout: 'blank' },
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
        { path: 'network', name: 'server-network', component: () => import('@/pages/user/ServerNetworkPage.vue') },
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
      path: '/admin/servers/:id',
      component: () => import('@/pages/AdminServerDetailPage.vue'),
      meta: { admin: true },
      children: [
        {
          path: '',
          name: 'admin-server-detail',
          redirect: (to) => ({ name: 'admin-server-overview', params: to.params }),
        },
        {
          path: 'overview',
          name: 'admin-server-overview',
          component: () => import('@/pages/admin-server/AdminServerOverviewPane.vue'),
          meta: { admin: true },
        },
        {
          path: 'settings',
          name: 'admin-server-settings',
          component: () => import('@/pages/admin-server/AdminServerSettingsPane.vue'),
          meta: { admin: true },
        },
        {
          path: 'llm',
          name: 'admin-server-llm',
          component: () => import('@/pages/admin-server/AdminServerLlmPane.vue'),
          meta: { admin: true },
        },
        {
          path: 'lifecycle',
          name: 'admin-server-lifecycle',
          component: () => import('@/pages/admin-server/AdminServerLifecyclePane.vue'),
          meta: { admin: true },
        },
      ],
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
      path: '/admin/certificates',
      name: 'certificates',
      component: () => import('@/pages/CertificatesPage.vue'),
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
          path: 'tunnel',
          name: 'host-tunnel',
          component: () => import('@/pages/host/HostTunnelPane.vue'),
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
      path: '/admin/billing',
      name: 'admin-billing',
      component: () => import('@/pages/admin/AdminBillingPage.vue'),
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

/**
 * Handle stale chunk errors after a new frontend release is deployed.
 *
 * After an atomic deploy, the previously loaded `main-*.js` references
 * lazy-loaded chunks by their old hash (e.g. `CertificatesPage-su0P1jZw.js`).
 * Those filenames no longer exist in the new release directory; nginx's SPA
 * fallback then returns `index.html` with `Content-Type: text/html`, which the
 * browser refuses to execute as a module ("Failed to fetch dynamically
 * imported module" / "Expected a JavaScript-or-Wasm module script but the
 * server responded with a MIME type of text/html").
 *
 * Reload the page so the freshly fetched `index.html` pulls in the new
 * `main-*.js` and the matching chunk hashes. The hash route is preserved
 * across reload, so the user lands on the same destination automatically.
 *
 * We guard against reload loops with a sessionStorage marker that is cleared
 * once a navigation succeeds.
 */
const CHUNK_RELOAD_KEY = 'erocraft:chunk-reload-at'
const CHUNK_ERROR_RE = /Failed to fetch dynamically imported module|error loading dynamically imported module|Importing a module script failed|Failed to load module script/i

router.onError((err) => {
  const msg = String((err as Error)?.message ?? err ?? '')
  if (!CHUNK_ERROR_RE.test(msg)) return
  try {
    const last = Number(sessionStorage.getItem(CHUNK_RELOAD_KEY) || '0')
    // Prevent reload storm: if we already reloaded within the last 10s, give up.
    if (Date.now() - last < 10_000) return
    sessionStorage.setItem(CHUNK_RELOAD_KEY, String(Date.now()))
  } catch {
    /* sessionStorage unavailable — fall through and reload anyway */
  }
  window.location.reload()
})

router.afterEach(() => {
  try {
    sessionStorage.removeItem(CHUNK_RELOAD_KEY)
  } catch {
    /* ignore */
  }
})

export default router

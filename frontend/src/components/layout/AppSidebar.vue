<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter, useRoute } from 'vue-router'
import { useAppStore } from '@/stores/app'
import { useSupportStore } from '@/stores/support'
import { confirmPendingChanges } from '@/composables/useDirtyForm'
import { useToast } from '@/composables/useToast'
import MsIcon from '../ui/MsIcon.vue'
import BaseButton from '../ui/BaseButton.vue'
import ThemeToggle from '../ui/ThemeToggle.vue'
import ToggleSwitch from '../ui/ToggleSwitch.vue'
import SupportModal from '@/components/billing/SupportModal.vue'

defineOptions({ name: 'AppSidebar' })
const { t } = useI18n({ useScope: 'global' })
const router = useRouter()
const route = useRoute()
const app = useAppStore()
const support = useSupportStore()
const { toast } = useToast()
const isUserLayout = computed(() => route.meta.layout === 'user')
interface NavItem { page: string; icon: string; labelKey: string }
interface NavGroup { label: string; items: NavItem[] }
const groups = computed<NavGroup[]>(() => isUserLayout.value ? [
  { label: t('nav.overview'), items: [
    { page: 'user-home', icon: 'home', labelKey: 'userHome.title' },
  ] },
  { label: t('nav.userServices'), items: [
    { page: 'user-servers', icon: 'dns', labelKey: 'userServers.title' },
    { page: 'user-plans', icon: 'storefront', labelKey: 'billing.plans.pageTitle' },
  ] },
  { label: t('nav.userBilling'), items: [
    { page: 'user-orders', icon: 'receipt_long', labelKey: 'billing.orders.pageTitle' },
    { page: 'user-promotions', icon: 'redeem', labelKey: 'nav.promotions' },
  ] },
] : [
  { label: t('nav.overview'), items: [
    { page: 'dashboard', icon: 'dashboard', labelKey: 'dashboard.title' },
  ] },
  { label: t('nav.operations'), items: [
    { page: 'servers', icon: 'dns', labelKey: 'servers.title' },
    { page: 'users', icon: 'group', labelKey: 'users.title' },
    { page: 'admin-billing', icon: 'receipt_long', labelKey: 'billing.admin.title' },
    { page: 'admin-support', icon: 'support_agent', labelKey: 'support.inbox' },
  ] },
  { label: t('nav.infrastructure'), items: [
    { page: 'hosts', icon: 'dvr', labelKey: 'hosts.title' },
    { page: 'certificates', icon: 'workspace_premium', labelKey: 'certificates.title' },
  ] },
  { label: t('nav.system'), items: [
    { page: 'notifications', icon: 'notifications', labelKey: 'notifications.title' },
    { page: 'activity-logs', icon: 'history', labelKey: 'logs.title' },
    { page: 'settings', icon: 'settings', labelKey: 'settings.title' },
  ] },
])
const currentPage = computed(() => {
  const name = String(route.name || '')
  if (name.startsWith('host-')) return 'hosts'
  if (name.startsWith('admin-server-')) return 'servers'
  if (name.startsWith('server-')) return 'user-servers'
  if (name === 'user-order-detail') return 'user-orders'
  return name
})
async function go(page: string, query?: Record<string, string>) {
  const failure = await router.push({ name: page, query })
  if (!failure) app.closeMobileSidebar()
}
const loggingOut = ref(false)
async function doLogout() {
  if (loggingOut.value) return
  loggingOut.value = true
  try {
    if (!await confirmPendingChanges()) return
    const response = await fetch('/api/logout', { method: 'POST' })
    if (!response.ok) throw new Error('logout')
    app.clearSessionUser()
    await router.push({ name: 'login' })
  } catch { toast(t('nav.logoutFailed'), 'error') }
  finally { loggingOut.value = false }
}
const supportOpen = ref(false)
function openSupport() { supportOpen.value = true; app.closeMobileSidebar() }
function openTutorial() {
  if (app.tutorialUrl?.trim()) window.open(app.tutorialUrl.trim(), '_blank', 'noopener,noreferrer')
  app.closeMobileSidebar()
}
</script>

<template>
  <aside class="sidebar" :class="{ collapsed: app.sidebarCollapsed, 'mobile-open': app.mobileSidebarOpen }" :aria-label="t('nav.navigation')" @keydown.esc="app.closeMobileSidebar()">
    <button class="sidebar-logo" :title="t('nav.home')" @click="go(isUserLayout ? 'user-home' : 'dashboard')">
      <img v-if="app.sidebarBannerUrl" class="logo-banner" :src="app.sidebarBannerUrl" :alt="app.displayName" />
      <template v-else><span class="logo-mark">{{ app.displayName[0] }}</span><span class="logo-text">{{ app.displayName }}</span></template>
    </button>
    <div v-if="app.isAdmin" class="role-switch">
      <ToggleSwitch :model-value="isUserLayout" :label-off="t('nav.switchToAdmin')" :label-on="t('nav.switchToUser')" :aria-label="t('nav.workspace')" size="sm" block @update:model-value="go($event ? 'user-home' : 'dashboard')" />
    </div>
    <button class="sidebar-toggle" :aria-label="t('common.sidebar.toggle')" :aria-expanded="!app.sidebarCollapsed" @click="app.toggleSidebar()"><MsIcon :name="app.sidebarCollapsed ? 'chevron_right' : 'chevron_left'" size="xs" /></button>
    <nav class="sidebar-nav">
      <div v-for="group in groups" :key="group.label" class="nav-group">
        <div class="nav-group-title">{{ group.label }}</div>
        <button v-for="item in group.items" :key="item.page" class="nav-item" :class="{ active: currentPage === item.page }"
          :aria-current="currentPage === item.page ? 'page' : undefined" :title="t(item.labelKey)" @click="go(item.page)">
          <MsIcon :name="item.icon" size="sm" /><span class="nav-label">{{ t(item.labelKey) }}</span>
          <span v-if="item.page === 'admin-support' && support.unread" class="unread-count">{{ support.unread > 99 ? '99+' : support.unread }}</span>
        </button>
      </div>
      <div v-if="isUserLayout" class="nav-group">
        <div class="nav-group-title">{{ t('nav.help') }}</div>
        <button v-if="app.tutorialUrl" class="nav-item" :title="t('nav.tutorial')" @click="openTutorial"><MsIcon name="menu_book" size="sm" /><span class="nav-label">{{ t('nav.tutorial') }}</span></button>
        <button class="nav-item" :title="t('billing.support.title')" @click="openSupport"><MsIcon name="support_agent" size="sm" /><span class="nav-label">{{ t('billing.support.title') }}</span></button>
      </div>
    </nav>
    <div class="sidebar-footer">
      <button class="account-entry" :title="t('account.title')" @click="go(isUserLayout ? 'account' : 'admin-account')">
        <span class="avatar">{{ app.sessionUser?.username[0]?.toUpperCase() }}</span>
        <span class="account-identity"><strong>{{ app.sessionUser?.username }}</strong><small>{{ t('account.title') }}</small></span>
      </button>
      <ThemeToggle />
      <BaseButton variant="ghost" size="sm" square :loading="loggingOut" :title="t('common.btn.logout')" :aria-label="t('common.btn.logout')" @click="doLogout"><MsIcon name="logout" size="sm" /></BaseButton>
    </div>
    <SupportModal v-model="supportOpen" />
  </aside>
</template>

<style scoped>
.sidebar { width: var(--sidebar-w, 220px); position: fixed; inset: 0 auto 0 0; display: flex; flex-direction: column; background: var(--bg2); border-right: 1px solid var(--bd); z-index: 50; transition: width .2s; }
.sidebar button { font-family: inherit; }
.sidebar-logo { display: flex; align-items: center; gap: 10px; border: 0; background: none; color: var(--t1); text-align: left; padding: 22px 16px 20px; min-height: 72px; cursor: pointer; flex-shrink: 0; overflow: hidden; }
.logo-banner { width: 100%; height: 32px; object-fit: contain; }
.logo-mark { width: 28px; height: 28px; display: grid; place-items: center; border-radius: var(--r-sm); background: color-mix(in srgb, var(--ac) 16%, transparent); color: var(--ac); font-size: var(--text-lg); font-weight: 700; flex-shrink: 0; }
.logo-text { font-size: 1.08rem; font-weight: 700; letter-spacing: -.035em; line-height: 1.3; }
.role-switch { margin: 0 12px 12px; }
.sidebar-toggle { position: absolute; top: 50%; right: -8px; transform: translateY(-50%); width: 16px; height: 48px; padding: 0; display: grid; place-items: center; border: 1px solid var(--bd); border-radius: 8px; color: var(--t3); background: var(--bg2); cursor: pointer; opacity: 0; transition: opacity .2s; }
.sidebar:hover .sidebar-toggle, .sidebar-toggle:focus-visible, .collapsed .sidebar-toggle { opacity: 1; }
.sidebar-nav { flex: 1; min-height: 0; overflow-y: auto; overflow-x: hidden; padding-bottom: 12px; }
.nav-group { margin-bottom: 12px; }
.nav-group-title { padding: 10px 18px 6px; color: var(--t3); font-size: var(--text-xs); font-weight: 600; letter-spacing: .05em; }
.nav-item { display: flex; align-items: center; gap: 10px; width: calc(100% - 16px); margin: 2px 8px; padding: 8px 10px; border: 0; border-radius: var(--r-sm); background: none; color: var(--t2); font: inherit; font-size: var(--text-base); text-align: left; cursor: pointer; }
.nav-label { flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.nav-item:hover { background: color-mix(in srgb, var(--t1) 6%, transparent); color: var(--t1); }
.nav-item.active { background: color-mix(in srgb, var(--ac) 12%, transparent); color: var(--t1); font-weight: 600; }
.nav-item.active :deep(.ms) { color: var(--ac); font-variation-settings: 'FILL' 1; }
.unread-count { border-radius: var(--r-pill); padding: 1px 5px; background: var(--ac); color: var(--bg); font-size: var(--text-xs); }
.sidebar-footer { flex-shrink: 0; display: flex; align-items: center; gap: 6px; border-top: 1px solid var(--bd); padding: 14px 12px; }
.account-entry { flex: 1; min-width: 0; display: flex; align-items: center; gap: 8px; background: none; border: 0; border-radius: var(--r-sm); padding: 0; text-align: left; color: var(--t1); cursor: pointer; }
.avatar { width: 30px; height: 30px; display: grid; place-items: center; border: 1px solid var(--bd); border-radius: 50%; background: var(--bg4); color: var(--t2); font-size: var(--text-xs); flex-shrink: 0; }
.account-identity { min-width: 0; }
.account-identity strong { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: var(--text-sm); }
.account-identity small { color: var(--t3); font-size: var(--text-xs); }
.sidebar button:focus-visible { outline: 2px solid var(--ac); outline-offset: -2px; }
@media (min-width: 769px) {
  .sidebar.collapsed { width: 56px; }
  .collapsed .logo-text, .collapsed .nav-label, .collapsed .role-switch, .collapsed .account-identity { display: none; }
  .collapsed .sidebar-logo { padding: 22px 10px 20px; justify-content: center; }
  .collapsed .nav-item { padding: 8px 0; justify-content: center; position: relative; }
  .collapsed .nav-group-title { height: 1px; padding: 0; margin: 12px 16px; background: var(--bd); overflow: hidden; font-size: 0; }
  .collapsed .unread-count { position: absolute; top: 0; right: 0; width: 6px; height: 6px; padding: 0; font-size: 0; }
  .collapsed .sidebar-footer { flex-direction: column; padding: 12px 4px; }
  .collapsed .account-entry { flex: 0; }
}
@media (max-width: 768px) {
  .sidebar { transform: translateX(-100%); transition: transform .2s; }
  .sidebar.mobile-open { transform: translateX(0); }
  .sidebar-toggle { display: none; }
}
</style>

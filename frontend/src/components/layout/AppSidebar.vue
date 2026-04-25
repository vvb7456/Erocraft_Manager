<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useRouter, useRoute } from 'vue-router'
import { useAppStore } from '@/stores/app'
import { useServerResourceStore } from '@/stores/serverResources'
import { useApiFetch } from '@/composables/useApiFetch'
import { computed, ref, onBeforeUnmount, watch } from 'vue'
import MsIcon from '../ui/MsIcon.vue'
import StatusDot from '../ui/StatusDot.vue'
import { getStatusDotKey } from '@/utils/status'
import BaseButton from '../ui/BaseButton.vue'
import LanguageToggle from '../ui/LanguageToggle.vue'

defineOptions({ name: 'AppSidebar' })

const { t } = useI18n({ useScope: 'global' })
const router = useRouter()
const route = useRoute()
const app = useAppStore()
const resourceStore = useServerResourceStore()
const { get } = useApiFetch()

// ── Layout mode ──
const isUserLayout = computed(() => route.meta.layout === 'user')

// ── Admin nav items ──
interface NavItem {
  page: string
  icon: string
  labelKey: string
}

const adminNavItems: NavItem[] = [
  { page: 'dashboard',       icon: 'dashboard',  labelKey: 'nav.dashboard' },
  { page: 'servers',         icon: 'dns',        labelKey: 'nav.servers' },
  { page: 'certificates',    icon: 'workspace_premium', labelKey: 'nav.certificates' },
  { page: 'users',           icon: 'group',      labelKey: 'nav.users' },
  { page: 'activity-logs',   icon: 'history',    labelKey: 'nav.activityLogs' },
  { page: 'email-templates', icon: 'mail',       labelKey: 'nav.emailTemplates' },
]

const settingsItem: NavItem = {
  page: 'settings', icon: 'settings', labelKey: 'nav.settings',
}

const accountItem: NavItem = {
  page: 'account', icon: 'person', labelKey: 'nav.account',
}

// ── User server list ──
interface ServerItem {
  id: number
  name: string
  status: string | null
  isSuspended: boolean
  isInstalling: boolean
}

const servers = ref<ServerItem[]>([])
const serversExpanded = ref(true)

async function loadServers() {
  const data = await get<ServerItem[]>('/api/user/servers', { silent: true })
  if (data) {
    servers.value = data
    const ids = data.map(s => s.id)
    if (ids.length > 0) {
      resourceStore.subscribe('sidebar', ids, 10000)
    }
  }
}

function statusDotKey(s: ServerItem): 'running' | 'loading' | 'error' | 'stopped' {
  const st = resourceStore.getState(s.id) || s.status || 'offline'
  return getStatusDotKey(st, s.isSuspended, s.isInstalling, resourceStore.isStale(s.id))
}

function toggleExpand() {
  serversExpanded.value = !serversExpanded.value
}

// ── Navigation ──
const currentPage = computed(() => {
  const name = typeof route.name === 'string' ? route.name : ''
  // Map detail routes to their parent list item so the sidebar stays
  // highlighted while the user is drilled in.
  if (name.startsWith('host-')) return 'hosts'
  if (name.startsWith('admin-server-')) return 'servers'
  return name
})
const currentServerId = computed(() => route.params.id ? Number(route.params.id) : null)

function navTo(item: NavItem) {
  router.push({ name: item.page })
  if (window.innerWidth <= 768) app.closeMobileSidebar()
}

function goOverview() {
  router.push({ name: 'user-servers' })
  if (window.innerWidth <= 768) app.closeMobileSidebar()
}

function goToServer(id: number) {
  router.push({ name: 'server-console', params: { id } })
  if (window.innerWidth <= 768) app.closeMobileSidebar()
}

async function doLogout() {
  await fetch('/api/logout', { method: 'POST' })
  app.clearSessionUser()
  router.push({ name: 'login' })
}

// ── Lifecycle ──
watch(isUserLayout, (val) => {
  if (val) {
    loadServers()
  } else {
    servers.value = []
    resourceStore.unsubscribe('sidebar')
  }
}, { immediate: true })

onBeforeUnmount(() => {
  resourceStore.unsubscribe('sidebar')
})
</script>

<template>
  <nav class="sidebar" :class="{ collapsed: app.sidebarCollapsed, 'mobile-open': app.mobileSidebarOpen }">
    <button class="sidebar-toggle" :title="t('common.sidebar.toggle')" @click="app.toggleSidebar()">◀</button>

    <div
      class="sidebar-logo"
      :class="{ 'sidebar-logo--banner-only': !!app.sidebarBannerUrl, 'sidebar-logo--text-only': !app.sidebarBannerUrl }"
    >
      <template v-if="app.sidebarBannerUrl">
        <img class="logo-banner" :src="app.sidebarBannerUrl" :alt="app.displayName" />
      </template>
      <template v-else>
        <span class="logo-text">{{ app.displayName }}</span>
      </template>
    </div>

    <div class="sidebar-nav">
      <!-- ═══ User layout: server list ═══ -->
      <template v-if="isUserLayout">
        <div class="nav-group">
          <button
            class="nav-item nav-item--group"
            @click="toggleExpand"
          >
            <span class="icon"><MsIcon name="dns" size="md" /></span>
            <span class="nav-label">{{ t('nav.servers') }}</span>
            <span
              v-if="!app.sidebarCollapsed"
              class="expand-arrow"
              :class="{ expanded: serversExpanded }"
            ><MsIcon name="expand_more" size="sm" /></span>
          </button>

          <div v-if="serversExpanded && !app.sidebarCollapsed" class="nav-sub">
            <button
              class="nav-sub-item"
              :class="{ active: currentPage === 'user-servers' }"
              @click="goOverview"
            >
              <MsIcon name="monitoring" size="sm" />
              <span class="nav-sub-label">{{ t('nav.overview') }}</span>
            </button>
            <button
              v-for="s in servers"
              :key="s.id"
              class="nav-sub-item"
              :class="{ active: currentServerId === s.id }"
              @click="goToServer(s.id)"
            >
              <StatusDot :status="statusDotKey(s)" size="sm" />
              <span class="nav-sub-label">{{ s.name }}</span>
            </button>
          </div>
        </div>
      </template>

      <!-- ═══ Admin layout: static nav + hosts group ═══ -->
      <template v-else>
        <template v-for="item in adminNavItems" :key="item.page">
          <button
            class="nav-item"
            :class="{ active: currentPage === item.page }"
            @click="navTo(item)"
          >
            <span class="icon"><MsIcon :name="item.icon" size="md" /></span>
            <span class="nav-label">{{ t(item.labelKey) }}</span>
          </button>

          <!-- Inject Hosts right after Servers so infra sits next to the things running on it. -->
          <template v-if="item.page === 'servers'">
            <button
              class="nav-item"
              :class="{ active: currentPage === 'hosts' }"
              @click="navTo({ page: 'hosts', icon: 'dvr', labelKey: 'nav.hosts' })"
            >
              <span class="icon"><MsIcon name="dvr" size="md" /></span>
              <span class="nav-label">{{ t('nav.hosts') }}</span>
            </button>
          </template>
        </template>
      </template>

      <div style="flex: 1" />

      <button
        v-if="isUserLayout"
        class="nav-item"
        :class="{ active: currentPage === 'account' }"
        @click="navTo(accountItem)"
      >
        <span class="icon"><MsIcon :name="accountItem.icon" size="md" /></span>
        <span class="nav-label">{{ t(accountItem.labelKey) }}</span>
      </button>

      <!-- Settings (admin only) -->
      <button
        v-if="!isUserLayout"
        class="nav-item"
        :class="{ active: currentPage === 'settings' }"
        @click="navTo(settingsItem)"
      >
        <span class="icon"><MsIcon :name="settingsItem.icon" size="md" /></span>
        <span class="nav-label">{{ t(settingsItem.labelKey) }}</span>
      </button>
    </div>

    <div class="sidebar-footer">
      <div class="footer-expanded">
        <div class="footer-logout-row">
          <LanguageToggle />
          <BaseButton size="sm" style="font-size:.72rem;flex:1;text-align:center;justify-content:center" @click="doLogout">
            <MsIcon name="logout" />
            {{ t('common.btn.logout') }}
          </BaseButton>
        </div>
      </div>
      <div class="footer-collapsed">
        <LanguageToggle mode="stacked" class="lang-switcher-collapsed" />
        <button @click="doLogout" :title="t('common.btn.logout')" class="logout-btn-mini">
          <MsIcon name="logout" />
        </button>
      </div>
    </div>
  </nav>
</template>

<style scoped>
/* ── Sidebar shell ── */
.sidebar {
  width: clamp(200px, 14vw, 260px);
  background: var(--bg2);
  border-right: 1px solid var(--bd);
  display: flex;
  flex-direction: column;
  position: fixed;
  top: 0;
  left: 0;
  bottom: 0;
  z-index: 50;
  transition: width .25s ease;
}

.sidebar.collapsed {
  width: 56px;
}

/* ── Logo ── */
.sidebar-logo {
  padding: 0 16px;
  min-height: 64px;
  border-bottom: 1px solid var(--bd);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  white-space: nowrap;
  overflow: hidden;
}

.sidebar-logo--banner-only {
  padding: 12px 16px;
}

.sidebar-logo--text-only {
  justify-content: flex-start;
  gap: 12px;
}

.sidebar-logo--text-only::before {
  content: '';
  width: 8px;
  height: 28px;
  border-radius: 999px;
  background: linear-gradient(180deg, var(--brand-title-accent) 0%, var(--brand-title-accent-2) 100%);
  box-shadow: 0 0 14px var(--brand-glow);
  flex-shrink: 0;
}

.logo-banner {
  display: block;
  width: 100%;
  max-height: 46px;
  object-fit: contain;
  flex-shrink: 0;
}

.sidebar-logo .logo-text {
  display: inline-block;
  max-width: 100%;
  font-family: 'IBM Plex Sans', 'IBM Plex Sans SC', -apple-system, sans-serif;
  font-size: 1.42rem;
  font-weight: 700;
  line-height: 1.2;
  color: var(--brand-title-solid);
  letter-spacing: -0.035em;
  text-wrap: balance;
}

.sidebar.collapsed .sidebar-logo {
  padding: 20px 12px;
  justify-content: center;
}

.sidebar.collapsed .sidebar-logo--banner-only {
  padding: 12px 8px;
}

.sidebar.collapsed .sidebar-logo--text-only {
  justify-content: center;
}

.sidebar.collapsed .logo-banner {
  max-height: 28px;
}

.sidebar.collapsed .sidebar-logo .logo-text {
  display: none;
}

.sidebar.collapsed .sidebar-logo--text-only::before {
  height: 24px;
}

.sidebar-logo small {
  display: block;
  font-size: var(--text-xs);
  font-weight: 400;
  -webkit-text-fill-color: var(--t3);
  margin-top: 2px;
}

/* ── Nav ── */
.sidebar-nav {
  flex: 1;
  padding: 12px 0;
  display: flex;
  flex-direction: column;
}

/* ── Toggle button ── */
.sidebar-toggle {
  position: absolute;
  top: 22px;
  right: -12px;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: var(--bg2);
  border: 1px solid var(--bd);
  color: var(--t2);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--text-xs);
  z-index: 51;
  transition: transform .25s;
  opacity: 0;
}

.sidebar:hover .sidebar-toggle {
  opacity: 1;
}

.sidebar.collapsed .sidebar-toggle {
  opacity: 1;
  transform: rotate(180deg);
}

/* ── Nav item ── */
.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 11px 20px;
  cursor: pointer;
  color: var(--t2);
  font-size: var(--text-md);
  font-weight: 500;
  transition: all .15s;
  border: none;
  border-left: 3px solid transparent;
  background: none;
  font-family: inherit;
  width: 100%;
  text-align: left;
  white-space: nowrap;
  overflow: hidden;
}

.sidebar.collapsed .nav-item {
  padding: 10px 0;
  justify-content: center;
  border-left-width: 0;
}

.sidebar.collapsed .nav-label {
  display: none;
}

.nav-item:hover {
  background: rgba(20, 184, 166, .06);
  color: var(--t1);
}

.nav-item:focus-visible {
  outline: 2px solid var(--ac);
  outline-offset: 2px;
}

.nav-item.active {
  color: var(--ac);
  border-left-color: var(--ac);
  background: rgba(20, 184, 166, .08);
}

.sidebar.collapsed .nav-item.active {
  border-left-color: transparent;
  background: rgba(20, 184, 166, .12);
}

.nav-item .icon {
  font-size: 1.1rem;
  width: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.nav-item .icon .ms {
  font-size: 28px;
  font-variation-settings: 'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 28;
}

.nav-item.active .icon .ms {
  font-variation-settings: 'FILL' 1, 'wght' 500, 'GRAD' 0, 'opsz' 28;
}

/* ── Nav group & sub-items ── */
.nav-group {
  display: flex;
  flex-direction: column;
}

.nav-group .nav-item {
  position: relative;
}

.expand-arrow {
  margin-left: auto;
  display: flex;
  align-items: center;
  padding: 4px;
  border-radius: var(--r-xs);
  transition: transform .2s;
  color: var(--t3);
}

.expand-arrow:hover {
  color: var(--t1);
}

.expand-arrow.expanded {
  transform: rotate(180deg);
}

.nav-sub {
  display: flex;
  flex-direction: column;
}

.nav-sub-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 20px 12px 63px;
  cursor: pointer;
  color: var(--t2);
  font-size: var(--text-base);
  font-weight: 400;
  transition: all .15s;
  border: none;
  background: none;
  font-family: inherit;
  width: 100%;
  text-align: left;
  white-space: nowrap;
  overflow: hidden;
}

.nav-sub-item:hover {
  color: var(--t1);
  background: rgba(20, 184, 166, .06);
}

.nav-sub-item.active {
  color: var(--ac);
  background: rgba(20, 184, 166, .08);
}

.nav-sub-label {
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Trailing kind icon on host sub-items */
.nav-sub-item > .nav-sub-label {
  flex: 1;
}

.nav-sub-item .host-kind {
  color: var(--t3);
  margin-left: auto;
  flex-shrink: 0;
}

.nav-sub-item:hover .host-kind,
.nav-sub-item.active .host-kind {
  color: inherit;
}

/* ── Footer ── */
.sidebar-footer {
  padding: 12px 20px;
  border-top: 1px solid var(--bd);
  font-size: var(--text-sm);
  color: var(--t3);
  overflow: hidden;
}

.sidebar.collapsed .sidebar-footer {
  padding: 12px 8px;
  text-align: center;
}

.sidebar.collapsed .sidebar-footer .footer-expanded {
  display: none;
}

.sidebar-footer .footer-collapsed {
  display: none;
}

.sidebar.collapsed .sidebar-footer .footer-collapsed {
  display: block;
}

.footer-logout-row {
  display: flex;
  gap: 6px;
  margin-bottom: 8px;
  align-items: stretch;
}

.lang-switcher-collapsed {
  margin-bottom: 6px;
}

.logout-btn-mini {
  background: none;
  border: none;
  color: var(--t3);
  font-size: var(--text-md);
  cursor: pointer;
  padding: 2px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.logout-btn-mini:hover {
  color: var(--red);
}

/* ── Mobile responsive ── */
@media (max-width: 768px) {
  .sidebar {
    transform: translateX(-100%);
    transition: transform .3s ease;
    background: color-mix(in srgb, var(--bg2) 75%, transparent);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
  }

  .sidebar.mobile-open {
    transform: translateX(0);
  }

  .sidebar-toggle {
    display: none;
  }
}

/* ── Light Theme ── */
:global([data-theme="light"]) .sidebar {
  background: #dce4e2;
}
</style>

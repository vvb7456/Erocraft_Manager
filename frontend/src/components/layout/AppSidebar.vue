<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useRouter, useRoute } from 'vue-router'
import { useAppStore } from '@/stores/app'
import { useServerResourceStore } from '@/stores/serverResources'
import { useApiFetch } from '@/composables/useApiFetch'
import { switchLanguage } from '@/i18n/vue-i18n'
import { computed, ref, onMounted, onBeforeUnmount, watch } from 'vue'
import MsIcon from '../ui/MsIcon.vue'
import StatusDot from '../ui/StatusDot.vue'
import BaseButton from '../ui/BaseButton.vue'

defineOptions({ name: 'AppSidebar' })

const { t, locale } = useI18n({ useScope: 'global' })
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
  { page: 'users',           icon: 'group',      labelKey: 'nav.users' },
  { page: 'activity-logs',   icon: 'history',    labelKey: 'nav.activityLogs' },
  { page: 'email-templates', icon: 'mail',       labelKey: 'nav.emailTemplates' },
]

const settingsItem: NavItem = {
  page: 'settings', icon: 'settings', labelKey: 'nav.settings',
}

// ── User server list ──
interface ServerItem {
  id: number
  name: string
  status: string | null
  isSuspended: boolean
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
  if (s.isSuspended) return 'error'
  const st = resourceStore.getState(s.id) || s.status || 'offline'
  if (st === 'running') return 'running'
  if (st === 'starting' || st === 'stopping' || st === 'installing') return 'loading'
  return 'stopped'
}

function toggleExpand() {
  serversExpanded.value = !serversExpanded.value
}

// ── Navigation ──
const currentPage = computed(() => route.name as string)
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

// ── Lang & logout ──
function toggleLang() {
  switchLanguage(locale.value === 'zh-CN' ? 'en' : 'zh-CN')
}

function setLang(lng: string) {
  switchLanguage(lng)
}

async function doLogout() {
  await fetch('/api/logout', { method: 'POST' })
  router.push({ name: 'login' })
}

// ── Lifecycle ──
watch(isUserLayout, (val) => {
  if (val) loadServers()
  else {
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

    <div class="sidebar-logo">
      <span class="logo-icon-text">PM</span>
      <span class="logo-text">{{ app.brandName }}</span>
    </div>

    <div class="sidebar-nav">
      <!-- ═══ User layout: server list ═══ -->
      <template v-if="isUserLayout">
        <div class="nav-group">
          <button
            class="nav-item"
            :class="{ active: currentPage === 'user-servers' }"
            @click="goOverview"
          >
            <span class="icon"><MsIcon name="dns" size="md" /></span>
            <span class="nav-label">{{ t('nav.servers') }}</span>
            <span
              v-if="servers.length && !app.sidebarCollapsed"
              class="expand-arrow"
              :class="{ expanded: serversExpanded }"
              @click.stop="toggleExpand"
            ><MsIcon name="expand_more" size="sm" /></span>
          </button>

          <div v-if="serversExpanded && servers.length && !app.sidebarCollapsed" class="nav-sub">
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

      <!-- ═══ Admin layout: static nav ═══ -->
      <template v-else>
        <button
          v-for="item in adminNavItems"
          :key="item.page"
          class="nav-item"
          :class="{ active: currentPage === item.page }"
          @click="navTo(item)"
        >
          <span class="icon"><MsIcon :name="item.icon" size="md" /></span>
          <span class="nav-label">{{ t(item.labelKey) }}</span>
        </button>
      </template>

      <div style="flex: 1" />

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
          <button
            class="lang-toggle"
            :title="locale === 'zh-CN' ? t('common.lang.switch_en') : t('common.lang.switch_zh')"
            @click="toggleLang()"
          >{{ locale === 'zh-CN' ? 'EN' : '中' }}</button>
          <BaseButton size="sm" style="font-size:.72rem;flex:1;text-align:center;justify-content:center" @click="doLogout">
            <MsIcon name="logout" />
            {{ t('common.btn.logout') }}
          </BaseButton>
        </div>
      </div>
      <div class="footer-collapsed">
        <div class="lang-switcher-collapsed">
          <button
            class="lang-btn-mini"
            :class="{ active: locale === 'zh-CN' }"
            :title="t('common.lang.switch_zh')"
            @click="setLang('zh-CN')"
          >中</button>
          <button
            class="lang-btn-mini"
            :class="{ active: locale === 'en' }"
            :title="t('common.lang.switch_en')"
            @click="setLang('en')"
          >EN</button>
        </div>
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
  gap: 10px;
  white-space: nowrap;
  overflow: hidden;
}

.sidebar-logo .logo-icon {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  flex-shrink: 0;
  transition: width .25s, height .25s;
  display: none;
}

.sidebar-logo .logo-text {
  font-size: 1.35rem;
  font-weight: 700;
  background: linear-gradient(135deg, #14b8a6, #06b6d4);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  color: transparent;
}

.sidebar.collapsed .sidebar-logo {
  padding: 20px 12px;
  justify-content: center;
}

.sidebar.collapsed .sidebar-logo .logo-icon {
  display: block;
  width: 30px;
  height: 30px;
}

.sidebar.collapsed .sidebar-logo .logo-text {
  display: none;
}

.sidebar-logo small {
  display: block;
  font-size: var(--text-xs);
  font-weight: 400;
  -webkit-text-fill-color: var(--t3);
  margin-top: 2px;
}

/* ── Logo icon text ── */
.logo-icon-text {
  font-size: var(--text-xl);
  font-weight: 700;
  background: linear-gradient(135deg, #14b8a6, #06b6d4);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  color: transparent;
  flex-shrink: 0;
}

.sidebar.collapsed .logo-icon-text {
  font-size: var(--text-md);
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

.lang-toggle {
  background: var(--bg2);
  border: 1px solid var(--bd);
  color: var(--t2);
  border-radius: 4px;
  font-size: var(--text-xs);
  font-weight: 600;
  padding: 4px 8px;
  cursor: pointer;
  transition: background .15s, color .15s, border-color .15s;
  letter-spacing: .03em;
  white-space: nowrap;
  flex-shrink: 0;
}

.lang-toggle:hover {
  background: var(--bg3);
  color: var(--t1);
}

.lang-switcher-collapsed {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  margin-bottom: 6px;
}

.lang-btn-mini {
  background: var(--bg2);
  border: 1px solid var(--bd);
  color: var(--t2);
  border-radius: 3px;
  font-size: var(--text-xs);
  font-weight: 700;
  padding: 2px 5px;
  cursor: pointer;
  transition: background .15s, color .15s;
  line-height: 1;
}

.lang-btn-mini:hover {
  background: var(--bg3);
  color: var(--t1);
}

.lang-btn-mini.active {
  background: var(--ac);
  border-color: var(--ac);
  color: #fff;
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

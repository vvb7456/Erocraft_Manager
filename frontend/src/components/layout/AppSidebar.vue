<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useRouter, useRoute } from 'vue-router'
import { useAppStore } from '@/stores/app'
import { switchLanguage } from '@/i18n/vue-i18n'
import { computed } from 'vue'
import MsIcon from '../ui/MsIcon.vue'
import BaseButton from '../ui/BaseButton.vue'

defineOptions({ name: 'AppSidebar' })

const { t, locale } = useI18n({ useScope: 'global' })
const router = useRouter()
const route = useRoute()
const app = useAppStore()

interface NavItem {
  page: string
  icon: string
  labelKey?: string
  label?: string
}

const navItems: NavItem[] = [
  { page: 'dashboard',      icon: 'dashboard',       labelKey: 'nav.dashboard' },
  { page: 'servers',        icon: 'dns',             labelKey: 'nav.servers' },
  { page: 'users',          icon: 'group',           labelKey: 'nav.users' },
  { page: 'activity-logs',  icon: 'history',         labelKey: 'nav.activityLogs' },
  { page: 'email-templates',icon: 'mail',            labelKey: 'nav.emailTemplates' },
]

const settingsItem: NavItem = {
  page: 'settings', icon: 'settings', labelKey: 'nav.settings',
}

const currentPage = computed(() => route.name as string)

function navTo(item: NavItem) {
  router.push({ name: item.page })
  if (window.innerWidth <= 768) {
    app.closeMobileSidebar()
  }
}

function getLabel(item: NavItem) {
  return item.labelKey ? t(item.labelKey) : (item.label ?? '')
}

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
</script>

<template>
  <nav class="sidebar" :class="{ collapsed: app.sidebarCollapsed, 'mobile-open': app.mobileSidebarOpen }">
    <button
      class="sidebar-toggle"
      :title="t('common.sidebar.toggle')"
      @click="app.toggleSidebar()"
    >◀</button>

    <div class="sidebar-logo">
      <span class="logo-icon-text">PM</span>
      <span class="logo-text">{{ app.brandName }}</span>
    </div>

    <div class="sidebar-nav">
      <button
        v-for="item in navItems"
        :key="item.page"
        class="nav-item"
        :class="{ active: currentPage === item.page }"
        @click="navTo(item)"
      >
        <span class="icon"><MsIcon :name="item.icon" size="md" /></span>
        <span class="nav-label">{{ getLabel(item) }}</span>
      </button>

      <div style="flex: 1" />

      <button
        class="nav-item"
        :class="{ active: currentPage === 'settings' }"
        @click="navTo(settingsItem)"
      >
        <span class="icon"><MsIcon :name="settingsItem.icon" size="md" /></span>
        <span class="nav-label">{{ getLabel(settingsItem) }}</span>
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
        <div style="text-align:center">
          <span style="font-size:.68rem;color:var(--t3)">
            <span v-if="app.version">{{ app.version }}</span>
          </span>
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

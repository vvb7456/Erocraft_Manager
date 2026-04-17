import { createI18n } from 'vue-i18n'

// ── Static locale imports ──
import zhCommon from './locales/zh-CN/common.json'
import zhNav from './locales/zh-CN/nav.json'
import zhDashboard from './locales/zh-CN/dashboard.json'
import zhSettings from './locales/zh-CN/settings.json'
import zhLogin from './locales/zh-CN/login.json'
import zhServers from './locales/zh-CN/servers.json'
import zhUsers from './locales/zh-CN/users.json'
import zhLogs from './locales/zh-CN/logs.json'
import zhAutomation from './locales/zh-CN/automation.json'
import zhEmailTemplates from './locales/zh-CN/email-templates.json'
import zhUserServers from './locales/zh-CN/user-servers.json'

import enCommon from './locales/en/common.json'
import enNav from './locales/en/nav.json'
import enDashboard from './locales/en/dashboard.json'
import enSettings from './locales/en/settings.json'
import enLogin from './locales/en/login.json'
import enServers from './locales/en/servers.json'
import enUsers from './locales/en/users.json'
import enLogs from './locales/en/logs.json'
import enAutomation from './locales/en/automation.json'
import enEmailTemplates from './locales/en/email-templates.json'
import enUserServers from './locales/en/user-servers.json'

function detectLanguage(): string {
  const stored = localStorage.getItem('lang')
  if (stored) return stored
  const nav = navigator.language || ''
  return nav.startsWith('zh') ? 'zh-CN' : 'en'
}

const i18n = createI18n({
  legacy: false,
  locale: detectLanguage(),
  fallbackLocale: 'zh-CN',
  messages: {
    'zh-CN': {
      common: zhCommon, nav: zhNav, dashboard: zhDashboard,
      settings: zhSettings, login: zhLogin, servers: zhServers,
      users: zhUsers, logs: zhLogs,
      automation: zhAutomation, emailTemplates: zhEmailTemplates,
      userServers: zhUserServers,
    },
    en: {
      common: enCommon, nav: enNav, dashboard: enDashboard,
      settings: enSettings, login: enLogin, servers: enServers,
      users: enUsers, logs: enLogs,
      automation: enAutomation, emailTemplates: enEmailTemplates,
      userServers: enUserServers,
    },
  },
})

export default i18n

/** Switch language and persist to localStorage */
export function switchLanguage(lng: string) {
  const { locale } = i18n.global
  ;(locale as { value: string }).value = lng
  localStorage.setItem('lang', lng)
  document.documentElement.lang = lng === 'zh-CN' ? 'zh-CN' : 'en'
}

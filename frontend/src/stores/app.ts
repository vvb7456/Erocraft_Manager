import { defineStore } from 'pinia'
import { ApiError, fetchApi, readApiJson } from '@/composables/apiClient'
import i18n from '@/i18n/vue-i18n'
import { computed, ref } from 'vue'

const DEFAULT_BANNER_URL = '/banner.png'
const SESSION_USER_TTL_MS = 30_000
const SESSION_ANON_TTL_MS = 5_000

export interface SessionUser {
  ok: boolean
  username: string
  is_admin: boolean
  has_owned_server: boolean
  language: string
}

export interface PublicBranding {
  allowRegistration: boolean
  agreementsDefaultChecked: boolean
  supportEmail: string
  supportQqGroup: string
  supportQq: string
  supportWechat: string
  supportFooterNote: string
}

export const useAppStore = defineStore('app', () => {
  const sidebarCollapsed = ref(localStorage.getItem('sidebar_collapsed') === '1')
  const mobileSidebarOpen = ref(false)
  const isAdmin = ref(false)
  const hasOwnedServer = ref(false)
  const version = ref('')
  const brandName = ref('Erocraft Manager')
  const systemName = ref('')
  const bannerUrl = ref('')
  const icpRecord = ref('')
  const tutorialUrl = ref('')
  const timezone = ref('Asia/Shanghai')
  const sessionUser = ref<SessionUser | null>(null)
  const sessionUserFetchedAt = ref(0)
  let sessionUserPromise: Promise<SessionUser | null> | null = null
  const brandingLoaded = ref(false)
  const branding = ref<PublicBranding>({
    allowRegistration: true,
    agreementsDefaultChecked: false,
    supportEmail: '',
    supportQqGroup: '',
    supportQq: '',
    supportWechat: '',
    supportFooterNote: '',
  })
  let brandingPromise: Promise<void> | null = null
  const hasSystemName = computed(() => systemName.value.trim().length > 0)
  const hasCustomBannerUrl = computed(() => bannerUrl.value.trim().length > 0)
  const displayName = computed(() =>
    hasSystemName.value ? systemName.value.trim() : brandName.value,
  )
  const authBannerUrl = computed(() =>
    hasCustomBannerUrl.value ? bannerUrl.value.trim() : DEFAULT_BANNER_URL,
  )
  const sidebarBannerUrl = computed(() => {
    if (hasCustomBannerUrl.value) return bannerUrl.value.trim()
    return hasSystemName.value ? '' : DEFAULT_BANNER_URL
  })
  const currentYear = new Date().getFullYear()
  const footerText = computed(() => {
    const parts = [`${brandName.value} © 2015 - ${currentYear}`]
    if (icpRecord.value) parts.push(icpRecord.value)
    parts.push(i18n.global.t('common.footer.allRightsReserved'))
    return parts.join(' | ')
  })

  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value
    localStorage.setItem('sidebar_collapsed', sidebarCollapsed.value ? '1' : '0')
  }

  function openMobileSidebar() {
    mobileSidebarOpen.value = true
  }

  function closeMobileSidebar() {
    mobileSidebarOpen.value = false
  }

  function toggleMobileSidebar() {
    mobileSidebarOpen.value = !mobileSidebarOpen.value
  }

  function setIsAdmin(value: boolean) {
    isAdmin.value = value
  }

  function setSessionUser(value: SessionUser | null) {
    sessionUser.value = value
    sessionUserFetchedAt.value = value ? Date.now() : 0
    setIsAdmin(!!value?.is_admin)
    hasOwnedServer.value = !!value?.has_owned_server
  }

  function clearSessionUser() {
    sessionUserPromise = null
    setSessionUser(null)
  }

  function markSessionExpired() {
    sessionUserPromise = null
    sessionUser.value = null
    sessionUserFetchedAt.value = Date.now()
    setIsAdmin(false)
    hasOwnedServer.value = false
  }

  async function fetchSessionUser(opts: { force?: boolean } = {}) {
    const now = Date.now()
    const ttl = sessionUser.value ? SESSION_USER_TTL_MS : SESSION_ANON_TTL_MS
    if (
      !opts.force
      && sessionUserFetchedAt.value > 0
      && now - sessionUserFetchedAt.value < ttl
    ) {
      return sessionUser.value
    }
    if (!opts.force && sessionUserPromise) {
      return await sessionUserPromise
    }

    sessionUserPromise = fetchApi('/api/me')
      .then(async (res) => {
        const data = await readApiJson<SessionUser>(res)
        setSessionUser(data)
        return data
      })
      .catch(failure => {
        if (failure instanceof ApiError && failure.status === 401 && failure.code === 'auth.session_required') {
          markSessionExpired()
          return null
        }
        throw failure
      })
      .finally(() => {
        sessionUserPromise = null
      })

    return await sessionUserPromise
  }

  async function loadBranding(opts: { force?: boolean } = {}) {
    if (!opts.force && brandingLoaded.value) return
    if (!opts.force && brandingPromise) return await brandingPromise
    brandingPromise = (async () => {
      try {
        const res = await fetch('/api/public/branding')
        if (!res.ok) return
        const data = await res.json() as Record<string, unknown>
        branding.value = {
          allowRegistration: data.allow_registration !== false,
          agreementsDefaultChecked: data.agreements_default_checked === true,
          supportEmail: typeof data.support_email === 'string' ? data.support_email : '',
          supportQqGroup: typeof data.support_qq_group === 'string' ? data.support_qq_group : '',
          supportQq: typeof data.support_qq === 'string' ? data.support_qq : '',
          supportWechat: typeof data.support_wechat === 'string' ? data.support_wechat : '',
          supportFooterNote: typeof data.support_footer_note === 'string' ? data.support_footer_note : '',
        }
        brandingLoaded.value = true
      } catch { /* ignore */ }
      finally {
        brandingPromise = null
      }
    })()
    await brandingPromise
  }

  async function loadVersion() {
    await Promise.all([
      (async () => {
        try {
          const res = await fetch('/api/version')
          if (res.ok) {
            const data = await res.json()
            version.value = data.version || ''
            brandName.value = data.brandName || 'Erocraft Manager'
            systemName.value = data.systemName || ''
            bannerUrl.value = data.bannerUrl || ''
            icpRecord.value = data.icpRecord || ''
            tutorialUrl.value = data.tutorialUrl || ''
            timezone.value = data.timezone || 'Asia/Shanghai'
            document.title = brandName.value
          }
        } catch { /* ignore */ }
      })(),
      loadBranding({ force: true }),
    ])
  }

  return {
    sidebarCollapsed,
    mobileSidebarOpen,
    isAdmin,
    hasOwnedServer,
    version,
    brandName,
    systemName,
    bannerUrl,
    hasSystemName,
    hasCustomBannerUrl,
    displayName,
    authBannerUrl,
    sidebarBannerUrl,
    footerText,
    icpRecord,
    tutorialUrl,
    timezone,
    branding,
    brandingLoaded,
    sessionUser,
    toggleSidebar,
    openMobileSidebar,
    closeMobileSidebar,
    toggleMobileSidebar,
    setIsAdmin,
    setSessionUser,
    clearSessionUser,
    markSessionExpired,
    fetchSessionUser,
    loadBranding,
    loadVersion,
  }
})

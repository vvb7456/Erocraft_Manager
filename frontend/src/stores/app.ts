import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

const DEFAULT_BANNER_URL = '/banner.png'
const SESSION_USER_TTL_MS = 30_000

interface SessionUser {
  ok: boolean
  username: string
  is_admin: boolean
  language: string
}

export const useAppStore = defineStore('app', () => {
  const sidebarCollapsed = ref(localStorage.getItem('sidebar_collapsed') === '1')
  const mobileSidebarOpen = ref(false)
  const isAdmin = ref(false)
  const version = ref('')
  const brandName = ref('Erocraft Manager')
  const systemName = ref('')
  const bannerUrl = ref('')
  const icpRecord = ref('')
  const timezone = ref('Asia/Shanghai')
  const sessionUser = ref<SessionUser | null>(null)
  const sessionUserFetchedAt = ref(0)
  let sessionUserPromise: Promise<SessionUser | null> | null = null
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
  }

  function clearSessionUser() {
    sessionUserPromise = null
    setSessionUser(null)
  }

  async function fetchSessionUser(opts: { force?: boolean } = {}) {
    const now = Date.now()
    if (
      !opts.force
      && sessionUser.value
      && now - sessionUserFetchedAt.value < SESSION_USER_TTL_MS
    ) {
      return sessionUser.value
    }
    if (!opts.force && sessionUserPromise) {
      return await sessionUserPromise
    }

    sessionUserPromise = fetch('/api/me')
      .then(async (res) => {
        if (!res.ok) {
          clearSessionUser()
          return null
        }
        const data = await res.json() as SessionUser
        setSessionUser(data)
        return data
      })
      .catch(() => null)
      .finally(() => {
        sessionUserPromise = null
      })

    return await sessionUserPromise
  }

  async function loadVersion() {
    try {
      const res = await fetch('/api/version')
      if (res.ok) {
        const data = await res.json()
        version.value = data.version || ''
        brandName.value = data.brandName || 'Erocraft Manager'
        systemName.value = data.systemName || ''
        bannerUrl.value = data.bannerUrl || ''
        icpRecord.value = data.icpRecord || ''
        timezone.value = data.timezone || 'Asia/Shanghai'
        document.title = brandName.value
      }
    } catch { /* ignore */ }
  }

  return {
    sidebarCollapsed,
    mobileSidebarOpen,
    isAdmin,
    version,
    brandName,
    systemName,
    bannerUrl,
    hasSystemName,
    hasCustomBannerUrl,
    displayName,
    authBannerUrl,
    sidebarBannerUrl,
    icpRecord,
    timezone,
    sessionUser,
    toggleSidebar,
    openMobileSidebar,
    closeMobileSidebar,
    toggleMobileSidebar,
    setIsAdmin,
    setSessionUser,
    clearSessionUser,
    fetchSessionUser,
    loadVersion,
  }
})

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

const DEFAULT_BANNER_URL = '/banner.png'

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
    toggleSidebar,
    openMobileSidebar,
    closeMobileSidebar,
    toggleMobileSidebar,
    setIsAdmin,
    loadVersion,
  }
})

import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useAppStore = defineStore('app', () => {
  const sidebarCollapsed = ref(localStorage.getItem('sidebar_collapsed') === '1')
  const mobileSidebarOpen = ref(false)
  const version = ref('')
  const brandName = ref('Ptero Manager')
  const timezone = ref('Asia/Shanghai')

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

  async function loadVersion() {
    try {
      const res = await fetch('/api/version')
      if (res.ok) {
        const data = await res.json()
        version.value = data.version || ''
        brandName.value = data.brandName || 'Ptero Manager'
        timezone.value = data.timezone || 'Asia/Shanghai'
        document.title = brandName.value
      }
    } catch { /* ignore */ }
  }

  return {
    sidebarCollapsed,
    mobileSidebarOpen,
    version,
    brandName,
    timezone,
    toggleSidebar,
    openMobileSidebar,
    closeMobileSidebar,
    toggleMobileSidebar,
    loadVersion,
  }
})

<script setup lang="ts">
import { onMounted, computed } from 'vue'
import { RouterView, useRoute } from 'vue-router'
import AppSidebar from '@/components/layout/AppSidebar.vue'
import ToastContainer from '@/components/ui/ToastContainer.vue'
import ConfirmProvider from '@/components/ui/ConfirmProvider.vue'
import RenewFlowProvider from '@/components/billing/RenewFlowProvider.vue'
import SupportWidget from '@/components/support/SupportWidget.vue'
import SupportNotificationProvider from '@/components/support/SupportNotificationProvider.vue'
import { provideToast } from '@/composables/useToast'
import { useTheme } from '@/composables/useTheme'
import { providePageHeader } from '@/composables/usePageHeader'
import { useAppStore } from '@/stores/app'

defineOptions({ name: 'App' })

provideToast()
useTheme()
providePageHeader()

const app = useAppStore()
const route = useRoute()

const isBlankLayout = computed(() => route.meta.layout === 'blank')

onMounted(() => {
  app.loadVersion()
})

function onOverlayClick() {
  app.closeMobileSidebar()
}
</script>

<template>
  <ConfirmProvider>
  <SupportNotificationProvider>
  <!-- Blank layout for login -->
  <template v-if="isBlankLayout">
    <RouterView />
  </template>

  <!-- Main layout with sidebar -->
  <template v-else>
    <div
      class="mobile-overlay"
      :class="{ active: app.mobileSidebarOpen }"
      @click="onOverlayClick"
    />

    <AppSidebar />

    <main class="content" :class="{ 'sidebar-collapsed': app.sidebarCollapsed }">
      <RouterView />
    </main>
  </template>

  <ToastContainer />
  <RenewFlowProvider />
  <SupportWidget v-if="app.sessionUser && !app.isAdmin && !route.meta.public && route.name !== 'user-support'" :key="app.sessionUser.username" />
  </SupportNotificationProvider>
  </ConfirmProvider>
</template>

<style scoped>
.content { margin-left: var(--sidebar-w); min-width: 0; flex: 1; height: 100dvh; overflow-y: auto; transition: margin-left .25s ease; }
.content.sidebar-collapsed { margin-left: 56px; }
.content :deep(.page-header + .page-body) { padding-top: var(--sp-3); }
@media (max-width: 768px) { .content, .content.sidebar-collapsed { margin-left: 0; } }
</style>

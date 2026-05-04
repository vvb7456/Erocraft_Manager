<script setup lang="ts">
import { onMounted, computed } from 'vue'
import { RouterView, useRoute } from 'vue-router'
import AppSidebar from '@/components/layout/AppSidebar.vue'
import ToastContainer from '@/components/ui/ToastContainer.vue'
import ConfirmProvider from '@/components/ui/ConfirmProvider.vue'
import RenewFlowProvider from '@/components/billing/RenewFlowProvider.vue'
import { provideToast } from '@/composables/useToast'
import { useTheme } from '@/composables/useTheme'
import { useAppStore } from '@/stores/app'

defineOptions({ name: 'App' })

provideToast()
useTheme()

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
  </ConfirmProvider>
</template>

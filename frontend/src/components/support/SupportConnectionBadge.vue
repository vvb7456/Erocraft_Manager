<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { supportConnectionStatus } from '@/composables/useSupportEvents'

const { t } = useI18n()
const status = ref(supportConnectionStatus.value)
let timer: ReturnType<typeof setTimeout> | undefined
watch(supportConnectionStatus, value => {
  clearTimeout(timer)
  // Brief reconnects are normal during session reauthentication; avoid flashing the badge.
  if (value === 'reconnecting' && status.value === 'connected') timer = setTimeout(() => { status.value = value }, 2500)
  else status.value = value
})
onBeforeUnmount(() => clearTimeout(timer))
</script>

<template>
  <span class="connection-status" :data-state="status" role="status"><span class="status-dot" />{{ t(`support.connection.${status}`) }}</span>
</template>

<style scoped>
.connection-status { display: inline-flex; flex-shrink: 0; align-items: center; gap: var(--sp-1); padding: var(--sp-1) var(--sp-2); border-radius: var(--r-pill); color: var(--t3); background: var(--bg3); font-size: var(--text-xs); line-height: 1.2; white-space: nowrap; }
.status-dot { width: 5px; height: 5px; border-radius: 50%; background: currentColor; }
.connection-status[data-state="connected"] { color: var(--ac); background: color-mix(in srgb, var(--ac) 9%, transparent); }
.connection-status[data-state="offline"], .connection-status[data-state="disconnected"] { color: var(--red); background: color-mix(in srgb, var(--red) 8%, transparent); }
</style>

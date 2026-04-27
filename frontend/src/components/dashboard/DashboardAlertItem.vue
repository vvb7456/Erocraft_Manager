<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import MsIcon from '@/components/ui/MsIcon.vue'

defineOptions({ name: 'DashboardAlertItem' })

const props = defineProps<{
  alertType: string
  severity: string
  message?: string | null
  hostName?: string | null
  createdAt: string
}>()

const { t, te } = useI18n({ useScope: 'global' })

const timeAgo = computed(() => {
  const hasTz = /Z|[+-]\d{2}:?\d{2}$/.test(props.createdAt)
  const ts = new Date(hasTz ? props.createdAt : props.createdAt + 'Z').getTime()
  if (Number.isNaN(ts)) return '--'
  const delta = Math.max(0, Math.floor((Date.now() - ts) / 1000))
  if (delta < 60) return `${delta}s`
  if (delta < 3600) return `${Math.floor(delta / 60)}m`
  if (delta < 86400) return `${Math.floor(delta / 3600)}h`
  return `${Math.floor(delta / 86400)}d`
})

const alertTypeLabel = computed(() => {
  const key = `monitoring.alertType.${props.alertType}`
  return te(key) ? t(key) : props.alertType
})

const severityClass = computed(() => `sev-${props.severity}`)
</script>

<template>
  <div class="alert-item" :class="severityClass">
    <span class="bar" />
    <div class="body">
      <div class="line1">
        <span class="type">{{ alertTypeLabel }}</span>
        <span class="ago">{{ timeAgo }}</span>
      </div>
      <div class="line2">
        <span v-if="hostName" class="host"><MsIcon name="dns" size="xs" />{{ hostName }}</span>
        <span v-if="message" class="msg" :title="message">{{ message }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.alert-item {
  display: flex;
  gap: var(--sp-3);
  padding: var(--sp-2) var(--sp-3);
  border-radius: var(--r-md);
  background: var(--bg3);
  position: relative;
  overflow: hidden;
}
.bar {
  width: 3px;
  flex-shrink: 0;
  border-radius: 2px;
  background: var(--t3);
}
.alert-item.sev-critical .bar { background: var(--red); }
.alert-item.sev-warning .bar { background: var(--amber); }
.alert-item.sev-info .bar { background: var(--blue); }

.body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1;
}
.line1 {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: var(--sp-2);
}
.type {
  font-weight: 600;
  font-size: var(--text-sm);
  color: var(--t1);
}
.alert-item.sev-critical .type { color: var(--red); }
.alert-item.sev-warning .type { color: var(--amber); }
.alert-item.sev-info .type { color: var(--blue); }

.ago {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--t3);
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
}
.line2 {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: var(--text-xs);
  color: var(--t2);
  min-width: 0;
}
.host {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  flex-shrink: 0;
  font-family: var(--font-mono);
}
.msg {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
  min-width: 0;
}
</style>

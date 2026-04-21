<script setup lang="ts">
import StatusDot from '@/components/ui/StatusDot.vue'
import { useI18n } from 'vue-i18n'

defineOptions({ name: 'ProbeStatus' })

export interface ProbeData {
  name: string
  ok: boolean
  latencyMs: number | null
  source: string
  ts: string | null
}

defineProps<{ probes: ProbeData[] }>()
const { t } = useI18n({ useScope: 'global' })

function probeName(name: string): string {
  const map: Record<string, string> = {
    clash_proxy: t('monitoring.probe.names.clashProxy'),
    pve_host: t('monitoring.probe.names.pveHost'),
  }
  if (map[name]) return map[name]
  if (name.startsWith('wings_pub_')) return t('monitoring.probe.names.wingsPub', { id: name.slice(10) })
  return name
}
</script>

<template>
  <div class="probe-grid">
    <div v-for="p in probes" :key="p.name" class="probe-item">
      <StatusDot :status="p.ok ? 'online' : 'error'" size="sm" />
      <span class="probe-name">{{ probeName(p.name) }}</span>
      <span v-if="p.ok && p.latencyMs != null" class="probe-latency">
        {{ p.latencyMs.toFixed(0) }}ms
      </span>
      <span v-else-if="!p.ok" class="probe-fail">{{ t('monitoring.probe.failed') }}</span>
    </div>
    <div v-if="probes.length === 0" class="probe-empty">
      {{ t('monitoring.probe.none') }}
    </div>
  </div>
</template>

<style scoped>
.probe-grid {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-3) var(--sp-6);
}

.probe-item {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: var(--text-sm);
}

.probe-name {
  color: var(--t2);
}

.probe-latency {
  color: var(--t3);
  font-variant-numeric: tabular-nums;
  font-family: var(--font-mono);
  font-size: var(--text-xs);
}

.probe-fail {
  color: var(--red);
  font-size: var(--text-xs);
  font-weight: 500;
}

.probe-empty {
  color: var(--t3);
  font-size: var(--text-sm);
}
</style>

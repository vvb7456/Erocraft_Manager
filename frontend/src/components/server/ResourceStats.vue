<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { fmtBytes } from '@/utils/format'
import UsageBar from '@/components/ui/UsageBar.vue'

defineOptions({ name: 'ResourceStats' })

const props = defineProps<{
  cpuPercent: number
  memoryBytes: number
  diskBytes: number
  networkRx: number
  networkTx: number
  uptimeMs: number
  limits: { memory: number; disk: number; cpu: number }
  /** 'desktop' = vertical with labels + bars; 'mobile' = compact grid */
  layout?: 'desktop' | 'mobile'
  /** Hide the uptime row (parent renders it elsewhere). */
  hideUptime?: boolean
}>()

const { t } = useI18n({ useScope: 'global' })

function memPercent(): number {
  if (!props.limits.memory) return 0
  return Math.min(100, (props.memoryBytes / (props.limits.memory * 1024 * 1024)) * 100)
}

function diskPercent(): number {
  if (!props.limits.disk) return 0
  return Math.min(100, (props.diskBytes / (props.limits.disk * 1024 * 1024)) * 100)
}

function memLimit(): string {
  if (!props.limits.memory) return '∞'
  const mb = props.limits.memory
  return mb >= 1024 ? (mb / 1024).toFixed(1) + ' GB' : mb + ' MB'
}

function diskLimit(): string {
  if (!props.limits.disk) return '∞'
  const mb = props.limits.disk
  return mb >= 1024 ? (mb / 1024).toFixed(1) + ' GB' : mb + ' MB'
}

function cpuLimit(): string {
  if (!props.limits.cpu) return '∞'
  return props.limits.cpu + '%'
}

function formatUptime(ms: number): string {
  if (ms <= 0) return '—'
  const s = Math.floor(ms / 1000)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  if (h > 0) return `${h}h ${m}m`
  return `${m}m ${s % 60}s`
}
</script>

<template>
  <!-- Desktop layout -->
  <div v-if="layout !== 'mobile'" class="stats-grid">
    <div class="stat-row">
      <div class="stat-header">
        <span class="stat-label">{{ t('userServers.resources.cpu') }}</span>
        <span class="stat-value">{{ cpuPercent.toFixed(1) }}% <span class="stat-limit">/ {{ cpuLimit() }}</span></span>
      </div>
      <UsageBar :percent="cpuPercent" />
    </div>
    <div class="stat-row">
      <div class="stat-header">
        <span class="stat-label">{{ t('userServers.resources.memory') }}</span>
        <span class="stat-value">{{ fmtBytes(memoryBytes) }} <span class="stat-limit">/ {{ memLimit() }}</span></span>
      </div>
      <UsageBar :percent="memPercent()" />
    </div>
    <div class="stat-row">
      <div class="stat-header">
        <span class="stat-label">{{ t('userServers.resources.disk') }}</span>
        <span class="stat-value">{{ fmtBytes(diskBytes) }} <span class="stat-limit">/ {{ diskLimit() }}</span></span>
      </div>
      <UsageBar :percent="diskPercent()" />
    </div>
    <div class="stat-row stat-row--inline">
      <span class="stat-label">{{ t('userServers.resources.network') }}</span>
      <span class="stat-value">
        <span class="net-up">↑ {{ fmtBytes(networkTx) }}</span>
        <span class="net-down">↓ {{ fmtBytes(networkRx) }}</span>
      </span>
    </div>
    <div v-if="!hideUptime" class="stat-row stat-row--inline">
      <span class="stat-label">{{ t('userServers.resources.uptime') }}</span>
      <span class="stat-value">{{ formatUptime(uptimeMs) }}</span>
    </div>
  </div>

  <!-- Mobile layout -->
  <div v-else class="mobile-stats">
    <div class="mobile-stat">
      <div class="stat-header" style="margin-top: auto">
        <span class="mobile-stat-label">CPU</span>
        <span class="mobile-stat-value">{{ cpuPercent.toFixed(1) }}% / {{ cpuLimit() }}</span>
      </div>
      <UsageBar :percent="cpuPercent" class="mobile-stat-bar" />
    </div>
    <div class="mobile-stat">
      <div class="stat-header" style="margin-top: auto">
        <span class="mobile-stat-label">{{ t('userServers.resources.memory') }}</span>
        <span class="mobile-stat-value">{{ fmtBytes(memoryBytes) }} / {{ memLimit() }}</span>
      </div>
      <UsageBar :percent="memPercent()" class="mobile-stat-bar" />
    </div>
    <div class="mobile-stat">
      <div class="stat-header" style="margin-top: auto">
        <span class="mobile-stat-label">{{ t('userServers.resources.disk') }}</span>
        <span class="mobile-stat-value">{{ fmtBytes(diskBytes) }} / {{ diskLimit() }}</span>
      </div>
      <UsageBar :percent="diskPercent()" class="mobile-stat-bar" />
    </div>
    <div class="mobile-stat">
      <span class="mobile-stat-label">{{ t('userServers.resources.network') }}</span>
      <span class="mobile-stat-value" style="margin-top: auto">↑{{ fmtBytes(networkTx) }} ↓{{ fmtBytes(networkRx) }}</span>
    </div>
  </div>
</template>

<style scoped>
/* ── Desktop stats ── */
.stats-grid {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

.stat-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.stat-row--inline {
  flex-direction: row;
  justify-content: space-between;
  align-items: center;
  gap: var(--sp-2);
}

.stat-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}

.stat-label {
  font-size: var(--text-xs);
  color: var(--t3);
  font-weight: 500;
}

.stat-value {
  font-family: 'IBM Plex Mono', monospace;
  font-size: var(--text-xs);
  color: var(--t1);
}

.stat-limit {
  color: var(--t3);
  font-size: var(--text-xs);
}

.net-up, .net-down {
  margin-left: var(--sp-1);
}

.net-up { color: var(--ac2); }
.net-down { color: var(--blue); }

/* ── Mobile stats ── */
.mobile-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: var(--sp-3);
}

.mobile-stat {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.mobile-stat-label {
  font-size: var(--text-xs);
  color: var(--t3);
  font-weight: 500;
}

.mobile-stat-value {
  font-family: 'IBM Plex Mono', monospace;
  font-size: var(--text-xs);
  color: var(--t1);
}

.mobile-stat-bar {
  margin-top: 2px;
}

@media (max-width: 480px) {
  .mobile-stats {
    grid-template-columns: 1fr 1fr;
  }
}
</style>

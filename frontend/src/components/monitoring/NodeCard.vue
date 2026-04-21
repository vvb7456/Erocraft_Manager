<script setup lang="ts">
import StatusDot from '@/components/ui/StatusDot.vue'
import UsageBar from '@/components/ui/UsageBar.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

defineOptions({ name: 'NodeCard' })

export interface NodeData {
  id: number
  name: string
  fqdn: string
  agentOnline: boolean
  wingsOnline: boolean
  publicReachable: boolean | null
  lastSeen: string | null
  wingsVersion: string | null
  cpuPct: number | null
  cpuCores: number | null
  loadAvg: number[] | null
  memUsedMb: number | null
  memTotalMb: number | null
  memPct: number | null
  swapUsedMb: number | null
  swapTotalMb: number | null
  uptimeSec: number | null
  diskUsedMb: number | null
  diskTotalMb: number | null
  diskPct: number | null
  netRxBps: number | null
  netTxBps: number | null
  containerTotal: number | null
  containerRunning: number | null
  containerMemMb: number | null
  containerCpuPct: number | null
  containerDiskMb: number | null
  activeAlerts: number
}

const props = defineProps<{ node: NodeData }>()
// NOTE(CR §5.8): click emit removed until Phase-2 node-detail page lands.
// When the detail route exists, re-add ``defineEmits<{ click: [id: number] }>()``
// + ``@click`` on the root + restore ``cursor: pointer`` in scoped styles.
const { t } = useI18n({ useScope: 'global' })

/* ─ Overall status dot ─ */
const overallStatus = computed(() => {
  if (props.node.agentOnline && props.node.wingsOnline) return 'online'
  if (props.node.agentOnline || props.node.wingsOnline) return 'loading'
  return 'offline'
})

/* ─ Tri-state indicator helpers ─ */
type TriState = 'ok' | 'warn' | 'down' | 'unknown'
function triState(val: boolean | null | undefined): TriState {
  if (val === true) return 'ok'
  if (val === false) return 'down'
  return 'unknown'
}
const agentState = computed<TriState>(() => triState(props.node.agentOnline))
const wingsState = computed<TriState>(() => triState(props.node.wingsOnline))
const publicState = computed<TriState>(() => triState(props.node.publicReachable))

/* ─ Formatters ─ */
function formatBytes(bps: number | null): string {
  if (bps == null) return '--'
  if (bps < 1024) return bps + ' B/s'
  if (bps < 1024 * 1024) return (bps / 1024).toFixed(1) + ' KB/s'
  return (bps / 1024 / 1024).toFixed(1) + ' MB/s'
}
function formatMb(mb: number | null | undefined): string {
  if (mb == null) return '--'
  if (mb >= 1024) return (mb / 1024).toFixed(1) + 'G'
  return mb + 'M'
}
function formatUptime(sec: number | null): string {
  if (sec == null || sec <= 0) return '--'
  const d = Math.floor(sec / 86400)
  const h = Math.floor((sec % 86400) / 3600)
  const m = Math.floor((sec % 3600) / 60)
  if (d > 0) return `${d}d ${h}h`
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}
function formatAgo(iso: string | null): { text: string; stale: boolean } {
  if (!iso) return { text: '--', stale: true }
  // Backend returns naive UTC timestamps (no tz suffix). Append Z so Date parses as UTC.
  const hasTz = /Z|[+-]\d{2}:?\d{2}$/.test(iso)
  const ts = new Date(hasTz ? iso : iso + 'Z').getTime()
  if (Number.isNaN(ts)) return { text: '--', stale: true }
  const delta = Math.max(0, Math.floor((Date.now() - ts) / 1000))
  let text: string
  if (delta < 60) text = `${delta}s`
  else if (delta < 3600) text = `${Math.floor(delta / 60)}m`
  else if (delta < 86400) text = `${Math.floor(delta / 3600)}h`
  else text = `${Math.floor(delta / 86400)}d`
  return { text, stale: delta > 90 }
}
const lastSeenInfo = computed(() => formatAgo(props.node.lastSeen))
</script>

<template>
  <div class="node-card">
    <!-- Header -->
    <div class="nc-header">
      <div class="nc-title">
        <StatusDot :status="overallStatus" />
        <span class="nc-name">{{ node.name }}</span>
        <span v-if="node.wingsVersion" class="nc-pill">{{ node.wingsVersion }}</span>
        <span v-if="node.cpuCores" class="nc-pill nc-pill--cores">
          {{ t('monitoring.node.cores', { n: node.cpuCores }) }}
        </span>
        <span v-if="node.activeAlerts > 0" class="nc-alert">
          <MsIcon name="warning" size="sm" />
          {{ node.activeAlerts }}
        </span>
      </div>
      <div class="nc-conn">
        <span class="nc-conn-cell" :class="`s-${agentState}`" :title="t('monitoring.node.agent')">A</span>
        <span class="nc-conn-cell" :class="`s-${wingsState}`" :title="t('monitoring.node.wings')">W</span>
        <span class="nc-conn-cell" :class="`s-${publicState}`" :title="t('monitoring.node.public')">P</span>
      </div>
    </div>

    <!-- Sub-header: fqdn · uptime · last seen -->
    <div class="nc-sub">
      <span class="nc-fqdn">{{ node.fqdn }}</span>
      <template v-if="node.uptimeSec">
        <span class="nc-dot">·</span>
        <span>{{ t('monitoring.node.up') }} {{ formatUptime(node.uptimeSec) }}</span>
      </template>
      <span class="nc-dot">·</span>
      <span :class="{ 'nc-stale': lastSeenInfo.stale }">
        {{ t('monitoring.node.lastSeen') }} {{ t('monitoring.node.ago', { v: lastSeenInfo.text }) }}
      </span>
    </div>

    <!-- Metrics -->
    <div v-if="node.agentOnline" class="nc-metrics">
      <div class="m-row">
        <span class="m-label">{{ t('monitoring.node.cpu') }}</span>
        <UsageBar :percent="node.cpuPct ?? 0" :height="8" :danger="85" class="m-bar" />
        <span class="m-value">{{ node.cpuPct != null ? node.cpuPct + '%' : '--' }}</span>
        <span class="m-sub">
          <template v-if="node.loadAvg && node.loadAvg.length">
            {{ t('monitoring.node.load') }}
            <span class="m-mono">{{ (node.loadAvg[0] ?? 0).toFixed(2) }}</span>
            <span class="m-mono">{{ (node.loadAvg[1] ?? 0).toFixed(2) }}</span>
            <span class="m-mono">{{ (node.loadAvg[2] ?? 0).toFixed(2) }}</span>
          </template>
        </span>
      </div>
      <div class="m-row">
        <span class="m-label">{{ t('monitoring.node.mem') }}</span>
        <UsageBar :percent="node.memPct ?? 0" :height="8" :danger="85" class="m-bar" />
        <span class="m-value">{{ node.memPct != null ? node.memPct + '%' : '--' }}</span>
        <span class="m-sub">
          <span class="m-mono">{{ formatMb(node.memUsedMb) }}/{{ formatMb(node.memTotalMb) }}</span>
          <template v-if="node.swapTotalMb && node.swapTotalMb > 0">
            <span class="nc-dot">·</span>
            {{ t('monitoring.node.swap') }}
            <span class="m-mono">{{ formatMb(node.swapUsedMb) }}/{{ formatMb(node.swapTotalMb) }}</span>
          </template>
        </span>
      </div>
      <div class="m-row">
        <span class="m-label">{{ t('monitoring.node.dsk') }}</span>
        <UsageBar :percent="node.diskPct ?? 0" :height="8" :danger="85" class="m-bar" />
        <span class="m-value">{{ node.diskPct != null ? node.diskPct + '%' : '--' }}</span>
        <span class="m-sub">
          <span class="m-mono">{{ formatMb(node.diskUsedMb) }}/{{ formatMb(node.diskTotalMb) }}</span>
        </span>
      </div>
    </div>
    <div v-else class="nc-no-agent">
      <MsIcon name="cloud_off" size="sm" />
      <span>{{ t('monitoring.node.noAgent') }}</span>
    </div>

    <!-- Footer -->
    <div class="nc-footer">
      <span v-if="node.containerTotal != null" class="nc-containers">
        <MsIcon name="dns" size="sm" />
        <span class="m-mono">{{ node.containerRunning ?? 0 }}/{{ node.containerTotal }}</span>
        {{ t('monitoring.node.containers') }}
        <template v-if="node.containerCpuPct != null">
          <span class="nc-dot">·</span>
          CPU <span class="m-mono">{{ node.containerCpuPct.toFixed(0) }}%</span>
        </template>
        <template v-if="node.containerMemMb != null">
          <span class="nc-dot">·</span>
          MEM <span class="m-mono">{{ formatMb(node.containerMemMb) }}</span>
        </template>
        <template v-if="node.containerDiskMb != null">
          <span class="nc-dot">·</span>
          DSK <span class="m-mono">{{ formatMb(node.containerDiskMb) }}</span>
        </template>
      </span>
      <span v-if="node.netRxBps != null || node.netTxBps != null" class="nc-net">
        <span class="m-mono">↓ {{ formatBytes(node.netRxBps) }}</span>
        <span class="m-mono">↑ {{ formatBytes(node.netTxBps) }}</span>
      </span>
    </div>
  </div>
</template>

<style scoped>
.node-card {
  background: var(--bg3);
  border: 1px solid var(--bd);
  border-radius: var(--r-lg);
  padding: var(--sp-4) var(--sp-5);
  transition: border-color .15s ease, box-shadow .15s ease;
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.node-card:hover {
  border-color: var(--bd-f);
  box-shadow: 0 0 8px color-mix(in srgb, var(--ac) 15%, transparent);
}

/* ─ Header ─ */
.nc-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--sp-3);
}
.nc-title {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  min-width: 0;
  flex: 1;
}
.nc-name {
  font-weight: 600;
  font-size: var(--text-md);
  color: var(--t1);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.nc-pill {
  font-size: var(--text-xs);
  color: var(--t3);
  font-family: var(--font-mono);
  background: var(--bg);
  padding: 1px 6px;
  border-radius: var(--r-sm);
  white-space: nowrap;
}
.nc-pill--cores { color: var(--blue); }
.nc-alert {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  color: var(--amber);
  font-weight: 600;
  font-size: var(--text-xs);
}

/* ─ Connectivity tri-indicator ─ */
.nc-conn {
  display: inline-flex;
  border: 1px solid var(--bd);
  border-radius: var(--r-sm);
  overflow: hidden;
  flex-shrink: 0;
}
.nc-conn-cell {
  width: 22px;
  height: 20px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: var(--text-xs);
  font-weight: 700;
  font-family: var(--font-mono);
  border-right: 1px solid var(--bd);
}
.nc-conn-cell:last-child { border-right: none; }
.nc-conn-cell.s-ok { background: color-mix(in srgb, var(--green) 18%, transparent); color: var(--green); }
.nc-conn-cell.s-warn { background: color-mix(in srgb, var(--amber) 18%, transparent); color: var(--amber); }
.nc-conn-cell.s-down { background: color-mix(in srgb, var(--red) 18%, transparent); color: var(--red); }
.nc-conn-cell.s-unknown { background: var(--bg); color: var(--t3); }

/* ─ Sub-header ─ */
.nc-sub {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-1);
  font-size: var(--text-xs);
  color: var(--t3);
  font-variant-numeric: tabular-nums;
}
.nc-fqdn { font-family: var(--font-mono); }
.nc-dot { opacity: .5; }
.nc-stale { color: var(--red); }

/* ─ Metrics rows ─ */
.nc-metrics {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.m-row {
  display: grid;
  grid-template-columns: 1fr auto;
  row-gap: 4px;
}
.m-label {
  font-size: var(--text-xs);
  color: var(--t3);
  font-weight: 600;
  font-family: var(--font-mono);
  letter-spacing: 0.5px;
  grid-column: 1;
  grid-row: 1;
}
.m-value {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--t1);
  text-align: right;
  font-variant-numeric: tabular-nums;
  grid-column: 2;
  grid-row: 1;
}
.m-bar {
  min-width: 0;
  grid-column: 1 / 3;
  grid-row: 2;
}

.m-sub {
  font-size: var(--text-xs);
  color: var(--t3);
  display: inline-flex;
  align-items: center;
  gap: 4px;
  white-space: nowrap;
  min-width: 0;
  grid-column: 1 / 3;
  grid-row: 3;
  overflow: hidden;
  text-overflow: ellipsis;
  justify-content: flex-end;
}
.m-mono {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}

/* ─ No agent banner ─ */
.nc-no-agent {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  color: var(--t3);
  font-size: var(--text-sm);
  padding: var(--sp-3) 0;
}

/* ─ Footer ─ */
.nc-footer {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  padding-top: var(--sp-2);
  border-top: 1px solid var(--bd);
  font-size: var(--text-xs);
  color: var(--t3);
}
.nc-containers,
.nc-net {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}
.nc-net { gap: var(--sp-3); margin-left: auto; }

/* ─ Mobile tightening ─ */
@media (max-width: 480px) {
  .nc-sub { font-size: calc(var(--text-xs) - 1px); }
}
</style>

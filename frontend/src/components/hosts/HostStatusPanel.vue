<script setup lang="ts">
// HostStatusPanel — composite ECharts status panel for the overview tab.
//
// Pulls /api/admin/hosts/{hostId}/snapshot every 30s and renders:
//   - heartbeat / connectivity chips
//   - 4 gauges (CPU / MEM / DSK / LD)
//   - stats grid (cores, mem, swap, net, containers)
//   - 2 hero trend mini-charts (CPU 1h, MEM 1h)
//
// Threshold colors come from a fixed default for now (see TODO);
// per-host alert rules will replace them in C8 once the alerting
// settings API lands.
import {
  computed, onBeforeUnmount, onMounted, ref, watch,
} from 'vue'
import { useI18n } from 'vue-i18n'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { GaugeChart } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useApiFetch } from '@/composables/useApiFetch'
import Spinner from '@/components/ui/Spinner.vue'
import Badge from '@/components/ui/Badge.vue'
import StatusDot from '@/components/ui/StatusDot.vue'
import HostMetricsChart from '@/components/hosts/HostMetricsChart.vue'

use([GaugeChart, TooltipComponent, CanvasRenderer])

defineOptions({ name: 'HostStatusPanel' })

const props = defineProps<{
  hostId: number
  kind: string
}>()

const { t } = useI18n({ useScope: 'global' })
const { get } = useApiFetch()

interface SnapshotMetrics {
  ts: string
  agentOnline: boolean
  wingsOnline: boolean
  publicReachable: boolean | null
  cpuPct: number | null
  cpuCores: number | null
  memUsedMb: number | null
  memTotalMb: number | null
  memPct: number | null
  swapUsedMb: number | null
  swapTotalMb: number | null
  diskUsedMb: number | null
  diskTotalMb: number | null
  diskPct: number | null
  load1m: number | null
  load5m: number | null
  load15m: number | null
  uptimeSec: number | null
  netRxBps: number | null
  netTxBps: number | null
  containerTotal: number | null
  containerRunning: number | null
  containerMemMb: number | null
  containerCpuPct: number | null
  containerDiskMb: number | null
  wingsVersion: string | null
}

interface SnapshotResponse {
  hostId: number
  name: string
  kind: string
  enabled: boolean
  inboundReachable: boolean
  lastSeenAt: string | null
  lastStatusAt: string | null
  metrics: SnapshotMetrics | null
  probes: Array<{ name: string; ok: boolean; ts: string }>
}

const snap = ref<SnapshotResponse | null>(null)
const loading = ref(false)
let pollTimer: number | null = null

async function fetchSnapshot() {
  if (!Number.isFinite(props.hostId)) return
  loading.value = true
  try {
    const data = await get<SnapshotResponse>(`/api/admin/hosts/${props.hostId}/snapshot`)
    if (data) snap.value = data
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchSnapshot()
  pollTimer = window.setInterval(fetchSnapshot, 30_000)
})
onBeforeUnmount(() => { if (pollTimer !== null) clearInterval(pollTimer) })
watch(() => props.hostId, () => { snap.value = null; fetchSnapshot() })

// Theme tokens
type Tokens = { ac: string; t1: string; t3: string; bd: string; bg2: string; green: string; amber: string; red: string }
const tokens = ref<Tokens>({
  ac: '#14b8a6', t1: '#e4ece8', t3: '#5a706a', bd: '#263434', bg2: '#182020',
  green: '#34d399', amber: '#f59e0b', red: '#ef6060',
})
function readTokens() {
  if (typeof document === 'undefined') return
  const cs = getComputedStyle(document.documentElement)
  const pick = (n: string, fb: string) => cs.getPropertyValue(n).trim() || fb
  tokens.value = {
    ac: pick('--ac', tokens.value.ac),
    t1: pick('--t1', tokens.value.t1),
    t3: pick('--t3', tokens.value.t3),
    bd: pick('--bd', tokens.value.bd),
    bg2: pick('--bg2', tokens.value.bg2),
    green: pick('--green', tokens.value.green),
    amber: pick('--amber', tokens.value.amber),
    red: pick('--red', tokens.value.red),
  }
}
let themeObserver: MutationObserver | null = null
onMounted(() => {
  readTokens()
  themeObserver = new MutationObserver(readTokens)
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'data-theme'] })
})
onBeforeUnmount(() => { themeObserver?.disconnect() })

// Default thresholds (will be replaced by per-host alert rules in C8)
const DEFAULT_THRESHOLDS = {
  cpu: { warn: 90, crit: 100 },
  mem: { warn: 90, crit: 100 },
  disk: { warn: 85, crit: 95 },
  load: { warn: 1.5, crit: 2.0 }, // multipliers of cpu_cores
}

const metrics = computed(() => snap.value?.metrics)
const isWings = computed(() => props.kind === 'wings_node')
const chartHostId = computed(() => props.hostId)

const heartbeatAge = computed(() => {
  const ts = snap.value?.lastSeenAt
  if (!ts) return null
  const hasTz = /Z|[+-]\d{2}:?\d{2}$/.test(ts)
  const t = new Date(hasTz ? ts : ts + 'Z').getTime()
  if (Number.isNaN(t)) return null
  const diffMs = Date.now() - t
  return Math.max(0, Math.round(diffMs / 1000))
})

function fmtAge(sec: number | null): string {
  if (sec == null) return '—'
  if (sec < 60) return `${sec}s`
  if (sec < 3600) return `${Math.floor(sec / 60)}m`
  if (sec < 86400) return `${Math.floor(sec / 3600)}h`
  return `${Math.floor(sec / 86400)}d`
}

function fmtBytes(mb: number | null): string {
  if (mb == null) return '—'
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GiB`
  return `${mb} MiB`
}

function fmtRate(bps: number | null): string {
  if (bps == null) return '—'
  if (bps >= 1024 * 1024) return `${(bps / 1024 / 1024).toFixed(1)} MB/s`
  if (bps >= 1024) return `${(bps / 1024).toFixed(1)} KB/s`
  return `${bps} B/s`
}

const heartbeatTone = computed<'green' | 'amber' | 'red' | 'muted'>(() => {
  if (!snap.value?.enabled) return 'muted'
  const age = heartbeatAge.value
  if (age == null) return 'muted'
  if (age <= 90) return 'green'
  if (age <= 300) return 'amber'
  return 'red'
})

function gaugeOption(value: number | null, warn: number, crit: number, max = 100, formatter?: (v: number) => string) {
  const tk = tokens.value
  const v = value ?? 0
  return {
    backgroundColor: 'transparent',
    series: [{
      type: 'gauge',
      min: 0,
      max,
      // 260° arc — the original "open-bottom" look the user prefers.
      // Card-level header above the chart shows the label + value, so the
      // chart itself only renders the dial; no center detail text.
      startAngle: 220,
      endAngle: -40,
      radius: '78%',
      center: ['50%', '62%'],
      // No progress arc — the user wants the static three-band threshold
      // arc to be the only colored arc on the dial; severity is read from
      // the pointer position against those bands.
      progress: { show: false },
      pointer: {
        show: true,
        length: '78%',
        width: 4,
        itemStyle: { color: tk.t1 },
      },
      axisLine: {
        lineStyle: {
          width: 12,
          color: [
            [warn / max, tk.ac],
            [crit / max, tk.amber],
            [1, tk.red],
          ],
        },
      },
      axisTick: { show: false },
      splitLine: { show: false },
      axisLabel: { show: false },
      anchor: {
        show: true,
        size: 8,
        showAbove: true,
        itemStyle: { color: tk.t1 },
      },
      title: { show: false },
      detail: {
        // Sit in the open bottom of the 260° arc — pointer angles span
        // 220° → -40° (going through the top), so the bottom 100° wedge is
        // never crossed by the needle. Detail can never overlap the pointer.
        valueAnimation: false,
        offsetCenter: [0, '60%'],
        fontSize: 22,
        fontWeight: 600,
        color: tk.t1,
        formatter: () => (formatter ? formatter(v) : `${Math.round(v)}%`),
      },
      data: [{ value: v }],
    }],
  }
}

const cpuOption = computed(() => gaugeOption(
  metrics.value?.cpuPct ?? null,
  DEFAULT_THRESHOLDS.cpu.warn,
  DEFAULT_THRESHOLDS.cpu.crit,
))
const memOption = computed(() => gaugeOption(
  metrics.value?.memPct ?? null,
  DEFAULT_THRESHOLDS.mem.warn,
  DEFAULT_THRESHOLDS.mem.crit,
))
const diskOption = computed(() => gaugeOption(
  metrics.value?.diskPct ?? null,
  DEFAULT_THRESHOLDS.disk.warn,
  DEFAULT_THRESHOLDS.disk.crit,
))
const loadOption = computed(() => {
  const cores = metrics.value?.cpuCores ?? 1
  const max = Math.max(cores * 2, 2)
  const warn = cores * DEFAULT_THRESHOLDS.load.warn
  const crit = cores * DEFAULT_THRESHOLDS.load.crit
  return gaugeOption(
    metrics.value?.load1m ?? null, warn, crit, max,
    (v) => v.toFixed(2),
  )
})
</script>

<template>
  <section class="panel">
    <!-- header chips -->
    <header class="hdr">
      <Badge
        :color="heartbeatTone === 'green' ? 'var(--green)' : heartbeatTone === 'amber' ? 'var(--amber)' : heartbeatTone === 'red' ? 'var(--red)' : 'var(--t3)'"
        size="sm"
      >
        <StatusDot :status="heartbeatTone === 'green' ? 'running' : heartbeatTone === 'red' ? 'error' : 'stopped'" size="sm" />
        {{ t('hosts.overview.chip.heartbeat', { age: fmtAge(heartbeatAge) }) }}
      </Badge>
      <Badge v-if="metrics" :color="metrics.agentOnline ? 'var(--green)' : 'var(--red)'" size="sm">
        agent {{ metrics.agentOnline ? 'OK' : 'down' }}
      </Badge>
      <Badge v-if="isWings && metrics" :color="metrics.wingsOnline ? 'var(--green)' : 'var(--red)'" size="sm">
        wings {{ metrics.wingsOnline ? 'OK' : 'down' }}
      </Badge>
      <Badge :color="snap?.inboundReachable ? 'var(--green)' : 'var(--red)'" size="sm">
        inbound {{ snap?.inboundReachable ? 'OK' : 'down' }}
      </Badge>
      <Badge v-if="isWings && metrics?.wingsVersion" color="var(--blue)" size="sm">
        wings {{ metrics.wingsVersion }}
      </Badge>
    </header>

    <!-- gauges -->
    <div v-if="loading && !metrics" class="loading"><Spinner size="md" /></div>
    <template v-else-if="metrics">
      <div class="gauges">
        <div class="gauge-cell">
          <span class="gc-label">CPU</span>
          <VChart class="gauge" :option="cpuOption" autoresize />
        </div>
        <div class="gauge-cell">
          <span class="gc-label">MEM</span>
          <VChart class="gauge" :option="memOption" autoresize />
        </div>
        <div class="gauge-cell">
          <span class="gc-label">DSK</span>
          <VChart class="gauge" :option="diskOption" autoresize />
        </div>
        <div class="gauge-cell">
          <span class="gc-label">LD&nbsp;1m</span>
          <VChart class="gauge" :option="loadOption" autoresize />
        </div>
      </div>

      <!-- stats rows -->
      <div class="stats">
        <div class="stat-row">
          <span class="lbl">CPU</span>
          <span class="val">{{ metrics.cpuCores ?? '—' }} {{ t('hosts.overview.stats.cores') }} · {{ t('hosts.overview.stats.load') }} {{ metrics.load1m?.toFixed(2) ?? '—' }} / {{ metrics.load5m?.toFixed(2) ?? '—' }} / {{ metrics.load15m?.toFixed(2) ?? '—' }}</span>
        </div>
        <div class="stat-row">
          <span class="lbl">MEM</span>
          <span class="val">{{ fmtBytes(metrics.memUsedMb) }} / {{ fmtBytes(metrics.memTotalMb) }}</span>
        </div>
        <div class="stat-row" v-if="metrics.swapTotalMb">
          <span class="lbl">SWAP</span>
          <span class="val">{{ fmtBytes(metrics.swapUsedMb) }} / {{ fmtBytes(metrics.swapTotalMb) }}</span>
        </div>
        <div class="stat-row">
          <span class="lbl">DISK</span>
          <span class="val">{{ fmtBytes(metrics.diskUsedMb) }} / {{ fmtBytes(metrics.diskTotalMb) }}</span>
        </div>
        <div class="stat-row">
          <span class="lbl">NET</span>
          <span class="val">↓ {{ fmtRate(metrics.netRxBps) }} · ↑ {{ fmtRate(metrics.netTxBps) }}</span>
        </div>
        <div class="stat-row" v-if="isWings">
          <span class="lbl">{{ t('hosts.overview.stats.containers') }}</span>
          <span class="val">{{ metrics.containerRunning ?? 0 }} / {{ metrics.containerTotal ?? 0 }} · {{ fmtBytes(metrics.containerMemMb) }} · {{ metrics.containerCpuPct?.toFixed(1) ?? '—' }}%</span>
        </div>
      </div>

      <!-- hero trends -->
      <div v-if="chartHostId" class="hero">
        <div class="hero-cell">
          <div class="hero-title">{{ t('hosts.overview.hero.cpu') }}</div>
          <HostMetricsChart :hostId="chartHostId" metric="cpu" window="1h" :height="140" autoRefresh />
        </div>
        <div class="hero-cell">
          <div class="hero-title">{{ t('hosts.overview.hero.mem') }}</div>
          <HostMetricsChart :hostId="chartHostId" metric="mem" window="1h" :height="140" autoRefresh />
        </div>
      </div>
    </template>

    <div v-else class="muted">{{ isWings ? t('hosts.overview.noMetrics') : t('hosts.overview.noMetricsNonWings') }}</div>
  </section>
</template>

<style scoped>
.panel {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
  padding: var(--sp-4);
  background: var(--bg2);
  border: 1px solid var(--bd);
  border-radius: var(--r-md);
  min-width: 0;
  overflow: hidden;
}

.hdr {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
  align-items: center;
}

.gauges {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--sp-3);
}
.gauge-cell {
  position: relative;
  background: var(--bg3);
  border: 1px solid var(--bd);
  border-radius: var(--r-sm);
  padding: 0;
  min-width: 0;
  overflow: hidden;
}
.gc-label {
  position: absolute;
  top: var(--sp-2);
  left: var(--sp-2);
  z-index: 1;
  font-size: var(--text-xs);
  color: var(--t3);
  letter-spacing: .04em;
  text-transform: uppercase;
  pointer-events: none;
}
.gauge {
  width: 100%;
  height: 160px;
}

.stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--sp-1) var(--sp-4);
}
.stat-row {
  display: flex;
  align-items: baseline;
  gap: var(--sp-2);
  font-size: var(--text-sm);
  min-width: 0;
}
.lbl {
  color: var(--t3);
  font-size: var(--text-xs);
  letter-spacing: .04em;
  text-transform: uppercase;
  min-width: 60px;
}
.val {
  color: var(--t1);
  font-family: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace);
  font-variant-numeric: tabular-nums;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: var(--sp-3);
}
.hero-cell {
  background: var(--bg3);
  border: 1px solid var(--bd);
  border-radius: var(--r-sm);
  padding: var(--sp-2);
  min-width: 0;
}
.hero-title {
  font-size: var(--text-xs);
  color: var(--t3);
  letter-spacing: .04em;
  text-transform: uppercase;
  margin-bottom: var(--sp-1);
}

.loading {
  display: flex;
  justify-content: center;
  padding: var(--sp-6);
}
.muted {
  color: var(--t3);
  font-size: var(--text-sm);
  padding: var(--sp-4);
  text-align: center;
}

@media (max-width: 900px) {
  .gauges { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .stats { grid-template-columns: 1fr; }
  .hero { grid-template-columns: minmax(0, 1fr); }
}
@media (max-width: 480px) {
  .gauges { grid-template-columns: minmax(0, 1fr); }
}
</style>

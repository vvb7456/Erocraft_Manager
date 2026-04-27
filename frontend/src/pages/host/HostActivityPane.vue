<script setup lang="ts">
// HostActivityPane (C9) — historical charts + Wings debug log stream.
//
// Two vertical sections:
//   1. Resource history (wings_node only) — window selector + 4 ECharts time
//      series (CPU / MEM / DISK / LOAD) via <HostMetricsChart>.
//   2. Wings debug log (wings_node only) — SSE stream from
//      /api/admin/hosts/{hostId}/wings/logs/stream consumed via EventSource.
//
// Per scope decision (2026-04): host-scoped audit log section is OUT.
import {
  computed, inject, nextTick, onBeforeUnmount, ref, watch, type Ref,
} from 'vue'
import { useI18n } from 'vue-i18n'
import BaseCard from '@/components/ui/BaseCard.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import ChipSelect from '@/components/ui/ChipSelect.vue'
import HostMetricsChart from '@/components/hosts/HostMetricsChart.vue'
import HostBytesChart from '@/components/hosts/HostBytesChart.vue'
import type { HostDetail } from '@/types/host'

defineOptions({ name: 'HostActivityPane' })

const { t } = useI18n({ useScope: 'global' })
const host = inject<Ref<HostDetail | null>>('hostDetail')!

const isWings = computed(() => host.value?.kind === 'wings_node')
const hostId = computed(() => host.value?.id ?? 0)

// ── 1. History window selector ────────────────────────────────────────────
type Window = '1h' | '6h' | '24h' | '7d'
const windowValue = ref<Window>('1h')
const windowOptions = computed(() => ([
  { value: '1h',  label: t('hosts.activity.window.1h') },
  { value: '6h',  label: t('hosts.activity.window.6h') },
  { value: '24h', label: t('hosts.activity.window.24h') },
  { value: '7d',  label: t('hosts.activity.window.7d') },
]))
const enableZoom = computed(() => windowValue.value === '24h' || windowValue.value === '7d')

const netSeries = computed(() => ([
  { metric: 'net_rx', label: t('hosts.activity.series.netRx'), color: 'ac' as const },
  { metric: 'net_tx', label: t('hosts.activity.series.netTx'), color: 'blue' as const },
]))
const diskIoSeries = computed(() => ([
  { metric: 'disk_read',  label: t('hosts.activity.series.diskRead'),  color: 'green' as const },
  { metric: 'disk_write', label: t('hosts.activity.series.diskWrite'), color: 'amber' as const },
]))

// ── 2. Wings debug log SSE stream ─────────────────────────────────────────
interface LogLine { id: number; ts: string; text: string }

const logLines = ref<LogLine[]>([])
const logPaused = ref(false)
const logFollow = ref(true)
const logConnected = ref(false)
const logError = ref<string | null>(null)
const logBoxRef = ref<HTMLElement>()
const MAX_LINES = 1000
let lineSeq = 0
let es: EventSource | null = null

function nowHHMMSS(): string {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function appendLine(text: string) {
  if (logPaused.value) return
  logLines.value.push({ id: ++lineSeq, ts: nowHHMMSS(), text })
  if (logLines.value.length > MAX_LINES) {
    logLines.value.splice(0, logLines.value.length - MAX_LINES)
  }
  if (logFollow.value) {
    nextTick(() => {
      const el = logBoxRef.value
      if (el) el.scrollTop = el.scrollHeight
    })
  }
}

function openStream() {
  closeStream()
  if (!isWings.value || !hostId.value) return
  logError.value = null
  const url = `/api/admin/hosts/${hostId.value}/wings/logs/stream?lines=200`
  try {
    es = new EventSource(url, { withCredentials: true })
  } catch (e) {
    logError.value = String(e)
    return
  }
  es.onopen = () => {
    logConnected.value = true
    logError.value = null
  }
  es.onmessage = (ev) => {
    if (typeof ev.data === 'string' && ev.data.length) appendLine(ev.data)
  }
  es.onerror = () => {
    logConnected.value = false
    // EventSource auto-reconnects per `retry:` preamble; surface a hint.
    logError.value = t('hosts.activity.log.disconnected')
  }
}

function closeStream() {
  if (es) {
    es.close()
    es = null
  }
  logConnected.value = false
}

function clearLog() {
  logLines.value = []
  lineSeq = 0
}

function togglePause() { logPaused.value = !logPaused.value }
function toggleFollow() { logFollow.value = !logFollow.value }

watch(
  () => [isWings.value, hostId.value],
  () => {
    if (isWings.value && hostId.value) openStream()
    else closeStream()
  },
  { immediate: true },
)

onBeforeUnmount(closeStream)
</script>

<template>
  <div v-if="!host" class="muted">{{ t('hosts.detail.loading') }}</div>
  <div v-else class="pane-stack">
    <!-- ─────────── Resource history (wings_node only) ─────────── -->
    <BaseCard v-if="isWings && hostId" variant="bg2" class="hist-card">
      <header class="card-head">
        <h3 class="section-title">{{ t('hosts.activity.history.title') }}</h3>
        <ChipSelect
          v-model="windowValue"
          :options="windowOptions"
        />
      </header>
      <div class="chart-grid">
        <div class="chart-cell">
          <div class="chart-label">{{ t('hosts.activity.metric.cpu') }}</div>
          <HostMetricsChart
            :host-id="hostId"
            metric="cpu"
            :window="windowValue"
            :height="220"
            :data-zoom="enableZoom"
          />
        </div>
        <div class="chart-cell">
          <div class="chart-label">{{ t('hosts.activity.metric.mem') }}</div>
          <HostMetricsChart
            :host-id="hostId"
            metric="mem"
            :window="windowValue"
            :height="220"
            :data-zoom="enableZoom"
          />
        </div>
        <div class="chart-cell">
          <div class="chart-label">{{ t('hosts.activity.metric.disk') }}</div>
          <HostMetricsChart
            :host-id="hostId"
            metric="disk"
            :window="windowValue"
            :height="220"
            :data-zoom="enableZoom"
          />
        </div>
        <div class="chart-cell">
          <div class="chart-label">{{ t('hosts.activity.metric.load') }}</div>
          <HostMetricsChart
            :host-id="hostId"
            metric="load"
            :window="windowValue"
            :height="220"
            :data-zoom="enableZoom"
          />
        </div>
      </div>
      <div class="chart-grid">
        <div class="chart-cell">
          <div class="chart-label">{{ t('hosts.activity.metric.net') }}</div>
          <HostBytesChart
            :host-id="hostId"
            :series="netSeries"
            :window="windowValue"
            :height="220"
            :data-zoom="enableZoom"
          />
        </div>
        <div class="chart-cell">
          <div class="chart-label">{{ t('hosts.activity.metric.diskIo') }}</div>
          <HostBytesChart
            :host-id="hostId"
            :series="diskIoSeries"
            :window="windowValue"
            :height="220"
            :data-zoom="enableZoom"
          />
        </div>
      </div>
    </BaseCard>

    <!-- ─────────── Wings debug log (wings_node only) ─────────── -->
    <BaseCard v-if="isWings && hostId" variant="bg2" class="log-card">
      <header class="card-head">
        <h3 class="section-title">
          {{ t('hosts.activity.log.title') }}
          <span class="conn" :class="{ 'conn--on': logConnected }">
            <span class="conn-dot" />
            {{ logConnected ? t('hosts.activity.log.connected') : t('hosts.activity.log.connecting') }}
          </span>
        </h3>
        <div class="log-actions">
          <BaseButton size="sm" variant="ghost" @click="clearLog">
            <MsIcon name="delete_sweep" /> {{ t('hosts.activity.log.clear') }}
          </BaseButton>
          <BaseButton
            size="sm"
            :variant="logPaused ? 'primary' : 'ghost'"
            @click="togglePause"
          >
            <MsIcon :name="logPaused ? 'play_arrow' : 'pause'" />
            {{ logPaused ? t('hosts.activity.log.resume') : t('hosts.activity.log.pause') }}
          </BaseButton>
          <BaseButton
            size="sm"
            :variant="logFollow ? 'primary' : 'ghost'"
            @click="toggleFollow"
          >
            <MsIcon name="vertical_align_bottom" />
            {{ t('hosts.activity.log.follow') }}
          </BaseButton>
        </div>
      </header>
      <div ref="logBoxRef" class="log-box">
        <EmptyState
          v-if="!logLines.length"
          icon="description"
          :title="t('hosts.activity.log.empty')"
          density="compact"
        />
        <template v-else>
          <div v-for="ln in logLines" :key="ln.id" class="log-line">
            <span class="log-ts">{{ ln.ts }}</span>
            <span class="log-text">{{ ln.text }}</span>
          </div>
        </template>
      </div>
      <div v-if="logError" class="log-err">
        <MsIcon name="error_outline" /> {{ logError }}
      </div>
    </BaseCard>

    <!-- Non-wings host: explain why this tab is mostly empty. -->
    <BaseCard v-if="!isWings" variant="bg2" class="info-card">
      <EmptyState
        icon="info"
        :title="t('hosts.activity.nonWings.title')"
        :message="t('hosts.activity.nonWings.message')"
        density="compact"
      />
    </BaseCard>
  </div>
</template>

<style scoped>
.muted {
  color: var(--t3);
  font-size: var(--text-sm);
  padding: var(--sp-4);
}

.pane-stack {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

.hist-card,
.log-card,
.info-card { padding: var(--sp-4); }

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  margin-bottom: var(--sp-3);
  flex-wrap: wrap;
}

.section-title {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--t2);
  letter-spacing: .04em;
  text-transform: uppercase;
  margin: 0;
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
}

/* ── History grid ── */
.chart-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--sp-3);
}
.chart-grid + .chart-grid { margin-top: var(--sp-3); }
@media (max-width: 768px) {
  .chart-grid { grid-template-columns: 1fr; }
}
.chart-cell {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
  min-width: 0;
}
.chart-label {
  font-size: var(--text-xs);
  color: var(--t3);
  letter-spacing: .04em;
  text-transform: uppercase;
}

/* ── Log box ── */
.log-actions {
  display: inline-flex;
  gap: var(--sp-2);
  flex-wrap: wrap;
}

.conn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: var(--text-xs);
  color: var(--t3);
  text-transform: none;
  letter-spacing: 0;
  font-weight: 400;
}
.conn-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--t3);
}
.conn--on { color: var(--green); }
.conn--on .conn-dot {
  background: var(--green);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--green) 25%, transparent);
}

.log-box {
  background: var(--bg-in);
  border: 1px solid var(--bd);
  border-radius: var(--r-md);
  padding: var(--sp-2) var(--sp-3);
  height: 360px;
  overflow-y: auto;
  font-family: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace);
  font-size: var(--text-xs);
  line-height: 1.45;
  color: var(--t1);
}
.log-line {
  display: flex;
  gap: var(--sp-2);
  white-space: pre-wrap;
  word-break: break-all;
}
.log-ts {
  color: var(--t3);
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
}
.log-text { flex: 1; min-width: 0; }

.log-err {
  margin-top: var(--sp-2);
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-xs);
  color: var(--amber);
}
</style>

<script setup lang="ts">
/**
 * DashboardTrendsChart — multi-host single-metric trend over a window.
 *
 * Pulls /api/admin/hosts/{id}/history/metrics?metric=&window= for each host
 * in parallel and renders one line per host. Polls every 60s.
 *
 * Supported metrics:
 *   cpu, mem, disk           → unit '%' (axis 0..100)
 *   load                     → unit 'load'
 *   net_rx, net_tx           → unit 'bps'
 *   disk_read, disk_write    → unit 'bps'
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useApiFetch } from '@/composables/useApiFetch'
import Spinner from '@/components/ui/Spinner.vue'
import EmptyState from '@/components/ui/EmptyState.vue'

use([LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

defineOptions({ name: 'DashboardTrendsChart' })

type Metric = 'cpu' | 'mem' | 'disk' | 'load' | 'net_rx' | 'net_tx' | 'disk_read' | 'disk_write'
type Unit = 'pct' | 'bps' | 'load'

interface HostRef { id: number; name: string }
const props = withDefaults(defineProps<{
  hosts: HostRef[]
  metric: Metric
  window?: '1h' | '6h' | '24h' | '7d'
  unit?: Unit
  showLegend?: boolean
}>(), {
  window: '24h',
  unit: 'pct',
  showLegend: false,
})

const { t } = useI18n({ useScope: 'global' })
const { get } = useApiFetch()

const seriesByHost = ref<Record<number, [number, number][]>>({})
const loading = ref(false)
let pollTimer: ReturnType<typeof setInterval> | null = null
let alive = true

async function fetchOne(hostId: number) {
  const data = await get<{ series: [number, number][] }>(
    `/api/admin/hosts/${hostId}/history/metrics?metric=${props.metric}&window=${props.window}`,
  )
  if (!alive) return
  seriesByHost.value = { ...seriesByHost.value, [hostId]: data?.series || [] }
}

async function fetchAll() {
  if (!props.hosts.length) {
    seriesByHost.value = {}
    return
  }
  loading.value = true
  try {
    await Promise.all(props.hosts.map(h => fetchOne(h.id)))
  } finally {
    if (alive) loading.value = false
  }
}

onMounted(() => {
  fetchAll()
  pollTimer = setInterval(fetchAll, 60_000)
})
onUnmounted(() => {
  alive = false
  if (pollTimer) clearInterval(pollTimer)
})
watch(() => [props.metric, props.window, props.hosts.map(h => h.id).join(',')], fetchAll)

/* ── Theme tokens ── */
type Tokens = { ac: string; t1: string; t2: string; t3: string; bd: string; bg2: string; amber: string; red: string; blue: string; green: string; ac2: string }
const DEFAULT_TOKENS: Tokens = {
  ac: '#14b8a6', ac2: '#2dd4bf', t1: '#e4ece8', t2: '#94a8a0', t3: '#5a706a',
  bd: '#263434', bg2: '#182020', amber: '#f59e0b', red: '#ef6060', blue: '#60a5fa', green: '#34d399',
}
const tokens = ref<Tokens>({ ...DEFAULT_TOKENS })
let themeObserver: MutationObserver | null = null
function readTokens() {
  if (typeof document === 'undefined') return
  const cs = getComputedStyle(document.documentElement)
  const pick = (n: string, fb: string) => cs.getPropertyValue(n).trim() || fb
  tokens.value = {
    ac: pick('--ac', DEFAULT_TOKENS.ac),
    ac2: pick('--ac2', DEFAULT_TOKENS.ac2),
    t1: pick('--t1', DEFAULT_TOKENS.t1),
    t2: pick('--t2', DEFAULT_TOKENS.t2),
    t3: pick('--t3', DEFAULT_TOKENS.t3),
    bd: pick('--bd', DEFAULT_TOKENS.bd),
    bg2: pick('--bg2', DEFAULT_TOKENS.bg2),
    amber: pick('--amber', DEFAULT_TOKENS.amber),
    red: pick('--red', DEFAULT_TOKENS.red),
    blue: pick('--blue', DEFAULT_TOKENS.blue),
    green: pick('--green', DEFAULT_TOKENS.green),
  }
}
onMounted(() => {
  readTokens()
  if (typeof MutationObserver !== 'undefined') {
    themeObserver = new MutationObserver(readTokens)
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'class'] })
  }
})
onUnmounted(() => { themeObserver?.disconnect(); themeObserver = null })

const palette = computed(() => [tokens.value.ac, tokens.value.blue, tokens.value.amber, tokens.value.green, tokens.value.red, tokens.value.ac2])

const totalPoints = computed(() =>
  Object.values(seriesByHost.value).reduce((s, arr) => s + arr.length, 0),
)

/* Formatters */
function fmtBytes(v: number): string {
  const x = v ?? 0
  if (x < 1024) return `${x.toFixed(0)} B/s`
  if (x < 1024 * 1024) return `${(x / 1024).toFixed(1)} KB/s`
  if (x < 1024 * 1024 * 1024) return `${(x / 1024 / 1024).toFixed(1)} MB/s`
  return `${(x / 1024 / 1024 / 1024).toFixed(2)} GB/s`
}

const valueFormatter = computed(() => {
  if (props.unit === 'pct') return (v: number) => `${(v ?? 0).toFixed(1)}%`
  if (props.unit === 'bps') return (v: number) => fmtBytes(v)
  return (v: number) => (v ?? 0).toFixed(2)
})

const yAxisConfig = computed(() => {
  if (props.unit === 'pct') {
    return {
      type: 'value' as const,
      min: 0,
      max: 100,
      axisLabel: { color: tokens.value.t3, fontSize: 10, formatter: '{value}%' },
    }
  }
  if (props.unit === 'bps') {
    return {
      type: 'value' as const,
      min: 0,
      axisLabel: {
        color: tokens.value.t3,
        fontSize: 10,
        formatter: (v: number) => {
          if (v < 1024) return `${v}`
          if (v < 1024 * 1024) return `${(v / 1024).toFixed(0)}K`
          if (v < 1024 * 1024 * 1024) return `${(v / 1024 / 1024).toFixed(0)}M`
          return `${(v / 1024 / 1024 / 1024).toFixed(0)}G`
        },
      },
    }
  }
  return {
    type: 'value' as const,
    min: 0,
    axisLabel: { color: tokens.value.t3, fontSize: 10 },
  }
})

const option = computed(() => {
  const tk = tokens.value
  const pal = palette.value
  const fmt = valueFormatter.value
  return {
    backgroundColor: 'transparent',
    grid: { left: 44, right: 12, top: props.showLegend ? 28 : 12, bottom: 22 },
    legend: props.showLegend
      ? {
          show: true,
          type: 'scroll',
          top: 0,
          right: 8,
          textStyle: { color: tk.t2, fontSize: 11 },
          itemWidth: 12,
          itemHeight: 6,
          icon: 'roundRect',
        }
      : { show: false },
    tooltip: {
      trigger: 'axis',
      backgroundColor: tk.bg2,
      borderColor: tk.bd,
      textStyle: { color: tk.t1, fontSize: 11 },
      axisPointer: { type: 'line', lineStyle: { color: tk.t3 } },
      valueFormatter: fmt,
    },
    xAxis: {
      type: 'time' as const,
      axisLine: { lineStyle: { color: tk.bd } },
      axisLabel: { color: tk.t3, fontSize: 10, hideOverlap: true },
      splitLine: { show: false },
    },
    yAxis: {
      ...yAxisConfig.value,
      axisLine: { show: false },
      splitLine: { lineStyle: { color: tk.bd, type: 'dashed' as const, opacity: 0.4 } },
    },
    series: props.hosts.map((h, i) => ({
      name: h.name,
      type: 'line',
      smooth: true,
      symbol: 'none',
      lineStyle: { width: 2, color: pal[i % pal.length] },
      itemStyle: { color: pal[i % pal.length] },
      areaStyle: {
        color: {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: `${pal[i % pal.length]}30` },
            { offset: 1, color: `${pal[i % pal.length]}00` },
          ],
        },
      },
      data: seriesByHost.value[h.id] || [],
    })),
  }
})
</script>

<template>
  <div class="trends-wrap">
    <div v-if="loading && !totalPoints" class="loader">
      <Spinner />
    </div>
    <EmptyState v-else-if="!hosts.length" icon="history" :title="t('dashboard.empty.trends')" />
    <VChart v-else class="trends-chart" :option="option" autoresize />
  </div>
</template>

<style scoped>
.trends-wrap {
  width: 100%;
  height: 100%;
  position: relative;
}
.trends-chart { width: 100%; height: 100%; }
.loader {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}
</style>

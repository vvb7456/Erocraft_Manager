<script setup lang="ts">
// HostMetricsChart — single-metric ECharts line chart for one node.
//
// Pulls /api/monitoring/history/{nodeId}?metric=&window= and renders a
// time-series area chart. Used both inline in HostStatusPanel (small
// 1h hero charts) and full-size in HostActivityPane (C9, with dataZoom).
//
// Theme tokens are read from CSS vars on mount so the chart picks up
// brand colors without re-implementing the design system.
import {
  computed, onBeforeUnmount, onMounted, ref, watch,
} from 'vue'
import { useI18n } from 'vue-i18n'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, MarkLineComponent, DataZoomComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useApiFetch } from '@/composables/useApiFetch'
import Spinner from '@/components/ui/Spinner.vue'
import EmptyState from '@/components/ui/EmptyState.vue'

use([LineChart, GridComponent, TooltipComponent, MarkLineComponent, DataZoomComponent, CanvasRenderer])

defineOptions({ name: 'HostMetricsChart' })

type Metric = 'cpu' | 'mem' | 'disk' | 'load'
type Window = '1h' | '6h' | '24h' | '7d'

const props = withDefaults(defineProps<{
  nodeId: number
  metric: Metric
  window?: Window
  height?: number
  dataZoom?: boolean
  autoRefresh?: boolean   // 30s tick — used by overview hero charts
  warningThreshold?: number | null
  criticalThreshold?: number | null
}>(), {
  window: '1h',
  height: 220,
  dataZoom: false,
  autoRefresh: false,
  warningThreshold: null,
  criticalThreshold: null,
})

const { t } = useI18n({ useScope: 'global' })
const { get } = useApiFetch()

interface HistoryPoint extends Array<number> { 0: number; 1: number }

const series = ref<HistoryPoint[]>([])
const loading = ref(false)
let pollTimer: number | null = null

async function fetchHistory() {
  if (!Number.isFinite(props.nodeId)) return
  loading.value = true
  try {
    const data = await get<{ series: HistoryPoint[] }>(
      `/api/monitoring/history/${props.nodeId}?metric=${props.metric}&window=${props.window}`,
    )
    series.value = data?.series || []
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchHistory()
  if (props.autoRefresh) {
    pollTimer = window.setInterval(fetchHistory, 30_000)
  }
})
onBeforeUnmount(() => {
  if (pollTimer !== null) clearInterval(pollTimer)
})
watch(() => [props.nodeId, props.metric, props.window], fetchHistory)

// Theme tokens from CSS vars
type Tokens = { ac: string; ac2: string; t1: string; t3: string; bd: string; bg2: string; amber: string; red: string }
const tokens = ref<Tokens>({
  ac: '#14b8a6', ac2: '#2dd4bf', t1: '#e4ece8', t3: '#5a706a',
  bd: '#263434', bg2: '#182020', amber: '#f59e0b', red: '#ef6060',
})
function readTokens() {
  if (typeof document === 'undefined') return
  const cs = getComputedStyle(document.documentElement)
  const pick = (n: string, fb: string) => cs.getPropertyValue(n).trim() || fb
  tokens.value = {
    ac:    pick('--ac',    tokens.value.ac),
    ac2:   pick('--ac2',   tokens.value.ac2),
    t1:    pick('--t1',    tokens.value.t1),
    t3:    pick('--t3',    tokens.value.t3),
    bd:    pick('--bd',    tokens.value.bd),
    bg2:   pick('--bg2',   tokens.value.bg2),
    amber: pick('--amber', tokens.value.amber),
    red:   pick('--red',   tokens.value.red),
  }
}
let themeObserver: MutationObserver | null = null
onMounted(() => {
  readTokens()
  themeObserver = new MutationObserver(readTokens)
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'data-theme'] })
})
onBeforeUnmount(() => { themeObserver?.disconnect() })

const yMax = computed(() => (props.metric === 'load' ? null : 100))
const yFormatter = computed(() => {
  if (props.metric === 'load') return (v: number) => v.toFixed(2)
  return (v: number) => `${v}%`
})

const option = computed(() => {
  const tk = tokens.value
  const markLines: object[] = []
  if (props.warningThreshold != null) {
    markLines.push({
      yAxis: props.warningThreshold,
      lineStyle: { color: tk.amber, type: 'dashed', width: 1 },
      label: { color: tk.amber, fontSize: 10, formatter: 'warn' },
    })
  }
  if (props.criticalThreshold != null) {
    markLines.push({
      yAxis: props.criticalThreshold,
      lineStyle: { color: tk.red, type: 'dashed', width: 1 },
      label: { color: tk.red, fontSize: 10, formatter: 'crit' },
    })
  }

  return {
    backgroundColor: 'transparent',
    grid: { left: 40, right: 12, top: 12, bottom: props.dataZoom ? 36 : 18 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: tk.bg2,
      borderColor: tk.bd,
      textStyle: { color: tk.t1, fontSize: 12 },
      valueFormatter: (v: number) => yFormatter.value(v),
    },
    xAxis: {
      type: 'time',
      axisLine: { lineStyle: { color: tk.bd } },
      axisLabel: { color: tk.t3, fontSize: 10 },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value',
      min: 0,
      ...(yMax.value != null ? { max: yMax.value } : {}),
      axisLine: { show: false },
      axisLabel: {
        color: tk.t3, fontSize: 10,
        formatter: (v: number) => yFormatter.value(v),
      },
      splitLine: { lineStyle: { color: tk.bd, type: 'dashed' } },
    },
    ...(props.dataZoom ? { dataZoom: [{ type: 'inside' }, { type: 'slider', height: 18, bottom: 4 }] } : {}),
    series: [{
      type: 'line',
      smooth: true,
      showSymbol: false,
      lineStyle: { color: tk.ac, width: 2 },
      areaStyle: {
        color: {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: `${tk.ac}55` },
            { offset: 1, color: `${tk.ac}00` },
          ],
        },
      },
      markLine: markLines.length ? { silent: true, symbol: 'none', data: markLines } : undefined,
      data: series.value,
    }],
  }
})
</script>

<template>
  <div class="hmc" :style="{ height: `${height}px` }">
    <div v-if="loading && !series.length" class="hmc-loading"><Spinner size="sm" /></div>
    <EmptyState
      v-else-if="!series.length"
      icon="show_chart"
      :title="t('hosts.overview.chart.empty')"
      density="compact"
    />
    <VChart v-else class="hmc-chart" :option="option" autoresize />
  </div>
</template>

<style scoped>
.hmc {
  position: relative;
  width: 100%;
  min-width: 0;
  overflow: hidden;
}
.hmc-chart {
  width: 100%;
  height: 100%;
}
.hmc-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}
</style>

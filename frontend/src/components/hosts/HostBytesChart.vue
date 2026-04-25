<script setup lang="ts">
// HostBytesChart — dual-series ECharts line chart for byte-rate metrics.
//
// Pulls two /api/admin/monitoring/history legs (e.g. net_rx + net_tx) and
// renders them as two overlaid lines with a byte/s y-axis formatter
// (auto-scaling B/KB/MB/GB). Used in HostActivityPane for the network
// throughput and disk IO panels.
import {
  computed, onBeforeUnmount, onMounted, ref, watch,
} from 'vue'
import { useI18n } from 'vue-i18n'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, DataZoomComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useApiFetch } from '@/composables/useApiFetch'
import Spinner from '@/components/ui/Spinner.vue'
import EmptyState from '@/components/ui/EmptyState.vue'

use([LineChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, CanvasRenderer])

defineOptions({ name: 'HostBytesChart' })

type Window = '1h' | '6h' | '24h' | '7d'

interface SeriesSpec {
  metric: string   // 'net_rx' | 'net_tx' | 'disk_read' | 'disk_write'
  label: string
  color: 'ac' | 'blue' | 'amber' | 'green'
}

const props = withDefaults(defineProps<{
  nodeId: number
  series: SeriesSpec[]     // typically 2 legs
  window?: Window
  height?: number
  dataZoom?: boolean
}>(), {
  window: '1h',
  height: 220,
  dataZoom: false,
})

const { t } = useI18n({ useScope: 'global' })
const { get } = useApiFetch()

type Point = [number, number]

const data = ref<Point[][]>([])   // one array per series
const loading = ref(false)

async function fetchAll() {
  if (!Number.isFinite(props.nodeId)) return
  loading.value = true
  try {
    const results = await Promise.all(
      props.series.map(s =>
        get<{ series: Point[] }>(
          `/api/admin/monitoring/history/${props.nodeId}?metric=${s.metric}&window=${props.window}`,
        ).then(d => d?.series || []),
      ),
    )
    data.value = results
  } finally {
    loading.value = false
  }
}

onMounted(fetchAll)
watch(() => [props.nodeId, props.window, props.series.map(s => s.metric).join('|')], fetchAll)

// Theme tokens
type Tokens = { ac: string; blue: string; amber: string; green: string; t1: string; t3: string; bd: string; bg2: string }
const tokens = ref<Tokens>({
  ac: '#14b8a6', blue: '#60a5fa', amber: '#f59e0b', green: '#34d399',
  t1: '#e4ece8', t3: '#5a706a', bd: '#263434', bg2: '#182020',
})
function readTokens() {
  if (typeof document === 'undefined') return
  const cs = getComputedStyle(document.documentElement)
  const pick = (n: string, fb: string) => cs.getPropertyValue(n).trim() || fb
  tokens.value = {
    ac:    pick('--ac',    tokens.value.ac),
    blue:  pick('--blue',  tokens.value.blue),
    amber: pick('--amber', tokens.value.amber),
    green: pick('--green', tokens.value.green),
    t1:    pick('--t1',    tokens.value.t1),
    t3:    pick('--t3',    tokens.value.t3),
    bd:    pick('--bd',    tokens.value.bd),
    bg2:   pick('--bg2',   tokens.value.bg2),
  }
}
let themeObserver: MutationObserver | null = null
onMounted(() => {
  readTokens()
  themeObserver = new MutationObserver(readTokens)
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'data-theme'] })
})
onBeforeUnmount(() => { themeObserver?.disconnect() })

// Byte/s formatter: auto-scale B/s → KB/s → MB/s → GB/s. Thresholds use
// 1024^n boundaries (traditional binary sizing matches how /proc and
// most admin tooling report network + disk rates).
function formatBps(v: number): string {
  if (v == null || !isFinite(v)) return '—'
  const abs = Math.abs(v)
  if (abs < 1024) return `${v.toFixed(0)} B/s`
  if (abs < 1024 ** 2) return `${(v / 1024).toFixed(1)} KB/s`
  if (abs < 1024 ** 3) return `${(v / 1024 ** 2).toFixed(2)} MB/s`
  return `${(v / 1024 ** 3).toFixed(2)} GB/s`
}

const isEmpty = computed(() => data.value.every(s => s.length === 0))

const option = computed(() => {
  const tk = tokens.value
  const seriesColors: Record<SeriesSpec['color'], string> = {
    ac: tk.ac, blue: tk.blue, amber: tk.amber, green: tk.green,
  }
  return {
    backgroundColor: 'transparent',
    grid: { left: 56, right: 12, top: 28, bottom: props.dataZoom ? 36 : 18 },
    legend: {
      top: 0,
      right: 0,
      textStyle: { color: tk.t3, fontSize: 11 },
      itemWidth: 14,
      itemHeight: 10,
      data: props.series.map(s => s.label),
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: tk.bg2,
      borderColor: tk.bd,
      textStyle: { color: tk.t1, fontSize: 12 },
      valueFormatter: (v: number) => formatBps(v),
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
      axisLine: { show: false },
      axisLabel: {
        color: tk.t3, fontSize: 10,
        formatter: (v: number) => formatBps(v),
      },
      splitLine: { lineStyle: { color: tk.bd, type: 'dashed' } },
    },
    ...(props.dataZoom ? { dataZoom: [{ type: 'inside' }, { type: 'slider', height: 18, bottom: 4 }] } : {}),
    series: props.series.map((s, idx) => ({
      name: s.label,
      type: 'line',
      smooth: true,
      showSymbol: false,
      lineStyle: { color: seriesColors[s.color], width: 2 },
      areaStyle: {
        color: {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: `${seriesColors[s.color]}44` },
            { offset: 1, color: `${seriesColors[s.color]}00` },
          ],
        },
      },
      data: data.value[idx] || [],
    })),
  }
})
</script>

<template>
  <div class="hbc" :style="{ height: `${height}px` }">
    <div v-if="loading && isEmpty" class="hbc-loading"><Spinner size="sm" /></div>
    <EmptyState
      v-else-if="isEmpty"
      icon="show_chart"
      :title="t('hosts.overview.chart.empty')"
      density="compact"
    />
    <VChart v-else class="hbc-chart" :option="option" autoresize />
  </div>
</template>

<style scoped>
.hbc {
  position: relative;
  width: 100%;
  min-width: 0;
  overflow: hidden;
}
.hbc-chart {
  width: 100%;
  height: 100%;
}
.hbc-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}
</style>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { PieChart } from 'echarts/charts'
import { TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import BaseCard from '@/components/ui/BaseCard.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import Spinner from '@/components/ui/Spinner.vue'
import AlertBanner from '@/components/ui/AlertBanner.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import StatCard from '@/components/ui/StatCard.vue'
import PageHeader from '@/components/layout/PageHeader.vue'
import NodeCard from '@/components/monitoring/NodeCard.vue'
import ProbeStatus from '@/components/monitoring/ProbeStatus.vue'
import type { NodeData } from '@/components/monitoring/NodeCard.vue'
import type { ProbeData } from '@/components/monitoring/ProbeStatus.vue'

use([PieChart, TooltipComponent, LegendComponent, CanvasRenderer])

defineOptions({ name: 'DashboardPage' })

const { t } = useI18n({ useScope: 'global' })
const { get, loading, error } = useApiFetch()
const monitoringApi = useApiFetch()

interface DashboardData {
  totalUsers: number
  totalServers: number
  normalCount: number
  statusDistribution: {
    normal: number
    expiring_soon: number
    expired: number
    suspended: number
    permanent: number
  }
}

interface MonitoringData {
  nodes: NodeData[]
  probes: ProbeData[]
  alerts: { active: number; todayTotal: number }
}

const data = ref<DashboardData | null>(null)
const monitoring = ref<MonitoringData | null>(null)

/* ── Design tokens (CSS vars) — re-read on theme change ── */
type Tokens = {
  bg2: string; bg3: string; bd: string; t1: string; t3: string;
  green: string; amber: string; red: string; blue: string; ac: string;
}
const DEFAULT_TOKENS: Tokens = {
  bg2: '#182020', bg3: '#111818', bd: '#263434',
  t1: '#e4ece8', t3: '#5a706a',
  green: '#34d399', amber: '#f59e0b', red: '#ef6060', blue: '#60a5fa', ac: '#14b8a6',
}
const tokens = ref<Tokens>({ ...DEFAULT_TOKENS })
let themeObserver: MutationObserver | null = null

function readTokens() {
  if (typeof document === 'undefined') return
  const cs = getComputedStyle(document.documentElement)
  const pick = (name: string, fallback: string) => {
    const v = cs.getPropertyValue(name).trim()
    return v || fallback
  }
  tokens.value = {
    bg2: pick('--bg2', DEFAULT_TOKENS.bg2),
    bg3: pick('--bg3', DEFAULT_TOKENS.bg3),
    bd: pick('--bd', DEFAULT_TOKENS.bd),
    t1: pick('--t1', DEFAULT_TOKENS.t1),
    t3: pick('--t3', DEFAULT_TOKENS.t3),
    green: pick('--green', DEFAULT_TOKENS.green),
    amber: pick('--amber', DEFAULT_TOKENS.amber),
    red: pick('--red', DEFAULT_TOKENS.red),
    blue: pick('--blue', DEFAULT_TOKENS.blue),
    ac: pick('--ac', DEFAULT_TOKENS.ac),
  }
}
const notConfigured = ref(false)
let pollTimer: ReturnType<typeof setInterval> | null = null

const normalRate = computed(() => {
  if (!data.value || data.value.totalServers === 0) return 0
  return Math.round((data.value.normalCount / data.value.totalServers) * 100)
})

const expiringSoonCount = computed(() => data.value?.statusDistribution.expiring_soon ?? 0)

/* ── ECharts Donut Option ── */
const donutOption = computed(() => {
  if (!data.value) return {}
  const d = data.value.statusDistribution
  const total = data.value.totalServers
  const tk = tokens.value
  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'item',
      backgroundColor: tk.bg2,
      borderColor: tk.bd,
      textStyle: { color: tk.t1, fontSize: 13 },
      formatter: '{b}: {c} ({d}%)',
    },
    legend: { show: false },
    series: [{
      type: 'pie',
      radius: ['52%', '78%'],
      center: ['50%', '50%'],
      avoidLabelOverlap: false,
      label: {
        show: true,
        position: 'center',
        formatter: () => `{total|${total}}\n{sub|${t('dashboard.stats.totalServers')}}`,
        rich: {
          total: { fontSize: 28, fontWeight: 700, color: tk.t1, lineHeight: 36 },
          sub: { fontSize: 11, color: tk.t3, lineHeight: 18 },
        },
      },
      labelLine: { show: false },
      itemStyle: { borderRadius: 4, borderColor: tk.bg3, borderWidth: 2 },
      emphasis: {
        itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(20,184,166,0.3)' },
      },
      data: [
        { name: t('dashboard.status.normal'), value: d.normal, itemStyle: { color: tk.green } },
        { name: t('dashboard.status.expiringSoon'), value: d.expiring_soon, itemStyle: { color: tk.amber } },
        { name: t('dashboard.status.expired'), value: d.expired, itemStyle: { color: tk.red } },
        { name: t('dashboard.status.suspended'), value: d.suspended, itemStyle: { color: tk.t3 } },
        { name: t('dashboard.status.permanent'), value: d.permanent ?? 0, itemStyle: { color: tk.blue } },
      ].filter(s => s.value > 0),
    }],
  }
})

const legendItems = computed(() => {
  if (!data.value) return []
  const d = data.value.statusDistribution
  const total = data.value.totalServers || 1
  const tk = tokens.value
  return [
    { label: t('dashboard.status.normal'), count: d.normal, color: tk.green },
    { label: t('dashboard.status.expiringSoon'), count: d.expiring_soon, color: tk.amber },
    { label: t('dashboard.status.expired'), count: d.expired, color: tk.red },
    { label: t('dashboard.status.suspended'), count: d.suspended, color: tk.t3 },
    { label: t('dashboard.status.permanent'), count: d.permanent ?? 0, color: tk.blue },
  ].map(s => ({ ...s, pct: Math.round((s.count / total) * 100) }))
})

// Guard against writes after the component has been unmounted. If the
// polling request is in flight when the user navigates away, the awaited
// response would otherwise mutate ``monitoring.value`` on a dead component
// and ECharts reactivity might recompute against stale tokens (CR §5.7).
let alive = true

async function loadMonitoring() {
  const res = await monitoringApi.get<MonitoringData>('/api/admin/monitoring/overview')
  if (!alive) return
  if (res) monitoring.value = res
}

onMounted(async () => {
  readTokens()
  if (typeof MutationObserver !== 'undefined') {
    themeObserver = new MutationObserver(readTokens)
    themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme', 'class'],
    })
  }

  const res = await get<DashboardData>('/api/admin/dashboard')
  if (!alive) return
  if (res) {
    data.value = res
  } else if (error.value) {
    notConfigured.value = true
  }

  await loadMonitoring()
  pollTimer = setInterval(loadMonitoring, 30_000)
})

onUnmounted(() => {
  alive = false
  if (pollTimer) clearInterval(pollTimer)
  themeObserver?.disconnect()
  themeObserver = null
})
</script>

<template>
  <PageHeader icon="dashboard" :title="t('dashboard.title')" />

  <div class="page-body">
    <!-- Loading -->
    <div v-if="loading" style="display:flex;justify-content:center;padding:var(--sp-8)">
      <Spinner size="lg" />
    </div>

    <!-- Error / Not Configured -->
    <EmptyState
      v-else-if="notConfigured"
      icon="settings"
      :title="t('dashboard.notConfigured')"
      :message="t('dashboard.notConfiguredMsg')"
    >
      <BaseButton variant="primary" href="#/settings" style="margin-top: var(--sp-3)">
        {{ t('dashboard.goToSettings') }}
      </BaseButton>
    </EmptyState>

    <AlertBanner v-else-if="error" tone="danger" icon="error">
      {{ error }}
    </AlertBanner>

    <!-- Content -->
    <template v-else-if="data">
      <!-- Active Alert Banner -->
      <AlertBanner
        v-if="monitoring?.alerts?.active"
        tone="warning"
        icon="warning"
        class="alert-section"
      >
        {{ t('dashboard.alertBanner', { count: monitoring.alerts.active }) }}
      </AlertBanner>

      <!-- KPI Row (StatCard variant="kpi", CR §5.9) -->
      <div class="kpi-row">
        <StatCard variant="kpi" :label="t('dashboard.stats.totalUsers')">
          <template #value>{{ data.totalUsers }}</template>
        </StatCard>
        <StatCard variant="kpi" :label="t('dashboard.stats.totalServers')">
          <template #value>{{ data.totalServers }}</template>
        </StatCard>
        <StatCard
          variant="kpi"
          :tone="normalRate < 80 ? 'warn' : 'default'"
          :label="t('dashboard.stats.normalRate')"
        >
          <template #value>{{ normalRate }}<span class="kpi-unit">%</span></template>
        </StatCard>
        <StatCard
          variant="kpi"
          :tone="expiringSoonCount > 0 ? 'warn' : 'default'"
          :label="t('dashboard.stats.expiringSoon')"
        >
          <template #value>{{ expiringSoonCount }}</template>
        </StatCard>
      </div>

      <!-- Two-column layout -->
      <div class="dash-columns">
        <!-- Left: Infrastructure + Connectivity -->
        <div class="dash-col-left">
          <div class="section-header">
            <MsIcon name="memory" size="sm" />
            <h3>{{ t('dashboard.infrastructure') }}</h3>
            <span v-if="monitoring?.nodes?.length" class="section-badge">
              {{ monitoring.nodes.length }}
            </span>
          </div>

          <template v-if="monitoring?.nodes?.length">
            <NodeCard
              v-for="node in monitoring.nodes"
              :key="node.id"
              :node="node"
              class="node-panel"
            />
          </template>
          <div v-else class="empty-hint">
            <MsIcon name="cloud_off" size="sm" />
            <span>{{ t('monitoring.node.noAgent') }}</span>
          </div>

          <!-- Connectivity Probes -->
          <BaseCard v-if="monitoring?.probes?.length" variant="bg3" class="probe-card">
            <div class="section-header section-header--inner">
              <MsIcon name="lan" size="sm" />
              <h3>{{ t('dashboard.connectivity') }}</h3>
            </div>
            <ProbeStatus :probes="monitoring.probes" />
          </BaseCard>
        </div>

        <!-- Right: Server Status -->
        <div class="dash-col-right">
          <div class="section-header">
            <MsIcon name="dns" size="sm" />
            <h3>{{ t('dashboard.chart.title') }}</h3>
          </div>

          <!-- ECharts Donut Card -->
          <BaseCard variant="bg3" class="status-card">
            <VChart v-if="data" class="donut-chart" :option="donutOption" autoresize />
            <div class="status-legend">
              <div v-for="item in legendItems" :key="item.label" class="legend-item">
                <span class="legend-dot" :style="{ background: item.color }" />
                <span class="legend-label">{{ item.label }}</span>
                <span class="legend-count">{{ item.count }}</span>
                <span class="legend-pct">{{ item.pct }}%</span>
              </div>
            </div>
          </BaseCard>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
/* ── Alert ── */
.alert-section {
  margin-bottom: var(--sp-5);
}

/* ── KPI Row (tiles rendered via StatCard variant="kpi") ── */
.kpi-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--sp-4);
  margin-bottom: var(--sp-6);
}

.kpi-unit {
  font-size: 1rem;
  font-weight: 500;
  color: var(--t2);
  margin-left: 1px;
}

/* ── Columns ── */
.dash-columns {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--sp-5);
  align-items: start;
}

.dash-col-left {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}

.dash-col-right {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}

/* ── Section Header ── */
.section-header {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  color: var(--t1);
}

.section-header h3 {
  font-size: var(--text-base);
  font-weight: 600;
  margin: 0;
}

.section-header--inner {
  margin-bottom: var(--sp-3);
}

.section-badge {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--ac);
  background: color-mix(in srgb, var(--ac) 12%, transparent);
  padding: 1px 8px;
  border-radius: var(--r-pill);
  margin-left: var(--sp-1);
}

.node-panel {
  width: 100%;
}

.empty-hint {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  color: var(--t3);
  font-size: var(--text-sm);
  padding: var(--sp-6) 0;
}

/* ── Donut ── */
.status-card {
  padding: var(--sp-4);
}

.donut-chart {
  width: 100%;
  height: 260px;
}

/* ── Status Legend ── */
.status-legend {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
  padding: 0 var(--sp-1) var(--sp-2);
}

.legend-item {
  display: grid;
  grid-template-columns: 8px 1fr auto auto;
  align-items: center;
  gap: var(--sp-2);
  padding: 3px 0;
}

.legend-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.legend-label {
  font-size: var(--text-xs);
  color: var(--t2);
}

.legend-count {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--t1);
  font-variant-numeric: tabular-nums;
  text-align: right;
}

.legend-pct {
  font-size: var(--text-xs);
  color: var(--t3);
  font-variant-numeric: tabular-nums;
  width: 34px;
  text-align: right;
}

/* ── Probe Card ── */
.probe-card {
  padding: var(--sp-5);
}

/* ── Responsive ── */
@media (max-width: 768px) {
  .kpi-row {
    grid-template-columns: repeat(2, 1fr);
  }

  .dash-columns {
    grid-template-columns: 1fr;
  }

  .donut-chart {
    height: 200px;
  }
}
</style>

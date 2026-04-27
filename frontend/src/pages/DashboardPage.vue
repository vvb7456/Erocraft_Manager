<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { PieChart } from 'echarts/charts'
import { TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

import PageHeader from '@/components/layout/PageHeader.vue'
import BaseCard from '@/components/ui/BaseCard.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import Spinner from '@/components/ui/Spinner.vue'
import AlertBanner from '@/components/ui/AlertBanner.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import AddCard from '@/components/ui/AddCard.vue'
import BaseModal from '@/components/ui/BaseModal.vue'

import KpiTile from '@/components/dashboard/KpiTile.vue'
import DashboardHostCard from '@/components/dashboard/DashboardHostCard.vue'
import type { DashboardHostData } from '@/components/dashboard/DashboardHostCard.vue'
import DashboardAlertItem from '@/components/dashboard/DashboardAlertItem.vue'
import DashboardExpiringRow from '@/components/dashboard/DashboardExpiringRow.vue'
import DashboardActivityRow from '@/components/dashboard/DashboardActivityRow.vue'
import DashboardTrendsChart from '@/components/dashboard/DashboardTrendsChart.vue'

use([PieChart, TooltipComponent, LegendComponent, CanvasRenderer])

defineOptions({ name: 'DashboardPage' })

const MAX_PINNED = 4
const PIN_STORAGE_KEY = 'erocraft.dashboard.pinnedHostIds'

const { t } = useI18n({ useScope: 'global' })
const dashboardApi = useApiFetch()
const monitoringApi = useApiFetch()
const alertsApi = useApiFetch()
const activityApi = useApiFetch()

/* ── Types ── */
interface ExpiringServer {
  id: number
  name: string
  ownerUsername: string | null
  ownerEmail: string | null
  nodeName: string | null
  expiresAt: string | null
  daysLeft: number
  isSuspended: boolean
}
interface CertSummary { total: number; expiringSoon: number; expired: number }
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
  expiringServers: ExpiringServer[]
  certSummary: CertSummary
}
interface MonitoringData {
  nodes: DashboardHostData[]
  probes: unknown[]
  alerts: { active: number; todayTotal: number }
}
interface AlertItem {
  id: number; hostId: number | null; alertType: string; severity: string
  message: string | null; createdAt: string; resolvedAt: string | null; notified: boolean
}
interface ActivityItem {
  id: number; timestamp: string | null; actor: string; action: string; status: string
  category?: string | null; detailKey?: string | null; detailParams?: Record<string, unknown> | null
}

/* ── State ── */
const data = ref<DashboardData | null>(null)
const monitoring = ref<MonitoringData | null>(null)
const alerts = ref<AlertItem[]>([])
const activity = ref<ActivityItem[]>([])
const loading = ref(true)
const fatalError = ref<string | null>(null)
const notConfigured = ref(false)

const hostMap = computed<Record<number, DashboardHostData>>(() => {
  const m: Record<number, DashboardHostData> = {}
  for (const n of monitoring.value?.nodes ?? []) m[n.id] = n
  return m
})

/* ── Pinned hosts (localStorage) ── */
const pinnedIds = ref<number[]>([])
const pickerOpen = ref(false)

function loadPinned() {
  try {
    const raw = localStorage.getItem(PIN_STORAGE_KEY)
    if (raw) {
      const arr = JSON.parse(raw)
      if (Array.isArray(arr)) pinnedIds.value = arr.filter((x): x is number => typeof x === 'number').slice(0, MAX_PINNED)
    }
  } catch { /* ignore */ }
}
function savePinned() {
  try { localStorage.setItem(PIN_STORAGE_KEY, JSON.stringify(pinnedIds.value)) } catch { /* ignore */ }
}
function pinHost(id: number) {
  if (pinnedIds.value.includes(id)) return
  if (pinnedIds.value.length >= MAX_PINNED) return
  pinnedIds.value = [...pinnedIds.value, id]
  savePinned()
  if (availableHosts.value.length === 0) pickerOpen.value = false
}
function unpinHost(id: number) {
  pinnedIds.value = pinnedIds.value.filter(x => x !== id)
  savePinned()
}

/* Auto-fill on first load if user has none pinned yet */
const autoFilledOnce = ref(false)
watch(() => monitoring.value?.nodes, (nodes) => {
  if (autoFilledOnce.value) return
  if (!nodes?.length) return
  if (pinnedIds.value.length === 0) {
    pinnedIds.value = nodes.slice(0, MAX_PINNED).map(n => n.id)
    savePinned()
  } else {
    // prune ids that no longer exist
    const valid = new Set(nodes.map(n => n.id))
    const next = pinnedIds.value.filter(x => valid.has(x))
    if (next.length !== pinnedIds.value.length) {
      pinnedIds.value = next
      savePinned()
    }
  }
  autoFilledOnce.value = true
})

const pinnedHosts = computed<DashboardHostData[]>(() =>
  pinnedIds.value.map(id => hostMap.value[id]).filter((x): x is DashboardHostData => !!x),
)
const availableHosts = computed<DashboardHostData[]>(() => {
  const set = new Set(pinnedIds.value)
  return (monitoring.value?.nodes ?? []).filter(n => !set.has(n.id))
})
const slotCount = computed(() => Math.min(MAX_PINNED, Math.max(pinnedHosts.value.length + 1, 1)))
const emptySlots = computed(() => Array.from({ length: Math.max(0, slotCount.value - pinnedHosts.value.length) }))
const canAddMore = computed(() => pinnedIds.value.length < MAX_PINNED && availableHosts.value.length > 0)

const hostsByName = computed<Record<number, string>>(() => {
  const m: Record<number, string> = {}
  for (const n of monitoring.value?.nodes ?? []) m[n.id] = n.name
  return m
})

/* All monitored hosts feed the trend charts */
const trendHosts = computed(() =>
  (monitoring.value?.nodes ?? []).map(n => ({ id: n.id, name: n.name })),
)

/* Palette must mirror DashboardTrendsChart so the inline legend matches the chart lines */
const TREND_PALETTE = [
  'var(--ac)', 'var(--blue)', 'var(--amber)', 'var(--green)', 'var(--red)', 'var(--ac2)',
]

/* ── Theme tokens ── */
type Tokens = { bg2: string; bg3: string; bd: string; t1: string; t2: string; t3: string; green: string; amber: string; red: string; blue: string; ac: string }
const DEFAULT_TOKENS: Tokens = {
  bg2: '#182020', bg3: '#111818', bd: '#263434',
  t1: '#e4ece8', t2: '#94a8a0', t3: '#5a706a',
  green: '#34d399', amber: '#f59e0b', red: '#ef6060', blue: '#60a5fa', ac: '#14b8a6',
}
const tokens = ref<Tokens>({ ...DEFAULT_TOKENS })
let themeObserver: MutationObserver | null = null
function readTokens() {
  if (typeof document === 'undefined') return
  const cs = getComputedStyle(document.documentElement)
  const pick = (n: string, f: string) => cs.getPropertyValue(n).trim() || f
  tokens.value = {
    bg2: pick('--bg2', DEFAULT_TOKENS.bg2),
    bg3: pick('--bg3', DEFAULT_TOKENS.bg3),
    bd: pick('--bd', DEFAULT_TOKENS.bd),
    t1: pick('--t1', DEFAULT_TOKENS.t1),
    t2: pick('--t2', DEFAULT_TOKENS.t2),
    t3: pick('--t3', DEFAULT_TOKENS.t3),
    green: pick('--green', DEFAULT_TOKENS.green),
    amber: pick('--amber', DEFAULT_TOKENS.amber),
    red: pick('--red', DEFAULT_TOKENS.red),
    blue: pick('--blue', DEFAULT_TOKENS.blue),
    ac: pick('--ac', DEFAULT_TOKENS.ac),
  }
}

/* ── Derived ── */
const onlineHostCount = computed(() => (monitoring.value?.nodes ?? []).filter(n => n.agentOnline).length)
const totalHostCount = computed(() => monitoring.value?.nodes?.length ?? 0)
const totalsForKpi = computed(() => {
  const d = data.value?.statusDistribution
  if (!d) return null
  return { normal: d.normal, expiringSoon: d.expiring_soon, expired: d.expired }
})

/* ── Donut option ── */
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
      radius: ['62%', '82%'],
      center: ['50%', '50%'],
      avoidLabelOverlap: false,
      label: {
        show: true,
        position: 'center',
        formatter: () => `{total|${total}}\n{sub|${t('dashboard.stats.totalServers')}}`,
        rich: {
          total: { fontSize: 32, fontWeight: 700, color: tk.t1, lineHeight: 40 },
          sub: { fontSize: 11, color: tk.t3, lineHeight: 18 },
        },
      },
      labelLine: { show: false },
      itemStyle: { borderRadius: 4, borderColor: tk.bg2, borderWidth: 2 },
      emphasis: {
        scale: true, scaleSize: 4,
        itemStyle: { shadowBlur: 12, shadowColor: 'rgba(20,184,166,0.35)' },
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

/* ── Loaders ── */
let alive = true
async function loadDashboard() {
  const res = await dashboardApi.get<DashboardData>('/api/admin/dashboard')
  if (!alive) return
  if (res) data.value = res
  else if (dashboardApi.error.value) notConfigured.value = true
}
async function loadMonitoring() {
  const res = await monitoringApi.get<MonitoringData>('/api/admin/monitoring/overview')
  if (!alive) return
  if (res) monitoring.value = res
}
async function loadAlerts() {
  const res = await alertsApi.get<{ items: AlertItem[]; total: number }>(
    '/api/admin/monitoring/alerts?active_only=true&limit=12'
  )
  if (!alive) return
  if (res?.items) alerts.value = res.items
}
async function loadActivity() {
  const res = await activityApi.get<{ logs: ActivityItem[] }>(
    '/api/admin/activity-logs?per_page=15'
  )
  if (!alive) return
  if (res?.logs) activity.value = res.logs
}
async function refreshLive() {
  await Promise.all([loadDashboard(), loadMonitoring(), loadAlerts(), loadActivity()])
}

let pollTimer: ReturnType<typeof setInterval> | null = null

onMounted(async () => {
  loadPinned()
  readTokens()
  if (typeof MutationObserver !== 'undefined') {
    themeObserver = new MutationObserver(readTokens)
    themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme', 'class'],
    })
  }
  loading.value = true
  try { await refreshLive() }
  catch (e) { fatalError.value = String(e) }
  finally { if (alive) loading.value = false }
  pollTimer = setInterval(refreshLive, 30_000)
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
    <div v-if="loading && !data" class="loading">
      <Spinner size="lg" />
    </div>

    <EmptyState
      v-else-if="notConfigured"
      icon="settings"
      :title="t('dashboard.notConfigured')"
      :message="t('dashboard.notConfiguredMsg')"
    >
      <BaseButton variant="primary" href="#/admin/settings" style="margin-top: var(--sp-3)">
        {{ t('dashboard.goToSettings') }}
      </BaseButton>
    </EmptyState>

    <AlertBanner v-else-if="fatalError" tone="danger" icon="error">
      {{ fatalError }}
    </AlertBanner>

    <template v-else-if="data">
      <!-- ── KPI Row ── -->
      <div class="kpi-row">
        <KpiTile
          icon="dns"
          :label="t('dashboard.kpi.servers')"
          :value="data.totalServers"
          :sub-items="totalsForKpi ? [
            { label: t('dashboard.status.normal'), value: totalsForKpi.normal, tone: 'green' },
            { label: t('dashboard.status.expiringSoon'), value: totalsForKpi.expiringSoon, tone: totalsForKpi.expiringSoon > 0 ? 'amber' : 'default' },
            { label: t('dashboard.status.expired'), value: totalsForKpi.expired, tone: totalsForKpi.expired > 0 ? 'red' : 'default' },
          ] : []"
        />
        <KpiTile
          icon="group"
          :label="t('dashboard.kpi.users')"
          :value="data.totalUsers"
        />
        <KpiTile
          icon="hub"
          :label="t('dashboard.kpi.hosts')"
          :value="`${onlineHostCount}/${totalHostCount}`"
          :tone="monitoring && monitoring.alerts.active > 0 ? 'amber' : 'default'"
          :sub-items="monitoring ? [
            { label: t('dashboard.kpi.activeAlerts'), value: monitoring.alerts.active, tone: monitoring.alerts.active > 0 ? 'amber' : 'default' },
          ] : []"
        />
        <KpiTile
          icon="verified"
          :label="t('dashboard.kpi.certs')"
          :value="data.certSummary.expiringSoon"
          :tone="data.certSummary.expired > 0 ? 'red' : (data.certSummary.expiringSoon > 0 ? 'amber' : 'default')"
          :sub-items="[
            { label: t('dashboard.kpi.certTotal'), value: data.certSummary.total },
            ...(data.certSummary.expired > 0 ? [{ label: t('dashboard.status.expired'), value: data.certSummary.expired, tone: 'red' as const }] : []),
          ]"
        />
      </div>

      <!-- ── Row A: Pinned hosts (2/3) + Status distribution donut (1/3) ── -->
      <div class="row row-a">
        <section class="hosts-section">
          <header class="sec-head">
            <div class="sec-title">
              <MsIcon name="memory" size="sm" />
              <h3>{{ t('dashboard.section.infrastructure') }}</h3>
              <span class="sec-badge">
                {{ pinnedHosts.length }}/{{ MAX_PINNED }}
              </span>
            </div>
          </header>

          <div class="host-grid">
            <DashboardHostCard
              v-for="host in pinnedHosts"
              :key="host.id"
              :host="host"
              removable
              @unpin="unpinHost"
            />
            <AddCard
              v-for="(_, i) in emptySlots"
              :key="`add-${i}`"
              :label="i === 0 && canAddMore ? t('dashboard.host.add') : t('dashboard.host.empty')"
              :disabled="!canAddMore"
              @click="canAddMore && (pickerOpen = true)"
            />
          </div>
        </section>

        <section class="dist-section">
          <header class="sec-head">
            <div class="sec-title">
              <MsIcon name="pie_chart" size="sm" />
              <h3>{{ t('dashboard.chart.title') }}</h3>
            </div>
          </header>
          <BaseCard variant="bg2" class="dist-card stretch-card">
            <VChart class="donut-chart" :option="donutOption" autoresize />
            <div class="legend">
              <span v-for="i in legendItems" :key="i.label" class="leg-item">
                <span class="leg-dot" :style="{ background: i.color }" />
                <span class="leg-lab">{{ i.label }}</span>
                <span class="leg-cnt">{{ i.count }}</span>
                <span class="leg-pct">({{ i.pct }}%)</span>
              </span>
            </div>
          </BaseCard>
        </section>
      </div>

      <!-- ── Row B: Cluster trends (4 charts) ── -->
      <section class="trends-section">
        <header class="sec-head">
          <div class="sec-title">
            <MsIcon name="monitoring" size="sm" />
            <h3>{{ t('dashboard.section.trends') }}</h3>
            <span class="sec-badge sec-badge--mute">24h</span>
            <span v-if="(monitoring?.nodes ?? []).length" class="trends-legend">
              <span
                v-for="(h, i) in (monitoring?.nodes ?? [])"
                :key="h.id"
                class="tl-item"
              >
                <span class="tl-dot" :style="{ background: TREND_PALETTE[i % TREND_PALETTE.length] }" />
                {{ h.name }}
              </span>
            </span>
          </div>
        </header>
        <div class="trends-grid">
          <BaseCard variant="bg2" class="trend-card">
            <div class="trend-head"><MsIcon name="memory" size="xs" />CPU</div>
            <div class="trend-body">
              <DashboardTrendsChart
                :hosts="trendHosts"
                metric="cpu"
                unit="pct"
                window="24h"
              />
            </div>
          </BaseCard>
          <BaseCard variant="bg2" class="trend-card">
            <div class="trend-head"><MsIcon name="memory" size="xs" />MEM</div>
            <div class="trend-body">
              <DashboardTrendsChart
                :hosts="trendHosts"
                metric="mem"
                unit="pct"
                window="24h"
              />
            </div>
          </BaseCard>
          <BaseCard variant="bg2" class="trend-card">
            <div class="trend-head"><MsIcon name="arrow_upward" size="xs" />NET TX</div>
            <div class="trend-body">
              <DashboardTrendsChart
                :hosts="trendHosts"
                metric="net_tx"
                unit="bps"
                window="24h"
              />
            </div>
          </BaseCard>
          <BaseCard variant="bg2" class="trend-card">
            <div class="trend-head"><MsIcon name="save" size="xs" />DISK WRITE</div>
            <div class="trend-body">
              <DashboardTrendsChart
                :hosts="trendHosts"
                metric="disk_write"
                unit="bps"
                window="24h"
              />
            </div>
          </BaseCard>
        </div>
      </section>

      <!-- ── Row C: Alerts · Expiring · Activity ── -->
      <div class="row row-c">
        <section class="alerts-section">
          <header class="sec-head">
            <div class="sec-title">
              <MsIcon name="warning" size="sm" />
              <h3>{{ t('dashboard.section.alerts') }}</h3>
              <span v-if="alerts.length" class="sec-badge sec-badge--warn">{{ alerts.length }}</span>
            </div>
          </header>
          <BaseCard variant="bg2" class="alerts-card stretch-card">
            <div v-if="alerts.length" class="alerts-list">
              <DashboardAlertItem
                v-for="a in alerts"
                :key="a.id"
                :alert-type="a.alertType"
                :severity="a.severity"
                :message="a.message"
                :host-name="a.hostId ? hostsByName[a.hostId] : null"
                :created-at="a.createdAt"
              />
            </div>
            <div v-else class="empty-inline empty-inline--ok">
              <MsIcon name="check_circle" size="md" />
              <span>{{ t('dashboard.empty.alerts') }}</span>
            </div>
          </BaseCard>
        </section>

        <section class="exp-section">
          <header class="sec-head">
            <div class="sec-title">
              <MsIcon name="schedule" size="sm" />
              <h3>{{ t('dashboard.section.expiring') }}</h3>
              <span v-if="data.expiringServers.length" class="sec-badge sec-badge--warn">
                {{ data.expiringServers.length }}
              </span>
            </div>
          </header>
          <BaseCard variant="bg2" class="exp-card stretch-card">
            <div v-if="data.expiringServers.length" class="exp-list">
              <DashboardExpiringRow
                v-for="srv in data.expiringServers"
                :key="srv.id"
                v-bind="srv"
              />
            </div>
            <div v-else class="empty-inline empty-inline--ok">
              <MsIcon name="check_circle" size="md" />
              <span>{{ t('dashboard.empty.expiring') }}</span>
            </div>
          </BaseCard>
        </section>

        <section class="activity-section">
          <header class="sec-head">
            <div class="sec-title">
              <MsIcon name="history" size="sm" />
              <h3>{{ t('dashboard.section.activity') }}</h3>
            </div>
          </header>
          <BaseCard variant="bg2" class="activity-card stretch-card">
            <div v-if="activity.length" class="activity-list">
              <DashboardActivityRow
                v-for="log in activity"
                :key="log.id"
                :timestamp="log.timestamp"
                :actor="log.actor"
                :action="log.action"
                :status="log.status"
                :category="log.category"
                :detail-key="log.detailKey"
                :detail-params="log.detailParams"
              />
            </div>
            <div v-else class="empty-inline">
              <MsIcon name="history" size="md" />
              <span>{{ t('dashboard.empty.activity') }}</span>
            </div>
          </BaseCard>
        </section>
      </div>
    </template>
  </div>

  <!-- ── Host picker modal ── -->
  <BaseModal
    v-model="pickerOpen"
    :title="t('dashboard.host.pickerTitle')"
    :subtitle="t('dashboard.host.pickerSubtitle', { remaining: MAX_PINNED - pinnedIds.length })"
    icon="hub"
    size="md"
  >
    <div v-if="availableHosts.length" class="picker-list">
      <button
        v-for="h in availableHosts"
        :key="h.id"
        type="button"
        class="picker-item"
        :disabled="pinnedIds.length >= MAX_PINNED"
        @click="pinHost(h.id)"
      >
        <span class="pick-name">{{ h.name }}</span>
        <span class="pick-fqdn">{{ h.fqdn }}</span>
        <span class="pick-kind">{{ t(`hosts.kind.${h.kind}`) }}</span>
        <MsIcon name="add" size="sm" />
      </button>
    </div>
    <EmptyState
      v-else
      icon="check_circle"
      :title="t('dashboard.host.allPinned')"
    />
  </BaseModal>
</template>

<style scoped>
.page-body {
  display: flex;
  flex-direction: column;
  gap: var(--sp-6);
  padding-bottom: var(--sp-8);
}
.loading { display: flex; justify-content: center; padding: var(--sp-8); }

/* ── KPI Row ── */
.kpi-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--sp-4);
}

/* ── Section header ── */
.sec-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  margin-bottom: var(--sp-3);
}
.sec-title {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  color: var(--t1);
}
.sec-title h3 {
  margin: 0;
  font-size: var(--text-base);
  font-weight: 600;
}
.sec-badge {
  font-size: var(--text-xs);
  font-weight: 600;
  padding: 1px 8px;
  border-radius: var(--r-pill);
  background: color-mix(in srgb, var(--ac) 12%, transparent);
  color: var(--ac);
  font-variant-numeric: tabular-nums;
}
.sec-badge--warn {
  background: color-mix(in srgb, var(--amber) 18%, transparent);
  color: var(--amber);
}
.sec-badge--mute {
  background: var(--bg);
  color: var(--t3);
}

/* ─ Row layouts ─ */
.row {
  display: grid;
  gap: var(--sp-5);
}
.row-a { grid-template-columns: 2fr 1fr; }
.row-c { grid-template-columns: 1fr 1.2fr 1.5fr; }

/* Each section becomes a flex column so its inner card grows to fill row height */
.row > section {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.stretch-card {
  flex: 1;
  display: flex;
  flex-direction: column;
}

/* ── Hosts grid ── */
.host-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--sp-3);
  flex: 1;
  align-content: start;
}

/* ── Alerts ── */
.alerts-card { padding: var(--sp-2); overflow: auto; }
.alerts-list {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

/* ── Distribution donut ── */
.dist-card {
  padding: var(--sp-3) var(--sp-4) var(--sp-3);
  display: flex;
  flex-direction: column;
}
.donut-chart {
  width: 100%;
  flex: 1;
  min-height: 200px;
}
.legend {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-1) var(--sp-3);
  padding-top: var(--sp-2);
  border-top: 1px dashed var(--bd);
  margin-top: var(--sp-2);
  justify-content: center;
}
.leg-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: var(--text-xs);
  white-space: nowrap;
}
.leg-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.leg-lab { color: var(--t2); }
.leg-cnt { color: var(--t1); font-weight: 600; font-variant-numeric: tabular-nums; }
.leg-pct { color: var(--t3); font-variant-numeric: tabular-nums; }

/* ─ Expiring (denser) ─ */
.exp-card {
  padding: 0;
  overflow: auto;
}
.exp-list {
  display: flex;
  flex-direction: column;
}

/* ─ Activity (denser) ─ */
.activity-card {
  padding: 0;
  overflow: auto;
}
.activity-list {
  display: flex;
  flex-direction: column;
}

/* ─ Trends row ─ */
.trends-section { display: flex; flex-direction: column; }
.trends-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--sp-3);
}
.trend-card {
  display: flex;
  flex-direction: column;
  padding: var(--sp-2) var(--sp-2) var(--sp-1);
  height: 200px;
}
.trend-head {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.06em;
  color: var(--t3);
  text-transform: uppercase;
  padding: 0 var(--sp-1) 4px;
}
.trend-body { flex: 1; min-height: 0; }

/* Inline legend in trends section header */
.trends-legend {
  display: inline-flex;
  flex-wrap: wrap;
  gap: var(--sp-1) var(--sp-3);
  margin-left: var(--sp-3);
}
.tl-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: var(--text-xs);
  color: var(--t2);
  white-space: nowrap;
}
.tl-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

/* ── Empty states ── */
.empty-inline {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--sp-2);
  padding: var(--sp-6);
  color: var(--t3);
  font-size: var(--text-sm);
  flex: 1;
}
.empty-inline--ok { color: var(--green); }
.empty-inline--ok :deep(.ms-icon),
.empty-inline--ok :deep(.ms) { color: var(--green); }

/* ── Picker modal ── */
.picker-list {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
  max-height: 50vh;
  overflow: auto;
}
.picker-item {
  display: grid;
  grid-template-columns: 1fr 2fr auto auto;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-2) var(--sp-3);
  background: var(--bg3);
  border: 1px solid var(--bd);
  border-radius: var(--r-md);
  color: var(--t1);
  cursor: pointer;
  font-size: var(--text-sm);
  text-align: left;
  transition: border-color .12s ease, background .12s ease;
}
.picker-item:hover:not(:disabled) {
  border-color: var(--bd-f);
  background: var(--bg4);
}
.picker-item:disabled { opacity: 0.5; cursor: not-allowed; }
.pick-name { font-weight: 600; }
.pick-fqdn { color: var(--t3); font-family: var(--font-mono); font-size: var(--text-xs); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.pick-kind {
  font-size: var(--text-xs);
  color: var(--t2);
  padding: 1px 8px;
  border-radius: var(--r-pill);
  background: var(--bg);
}

/* ── Responsive ── */
@media (max-width: 1400px) {
  .row-c { grid-template-columns: 1fr 1fr; }
  .row-c .activity-section { grid-column: 1 / -1; }
  .trends-grid { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 1100px) {
  .row-a { grid-template-columns: 1.5fr 1fr; }
}
@media (max-width: 900px) {
  .kpi-row { grid-template-columns: repeat(2, 1fr); }
  .row-a, .row-c { grid-template-columns: 1fr; }
  .row-c .activity-section { grid-column: auto; }
  .host-grid { grid-template-columns: 1fr; }
  .trends-grid { grid-template-columns: 1fr; }
}
@media (max-width: 560px) {
  .kpi-row { grid-template-columns: 1fr; }
}
</style>

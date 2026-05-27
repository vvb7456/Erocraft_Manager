<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useApiFetch } from '@/composables/useApiFetch'
import { useConfirm } from '@/composables/useConfirm'
import { useToast } from '@/composables/useToast'
import { useServerResourceStore } from '@/stores/serverResources'
import { usePowerPendingStore, type PowerAction } from '@/stores/powerPending'
import { useAppStore } from '@/stores/app'
import { getEggMeta, hasWebUi } from '@/config/eggRegistry'
import PageHeader from '@/components/layout/PageHeader.vue'
import SectionToolbar from '@/components/ui/SectionToolbar.vue'
import FilterInput from '@/components/ui/FilterInput.vue'
import DataTable from '@/components/ui/DataTable.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import StatusDot from '@/components/ui/StatusDot.vue'
import Badge from '@/components/ui/Badge.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import StatCard from '@/components/ui/StatCard.vue'
import ActionSheet from '@/components/ui/ActionSheet.vue'
import CardTap from '@/components/ui/CardTap.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import UsageBar from '@/components/ui/UsageBar.vue'
import ToggleSwitch from '@/components/ui/ToggleSwitch.vue'
import { getStatusDotKey, getStatusColor } from '@/utils/status'
import { useRenewFlow } from '@/composables/useRenewFlow'
import CreateOrderModal from '@/components/CreateOrderModal.vue'

defineOptions({ name: 'UserServersPage' })

const { t, te } = useI18n({ useScope: 'global' })
const router = useRouter()
const { get } = useApiFetch()
const { confirm } = useConfirm()
const { toast } = useToast()
const app = useAppStore()
const resourceStore = useServerResourceStore()
const pendingStore = usePowerPendingStore()

interface Server {
  id: number
  uuid: string
  name: string
  status: string | null
  isSuspended: boolean
  isInstalling: boolean
  isInstalled: boolean
  nodeId: number
  eggId: number
  eggName: string
  limits: { memory: number; disk: number; cpu: number }
  allocation: { ip: string | null; port: number | null }
  node: { fqdn: string | null }
  expirationDate: string | null
  daysLeft: number | null
  address: string | null
  planId: number | null
  hasUpgradeOptions: boolean
}

const servers = ref<Server[]>([])
const initialLoading = ref(true)
const searchTerm = ref('')
const page = ref(1)
const perPage = ref(20)
const showAllServers = ref(false)
const canShowAllServers = computed(() => app.isAdmin)

// ── Selection & batch ──
const selectedIds = ref<Set<number>>(new Set())
const batchActionType = ref('')
const batchActionOptions = computed(() => [
  { value: 'start', label: t('userServers.power.start') },
  { value: 'restart', label: t('userServers.power.restart') },
  { value: 'stop', label: t('userServers.power.stop') },
  { value: 'kill', label: t('userServers.power.kill') },
])

const allSelected = computed({
  get: () => paginated.value.length > 0 && paginated.value.every(s => selectedIds.value.has(s.id)),
  set: (v: boolean) => {
    const s = new Set(selectedIds.value)
    if (v) {
      paginated.value.forEach(srv => s.add(srv.id))
    } else {
      paginated.value.forEach(srv => s.delete(srv.id))
    }
    selectedIds.value = s
  },
})

function toggleSelect(id: number) {
  const s = new Set(selectedIds.value)
  if (s.has(id)) s.delete(id)
  else s.add(id)
  selectedIds.value = s
}

async function executeBatchAction() {
  const ids = [...selectedIds.value]
  if (!ids.length || !batchActionType.value) return
  const action = batchActionType.value
  if (action === 'restart' || action === 'stop' || action === 'kill') {
    const msgKey = action === 'restart' ? 'confirmRestart' : action === 'stop' ? 'confirmStop' : 'confirmKill'
    const ok = await confirm({
      title: t(action === 'kill' ? 'common.confirm.dangerTitle' : 'common.confirm.title'),
      message: t(`userServers.power.${msgKey}`),
      confirmText: t(`userServers.power.${action}`),
      variant: action === 'kill' ? 'danger' : 'default',
    })
    if (!ok) return
  }
  const actionTyped = action as PowerAction
  // Filter: skip servers with pending actions, and skip servers in inapplicable states
  const allowedIds = ids.filter(id => {
    if (!pendingStore.isActionAllowed(id, actionTyped)) return false
    const state = resourceStore.getState(id)
    if (actionTyped === 'start' && state !== 'offline' && state !== 'stopped') return false
    if ((actionTyped === 'stop' || actionTyped === 'restart') && state !== 'running') return false
    if (actionTyped === 'kill' && state !== 'running' && state !== 'stopping') return false
    return true
  })
  if (!allowedIds.length) return
  // Suppress per-server toasts (pass undefined for toastFn) so we can present
  // a single aggregated summary at the end. (Audit FM6.)
  const results = await Promise.allSettled(
    allowedIds.map(id => pendingStore.sendPower(id, actionTyped, undefined)),
  )
  const failedIds: number[] = []
  results.forEach((r, idx) => {
    const id = allowedIds[idx]
    if (r.status === 'rejected') failedIds.push(id)
    else if (r.value !== null) failedIds.push(id)  // PowerError returned
  })
  const total = allowedIds.length
  const okCount = total - failedIds.length
  if (failedIds.length === 0) {
    toast(t('userServers.batch.resultAllOk', { total }), 'success')
  } else {
    const failedNames = failedIds
      .map(id => servers.value.find(s => s.id === id)?.name ?? `#${id}`)
      .join('、')
    if (okCount === 0) {
      toast(t('userServers.batch.resultAllFail', { total, names: failedNames }), 'error')
    } else {
      toast(t('userServers.batch.resultPartial', { ok: okCount, total, names: failedNames }), 'warning')
    }
  }
  selectedIds.value = new Set()
  batchActionType.value = ''
}

// ── Summary stats ──
const totalServers = computed(() => servers.value.length)
const runningCount = computed(() =>
  servers.value.filter(s => resourceStore.getState(s.id) === 'running').length
)
const needRenewCount = computed(() =>
  servers.value.filter(s => s.daysLeft !== null && s.daysLeft <= 7).length
)

// ── Filtered & paginated list ──
const filteredServers = computed(() => {
  const q = searchTerm.value.toLowerCase().trim()
  if (!q) return servers.value
  return servers.value.filter(s => s.name.toLowerCase().includes(q))
})

const totalPages = computed(() => Math.max(1, Math.ceil(filteredServers.value.length / perPage.value)))

const paginated = computed(() => {
  const start = (page.value - 1) * perPage.value
  return filteredServers.value.slice(start, start + perPage.value)
})

function pruneSelectionToCurrentPage() {
  const pageIds = new Set(paginated.value.map((server) => server.id))
  const next = new Set(
    [...selectedIds.value].filter((id) => pageIds.has(id)),
  )
  if (next.size !== selectedIds.value.size) {
    selectedIds.value = next
  }
  if (selectedIds.value.size === 0) {
    batchActionType.value = ''
  }
}

watch(paginated, pruneSelectionToCurrentPage, { immediate: true })

// ── Load data ──
async function loadServers() {
  const scope = canShowAllServers.value && showAllServers.value ? 'all' : 'owner'
  const data = await get<Server[]>(`/api/user/servers?scope=${scope}`)
  if (data) {
    servers.value = data
    // Subscribe to store with 5s interval (faster than sidebar's 10s)
    const ids = data.map(s => s.id)
    if (ids.length > 0) {
      resourceStore.subscribe('serverList', ids, 5000)
    }
  }
  initialLoading.value = false
}

onMounted(() => {
  loadServers()
})

onBeforeUnmount(() => {
  resourceStore.unsubscribe('serverList')
  if (installPollTimer) clearInterval(installPollTimer)
})

// Poll server list while any server is installing, to detect completion
const hasInstalling = computed(() => servers.value.some(s => s.isInstalling))
let installPollTimer: ReturnType<typeof setInterval> | null = null
watch(hasInstalling, (val) => {
  if (val && !installPollTimer) {
    installPollTimer = setInterval(loadServers, 10000)
  } else if (!val && installPollTimer) {
    clearInterval(installPollTimer)
    installPollTimer = null
  }
}, { immediate: true })

watch(showAllServers, () => {
  page.value = 1
  selectedIds.value = new Set()
  batchActionType.value = ''
  loadServers()
})

// ── Helpers ──
function liveState(s: Server): string {
  return resourceStore.getState(s.id) || s.status || 'offline'
}

function displayState(s: Server): string {
  if (resourceStore.isStale(s.id)) return 'disconnected'
  if (s.isSuspended) return 'suspended'
  if (s.isInstalling) return 'installing'
  const st = liveState(s)
  return st === 'stopped' ? 'offline' : st
}

function statusDotKeyFor(s: Server) {
  return getStatusDotKey(liveState(s), s.isSuspended, s.isInstalling, resourceStore.isStale(s.id))
}

function statusBadgeColor(s: Server): string {
  return getStatusColor(liveState(s), s.isSuspended, s.isInstalling, resourceStore.isStale(s.id))
}

function cpuText(s: Server): string {
  return (resourceStore.resources[s.id]?.cpu ?? 0).toFixed(1) + '%'
}

function cpuPercent(s: Server): number {
  // Bar percentage = used / allocated. CPU allocation may exceed 100% on
  // multi-core servers (e.g. 400 = 4 cores), so we must NOT cap the raw
  // absolute reading at 100 like the bar's 0-100 scale would suggest.
  const used = resourceStore.resources[s.id]?.cpu ?? 0
  const limit = s.limits.cpu
  if (!limit) return Math.max(0, Math.min(100, used))
  return Math.max(0, Math.min(100, (used / limit) * 100))
}

function memPercent(s: Server): number {
  if (!s.limits.memory) return 0
  const bytes = resourceStore.resources[s.id]?.memoryBytes ?? 0
  return Math.max(0, Math.min(100, (bytes / (s.limits.memory * 1024 * 1024)) * 100))
}

function diskPercent(s: Server): number {
  if (!s.limits.disk) return 0
  const bytes = resourceStore.resources[s.id]?.diskBytes ?? 0
  return Math.max(0, Math.min(100, (bytes / (s.limits.disk * 1024 * 1024)) * 100))
}

function cpuLimitText(s: Server): string {
  return s.limits.cpu ? `${s.limits.cpu}%` : '∞'
}

function memoryLimitText(s: Server): string {
  if (!s.limits.memory) return '∞'
  return s.limits.memory >= 1024 ? `${(s.limits.memory / 1024).toFixed(1)} GB` : `${s.limits.memory} MB`
}

function diskLimitText(s: Server): string {
  if (!s.limits.disk) return '∞'
  return s.limits.disk >= 1024 ? `${(s.limits.disk / 1024).toFixed(1)} GB` : `${s.limits.disk} MB`
}

function netText(s: Server): string {
  const rx = resourceStore.resources[s.id]?.networkRx ?? 0
  const tx = resourceStore.resources[s.id]?.networkTx ?? 0
  return `↑${fmtBytes(tx)} ↓${fmtBytes(rx)}`
}

function uptimeText(s: Server): string {
  const ms = resourceStore.resources[s.id]?.uptime ?? 0
  if (ms <= 0) return '—'
  const sec = Math.floor(ms / 1000)
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

function fmtBytes(bytes: number): string {
  const mb = bytes / (1024 * 1024)
  if (mb < 1024) return mb.toFixed(mb < 1 ? 1 : 0) + ' MB'
  return (mb / 1024).toFixed(2) + ' GB'
}

function expirationDisplay(s: Server): { date: string; tag: string; color: string } {
  if (!s.expirationDate) return { date: '—', tag: t('userServers.permanent'), color: 'var(--t3)' }
  const dateStr = s.expirationDate.slice(0, 10)
  if (s.daysLeft !== null && s.daysLeft < 0) return { date: dateStr, tag: t('userServers.expired'), color: 'var(--red)' }
  if (s.daysLeft !== null) return { date: dateStr, tag: t('userServers.daysLeft', { n: s.daysLeft }), color: s.daysLeft <= 7 ? 'var(--amber)' : 'var(--green)' }
  return { date: dateStr, tag: '', color: 'var(--t2)' }
}

function openUrl(s: Server) {
  if (s.address) window.open(`http://${s.address}`, '_blank')
}

function openLabel(eggName: string): string {
  const lbl = getEggMeta(eggName).label
  return lbl ? t('userServers.openApp', { name: lbl }) : t('userServers.openAppGeneric')
}

// ── Power action ──
const CREDENTIALS_ERROR = 'server.startup_credentials_required'

async function togglePower(s: Server) {
  if (pendingStore.has(s.id)) return
  const st = liveState(s)
  const action: PowerAction = st === 'running' ? 'restart' : 'start'
  if (action === 'restart') {
    const ok = await confirm({
      title: t('common.confirm.title'),
      message: t('userServers.power.confirmRestart'),
      confirmText: t('userServers.power.restart'),
    })
    if (!ok) return
  }
  const err = await pendingStore.sendPower(s.id, action, toast, [CREDENTIALS_ERROR])
  if (err && err.code === CREDENTIALS_ERROR) {
    const fields = err.missing.length
      ? err.missing.map((k) => {
          const lk = `userServers.power.credField.${k}`
          return te(lk) ? t(lk) : k
        }).join(t('common.listSep'))
      : ''
    const goSettings = await confirm({
      title: t('userServers.power.credentialsRequiredTitle'),
      message: t('userServers.power.credentialsRequiredMessage', { fields }),
      confirmText: t('userServers.power.goToSettings'),
    })
    if (goSettings) {
      router.push({ name: 'server-settings', params: { id: s.id } })
    }
  }
}

function powerBtnLabel(s: Server): string {
  const pa = pendingStore.get(s.id)
  if (pa === 'restart') return t('userServers.status.restarting')
  if (pa === 'start') return t('userServers.status.starting')
  if (pa === 'kill') return t('userServers.status.killingPower')
  if (pa === 'stop') return t('userServers.status.stopping')
  const st = liveState(s)
  if (st === 'starting') return t('userServers.status.starting')
  if (st === 'stopping') return t('userServers.status.stopping')
  return st === 'running' ? t('userServers.power.restart') : t('userServers.power.start')
}

function powerBtnIcon(s: Server): string {
  if (pendingStore.has(s.id)) return 'hourglass_empty'
  const st = liveState(s)
  if (st === 'starting' || st === 'stopping') return 'hourglass_empty'
  return st === 'running' ? 'refresh' : 'play_arrow'
}

function goToDetail(s: Server) {
  router.push({ name: 'server-console', params: { id: s.id } })
}

const { openRenew, loading: renewLoading } = useRenewFlow()
async function onRenew(s: Server) {
  if (!s.planId) return
  await openRenew({ serverId: s.id, serverName: s.name, planId: s.planId })
}

// ── Upgrade ──
const upgradeModalOpen = ref(false)
const upgradeServer = ref<Server | null>(null)
function onUpgrade(s: Server) {
  upgradeServer.value = s
  upgradeModalOpen.value = true
}

// ── Mobile action sheet ──
const mobileActionServer = ref<Server | null>(null)
const mobileActionOpen = ref(false)
function openMobileAction(s: Server) {
  mobileActionServer.value = s
  mobileActionOpen.value = true
}
</script>

<template>
  <PageHeader icon="dns" :title="t('userServers.title')" />

  <div class="page-body">
    <!-- Summary cards -->
    <div class="summary-row">
      <StatCard :label="t('userServers.summary.total')">
        <template #value>{{ totalServers }}</template>
      </StatCard>
      <StatCard :label="t('userServers.summary.running')" status="running">
        <template #value>{{ runningCount }}</template>
      </StatCard>
      <StatCard :label="t('userServers.summary.needRenew')" status="error">
        <template #value>{{ needRenewCount }}</template>
      </StatCard>
    </div>

    <!-- Toolbar -->
    <SectionToolbar>
      <template #start>
        <FilterInput v-model="searchTerm" :placeholder="t('userServers.searchPlaceholder')" class="filter-input tb-search" @update:modelValue="selectedIds = new Set()" />
        <div class="batch-controls tb-batch">
          <BaseSelect v-model="batchActionType" :options="batchActionOptions" :placeholder="t('userServers.batch.selectAction')" size="sm" fit :disabled="selectedIds.size === 0" />
          <BaseButton size="sm" :disabled="selectedIds.size === 0 || !batchActionType" @click="executeBatchAction">
            <MsIcon name="play_arrow" size="xs" /> {{ t('userServers.batch.execute') }}
          </BaseButton>
          <span v-if="selectedIds.size > 0" class="toolbar-status tb-status">{{ t('userServers.batch.selected', { n: selectedIds.size }) }}</span>
        </div>
      </template>
      <template #end>
        <div v-if="canShowAllServers" class="scope-switch tb-btn-group">
          <span class="scope-switch__label">{{ t('userServers.scope.all') }}</span>
          <ToggleSwitch v-model="showAllServers" size="sm" />
        </div>
      </template>
    </SectionToolbar>

    <!-- Table / Cards -->
    <DataTable
      :items="paginated"
      :page="page"
      :total-pages="totalPages"
      :per-page="perPage"
      :per-page-label="t('userServers.pagination.perPage')"
      :loading="initialLoading"
      empty-icon="dns"
      :empty-text="t('userServers.empty')"
      row-key="id"
      @update:page="page = $event"
      @update:per-page="perPage = $event; page = 1"
    >
      <template #empty>
        <EmptyState
          icon="dns"
          :title="t('userServers.empty')"
        >
          <BaseButton variant="primary" @click="router.push({ name: 'user-plans' })">
            <MsIcon name="storefront" />
            {{ t('userServers.buyServer') }}
          </BaseButton>
        </EmptyState>
      </template>

      <template #header>
        <th class="col-check">
          <input type="checkbox" v-model="allSelected" />
        </th>
        <th class="col-dot"></th>
        <th class="col-name">{{ t('userServers.table.name') }}</th>
        <th class="col-plan">{{ t('userServers.table.plan') }}</th>
        <th class="col-status">{{ t('userServers.table.status') }}</th>
        <th class="col-cpu">CPU</th>
        <th class="col-mem">{{ t('userServers.resources.memory') }}</th>
        <th class="col-disk">{{ t('userServers.resources.disk') }}</th>
        <th class="col-net">{{ t('userServers.resources.network') }}</th>
        <th class="col-uptime">{{ t('userServers.resources.uptime') }}</th>
        <th class="col-expiry">{{ t('userServers.table.expiry') }}</th>
        <th class="col-actions">{{ t('userServers.table.actions') }}</th>
      </template>

      <template #row="{ item: s }">
        <td class="col-check">
          <input type="checkbox" :checked="selectedIds.has(s.id)" @change="toggleSelect(s.id)" />
        </td>
        <td class="col-dot">
          <StatusDot :status="statusDotKeyFor(s)" size="sm" />
        </td>
        <td class="col-name">
          <a class="server-link" href="#" @click.prevent="goToDetail(s)">{{ s.name }}</a>
        </td>
        <td class="col-plan">{{ s.planName || s.eggName }}</td>
        <td class="col-status" :style="{ color: statusBadgeColor(s), fontWeight: s.isSuspended || s.isInstalling ? 600 : undefined }">{{ t(`userServers.status.${displayState(s)}`) }}</td>
        <td class="col-cpu mono">{{ cpuText(s) }}</td>
        <td class="col-mem mono">
          <div class="dual-line">{{ fmtBytes(resourceStore.resources[s.id]?.memoryBytes ?? 0) }}<span class="dual-sub">{{ s.limits.memory }} MB</span></div>
        </td>
        <td class="col-disk mono">
          <div class="dual-line">{{ fmtBytes(resourceStore.resources[s.id]?.diskBytes ?? 0) }}<span class="dual-sub">{{ s.limits.disk }} MB</span></div>
        </td>
        <td class="col-net mono">
          <div class="dual-line">↑{{ fmtBytes(resourceStore.resources[s.id]?.networkTx ?? 0) }}<span class="dual-sub">↓{{ fmtBytes(resourceStore.resources[s.id]?.networkRx ?? 0) }}</span></div>
        </td>
        <td class="col-uptime mono">{{ uptimeText(s) }}</td>
        <td class="col-expiry">
          <div class="expiry-cell">
            <span class="expiry-date">{{ expirationDisplay(s).date }}</span>
            <span v-if="expirationDisplay(s).tag" class="expiry-tag" :style="{ color: expirationDisplay(s).color }">{{ expirationDisplay(s).tag }}</span>
          </div>
        </td>
        <td class="col-actions">
          <div class="action-group">
            <BaseButton size="sm" @click="goToDetail(s)">
              {{ t('userServers.console') }}
            </BaseButton>
            <BaseButton size="sm" :loading="pendingStore.has(s.id)" :disabled="s.isSuspended || s.isInstalling || resourceStore.isStale(s.id) || pendingStore.has(s.id) || liveState(s) === 'starting' || liveState(s) === 'stopping'" @click="togglePower(s)">
              <MsIcon :name="powerBtnIcon(s)" size="xs" /> {{ powerBtnLabel(s) }}
            </BaseButton>
            <BaseButton size="sm" :disabled="!s.planId" :loading="renewLoading" :title="s.planId ? '' : t('userServers.renewFlow.noPlan')" @click="onRenew(s)">
              <MsIcon name="autorenew" size="xs" /> {{ t('userServers.renew') }}
            </BaseButton>
            <BaseButton size="sm" :disabled="!s.hasUpgradeOptions" @click="onUpgrade(s)">
              <MsIcon name="arrow_upward" size="xs" /> {{ t('userServers.upgrade.button') }}
            </BaseButton>
            <BaseButton v-if="s.address && hasWebUi(s.eggName)" variant="primary" size="sm" :disabled="s.isSuspended || s.isInstalling || liveState(s) !== 'running'" @click="openUrl(s)">
              <MsIcon name="open_in_new" size="xs" /> {{ openLabel(s.eggName) }}
            </BaseButton>
          </div>
        </td>
      </template>

      <!-- Mobile card -->
      <template #card="{ item: s }">
        <CardTap @tap="openMobileAction(s)">
          <div class="card-row--main">
            <div class="mobile-server-card__title">
              <span class="card-name">{{ s.name }}</span>
              <span v-if="uptimeText(s) !== '—'" class="mobile-server-card__uptime mono">{{ uptimeText(s) }}</span>
            </div>
            <Badge :color="statusBadgeColor(s)">{{ t(`userServers.status.${displayState(s)}`) }}</Badge>
          </div>
          <div class="mobile-server-card__meta">
            <MsIcon name="widgets" size="sm" class="mobile-server-card__meta-icon" />
            <span class="mobile-server-card__meta-label">{{ t('userServers.table.plan') }}：</span>
            <span class="mobile-server-card__meta-value">{{ s.planName || s.eggName }}</span>
          </div>
          <div class="mobile-server-card__expiry">
            <MsIcon name="schedule" size="sm" class="mobile-server-card__expiry-icon" />
            <span class="mobile-server-card__expiry-label">{{ t('userServers.table.expiry') }}：</span>
            <span class="mobile-server-card__expiry-value mono" :style="{ color: expirationDisplay(s).color }">
              {{ expirationDisplay(s).date }}
              <span v-if="expirationDisplay(s).tag"> · {{ expirationDisplay(s).tag }}</span>
            </span>
          </div>

          <div class="mobile-server-card__rows">
            <div class="mobile-server-card__row">
              <div class="mobile-server-card__item">
                <div class="mobile-server-card__stat-head">
                  <span class="mobile-server-card__label">CPU</span>
                  <span class="mobile-server-card__value mono">{{ cpuText(s) }} / {{ cpuLimitText(s) }}</span>
                </div>
                <UsageBar :percent="cpuPercent(s)" class="mobile-server-card__usage" />
              </div>

              <div class="mobile-server-card__item">
                <div class="mobile-server-card__stat-head">
                  <span class="mobile-server-card__label">{{ t('userServers.resources.memory') }}</span>
                  <span class="mobile-server-card__value mono">{{ fmtBytes(resourceStore.resources[s.id]?.memoryBytes ?? 0) }} / {{ memoryLimitText(s) }}</span>
                </div>
                <UsageBar :percent="memPercent(s)" class="mobile-server-card__usage" />
              </div>
            </div>

            <div class="mobile-server-card__row">
              <div class="mobile-server-card__item">
                <div class="mobile-server-card__stat-head">
                  <span class="mobile-server-card__label">{{ t('userServers.resources.disk') }}</span>
                  <span class="mobile-server-card__value mono">{{ fmtBytes(resourceStore.resources[s.id]?.diskBytes ?? 0) }} / {{ diskLimitText(s) }}</span>
                </div>
                <UsageBar :percent="diskPercent(s)" class="mobile-server-card__usage" />
              </div>

              <div class="mobile-server-card__item">
                <div class="mobile-server-card__stat-head">
                  <span class="mobile-server-card__label">{{ t('userServers.resources.network') }}</span>
                  <span class="mobile-server-card__value mono mobile-server-card__value--network">
                    <span class="mobile-server-card__net-up">↑{{ fmtBytes(resourceStore.resources[s.id]?.networkTx ?? 0) }}</span>
                    <span class="mobile-server-card__net-down">↓{{ fmtBytes(resourceStore.resources[s.id]?.networkRx ?? 0) }}</span>
                  </span>
                </div>
              </div>
            </div>
          </div>
        </CardTap>
      </template>
    </DataTable>

    <!-- Mobile Action Sheet -->
    <ActionSheet v-model="mobileActionOpen" :title="mobileActionServer?.name">
      <template v-if="mobileActionServer" #info>
        <StatusDot :status="statusDotKeyFor(mobileActionServer)" size="sm" />
        {{ t(`userServers.status.${displayState(mobileActionServer)}`) }}
        · {{ expirationDisplay(mobileActionServer).date }}
        <span :style="{ color: expirationDisplay(mobileActionServer).color }">{{ expirationDisplay(mobileActionServer).tag }}</span>
      </template>
      <template v-if="mobileActionServer">
        <button @click="mobileActionOpen = false; goToDetail(mobileActionServer!)">
          <MsIcon name="terminal" size="sm" /> {{ t('userServers.console') }}
        </button>
        <button :disabled="mobileActionServer.isSuspended || mobileActionServer.isInstalling || resourceStore.isStale(mobileActionServer.id) || pendingStore.has(mobileActionServer.id) || liveState(mobileActionServer) === 'starting' || liveState(mobileActionServer) === 'stopping'" @click="mobileActionOpen = false; togglePower(mobileActionServer!)">
          <MsIcon :name="powerBtnIcon(mobileActionServer)" size="sm" /> {{ powerBtnLabel(mobileActionServer) }}
        </button>
        <button :disabled="!mobileActionServer.planId" :title="mobileActionServer.planId ? '' : t('userServers.renewFlow.noPlan')" @click="mobileActionOpen = false; onRenew(mobileActionServer!)">
          <MsIcon name="autorenew" size="sm" /> {{ t('userServers.renew') }}
        </button>
        <button :disabled="!mobileActionServer.hasUpgradeOptions" @click="mobileActionOpen = false; onUpgrade(mobileActionServer!)">
          <MsIcon name="arrow_upward" size="sm" /> {{ t('userServers.upgrade.button') }}
        </button>
        <button v-if="mobileActionServer.address && hasWebUi(mobileActionServer.eggName)" :disabled="mobileActionServer.isSuspended || mobileActionServer.isInstalling || liveState(mobileActionServer) !== 'running'" @click="mobileActionOpen = false; openUrl(mobileActionServer!)">
          <MsIcon name="open_in_new" size="sm" /> {{ openLabel(mobileActionServer!.eggName) }}
        </button>
      </template>
    </ActionSheet>
    <!-- Upgrade Plan Modal -->
    <CreateOrderModal
      v-if="upgradeServer"
      v-model="upgradeModalOpen"
      :plan="null"
      mode="upgrade"
      :target-server-id="upgradeServer.id"
      :server-name="upgradeServer.name"
    />
  </div>
</template>

<style scoped>
.page-body {
  display: flex;
  flex-direction: column;
}

.summary-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--sp-3);
  margin-bottom: var(--sp-4);
}

.filter-input {
  flex: 1;
  max-width: 280px;
}

.scope-switch {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
}

.scope-switch__label {
  font-size: .8rem;
  color: var(--t2);
  white-space: nowrap;
}

@media (max-width: 768px) {
  .scope-switch {
    justify-content: space-between;
    width: 100%;
  }
  /* SectionToolbar 移动端会让 .tb-btn-group > * 平分行宽，
     此处取消该行为，让 label 自适应、Switch 贴右。 */
  .scope-switch > * {
    flex: 0 0 auto;
  }
}

/* ── Table columns ── */
.col-check { width: 1%; text-align: center !important; vertical-align: middle; }
.col-dot { width: 1%; text-align: center !important; vertical-align: middle; }
.col-name { width: 13%; }
.col-plan { width: 8%; color: var(--t2); }
.col-status { width: 7%; }
.col-cpu { width: 8%; }
.col-mem { width: 8%; }
.col-disk { width: 8%; }
.col-uptime { width: 6%; }
.col-net { width: 8%; }
.col-expiry { width: 10%; }
.col-actions { width: auto; }

.server-link {
  font-weight: 600;
  color: var(--ac);
  text-decoration: none;
}
.server-link:hover {
  text-decoration: underline;
}

.mono {
  font-family: 'IBM Plex Mono', monospace;
  font-size: .82rem;
  color: var(--t2);
}

.dual-line {
  display: flex;
  flex-direction: column;
  line-height: 1.4;
}

.dual-sub {
  color: var(--t3);
  font-size: .75rem;
}

.expiry-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.expiry-date {
  font-family: 'IBM Plex Mono', monospace;
  font-size: .82rem;
  color: var(--t2);
}

.expiry-tag {
  font-size: .75rem;
  font-weight: 500;
}

/* ── Desktop table row actions ── */
.action-group {
  display: flex;
  gap: var(--sp-2);
  flex-wrap: wrap;
  align-items: center;
}

/* ── Mobile card layout ── */
.card-name {
  font-weight: 600;
  font-size: .92rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}

.card-row--main {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}

.mobile-server-card__title {
  display: flex;
  align-items: baseline;
  gap: 6px;
  flex: 1;
  min-width: 0;
}

.mobile-server-card__uptime {
  color: var(--t3);
  font-size: .72rem;
  flex-shrink: 0;
}

.mobile-server-card__meta {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin-top: var(--sp-2);
  padding-bottom: var(--sp-2);
  border-bottom: 1px solid var(--bd);
  font-size: .82rem;
  color: var(--t2);
}

.mobile-server-card__meta-icon {
  color: var(--t3);
  flex-shrink: 0;
}

.mobile-server-card__meta-label {
  color: var(--t2);
  white-space: nowrap;
}

.mobile-server-card__meta-value {
  font-weight: 500;
  color: var(--t1);
}

.mobile-server-card__expiry {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin-top: var(--sp-2);
  font-size: .82rem;
  color: var(--t2);
  min-width: 0;
}

.mobile-server-card__expiry-icon {
  color: var(--t3);
  flex-shrink: 0;
}

.mobile-server-card__expiry-label {
  color: var(--t2);
  white-space: nowrap;
}

.mobile-server-card__expiry-value {
  font-size: .78rem;
  min-width: 0;
}

.mobile-server-card__rows {
  margin-top: var(--sp-2);
  padding-top: var(--sp-3);
  border-top: 1px solid var(--bd);
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

.mobile-server-card__row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  column-gap: var(--sp-4);
}

.mobile-server-card__item {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.mobile-server-card__stat-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--sp-2);
}

.mobile-server-card__label {
  font-size: .72rem;
  color: var(--t3);
  text-transform: uppercase;
  letter-spacing: .03em;
  white-space: nowrap;
}

.mobile-server-card__value {
  font-size: .76rem;
  color: var(--t1);
  text-align: right;
}

.mobile-server-card__usage {
  margin-top: 2px;
}

.mobile-server-card__value--network {
  display: flex;
  flex-direction: row;
  justify-content: flex-end;
  gap: 8px;
}

.mobile-server-card__net-up {
  color: var(--ac2);
}

.mobile-server-card__net-down {
  color: var(--blue);
}

@media (max-width: 768px) {
  .summary-row {
    grid-template-columns: repeat(3, 1fr);
    gap: var(--sp-2);
  }

  .summary-row :deep(.stat-card) {
    padding: var(--sp-2) var(--sp-3);
  }

  .filter-input {
    max-width: none;
    width: 100%;
  }

  :deep(.dt-footer) {
    border-top: none;
    margin-top: var(--sp-2);
  }
}
</style>

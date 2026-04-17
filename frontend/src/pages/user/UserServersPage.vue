<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useApiFetch } from '@/composables/useApiFetch'
import { useConfirm } from '@/composables/useConfirm'
import { useServerResourceStore } from '@/stores/serverResources'
import PageHeader from '@/components/layout/PageHeader.vue'
import SectionToolbar from '@/components/ui/SectionToolbar.vue'
import FilterInput from '@/components/ui/FilterInput.vue'
import DataTable from '@/components/ui/DataTable.vue'
import StatusDot from '@/components/ui/StatusDot.vue'
import Badge from '@/components/ui/Badge.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import StatCard from '@/components/ui/StatCard.vue'
import ActionSheet from '@/components/ui/ActionSheet.vue'
import CardTap from '@/components/ui/CardTap.vue'
import CardKV from '@/components/ui/CardKV.vue'
import MsIcon from '@/components/ui/MsIcon.vue'

defineOptions({ name: 'UserServersPage' })

const { t } = useI18n({ useScope: 'global' })
const router = useRouter()
const { get, post } = useApiFetch()
const { confirm } = useConfirm()
const resourceStore = useServerResourceStore()

interface Server {
  id: number
  uuid: string
  name: string
  status: string | null
  isSuspended: boolean
  isInstalling: boolean
  isInstalled: boolean
  nodeId: number
  limits: { memory: number; disk: number; cpu: number }
  allocation: { ip: string | null; port: number | null }
  node: { fqdn: string | null }
  expirationDate: string | null
  daysLeft: number | null
  address: string | null
}

const servers = ref<Server[]>([])
const initialLoading = ref(true)
const powerLoading = ref<Record<number, boolean>>({})
const searchTerm = ref('')
const page = ref(1)
const perPage = ref(20)

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
  const promises = ids.map(id => post(`/api/user/servers/${id}/power`, { action }))
  await Promise.all(promises)
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

// ── Load data ──
async function loadServers() {
  const data = await get<Server[]>('/api/user/servers')
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
})

// ── Helpers ──
function liveState(s: Server): string {
  return resourceStore.getState(s.id) || s.status || 'offline'
}

function displayState(s: Server): string {
  if (s.isSuspended) return 'suspended'
  if (s.isInstalling) return 'installing'
  const st = liveState(s)
  return st === 'stopped' ? 'offline' : st
}

function statusDotKey(s: Server): 'running' | 'loading' | 'error' | 'stopped' {
  if (s.isSuspended) return 'error'
  if (s.isInstalling) return 'loading'
  const st = liveState(s)
  if (st === 'running') return 'running'
  if (st === 'starting' || st === 'stopping' || st === 'installing') return 'loading'
  return 'stopped'
}

function statusBadgeColor(s: Server): string {
  if (s.isSuspended) return 'var(--red)'
  if (s.isInstalling) return 'var(--amber)'
  const st = liveState(s)
  if (st === 'running') return 'var(--green)'
  if (st === 'starting' || st === 'stopping' || st === 'installing') return 'var(--amber)'
  return 'var(--t3)'
}

function cpuText(s: Server): string {
  return (resourceStore.resources[s.id]?.cpu ?? 0).toFixed(1) + '%'
}

function memText(s: Server): string {
  const bytes = resourceStore.resources[s.id]?.memoryBytes ?? 0
  return `${fmtBytes(bytes)} / ${s.limits.memory} MB`
}

function diskText(s: Server): string {
  const bytes = resourceStore.resources[s.id]?.diskBytes ?? 0
  return `${fmtBytes(bytes)} / ${s.limits.disk} MB`
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

// ── Power action ──
async function togglePower(s: Server) {
  const st = liveState(s)
  const action = st === 'running' ? 'restart' : 'start'
  if (action === 'restart') {
    const ok = await confirm({
      title: t('common.confirm.title'),
      message: t('userServers.power.confirmRestart'),
      confirmText: t('userServers.power.restart'),
    })
    if (!ok) return
  }
  powerLoading.value[s.id] = true
  await post(`/api/user/servers/${s.id}/power`, { action })
  powerLoading.value[s.id] = false
}

function powerBtnLabel(s: Server): string {
  return liveState(s) === 'running' ? t('userServers.power.restart') : t('userServers.power.start')
}

function powerBtnIcon(s: Server): string {
  return liveState(s) === 'running' ? 'refresh' : 'play_arrow'
}

function goToDetail(s: Server) {
  router.push({ name: 'server-console', params: { id: s.id } })
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
        <FilterInput v-model="searchTerm" :placeholder="t('userServers.searchPlaceholder')" class="filter-input" @update:modelValue="selectedIds = new Set()" />
        <div class="batch-controls">
          <BaseSelect v-model="batchActionType" :options="batchActionOptions" :placeholder="t('userServers.batch.selectAction')" size="sm" fit :disabled="selectedIds.size === 0" />
          <BaseButton size="sm" :disabled="selectedIds.size === 0 || !batchActionType" @click="executeBatchAction">
            <MsIcon name="play_arrow" size="xs" /> {{ t('userServers.batch.execute') }}
          </BaseButton>
          <span v-if="selectedIds.size > 0" class="toolbar-status">{{ t('userServers.batch.selected', { n: selectedIds.size }) }}</span>
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
      <template #header>
        <th class="col-check">
          <input type="checkbox" v-model="allSelected" />
        </th>
        <th class="col-dot"></th>
        <th class="col-name">{{ t('userServers.table.name') }}</th>
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
          <StatusDot :status="statusDotKey(s)" size="sm" />
        </td>
        <td class="col-name">
          <a class="server-link" href="#" @click.prevent="goToDetail(s)">{{ s.name }}</a>
        </td>
        <td class="col-status" :style="s.isSuspended ? { color: 'var(--red)', fontWeight: 600 } : {}">{{ t(`userServers.status.${displayState(s)}`) }}</td>
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
            <BaseButton v-if="s.address" variant="primary" size="sm" :disabled="s.isSuspended || s.isInstalling || liveState(s) !== 'running'" @click="openUrl(s)">
              <MsIcon name="open_in_new" size="xs" /> {{ t('userServers.openApp') }}
            </BaseButton>
            <BaseButton size="sm" :loading="powerLoading[s.id]" :disabled="s.isSuspended || s.isInstalling" @click="togglePower(s)">
              <MsIcon :name="powerBtnIcon(s)" size="xs" /> {{ powerBtnLabel(s) }}
            </BaseButton>
            <BaseButton size="sm" @click="goToDetail(s)">
              {{ t('userServers.detail') }}
            </BaseButton>
            <BaseButton size="sm" disabled>
              {{ t('userServers.renew') }}
            </BaseButton>
          </div>
        </td>
      </template>

      <!-- Mobile card -->
      <template #card="{ item: s }">
        <CardTap @tap="openMobileAction(s)">
          <div class="card-row--main">
            <span class="card-name">{{ s.name }}</span>
            <Badge :color="statusBadgeColor(s)">{{ t(`userServers.status.${displayState(s)}`) }}</Badge>
          </div>
          <div class="card-expiry-row">
            <span class="card-kv-label">{{ t('userServers.table.expiry') }}</span>
            <span :style="{ color: expirationDisplay(s).color }">
              {{ expirationDisplay(s).date }}
              <span v-if="expirationDisplay(s).tag"> · {{ expirationDisplay(s).tag }}</span>
            </span>
          </div>
          <div class="card-detail card-detail--3col">
            <CardKV label="CPU"><span class="mono">{{ cpuText(s) }}</span></CardKV>
            <CardKV :label="t('userServers.resources.memory')">
              <span class="mono">{{ fmtBytes(resourceStore.resources[s.id]?.memoryBytes ?? 0) }}</span>
              <span class="card-kv-sub mono">{{ s.limits.memory }} MB</span>
            </CardKV>
            <CardKV :label="t('userServers.resources.disk')">
              <span class="mono">{{ fmtBytes(resourceStore.resources[s.id]?.diskBytes ?? 0) }}</span>
              <span class="card-kv-sub mono">{{ s.limits.disk }} MB</span>
            </CardKV>
          </div>
          <div class="card-detail">
            <CardKV :label="t('userServers.resources.network')">
              <span class="mono">↑{{ fmtBytes(resourceStore.resources[s.id]?.networkTx ?? 0) }} ↓{{ fmtBytes(resourceStore.resources[s.id]?.networkRx ?? 0) }}</span>
            </CardKV>
            <CardKV :label="t('userServers.resources.uptime')">
              <span class="mono">{{ uptimeText(s) }}</span>
            </CardKV>
          </div>
        </CardTap>
      </template>
    </DataTable>

    <!-- Mobile Action Sheet -->
    <ActionSheet v-model="mobileActionOpen" :title="mobileActionServer?.name">
      <template v-if="mobileActionServer" #info>
        <StatusDot :status="statusDotKey(mobileActionServer)" size="sm" />
        {{ t(`userServers.status.${displayState(mobileActionServer)}`) }}
        · {{ expirationDisplay(mobileActionServer).date }}
        <span :style="{ color: expirationDisplay(mobileActionServer).color }">{{ expirationDisplay(mobileActionServer).tag }}</span>
      </template>
      <template v-if="mobileActionServer">
        <button v-if="mobileActionServer.address" :disabled="mobileActionServer.isSuspended || mobileActionServer.isInstalling || liveState(mobileActionServer) !== 'running'" @click="mobileActionOpen = false; openUrl(mobileActionServer!)">
          <MsIcon name="open_in_new" size="sm" /> {{ t('userServers.openApp') }}
        </button>
        <button :disabled="mobileActionServer.isSuspended || mobileActionServer.isInstalling" @click="mobileActionOpen = false; togglePower(mobileActionServer!)">
          <MsIcon :name="powerBtnIcon(mobileActionServer)" size="sm" /> {{ powerBtnLabel(mobileActionServer) }}
        </button>
        <button @click="mobileActionOpen = false; goToDetail(mobileActionServer!)">
          <MsIcon name="arrow_forward" size="sm" /> {{ t('userServers.detail') }}
        </button>
        <button disabled>
          <MsIcon name="shopping_cart" size="sm" /> {{ t('userServers.renew') }}
        </button>
      </template>
    </ActionSheet>
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

.toolbar-status {
  font-size: .82rem;
  color: var(--t3);
  white-space: nowrap;
}

/* ── Table columns ── */
.col-check { width: 1%; text-align: center !important; vertical-align: middle; }
.col-dot { width: 1%; text-align: center !important; vertical-align: middle; }
.col-name { width: 14%; }
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
  flex: 1;
}

.card-kv-label {
  font-size: .72rem;
  color: var(--t3);
  text-transform: uppercase;
  letter-spacing: .03em;
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

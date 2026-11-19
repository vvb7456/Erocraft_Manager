<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useApiFetch } from '@/composables/useApiFetch'
import type { NodeOut } from '@/api/adminNodesLocations'
import PageHeader from '@/components/layout/PageHeader.vue'
import PageHeaderActions from '@/components/layout/PageHeaderActions.vue'
import TabSwitcher from '@/components/ui/TabSwitcher.vue'
import SectionToolbar from '@/components/ui/SectionToolbar.vue'
import StatCard from '@/components/ui/StatCard.vue'
import FilterInput from '@/components/ui/FilterInput.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import Badge from '@/components/ui/Badge.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import StatusDot from '@/components/ui/StatusDot.vue'
import DataTable from '@/components/ui/DataTable.vue'
import SortTh from '@/components/ui/SortTh.vue'
import { useTableSort } from '@/composables/useTableSort'
import { useClientPagination } from '@/composables/useTablePagination'
import CardTap from '@/components/ui/CardTap.vue'
import CardKV from '@/components/ui/CardKV.vue'
import ActionSheet from '@/components/ui/ActionSheet.vue'
import MobileFilterSheet from '@/components/ui/MobileFilterSheet.vue'
import HostCreateModal, { type PresetNodeInfo } from '@/components/hosts/HostCreateModal.vue'
import HostsNodesTab from '@/pages/host/HostsNodesTab.vue'
import HostsLocationsTab from '@/pages/host/HostsLocationsTab.vue'
import { classifyHostStatus } from '@/utils/heartbeat'

defineOptions({ name: 'HostsPage' })

const { t } = useI18n({ useScope: 'global' })
const route = useRoute()
const router = useRouter()
const { get, handleError } = useApiFetch()
const listLoading = ref(false)

// ── Top-level tabs (?tab=hosts|nodes|locations) ──
type TabKey = 'hosts' | 'nodes' | 'locations'
const VALID_TABS: TabKey[] = ['hosts', 'nodes', 'locations']

function pickInitialTab(): TabKey {
  const q = route.query.tab
  const raw = Array.isArray(q) ? q[0] : q
  if (raw && (VALID_TABS as string[]).includes(raw)) return raw as TabKey
  return 'hosts'
}

const activeTab = computed<TabKey>({
  get: pickInitialTab,
  set: (tab) => {
    void router.push({ query: { ...route.query, tab } })
  },
})

const tabs = computed(() => [
  { key: 'hosts', icon: 'dvr', label: t('hosts.tabs.hosts') },
  { key: 'nodes', icon: 'dns', label: t('hosts.tabs.nodes') },
  { key: 'locations', icon: 'public', label: t('hosts.tabs.locations') },
])

// ── Types ──
interface HostItem {
  id: number
  name: string
  kind: string
  hostname: string
  agent_url: string
  pterodactyl_node_id: number | null
  extra_metadata: Record<string, unknown> | null
  enabled: boolean
  last_seen_at: string | null
  created_at: string | null
  updated_at: string | null
}

type StatusKey = 'online' | 'warning' | 'offline' | 'disabled' | 'unconfigured'

// ── State ──
const rawHosts = ref<HostItem[]>([])
const searchTerm = ref('')
const filterKind = ref<string>('all')
const filterStatus = ref<string>('all')
const { sortBy, sortOrder, toggleSort, sortItems } = useTableSort({
  descColumns: ['last_seen_at'],
})

const nodesTabRef = ref<InstanceType<typeof HostsNodesTab> | null>(null)
let reloadTimer: number | null = null

// ── Fetching ──
async function loadHosts(silent = false) {
  if (!silent) listLoading.value = true
  try {
    const data = await get<HostItem[]>('/api/admin/hosts', { silent: true })
    if (data) rawHosts.value = data
  } finally {
    if (!silent) listLoading.value = false
  }
}

onMounted(() => {
  void loadHosts().catch(handleError)
  reloadTimer = window.setInterval(() => {
    if (activeTab.value === 'hosts') {
      void loadHosts(true).catch(handleError)
    }
  }, 15000)
})

onBeforeUnmount(() => {
  if (reloadTimer !== null) clearInterval(reloadTimer)
})

// ── Helpers ──
function classifyStatus(h: HostItem): StatusKey {
  return classifyHostStatus(h.enabled, h.last_seen_at)
}

function statusDotKey(s: StatusKey): 'running' | 'error' | 'stopped' {
  if (s === 'online') return 'running'
  if (s === 'offline') return 'error'
  if (s === 'warning') return 'stopped'
  return 'stopped'
}

function formatAgo(iso: string | null): string {
  if (!iso) return t('hosts.time.never')
  const hasTz = /Z|[+-]\d{2}:?\d{2}$/.test(iso)
  const ts = new Date(hasTz ? iso : iso + 'Z').getTime()
  if (Number.isNaN(ts)) return t('hosts.time.never')
  const delta = Math.max(0, Math.floor((Date.now() - ts) / 1000))
  if (delta < 60) return `${delta}s`
  if (delta < 3600) return `${Math.floor(delta / 60)}m`
  if (delta < 86400) return `${Math.floor(delta / 3600)}h`
  return `${Math.floor(delta / 86400)}d`
}

const KIND_BADGE_COLOR: Record<string, string> = {
  wings_node: 'var(--ac)',
  generic_linux: 'var(--t2)',
}

// ── Options ──
const kindOptions = computed(() => [
  { value: 'all', label: t('hosts.toolbar.all') },
  { value: 'wings_node', label: t('hosts.kind.wings_node') },
  { value: 'generic_linux', label: t('hosts.kind.generic_linux') },
])

const statusOptions = computed(() => [
  { value: 'all', label: t('hosts.toolbar.all') },
  { value: 'online', label: t('hosts.status.online') },
  { value: 'warning', label: t('hosts.status.warning') },
  { value: 'offline', label: t('hosts.status.offline') },
  { value: 'disabled', label: t('hosts.status.disabled') },
  { value: 'unconfigured', label: t('hosts.status.unconfigured') },
])

const STATUS_RANK: Record<StatusKey, number> = {
  online: 0,
  warning: 1,
  offline: 2,
  disabled: 3,
  unconfigured: 4,
}

function parseHeartbeatMs(iso: string | null): number | null {
  if (!iso) return null
  const hasTz = /Z|[+-]\d{2}:?\d{2}$/.test(iso)
  const ts = new Date(hasTz ? iso : iso + 'Z').getTime()
  return Number.isNaN(ts) ? null : ts
}

// ── Mobile filter sheet ──
const mobileFilterOpen = ref(false)
const sortColumns = computed(() => [
  { key: 'name', label: t('hosts.columns.name') },
  { key: 'kind', label: t('hosts.columns.kind') },
  { key: 'status', label: t('hosts.columns.status') },
  { key: 'last_seen_at', label: t('hosts.columns.lastSeen') },
  { key: 'hostname', label: t('hosts.columns.hostname') },
])
const filterGroups = computed(() => [
  {
    key: 'kind',
    label: t('hosts.toolbar.filterKind'),
    modelValue: filterKind.value,
    options: kindOptions.value,
  },
  {
    key: 'status',
    label: t('hosts.toolbar.filterStatus'),
    modelValue: filterStatus.value,
    options: statusOptions.value,
  },
])
function onMobileFilter(groupKey: string, value: string | number | boolean) {
  if (groupKey === 'kind') filterKind.value = String(value)
  else if (groupKey === 'status') filterStatus.value = String(value)
}

// ── Derived ──
const filtered = computed(() => {
  const q = searchTerm.value.toLowerCase().trim()
  return rawHosts.value.filter(h => {
    if (filterKind.value !== 'all' && h.kind !== filterKind.value) return false
    if (filterStatus.value !== 'all' && classifyStatus(h) !== filterStatus.value) return false
    if (q) {
      const hay = `${h.name} ${h.hostname} ${h.agent_url}`.toLowerCase()
      if (!hay.includes(q)) return false
    }
    return true
  })
})

const sorted = computed(() =>
  sortItems(filtered.value, {
    name: (h) => h.name,
    kind: (h) => t(`hosts.kind.${h.kind}`),
    status: (h) => STATUS_RANK[classifyStatus(h)],
    last_seen_at: (h) => parseHeartbeatMs(h.last_seen_at),
    hostname: (h) => h.hostname,
  }, {
    tieBreaker: (a, b) => a.id - b.id,
  }),
)

const { page, perPage, totalPages, paginated, setPerPage } = useClientPagination(sorted, {
  resetDeps: [searchTerm, filterKind, filterStatus, sortBy, sortOrder],
})

const summary = computed(() => ({ total: filtered.value.length }))

const hostStats = computed(() => {
  const list = rawHosts.value
  return {
    total: list.length,
    online: list.filter(h => classifyStatus(h) === 'online').length,
    wings: list.filter(h => h.kind === 'wings_node').length,
    other: list.filter(h => h.kind !== 'wings_node').length,
  }
})

// ── Navigation ──
function openHost(h: HostItem) {
  router.push({ name: 'host-detail', params: { id: h.id } })
}

// ── Create host modal (shared by Hosts tab & "Bind host" in Nodes tab) ──
const createOpen = ref(false)
const presetNode = ref<PresetNodeInfo | null>(null)

const usedNodeIds = computed(() =>
  rawHosts.value
    .map(h => h.pterodactyl_node_id)
    .filter((x): x is number => typeof x === 'number'),
)

function openCreate() {
  presetNode.value = null
  createOpen.value = true
}

function openBindNode(n: NodeOut) {
  presetNode.value = { id: n.id, name: n.name, fqdn: n.fqdn }
  createOpen.value = true
}

function onCreated() {
  void loadHosts()
  void nodesTabRef.value?.reload()
}

// ── Mobile action sheet ──
const mobileActionHost = ref<HostItem | null>(null)
const mobileActionOpen = ref(false)
function openMobileAction(h: HostItem) {
  mobileActionHost.value = h
  mobileActionOpen.value = true
}

function handleMobile(action: 'open') {
  const h = mobileActionHost.value
  mobileActionOpen.value = false
  if (!h) return
  if (action === 'open') openHost(h)
}
</script>

<template>
  <PageHeader icon="dvr" :title="t('hosts.title')">
    <TabSwitcher v-model="activeTab" :tabs="tabs" />
  </PageHeader>

  <div class="page-body">
    <div v-if="activeTab === 'hosts'" class="tab-content">
      <PageHeaderActions>
        <BaseButton size="sm" variant="primary" @click="openCreate">
          <MsIcon name="add" size="xs" />{{ t('hosts.toolbar.create') }}
        </BaseButton>
      </PageHeaderActions>

      <section class="stat-grid" aria-label="host summary">
        <StatCard :label="t('hosts.stats.total')" status="info" variant="kpi">
          <template #value>{{ hostStats.total }}</template>
          <template #sub>{{ t('hosts.stats.filtered', { n: filtered.length }) }}</template>
        </StatCard>
        <StatCard :label="t('hosts.stats.online')" status="running" variant="kpi">
          <template #value>{{ hostStats.online }}</template>
          <template #sub>{{ t('hosts.stats.agentReachable') }}</template>
        </StatCard>
        <StatCard :label="t('hosts.stats.wings')" status="info" variant="kpi">
          <template #value>{{ hostStats.wings }}</template>
          <template #sub>{{ t('hosts.kind.wings_node') }}</template>
        </StatCard>
        <StatCard :label="t('hosts.stats.other')" status="loading" variant="kpi">
          <template #value>{{ hostStats.other }}</template>
          <template #sub>{{ t('hosts.stats.otherSub') }}</template>
        </StatCard>
      </section>

      <SectionToolbar>
        <template #start>
          <div class="tb-search-row">
            <FilterInput
              v-model="searchTerm"
              :placeholder="t('hosts.toolbar.search')"
              class="tb-search"
            />
            <button
              class="tb-filter-btn"
              :title="t('common.filterSort.title')"
              @click="mobileFilterOpen = true"
            >
              <MsIcon name="tune" size="sm" />
            </button>
          </div>
          <div class="summary tb-status" role="status">
            <span>{{ t('hosts.summary.total', { n: summary.total }) }}</span>
          </div>
        </template>
        <template #end>
          <div class="tb-select-group tb-desktop-only">
            <BaseSelect
              v-model="filterKind"
              :options="kindOptions"
              :prefix="t('hosts.toolbar.filterKind') + ': '"
              size="sm"
              fit
            />
            <BaseSelect
              v-model="filterStatus"
              :options="statusOptions"
              :prefix="t('hosts.toolbar.filterStatus') + ': '"
              size="sm"
              fit
            />
          </div>
        </template>
      </SectionToolbar>

      <MobileFilterSheet
        v-model:open="mobileFilterOpen"
        :sort-columns="sortColumns"
        :sort-by="sortBy"
        :sort-order="sortOrder"
        :filters="filterGroups"
        @sort="toggleSort"
        @update:filter="onMobileFilter"
      />

      <div class="hosts-table-wrap">
      <DataTable
        :items="paginated"
        :page="page"
        :total-pages="totalPages"
        :per-page="perPage"
        :per-page-label="t('hosts.list.perPage')"
        :loading="listLoading"
        empty-icon="dvr"
        :empty-text="t('hosts.list.empty')"
        @update:page="page = $event"
        @update:per-page="setPerPage"
      >
        <template #header>
          <SortTh class="col-name" col="name" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('hosts.columns.name') }}</SortTh>
          <SortTh class="col-kind" col="kind" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('hosts.columns.kind') }}</SortTh>
          <SortTh class="col-hostname" col="hostname" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('hosts.columns.hostname') }}</SortTh>
          <th class="col-agent">{{ t('hosts.columns.agentUrl') }}</th>
          <SortTh class="col-seen" col="last_seen_at" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('hosts.columns.lastSeen') }}</SortTh>
          <SortTh class="col-status" col="status" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('hosts.columns.status') }}</SortTh>
          <th class="col-actions">{{ t('hosts.columns.actions') }}</th>
        </template>

        <template #row="{ item: h }">
          <td class="col-name" @click="openHost(h)">
            <span class="host-name-link">{{ h.name }}</span>
          </td>
          <td class="col-kind" @click="openHost(h)">
            <Badge :color="KIND_BADGE_COLOR[h.kind]" size="sm">
              {{ t(`hosts.kind.${h.kind}`) }}
            </Badge>
          </td>
          <td class="col-hostname mono" @click="openHost(h)">{{ h.hostname || '—' }}</td>
          <td class="col-agent mono" @click="openHost(h)">{{ h.agent_url }}</td>
          <td class="col-seen tabular" @click="openHost(h)">{{ formatAgo(h.last_seen_at) }}</td>
          <td class="col-status" @click="openHost(h)">
            <span class="status-cell">
              <StatusDot :status="statusDotKey(classifyStatus(h))" size="sm" />
              <span>{{ t(`hosts.status.${classifyStatus(h)}`) }}</span>
            </span>
          </td>
          <td class="col-actions">
            <div class="action-group">
              <BaseButton size="sm" @click.stop="openHost(h)">
                <MsIcon name="edit" size="xs" /> {{ t('common.btn.edit') }}
              </BaseButton>
            </div>
          </td>
        </template>

        <template #card="{ item: h }">
          <CardTap @tap="openMobileAction(h)">
            <div class="card-row--main">
              <span class="card-name">
                <StatusDot :status="statusDotKey(classifyStatus(h))" size="sm" />
                {{ h.name }}
              </span>
              <Badge :color="KIND_BADGE_COLOR[h.kind]" size="sm">
                {{ t(`hosts.kind.${h.kind}`) }}
              </Badge>
            </div>
            <div class="card-row--sub mono">{{ h.hostname || h.agent_url }}</div>
            <div class="card-detail">
              <CardKV :label="t('hosts.columns.status')">
                {{ t(`hosts.status.${classifyStatus(h)}`) }}
              </CardKV>
              <CardKV :label="t('hosts.columns.lastSeen')">
                <span class="tabular">{{ formatAgo(h.last_seen_at) }}</span>
              </CardKV>
            </div>
          </CardTap>
        </template>
      </DataTable>
      </div>

      <ActionSheet v-model="mobileActionOpen" :title="mobileActionHost?.name">
        <template v-if="mobileActionHost" #info>
          {{ mobileActionHost.agent_url }}
        </template>
        <template v-if="mobileActionHost">
          <button @click="handleMobile('open')">
            <MsIcon name="edit" size="sm" /> {{ t('common.btn.edit') }}
          </button>
        </template>
      </ActionSheet>
    </div>

    <div v-else-if="activeTab === 'nodes'" class="tab-content">
      <HostsNodesTab ref="nodesTabRef" @bindNode="openBindNode" />
    </div>

    <div v-else-if="activeTab === 'locations'" class="tab-content">
      <HostsLocationsTab />
    </div>
  </div>

  <HostCreateModal
    v-model="createOpen"
    :usedNodeIds="usedNodeIds"
    :presetNode="presetNode"
    @created="onCreated"
  />
</template>

<style scoped>
/* ── Toolbar ── */
.summary {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  color: var(--t3);
  font-size: var(--text-sm);
  flex-wrap: wrap;
}

/* ── Table cells ── */
.hosts-table-wrap :deep(.dt-table)      { min-width: 960px; }
.hosts-table-wrap :deep(.col-name)      { width: 16%; cursor: pointer; }
.hosts-table-wrap :deep(.col-kind)      { width: 10%; cursor: pointer; }
.hosts-table-wrap :deep(.col-hostname)  { width: 18%; cursor: pointer; }
.hosts-table-wrap :deep(.col-agent)     { width: 24%; cursor: pointer; }
.hosts-table-wrap :deep(.col-seen)      { width: 10%; cursor: pointer; }
.hosts-table-wrap :deep(.col-status)    { width: 12%; cursor: pointer; }
.hosts-table-wrap :deep(.col-actions)   { width: 10%; }

.mono {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  color: var(--t2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tabular {
  font-variant-numeric: tabular-nums;
  color: var(--t2);
}

.host-name-link {
  color: var(--t1);
  font-weight: 500;
  transition: color .15s;
}

.col-name:hover .host-name-link {
  color: var(--ac2);
}

.status-cell {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1);
}

.action-group {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}

/* ── Mobile cards ── */
.card-row--main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-2);
}

.card-row--sub {
  color: var(--t3);
  margin-top: 2px;
}

.card-detail {
  display: flex;
  gap: var(--sp-4);
  margin-top: var(--sp-2);
}

.card-name {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  color: var(--t1);
  font-weight: 500;
}
</style>

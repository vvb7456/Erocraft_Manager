<script setup lang="ts">
// C2 — host list: toolbar + filters + data table.
// Create / global-defaults / per-row actions are deliberately wired as
// stubs that surface a "coming in next step" toast; C3-C5 turn them on.
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useApiFetch } from '@/composables/useApiFetch'
import PageHeader from '@/components/layout/PageHeader.vue'
import SectionToolbar from '@/components/ui/SectionToolbar.vue'
import FilterInput from '@/components/ui/FilterInput.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import Badge from '@/components/ui/Badge.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import StatusDot from '@/components/ui/StatusDot.vue'
import DataTable from '@/components/ui/DataTable.vue'
import CardTap from '@/components/ui/CardTap.vue'
import CardKV from '@/components/ui/CardKV.vue'
import ActionSheet from '@/components/ui/ActionSheet.vue'
import GlobalDefaultsModal from '@/components/hosts/GlobalDefaultsModal.vue'
import HostCreateModal from '@/components/hosts/HostCreateModal.vue'

defineOptions({ name: 'HostsPage' })

const { t } = useI18n({ useScope: 'global' })
const router = useRouter()
// Note: we deliberately do NOT pull `loading` out of useApiFetch — that ref is
// shared across every request this composable instance issues, so a per-row
// probe/rotate/delete would briefly flip the table into a skeleton state.
// Instead we maintain a separate `listLoading` that tracks ONLY `loadHosts`.
const { get } = useApiFetch()
const listLoading = ref(false)

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
  inbound_reachable: boolean
  last_seen_at: string | null
  last_status_at: string | null
  created_at: string | null
  updated_at: string | null
}

type StatusKey = 'online' | 'offline' | 'disabled' | 'unconfigured'

// ── State ──
const rawHosts = ref<HostItem[]>([])
const searchTerm = ref('')
const filterKind = ref<string>('all')
const filterStatus = ref<string>('all')
const page = ref(1)
const perPage = ref(20)

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
  loadHosts()
  reloadTimer = window.setInterval(() => loadHosts(true), 15000)
})

onBeforeUnmount(() => {
  if (reloadTimer !== null) clearInterval(reloadTimer)
})

// ── Helpers ──
function classifyStatus(h: HostItem): StatusKey {
  if (!h.enabled) return 'disabled'
  // "unconfigured" in the design doc means agent_token missing; the list API
  // never exposes the ciphertext, so we proxy via inbound_reachable=false
  // AND last_seen_at=null — a brand-new row that has never spoken back yet.
  if (!h.inbound_reachable && !h.last_seen_at) return 'unconfigured'
  if (!h.inbound_reachable) return 'offline'
  return 'online'
}

function statusDotKey(s: StatusKey): 'running' | 'error' | 'stopped' {
  if (s === 'online') return 'running'
  if (s === 'offline') return 'error'
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
  nginx_proxy: 'var(--blue)',
  nas: 'var(--amber)',
  generic_linux: 'var(--t2)',
}

// ── Options ──
const kindOptions = computed(() => [
  { value: 'all', label: t('hosts.toolbar.all') },
  { value: 'wings_node', label: t('hosts.kind.wings_node') },
  { value: 'nginx_proxy', label: t('hosts.kind.nginx_proxy') },
  { value: 'nas', label: t('hosts.kind.nas') },
  { value: 'generic_linux', label: t('hosts.kind.generic_linux') },
])

const statusOptions = computed(() => [
  { value: 'all', label: t('hosts.toolbar.all') },
  { value: 'online', label: t('hosts.status.online') },
  { value: 'offline', label: t('hosts.status.offline') },
  { value: 'disabled', label: t('hosts.status.disabled') },
  { value: 'unconfigured', label: t('hosts.status.unconfigured') },
])

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

const totalPages = computed(() => Math.max(1, Math.ceil(filtered.value.length / perPage.value)))
const paginated = computed(() => {
  const start = (page.value - 1) * perPage.value
  return filtered.value.slice(start, start + perPage.value)
})

const summary = computed(() => ({ total: filtered.value.length }))

// ── Navigation ──
function openHost(h: HostItem) {
  router.push({ name: 'host-detail', params: { id: h.id } })
}

// ── Modals ──
const globalDefaultsOpen = ref(false)
const createOpen = ref(false)

const usedNodeIds = computed(() =>
  rawHosts.value
    .map(h => h.pterodactyl_node_id)
    .filter((x): x is number => typeof x === 'number')
)

// ── Stubbed actions (wired up in C3 / C4 / C5) ──
function openGlobalDefaults() { globalDefaultsOpen.value = true }
function openCreate() { createOpen.value = true }
function onCreated() { loadHosts() }

// ── Mobile action sheet ──
// Action sheet only carries one entry ("open detail") so the interaction
// stays consistent with how other admin list pages behave; probe / delete
// / token-reset all live on the host detail page.
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
  <PageHeader icon="dvr" :title="t('hosts.title')" />

  <div class="page-body">
    <SectionToolbar>
      <template #start>
        <FilterInput
          v-model="searchTerm"
          :placeholder="t('hosts.toolbar.search')"
          class="hosts-filter-input"
        />
        <div class="summary" role="status">
          <span>{{ t('hosts.summary.total', { n: summary.total }) }}</span>
        </div>
      </template>
      <template #end>
        <div class="toolbar-end-row">
          <BaseButton size="sm" @click="openGlobalDefaults">
            <MsIcon name="tune" size="xs" />
            {{ t('hosts.toolbar.globalDefaults') }}
          </BaseButton>
          <BaseButton size="sm" variant="primary" @click="openCreate">
            <MsIcon name="add" size="xs" />
            {{ t('hosts.toolbar.create') }}
          </BaseButton>
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
      @update:per-page="perPage = $event; page = 1"
    >
      <template #header>
        <th class="col-name">{{ t('hosts.columns.name') }}</th>
        <th class="col-kind">{{ t('hosts.columns.kind') }}</th>
        <th class="col-status">{{ t('hosts.columns.status') }}</th>
        <th class="col-seen">{{ t('hosts.columns.lastSeen') }}</th>
        <th class="col-hostname">{{ t('hosts.columns.hostname') }}</th>
        <th class="col-agent">{{ t('hosts.columns.agentUrl') }}</th>
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
        <td class="col-status" @click="openHost(h)">
          <span class="status-cell">
            <StatusDot :status="statusDotKey(classifyStatus(h))" size="sm" />
            <span>{{ t(`hosts.status.${classifyStatus(h)}`) }}</span>
          </span>
        </td>
        <td class="col-seen tabular" @click="openHost(h)">{{ formatAgo(h.last_seen_at) }}</td>
        <td class="col-hostname mono" @click="openHost(h)">{{ h.hostname || '—' }}</td>
        <td class="col-agent mono" @click="openHost(h)">{{ h.agent_url }}</td>
        <td class="col-actions">
          <div class="action-group">
            <BaseButton size="sm" @click.stop="openHost(h)" :title="t('hosts.actions.open')">
              <MsIcon name="open_in_new" size="xs" />
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
        <MsIcon name="open_in_new" size="sm" /> {{ t('hosts.actions.open') }}
      </button>
    </template>
  </ActionSheet>

  <GlobalDefaultsModal v-model="globalDefaultsOpen" />
  <HostCreateModal v-model="createOpen" :usedNodeIds="usedNodeIds" @created="onCreated" />
</template>

<style scoped>
/* ── Toolbar ── */
.hosts-filter-input {
  min-width: 240px;
  flex: 0 1 280px;
}

.summary {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  color: var(--t3);
  font-size: var(--text-sm);
  flex-wrap: wrap;
}

.toolbar-end-row {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}

/* ── Table cells ── */
.col-name      { width: 18%; cursor: pointer; }
.col-kind      { width: 10%; cursor: pointer; }
.col-hostname  { width: 14%; cursor: pointer; }
.col-agent     { width: 24%; cursor: pointer; }
.col-status    { width: 12%; cursor: pointer; }
.col-seen      { width: 10%; cursor: pointer; }
.col-actions   { width: 12%; text-align: right; }

.mono {
  font-family: 'IBM Plex Mono', ui-monospace, SFMono-Regular, monospace;
  font-size: var(--text-sm);
  color: var(--t2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 0;
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
  display: inline-flex;
  gap: var(--sp-1);
  justify-content: flex-end;
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

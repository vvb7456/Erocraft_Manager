<script setup lang="ts">
import { ApiError, apiErrorMessage } from '@/composables/apiClient'
// HostAllocationsPane — Pterodactyl-Panel-style port allocation manager.
// Mounted only on wings_node hosts (parent route hides the tab otherwise).
// Reads/writes the shared `panel.allocations` table via:
//   GET    /api/admin/hosts/{host_id}/allocations?assigned=&search=&page=&per_page=
//   POST   /api/admin/hosts/{host_id}/allocations            { ip, alias?, ports }
//   DELETE /api/admin/hosts/{host_id}/allocations/{id}
//   DELETE /api/admin/hosts/{host_id}/allocations            { ids: number[] }
import { computed, inject, onMounted, ref, watch, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'
import ListToolbar from '@/components/ui/ListToolbar.vue'
import PageHeaderActions from '@/components/layout/PageHeaderActions.vue'
import FilterInput from '@/components/ui/FilterInput.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import DataTable from '@/components/ui/DataTable.vue'
import SortTh from '@/components/ui/SortTh.vue'
import { useTableSort } from '@/composables/useTableSort'
import { useServerPagination } from '@/composables/useTablePagination'
import BaseButton from '@/components/ui/BaseButton.vue'
import Badge from '@/components/ui/Badge.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import CardTap from '@/components/ui/CardTap.vue'
import CardKV from '@/components/ui/CardKV.vue'
import MobileFilterSheet from '@/components/ui/MobileFilterSheet.vue'
import AlertBanner from '@/components/ui/AlertBanner.vue'
import CreateAllocationsModal from '@/components/hosts/CreateAllocationsModal.vue'
import AllocationEditModal from '@/components/hosts/AllocationEditModal.vue'

import type { HostDetail } from '@/types/host'

defineOptions({ name: 'HostAllocationsPane' })

interface ServerBrief {
  id: number
  uuid_short: string
  name: string
  owner_id: number
  owner_name: string | null
}
interface AllocationOut {
  id: number
  ip: string
  alias: string | null
  port: number
  notes: string | null
  server: ServerBrief | null
}
interface ListResponse {
  items: AllocationOut[]
  page: number
  per_page: number
  total: number
}

const { t } = useI18n({ useScope: 'global' })
const router = useRouter()
const { get, raw, handleError } = useApiFetch()
const { toast } = useToast()
const { confirm } = useConfirm()

const host = inject<Ref<HostDetail | null>>('hostDetail')!
const hostId = computed(() => host.value?.id ?? null)
const isWings = computed(() => host.value?.kind === 'wings_node')

const items = ref<AllocationOut[]>([])

type AssignedFilter = 'all' | 'assigned' | 'unassigned'
const filterAssigned = ref<AssignedFilter>('all')
const searchTerm = ref('')

const filterOptions = computed(() => [
  { value: 'all',        label: t('hosts.allocations.filter.all') },
  { value: 'assigned',   label: t('hosts.allocations.filter.assigned') },
  { value: 'unassigned', label: t('hosts.allocations.filter.unassigned') },
])

const mobileFilterOpen = ref(false)
const { sortBy, sortOrder, toggleSort } = useTableSort({
  defaultBy: 'ip',
  defaultOrder: 'asc',
})
const sortColumns = computed(() => [
  { key: 'ip', label: t('hosts.allocations.columns.ip') },
  { key: 'alias', label: t('hosts.allocations.columns.alias') },
  { key: 'port', label: t('hosts.allocations.columns.port') },
  { key: 'server', label: t('hosts.allocations.columns.server') },
])
const filterGroups = computed(() => [
  {
    key: 'assigned',
    label: t('hosts.allocations.filter.label'),
    modelValue: filterAssigned.value,
    options: filterOptions.value,
  },
])
function onMobileFilter(groupKey: string, value: string | number | boolean) {
  if (groupKey === 'assigned') {
    filterAssigned.value = String(value) as AssignedFilter
  }
}

const {
  page,
  perPage,
  total,
  totalPages,
  loading: listLoading,
  reload,
  setPerPage,
  resetStateWithoutFetch,
} = useServerPagination(
  async ({ page: reqPage, perPage: reqPerPage, isCurrent }) => {
    if (!hostId.value) return null
    const params = new URLSearchParams()
    if (filterAssigned.value === 'assigned')   params.set('assigned', 'true')
    if (filterAssigned.value === 'unassigned') params.set('assigned', 'false')
    if (searchTerm.value.trim()) params.set('search', searchTerm.value.trim())
    params.set('page', String(reqPage))
    params.set('per_page', String(reqPerPage))
    if (sortBy.value) {
      params.set('sort_by', sortBy.value)
      params.set('sort_order', sortOrder.value)
    }
    const data = await get<ListResponse>(
      `/api/admin/hosts/${hostId.value}/allocations?${params.toString()}`,
    )
    if (!data || !isCurrent()) return null
    items.value = data.items
    const visible = new Set(data.items.filter(i => !i.server).map(i => i.id))
    const next = new Set<number>()
    selectedIds.value.forEach(id => { if (visible.has(id)) next.add(id) })
    selectedIds.value = next
    return { total: data.total }
  },
  {
    initialPerPage: 20,
    enabled: () => !!hostId.value && isWings.value,
    filters: [filterAssigned, sortBy, sortOrder],
    search: searchTerm,
    onError: handleError,
  },
)

function load(silent = false) {
  return reload({ silent })
}

// ── Selection (multi-select via custom checkbox column) ──
// Only "free" allocations (server === null) can be selected for delete.
const selectedIds = ref<Set<number>>(new Set())
const batchBusy = ref(false)
const selectableIds = computed(() => items.value.filter(a => !a.server).map(a => a.id))
const allSelected = computed({
  get: () => {
    const sel = selectableIds.value
    return sel.length > 0 && sel.every(id => selectedIds.value.has(id))
  },
  set: (v: boolean) => {
    const sel = selectableIds.value
    const next = new Set(selectedIds.value)
    if (v) sel.forEach(id => next.add(id))
    else   sel.forEach(id => next.delete(id))
    selectedIds.value = next
  },
})
function toggleSelect(id: number) {
  const next = new Set(selectedIds.value)
  if (next.has(id)) next.delete(id); else next.add(id)
  selectedIds.value = next
}
function clearSelection() {
  selectedIds.value = new Set()
}
function invertSelection() {
  selectedIds.value = new Set(selectableIds.value.filter(id => !selectedIds.value.has(id)))
}

// ── Modals ──
const createOpen = ref(false)
const editOpen = ref(false)
const editingAllocation = ref<AllocationOut | null>(null)

function openEdit(a: AllocationOut) {
  editingAllocation.value = a
  editOpen.value = true
}

function onUpdated(updated: AllocationOut) {
  const idx = items.value.findIndex(item => item.id === updated.id)
  if (idx >= 0) items.value[idx] = updated
  else void load(true)
}

watch(hostId, (id, prev) => {
  if (id && id !== prev && isWings.value) {
    resetStateWithoutFetch()
    void load()
  }
})

onMounted(() => {
  if (host.value && !isWings.value) {
    router.replace({ name: 'host-overview', params: { id: String(host.value.id) } })
    return
  }
  if (hostId.value && isWings.value) {
    void load()
  }
})

// React when the host detail finishes loading after this pane mounts.
watch(host, (h) => {
  if (h && !isWings.value) {
    router.replace({ name: 'host-overview', params: { id: String(h.id) } })
  }
}, { immediate: false })

// ── Actions ──
function openServer(a: AllocationOut) {
  if (!a.server) return
  router.push(`/admin/servers/${a.server.id}`)
}

async function deleteOne(a: AllocationOut) {
  if (a.server) {
    toast(t('hosts.allocations.delete.inUse', { port: a.port }), 'error')
    return
  }
  const ok = await confirm({
    title: t('hosts.allocations.delete.singleTitle'),
    message: t('hosts.allocations.delete.singleMsg', { port: a.port }),
    variant: 'danger',
  })
  if (!ok) return
  try {
    const res = await raw(
      `/api/admin/hosts/${hostId.value}/allocations/${a.id}`,
      { method: 'DELETE', silent: true },
    )
    if (res.ok) {
      toast(t('hosts.allocations.delete.toastOk', { n: 1 }), 'success')
      selectedIds.value.delete(a.id)
      await load(true)
    }
  } catch (failure) {
    if (failure instanceof ApiError && failure.status === 409) {
      toast(t('hosts.allocations.delete.inUse', { port: a.port }), 'error')
      await load(true)
    } else toast(apiErrorMessage(failure), 'error')
  }
}

async function bulkDelete() {
  if (batchBusy.value) return
  const ids = Array.from(selectedIds.value)
  if (ids.length === 0) return
  batchBusy.value = true
  try {
    const ok = await confirm({
      title: t('hosts.allocations.delete.bulkTitle'),
      message: t('hosts.allocations.delete.bulkMsg', { n: ids.length }),
      variant: 'danger',
    })
    if (!ok) return
    const res = await raw(`/api/admin/hosts/${hostId.value}/allocations`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids }),
      silent: true,
    })
    if (res.ok) {
      toast(t('hosts.allocations.delete.toastOk', { n: ids.length }), 'success')
      clearSelection()
      await load(true)
    }
  } catch (failure) {
    if (failure instanceof ApiError && failure.status === 409) {
      const ports = failure.problem.context?.conflicting_ports
      const msg = (Array.isArray(ports) && ports.length)
        ? t('hosts.allocations.delete.inUse', { port: ports.join(', ') })
        : t('hosts.allocations.delete.failed')
      toast(msg, 'error')
      await load(true)
    } else toast(apiErrorMessage(failure), 'error')
  } finally { batchBusy.value = false }
}

function onCreated() {
  createOpen.value = false
  load(true)
}

// ── Empty messages ──
const isFiltered = computed(() =>
  filterAssigned.value !== 'all' || !!searchTerm.value.trim(),
)
const emptyText = computed(() =>
  isFiltered.value
    ? t('hosts.allocations.emptyFiltered')
    : t('hosts.allocations.empty'),
)
const emptyIcon = computed(() => isFiltered.value ? 'search_off' : 'lan')
</script>

<template>
  <div v-if="!host" class="muted">{{ t('hosts.detail.loading') }}</div>
  <AlertBanner v-else-if="!isWings || !hostId" tone="info" :icon="'info'">
    {{ t('hosts.allocations.notWings') }}
  </AlertBanner>

  <div v-else class="alloc-pane">
    <PageHeaderActions>
      <BaseButton size="sm" variant="primary" :disabled="batchBusy" @click="createOpen = true"><MsIcon name="add" size="xs" />{{ t('hosts.allocations.actions.create') }}</BaseButton>
    </PageHeaderActions>
    <ListToolbar :selected-count="selectedIds.size" :busy="batchBusy" @select-all="allSelected = true" @invert="invertSelection" @clear="clearSelection">
      <template #start>
        <div class="tb-search-row">
          <FilterInput
            v-model="searchTerm"
            :placeholder="t('hosts.allocations.search.placeholder')"
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
          {{ t('hosts.allocations.summaryFiltered', { n: total }) }}
        </div>
      </template>
      <template #end>
        <div class="tb-select-group tb-desktop-only">
          <BaseSelect
            v-model="filterAssigned"
            :options="filterOptions"
            :prefix="t('hosts.allocations.filter.label') + ': '"
            size="sm"
            fit
          />
        </div>
      </template>
      <template #selection-actions>
        <BaseButton size="sm" variant="danger" :disabled="batchBusy" :aria-label="t('hosts.allocations.selection.bulkDelete')" :title="t('hosts.allocations.selection.bulkDelete')" @click="bulkDelete"><MsIcon name="delete" size="sm" /><span class="selection-action-label">{{ t('hosts.allocations.selection.bulkDelete') }}</span></BaseButton>
      </template>
    </ListToolbar>

    <MobileFilterSheet
      v-model:open="mobileFilterOpen"
      :sort-columns="sortColumns"
      :sort-by="sortBy"
      :sort-order="sortOrder"
      :filters="filterGroups"
      @sort="toggleSort"
      @update:filter="onMobileFilter"
    />

    <div :inert="batchBusy">
    <DataTable
      :items="items"
      :page="page"
      :total-pages="totalPages"
      :per-page="perPage"
      :per-page-label="t('hosts.allocations.perPage')"
      :loading="listLoading"
      :empty-icon="emptyIcon"
      :empty-text="emptyText"
      @update:page="page = $event"
      @update:per-page="setPerPage"
    >
      <template #header>
        <th class="col-check">
          <input
            type="checkbox"
            v-model="allSelected"
            :disabled="selectableIds.length === 0"
            :aria-label="t('hosts.allocations.columns.select')"
          />
        </th>
        <SortTh class="col-ip" col="ip" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('hosts.allocations.columns.ip') }}</SortTh>
        <SortTh class="col-alias" col="alias" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('hosts.allocations.columns.alias') }}</SortTh>
        <SortTh class="col-port" col="port" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('hosts.allocations.columns.port') }}</SortTh>
        <SortTh class="col-server" col="server" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('hosts.allocations.columns.server') }}</SortTh>
        <th class="col-notes">{{ t('hosts.allocations.columns.notes') }}</th>
        <th class="col-actions">{{ t('hosts.allocations.columns.actions') }}</th>
      </template>

      <template #row="{ item: a }">
        <td class="col-check" @click.stop>
          <input
            type="checkbox"
            :disabled="!!a.server"
            :checked="selectedIds.has(a.id)"
            :aria-label="String(a.port)"
            @change="toggleSelect(a.id)"
          />
        </td>
        <td class="col-ip mono">{{ a.ip }}</td>
        <td class="col-alias">{{ a.alias || '—' }}</td>
        <td class="col-port mono tabular">
          <span class="port-cell">
            <span>:{{ a.port }}</span>
            <Badge v-if="a.server" color="var(--amber)" size="sm">
              {{ t('hosts.allocations.badge.inUse') }}
            </Badge>
            <Badge v-else color="var(--t3)" size="sm">
              {{ t('hosts.allocations.badge.free') }}
            </Badge>
          </span>
        </td>
        <td class="col-server">
          <a
            v-if="a.server"
            class="server-link"
            href="#"
            @click.prevent="openServer(a)"
          >
            <span class="server-name">{{ a.server.name }}</span>
            <span class="server-owner mono">{{ a.server.owner_name || `#${a.server.owner_id}` }}</span>
          </a>
          <span v-else class="muted">—</span>
        </td>
        <td class="col-notes">
          <span class="notes-text">{{ a.notes || '—' }}</span>
        </td>
        <td class="col-actions">
          <div class="action-group">
            <BaseButton
              size="sm"
              variant="default"
              @click.stop="openEdit(a)"
            >
              <MsIcon name="edit" size="xs" /> {{ t('common.btn.edit') }}
            </BaseButton>
            <BaseButton
              size="sm"
              variant="danger"
              :disabled="!!a.server"
              :title="a.server ? t('hosts.allocations.delete.inUse', { port: a.port }) : undefined"
              @click.stop="deleteOne(a)"
            >
              <MsIcon name="delete" size="xs" /> {{ t('hosts.allocations.actions.delete') }}
            </BaseButton>
          </div>
        </td>
      </template>

      <template #card="{ item: a }">
        <CardTap>
          <div class="card-row--main">
            <input type="checkbox" :disabled="!!a.server" :checked="selectedIds.has(a.id)" :aria-label="t('common.selection.select', { name: `${a.ip}:${a.port}` })" @click.stop @change="toggleSelect(a.id)" />
            <span class="card-name mono">
              {{ a.ip }}:{{ a.port }}
            </span>
            <Badge v-if="a.server" color="var(--amber)" size="sm">
              {{ t('hosts.allocations.badge.inUse') }}
            </Badge>
            <Badge v-else color="var(--t3)" size="sm">
              {{ t('hosts.allocations.badge.free') }}
            </Badge>
          </div>
          <div v-if="a.alias" class="card-row--sub">{{ a.alias }}</div>
          <div class="card-detail">
            <CardKV :label="t('hosts.allocations.columns.server')">
              <a
                v-if="a.server"
                class="server-link"
                href="#"
                @click.prevent.stop="openServer(a)"
              >{{ a.server.name }}</a>
              <span v-else class="muted">—</span>
            </CardKV>
            <CardKV v-if="a.notes" :label="t('hosts.allocations.columns.notes')">
              {{ a.notes }}
            </CardKV>
          </div>
          <div class="card-actions">
            <BaseButton
              size="sm"
              variant="default"
              @click.stop="openEdit(a)"
            >
              <MsIcon name="edit" size="xs" />
              {{ t('common.btn.edit') }}
            </BaseButton>
            <BaseButton
              size="sm"
              variant="danger"
              :disabled="!!a.server"
              @click.stop="deleteOne(a)"
            >
              <MsIcon name="delete" size="xs" />
              {{ t('hosts.allocations.actions.delete') }}
            </BaseButton>
          </div>
        </CardTap>
      </template>
    </DataTable>
    </div>

    <CreateAllocationsModal
      v-if="hostId"
      v-model="createOpen"
      :host-id="hostId"
      :default-alias="host?.hostname || ''"
      @created="onCreated"
    />

    <AllocationEditModal
      v-if="hostId"
      v-model="editOpen"
      :host-id="hostId"
      :allocation="editingAllocation"
      @updated="onUpdated"
    />
  </div>
</template>

<style scoped>
.alloc-pane {
  /* TabSwitcher already provides bottom spacing; no extra top margin here. */
}

.muted {
  color: var(--t3);
  font-size: var(--text-sm);
  padding: var(--sp-4);
}

.summary {
  font-size: var(--text-sm);
  color: var(--t2);
  white-space: nowrap;
}


/* ── Table cells ── */
:deep(.dt-table)    { min-width: 980px; }
:deep(.col-check)   { width: 40px; text-align: center !important; padding-right: 0 !important; }
:deep(.col-ip)      { width: 136px; }
:deep(.col-alias)   { width: 16%; }
:deep(.col-port)    { width: 148px; }
:deep(.col-server)  { width: 20%; }
:deep(.col-notes)   { width: auto; color: var(--t2); }
:deep(.col-actions) { width: 176px; }

.action-group {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}

.port-cell {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}

.server-link {
  display: inline-flex;
  flex-direction: column;
  gap: 2px;
  color: var(--ac);
  text-decoration: none;
}
.server-link:hover { color: var(--ac2); }
.server-name { font-weight: 500; }
.server-owner {
  font-size: var(--text-xs);
  color: var(--t3);
}

.notes-text {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}

.mono { font-family: var(--font-mono); }
.tabular { font-variant-numeric: tabular-nums; }

/* ── Mobile card slot ── */
.card-row--main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-2);
  flex-wrap: wrap;
}
.card-name { font-weight: 500; color: var(--t1); min-width: 0; word-break: break-all; }
.card-row--sub {
  margin-top: var(--sp-1);
  font-size: var(--text-sm);
  color: var(--t2);
  word-break: break-all;
}
.card-detail {
  margin-top: var(--sp-2);
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--sp-2);
}
.card-actions {
  margin-top: var(--sp-2);
  display: flex;
  justify-content: flex-end;
  gap: var(--sp-2);
  flex-wrap: wrap;
}
</style>

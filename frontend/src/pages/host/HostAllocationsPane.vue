<script setup lang="ts">
// HostAllocationsPane — Pterodactyl-Panel-style port allocation manager.
// Mounted only on wings_node hosts (parent route hides the tab otherwise).
// Reads/writes the shared `panel.allocations` table via:
//   GET    /api/admin/nodes/{node_id}/allocations?assigned=&search=&page=&per_page=
//   POST   /api/admin/nodes/{node_id}/allocations            { ip, alias?, ports }
//   DELETE /api/admin/nodes/{node_id}/allocations/{id}
//   DELETE /api/admin/nodes/{node_id}/allocations            { ids: number[] }
import { computed, inject, onMounted, ref, watch, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'
import SectionToolbar from '@/components/ui/SectionToolbar.vue'
import FilterInput from '@/components/ui/FilterInput.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import DataTable from '@/components/ui/DataTable.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import Badge from '@/components/ui/Badge.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import CardTap from '@/components/ui/CardTap.vue'
import CardKV from '@/components/ui/CardKV.vue'
import AlertBanner from '@/components/ui/AlertBanner.vue'
import CreateAllocationsModal from '@/components/hosts/CreateAllocationsModal.vue'

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
interface SummaryDTO { total: number; assigned: number; unassigned: number }
interface ListResponse {
  items: AllocationOut[]
  page: number
  per_page: number
  total: number
  summary: SummaryDTO
}

const { t } = useI18n({ useScope: 'global' })
const router = useRouter()
const { get } = useApiFetch()
const { toast } = useToast()
const { confirm } = useConfirm()

const host = inject<Ref<HostDetail | null>>('hostDetail')!
const nodeId = computed(() => host.value?.pterodactyl_node_id ?? null)
const isWings = computed(() => host.value?.kind === 'wings_node')

// ── List state ──
// Use a separate listLoading ref so it isn't shared with delete/create
// HTTP calls (useApiFetch.loading is shared across all requests).
const items = ref<AllocationOut[]>([])
const summary = ref<SummaryDTO>({ total: 0, assigned: 0, unassigned: 0 })
const total = ref(0)
const page = ref(1)
const perPage = ref(20)
const listLoading = ref(false)

// ── Filters ──
type AssignedFilter = 'all' | 'assigned' | 'unassigned'
const filterAssigned = ref<AssignedFilter>('all')
const searchTerm = ref('')

const filterOptions = computed(() => [
  { value: 'all',        label: t('hosts.allocations.filter.all') },
  { value: 'assigned',   label: t('hosts.allocations.filter.assigned') },
  { value: 'unassigned', label: t('hosts.allocations.filter.unassigned') },
])

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / perPage.value)))

// ── Selection (multi-select via custom checkbox column) ──
// Only "free" allocations (server === null) can be selected for delete.
const selectedIds = ref<Set<number>>(new Set())
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

// ── Modal ──
const createOpen = ref(false)

// ── Loaders ──
async function load(silent = false) {
  if (!nodeId.value) return
  if (!silent) listLoading.value = true
  try {
    const params = new URLSearchParams()
    if (filterAssigned.value === 'assigned')   params.set('assigned', 'true')
    if (filterAssigned.value === 'unassigned') params.set('assigned', 'false')
    if (searchTerm.value.trim()) params.set('search', searchTerm.value.trim())
    params.set('page', String(page.value))
    params.set('per_page', String(perPage.value))
    const data = await get<ListResponse>(
      `/api/admin/nodes/${nodeId.value}/allocations?${params.toString()}`,
    )
    if (data) {
      items.value = data.items
      summary.value = data.summary
      total.value = data.total
      // Drop any selection that no longer references a visible row.
      const visible = new Set(data.items.map(i => i.id))
      const next = new Set<number>()
      selectedIds.value.forEach(id => { if (visible.has(id)) next.add(id) })
      selectedIds.value = next
    }
  } finally {
    if (!silent) listLoading.value = false
  }
}

// Reset page on filter/search change.
watch([filterAssigned, searchTerm], () => {
  page.value = 1
  load()
})
watch([page, perPage], () => load())
watch(nodeId, (id) => { if (id) load() })

onMounted(() => {
  // Allocations are wings-only; redirect away when host is not a wings node.
  // Host detail may still be loading; the watcher below handles late arrival.
  if (host.value && !isWings.value) {
    router.replace({ name: 'host-overview', params: { id: String(host.value.id) } })
    return
  }
  if (nodeId.value) load()
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
    const res = await fetch(
      `/api/admin/nodes/${nodeId.value}/allocations/${a.id}`,
      { method: 'DELETE' },
    )
    if (res.ok) {
      toast(t('hosts.allocations.delete.toastOk', { n: 1 }), 'success')
      selectedIds.value.delete(a.id)
      await load(true)
    } else if (res.status === 409) {
      toast(t('hosts.allocations.delete.inUse', { port: a.port }), 'error')
      await load(true)
    } else {
      toast(t('hosts.allocations.delete.failed'), 'error')
    }
  } catch {
    toast(t('hosts.allocations.delete.failed'), 'error')
  }
}

async function bulkDelete() {
  const ids = Array.from(selectedIds.value)
  if (ids.length === 0) return
  const ok = await confirm({
    title: t('hosts.allocations.delete.bulkTitle'),
    message: t('hosts.allocations.delete.bulkMsg', { n: ids.length }),
    variant: 'danger',
  })
  if (!ok) return
  try {
    const res = await fetch(`/api/admin/nodes/${nodeId.value}/allocations`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids }),
    })
    if (res.ok) {
      toast(t('hosts.allocations.delete.toastOk', { n: ids.length }), 'success')
      clearSelection()
      await load(true)
    } else if (res.status === 409) {
      let ports: number[] | undefined
      try {
        const body = await res.json()
        // FastAPI HTTPException wraps payload under `detail`; fall back to root.
        ports = body?.detail?.conflicting_ports || body?.conflicting_ports
      } catch { /* swallow */ }
      const msg = (Array.isArray(ports) && ports.length)
        ? t('hosts.allocations.delete.inUse', { port: ports.join(', ') })
        : t('hosts.allocations.delete.failed')
      toast(msg, 'error')
      await load(true)
    } else {
      toast(t('hosts.allocations.delete.failed'), 'error')
    }
  } catch {
    toast(t('hosts.allocations.delete.failed'), 'error')
  }
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
  <AlertBanner v-else-if="!isWings || !nodeId" tone="info" :icon="'info'">
    {{ t('hosts.allocations.notWings') }}
  </AlertBanner>

  <div v-else class="alloc-pane">
    <SectionToolbar>
      <template #start>
        <FilterInput
          v-model="searchTerm"
          :placeholder="t('hosts.allocations.search.placeholder')"
          class="alloc-filter-input"
          @update:modelValue="page = 1"
        />
        <div class="summary" role="status">
          {{ t('hosts.allocations.summaryFiltered', { n: total }) }}
        </div>
      </template>
      <template #end>
        <div class="toolbar-end-row">
          <BaseButton
            v-if="selectedIds.size > 0"
            size="sm"
            variant="danger"
            class="toolbar-half"
            @click="bulkDelete"
          >
            <MsIcon name="delete" size="xs" />
            {{ t('hosts.allocations.selection.bulkDelete') }} ({{ selectedIds.size }})
          </BaseButton>
          <BaseButton
            size="sm"
            variant="primary"
            class="toolbar-half"
            @click="createOpen = true"
          >
            <MsIcon name="add" size="xs" />
            {{ t('hosts.allocations.actions.create') }}
          </BaseButton>
          <BaseSelect
            v-model="filterAssigned"
            :options="filterOptions"
            :prefix="t('hosts.allocations.filter.label') + ': '"
            size="sm"
            fit
            class="toolbar-half"
            @update:modelValue="page = 1"
          />
        </div>
      </template>
    </SectionToolbar>

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
      @update:per-page="perPage = $event; page = 1"
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
        <th class="col-ip">{{ t('hosts.allocations.columns.ip') }}</th>
        <th class="col-alias">{{ t('hosts.allocations.columns.alias') }}</th>
        <th class="col-port">{{ t('hosts.allocations.columns.port') }}</th>
        <th class="col-server">{{ t('hosts.allocations.columns.server') }}</th>
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
          <BaseButton
            size="sm"
            variant="danger"
            :disabled="!!a.server"
            :title="a.server ? t('hosts.allocations.delete.inUse', { port: a.port }) : t('hosts.allocations.actions.delete')"
            @click.stop="deleteOne(a)"
          >
            <MsIcon name="delete" size="xs" />
          </BaseButton>
        </td>
      </template>

      <template #card="{ item: a }">
        <CardTap>
          <div class="card-row--main">
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

    <CreateAllocationsModal
      v-if="nodeId"
      v-model="createOpen"
      :node-id="nodeId"
      :default-alias="host?.hostname || ''"
      @created="onCreated"
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

.alloc-filter-input {
  flex: 1;
  max-width: 280px;
}

@media (max-width: 768px) {
  .alloc-filter-input {
    max-width: none;
    width: 100%;
  }
}

@media (max-width: 768px) {
  .toolbar-half {
    flex: 1;
    min-width: 0;
  }
}

.summary {
  font-size: var(--text-sm);
  color: var(--t2);
  white-space: nowrap;
}

/* SectionToolbar provides batch-controls / toolbar-end-row / toolbar-status
   :slotted styles globally; no need to redefine here. */

/* ── Table cells ── */
.col-check { width: 36px; text-align: center !important; padding-right: 0 !important; }
.col-ip    { width: 130px; }
.col-alias { max-width: 220px; overflow: hidden; text-overflow: ellipsis; }
.col-port  { width: 150px; }
.col-server { min-width: 200px; }
.col-notes { color: var(--t2); max-width: 240px; overflow: hidden; text-overflow: ellipsis; }
.col-actions { width: 60px; text-align: right; }

.port-cell {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
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

.mono { font-family: 'IBM Plex Mono', ui-monospace, monospace; }
.tabular { font-variant-numeric: tabular-nums; }

/* ── Mobile card slot ── */
.card-row--main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-2);
}
.card-name { font-weight: 500; color: var(--t1); }
.card-row--sub {
  margin-top: var(--sp-1);
  font-size: var(--text-sm);
  color: var(--t2);
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
}

/* ── Transitions ── */
.fade-enter-active,
.fade-leave-active { transition: opacity .15s ease, transform .15s ease; }
.fade-enter-from,
.fade-leave-to { opacity: 0; transform: translateY(-4px); }
</style>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'
import PageHeader from '@/components/layout/PageHeader.vue'
import SectionToolbar from '@/components/ui/SectionToolbar.vue'
import FilterInput from '@/components/ui/FilterInput.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseModal from '@/components/ui/BaseModal.vue'
import Badge from '@/components/ui/Badge.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import DataTable from '@/components/ui/DataTable.vue'
import NumberInput from '@/components/form/NumberInput.vue'
import ActionSheet from '@/components/ui/ActionSheet.vue'
import CardTap from '@/components/ui/CardTap.vue'
import CardKV from '@/components/ui/CardKV.vue'
import FormField from '@/components/form/FormField.vue'
import CreateServerModal from '@/components/servers/CreateServerModal.vue'
import RenewBottomSheet from '@/components/servers/RenewBottomSheet.vue'

defineOptions({ name: 'ServersPage' })

const { t } = useI18n({ useScope: 'global' })
const route = useRoute()
const router = useRouter()
const { get, post, del, loading } = useApiFetch()
const { toast } = useToast()
const { confirm } = useConfirm()

// ── Types ──
interface ServerItem {
  pteroId: number
  uuid: string | null
  name: string
  ownerId: number | null
  ownerUsername: string | null
  eggName: string | null
  expirationDate: string | null
  daysLeft: number | null
  statusLabel: 'normal' | 'expiring_soon' | 'expired' | 'permanent'
  isSuspended: boolean
  panelUrl: string | null
}

// ── Raw data (from API, no sort/filter params) ──
const rawServers = ref<ServerItem[]>([])

// ── Client-side state ──
const filterStatus = ref('all')
const sortBy = ref('expiration_date')
const sortOrder = ref<'asc' | 'desc'>('asc')
const searchTerm = ref((route.query.q as string) || '')
const selectedIds = ref<Set<number>>(new Set())
const page = ref(1)
const perPage = ref(20)

// Renew inline — date picker
// Default: expired → today+30, not expired → expirationDate+30, permanent → today+30
const renewDateMap = ref<Map<number, string>>(new Map())

function calcDefaultRenewDate(s: ServerItem): string {
  const addDays = (base: Date, n: number) => {
    const d = new Date(base)
    d.setDate(d.getDate() + n)
    return d.toISOString().slice(0, 10)
  }
  const today = new Date()
  if (!s.expirationDate || (s.daysLeft !== null && s.daysLeft < 0)) {
    // Expired or permanent — base = today
    return addDays(today, 30)
  }
  // Not expired — base = current expiration date
  const expDate = new Date(s.expirationDate + 'T00:00:00')
  return addDays(expDate, 30)
}

function getRenewDate(s: ServerItem): string {
  return renewDateMap.value.get(s.pteroId) ?? calcDefaultRenewDate(s)
}
function setRenewDate(pteroId: number, val: string) {
  renewDateMap.value.set(pteroId, val)
}

// Batch operations
const batchRenewModalOpen = ref(false)
const batchRenewDays = ref(30)
const batchActionType = ref('')
const batchActionOptions = computed(() => [
  { value: 'suspend', label: t('servers.batch.suspend') },
  { value: 'unsuspend', label: t('servers.batch.unsuspend') },
  { value: 'renew', label: t('servers.batch.renew') },
  { value: 'email', label: t('servers.batch.email') },
  { value: 'delete', label: t('servers.batch.delete') },
])

// ── Options ──
const statusOptions = computed(() => [
  { value: 'all', label: t('servers.filter.all') },
  { value: 'normal', label: t('servers.filter.normal') },
  { value: 'expiring_soon', label: t('servers.filter.expiring_soon') },
  { value: 'expired', label: t('servers.filter.expired') },
  { value: 'permanent', label: t('servers.filter.permanent') },
])

// ── Fetch (no sort/filter/search params — gets everything) ──
const tableLoading = ref(true)

async function loadServers(silent = false) {
  if (!silent) tableLoading.value = true
  const data = await get<{ servers: ServerItem[]; panelUrl: string }>('/api/servers')
  if (data) {
    rawServers.value = data.servers
  }
  tableLoading.value = false
}

onMounted(async () => {
  await loadServers()
  // Auto-open create modal if navigated from user creation
  if (newForUser.value) {
    createModalOpen.value = true
  }
})

// ── Client-side filter → sort → paginate pipeline ──
const filtered = computed(() => {
  let list = rawServers.value

  // Text search
  const q = searchTerm.value.toLowerCase().trim()
  if (q) {
    list = list.filter(s =>
      s.name.toLowerCase().includes(q) ||
      (s.ownerUsername || '').toLowerCase().includes(q) ||
      String(s.pteroId).includes(q),
    )
  }

  // Status filter
  if (filterStatus.value !== 'all') {
    list = list.filter(s => s.statusLabel === filterStatus.value)
  }

  return list
})

const sorted = computed(() => {
  const list = [...filtered.value]
  const col = sortBy.value
  const asc = sortOrder.value === 'asc'

  list.sort((a, b) => {
    let va: string | number | null
    let vb: string | number | null

    if (col === 'server_name') {
      va = a.name.toLowerCase()
      vb = b.name.toLowerCase()
    } else if (col === 'expiration_date') {
      va = a.expirationDate
      vb = b.expirationDate
      // nulls (permanent) go last in asc, first in desc
      if (va === null && vb === null) return 0
      if (va === null) return asc ? 1 : -1
      if (vb === null) return asc ? -1 : 1
    } else if (col === 'owner_username') {
      va = (a.ownerUsername || '').toLowerCase()
      vb = (b.ownerUsername || '').toLowerCase()
    } else {
      va = a.pteroId
      vb = b.pteroId
    }

    if (va! < vb!) return asc ? -1 : 1
    if (va! > vb!) return asc ? 1 : -1
    return 0
  })

  return list
})

const totalPages = computed(() => Math.max(1, Math.ceil(sorted.value.length / perPage.value)))

// Reset page when filters change
const paginated = computed(() => {
  const start = (page.value - 1) * perPage.value
  return sorted.value.slice(start, start + perPage.value)
})

// ── Selection ──
const allSelected = computed({
  get: () => paginated.value.length > 0 && paginated.value.every(s => selectedIds.value.has(s.pteroId)),
  set: (v: boolean) => {
    const s = new Set(selectedIds.value)
    if (v) {
      paginated.value.forEach(srv => s.add(srv.pteroId))
    } else {
      paginated.value.forEach(srv => s.delete(srv.pteroId))
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

// ── Status helpers ──
function statusColor(s: ServerItem): string {
  if (s.isSuspended) return 'var(--red)'
  switch (s.statusLabel) {
    case 'normal': return 'var(--green)'
    case 'expiring_soon': return 'var(--amber)'
    case 'expired': return 'var(--red)'
    case 'permanent': return 'var(--t3)'
    default: return 'var(--t3)'
  }
}

function expirationText(s: ServerItem): string {
  if (s.expirationDate === null) return t('servers.status.permanent')
  if (s.daysLeft !== null && s.daysLeft < 0) return `${s.expirationDate} (${t('servers.status.expired')})`
  if (s.daysLeft === 0) return `${s.expirationDate} (${t('servers.status.today')})`
  if (s.daysLeft !== null) return `${s.expirationDate} (${t('servers.status.days_left', { n: s.daysLeft })})`
  return s.expirationDate
}

function panelStatusText(s: ServerItem): string {
  return s.isSuspended ? t('servers.status.suspended') : t('servers.status.normal')
}

// ── Actions ──
async function doRenew(s: ServerItem) {
  const targetDate = getRenewDate(s)
  const res = await post<{ message: string }>(`/api/servers/${s.pteroId}/renew`, { date: targetDate })
  if (res) {
    toast(res.message, 'success')
    await loadServers(true)
  }
}

async function toggleSuspend(s: ServerItem) {
  const titleKey = s.isSuspended ? 'servers.confirm.unsuspend_title' : 'servers.confirm.suspend_title'
  const msgKey = s.isSuspended ? 'servers.confirm.unsuspend_msg' : 'servers.confirm.suspend_msg'
  const ok = await confirm({
    title: t(titleKey),
    message: t(msgKey, { name: s.name }),
    variant: s.isSuspended ? 'default' : 'danger',
    confirmText: s.isSuspended ? t('servers.action.unsuspend') : t('servers.action.suspend'),
  })
  if (!ok) return
  const res = await post<{ message: string }>(`/api/servers/${s.pteroId}/suspend`)
  if (res) {
    toast(res.message, 'success')
    await loadServers(true)
  }
}

async function deleteServer(s: ServerItem) {
  const ok = await confirm({
    title: t('servers.confirm.delete_title'),
    message: t('servers.confirm.delete_msg', { name: s.name }),
    variant: 'danger',
    confirmText: t('common.btn.delete'),
  })
  if (!ok) return
  const res = await del<{ message: string }>(`/api/servers/${s.pteroId}`)
  if (res) {
    toast(res.message, 'success')
    selectedIds.value.delete(s.pteroId)
    await loadServers(true)
  }
}

// ── Batch ──
async function executeBatchAction() {
  const action = batchActionType.value
  if (!action) return
  const ids = [...selectedIds.value]
  if (!ids.length) return

  if (action === 'renew') {
    batchRenewDays.value = 30
    batchRenewModalOpen.value = true
    return
  }

  if (action === 'delete') {
    const ok = await confirm({
      title: t('servers.confirm.batch_delete_title'),
      message: t('servers.confirm.batch_delete_msg', { n: ids.length }),
      variant: 'danger',
      confirmText: t('common.btn.delete'),
    })
    if (!ok) return
  }

  if (action === 'email') {
    const ok = await confirm({
      title: t('servers.confirm.batch_email_title'),
      message: t('servers.confirm.batch_email_msg', { n: ids.length }),
      confirmText: t('common.btn.confirm'),
    })
    if (!ok) return
  }

  const res = await post<{ message: string }>('/api/servers/batch', { action, serverIds: ids })
  if (res) {
    toast(res.message, 'success')
    selectedIds.value = new Set()
    batchActionType.value = ''
    await loadServers(true)
  }
}

async function doBatchRenew() {
  const ids = [...selectedIds.value]
  if (!ids.length) return
  const res = await post<{ message: string }>('/api/servers/batch', {
    action: 'renew',
    serverIds: ids,
    days: batchRenewDays.value,
  })
  if (res) {
    toast(res.message, 'success')
    batchRenewModalOpen.value = false
    selectedIds.value = new Set()
    batchActionType.value = ''
    await loadServers(true)
  }
}

// ── Create Server Modal ──
const createModalOpen = ref(false)
const newForUser = ref((route.query.new_for_user as string) || '')

// ── Sort toggle (client-side, no reload) ──
function toggleSort(col: string) {
  if (sortBy.value === col) {
    sortOrder.value = sortOrder.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortBy.value = col
    sortOrder.value = 'asc'
  }
  page.value = 1
}

// ── Mobile renew sheet ──
const mobileRenewServer = ref<ServerItem | null>(null)
const mobileRenewOpen = ref(false)

// ── Mobile action sheet ──
const mobileActionServer = ref<ServerItem | null>(null)
const mobileActionOpen = ref(false)
function openMobileServerAction(s: ServerItem) {
  mobileActionServer.value = s
  mobileActionOpen.value = true
}
function openMobileRenew(s: ServerItem) {
  mobileRenewServer.value = s
  mobileRenewOpen.value = true
}
</script>

<template>
  <PageHeader icon="dns" :title="t('servers.title')" />

  <div class="page-body">
    <!-- Toolbar -->
    <SectionToolbar>
      <template #start>
        <FilterInput
          v-model="searchTerm"
          :placeholder="t('servers.search_placeholder')"
          class="servers-filter-input"
          @update:modelValue="page = 1"
        />
        <div class="batch-controls">
          <BaseSelect v-model="batchActionType" :options="batchActionOptions" :placeholder="t('servers.batch.select_action')" size="sm" fit :disabled="selectedIds.size === 0" />
          <BaseButton size="sm" :disabled="selectedIds.size === 0 || !batchActionType" @click="executeBatchAction">
            <MsIcon name="play_arrow" size="xs" /> {{ t('servers.batch.execute') }}
          </BaseButton>
          <span v-if="selectedIds.size > 0" class="toolbar-status">{{ t('servers.batch.selected', { n: selectedIds.size }) }}</span>
        </div>
      </template>
      <template #end>
        <div class="toolbar-end-row">
          <BaseButton size="sm" variant="primary" class="toolbar-half" @click="createModalOpen = true">
            <MsIcon name="add" size="xs" /> {{ t('servers.action.create') }}
          </BaseButton>
          <BaseSelect v-model="filterStatus" :options="statusOptions" size="sm" fit class="toolbar-half" @update:modelValue="page = 1" />
        </div>
      </template>
    </SectionToolbar>

    <!-- Table -->
    <DataTable
      :items="paginated"
      :page="page"
      :total-pages="totalPages"
      :per-page="perPage"
      :per-page-label="t('servers.pagination.per_page')"
      :loading="tableLoading"
      empty-icon="dns"
      :empty-text="t('servers.empty')"
      row-key="pteroId"
      @update:page="page = $event"
      @update:per-page="perPage = $event; page = 1"
    >
      <template #header>
        <th class="col-check">
          <input type="checkbox" v-model="allSelected" />
        </th>
        <th class="col-id sortable" @click="toggleSort('id')">
          {{ t('servers.table.id') }}
          <MsIcon v-if="sortBy === 'id'" :name="sortOrder === 'asc' ? 'arrow_upward' : 'arrow_downward'" size="xs" />
        </th>
        <th class="col-name sortable" @click="toggleSort('server_name')">
          {{ t('servers.table.name') }}
          <MsIcon v-if="sortBy === 'server_name'" :name="sortOrder === 'asc' ? 'arrow_upward' : 'arrow_downward'" size="xs" />
        </th>
        <th class="col-egg">{{ t('servers.table.egg') }}</th>
        <th class="col-owner sortable" @click="toggleSort('owner_username')">
          {{ t('servers.table.owner') }}
          <MsIcon v-if="sortBy === 'owner_username'" :name="sortOrder === 'asc' ? 'arrow_upward' : 'arrow_downward'" size="xs" />
        </th>
        <th class="col-expiry sortable" @click="toggleSort('expiration_date')">
          {{ t('servers.table.expiration') }}
          <MsIcon v-if="sortBy === 'expiration_date'" :name="sortOrder === 'asc' ? 'arrow_upward' : 'arrow_downward'" size="xs" />
        </th>
        <th class="col-status">{{ t('servers.table.panel_status') }}</th>
        <th class="col-actions">{{ t('servers.table.actions') }}</th>
      </template>
      <template #row="{ item: s }">
        <td class="col-check">
          <input type="checkbox" :checked="selectedIds.has(s.pteroId)" @change="toggleSelect(s.pteroId)" />
        </td>
        <td class="col-id">{{ s.pteroId }}</td>
        <td class="col-name">
          <a v-if="s.panelUrl" :href="s.panelUrl" target="_blank" rel="noopener" class="server-link">
            {{ s.name }}
          </a>
          <span v-else>{{ s.name }}</span>
        </td>
        <td class="col-egg">{{ s.eggName || '—' }}</td>
        <td class="col-owner">
          <a v-if="s.ownerUsername" href="#" class="owner-link" @click.prevent="router.push({ name: 'users', query: { q: s.ownerUsername } })">{{ s.ownerUsername }}</a>
          <span v-else>—</span>
        </td>
        <td class="col-expiry">
          <span :style="{ color: statusColor(s) }">{{ expirationText(s) }}</span>
        </td>
        <td class="col-status">
          <Badge :color="s.isSuspended ? 'var(--red)' : 'var(--green)'">
            {{ panelStatusText(s) }}
          </Badge>
        </td>
        <td class="col-actions">
          <div class="action-group">
            <div class="renew-inline">
              <input
                type="date"
                class="renew-date-input"
                :value="getRenewDate(s)"
                @input="setRenewDate(s.pteroId, ($event.target as HTMLInputElement).value)"
              />
              <BaseButton size="sm" @click="doRenew(s)">
                <MsIcon name="update" size="xs" /> {{ t('servers.action.renew') }}
              </BaseButton>
            </div>
            <BaseButton size="sm" :variant="s.isSuspended ? 'success' : 'warning'" @click="toggleSuspend(s)">
              <MsIcon :name="s.isSuspended ? 'check_circle' : 'block'" size="xs" />
              {{ s.isSuspended ? t('servers.action.unsuspend') : t('servers.action.suspend') }}
            </BaseButton>
            <BaseButton size="sm" variant="danger" @click="deleteServer(s)">
              <MsIcon name="delete" size="xs" /> {{ t('servers.action.delete') }}
            </BaseButton>
          </div>
        </td>
      </template>

      <!-- Mobile card -->
      <template #card="{ item: s }">
        <CardTap @tap="openMobileServerAction(s)">
          <div class="card-row--main">
            <span class="card-name">{{ s.name }} <span class="card-id-inline">#{{ s.pteroId }}</span></span>
            <Badge :color="s.isSuspended ? 'var(--red)' : 'var(--green)'" size="sm">
              {{ panelStatusText(s) }}
            </Badge>
          </div>
          <div class="card-expiry-row">
            <span class="card-kv-label">{{ t('servers.table.expiration') }}</span>
            <span :style="{ color: statusColor(s) }">{{ expirationText(s) }}</span>
          </div>
          <div class="card-detail">
            <CardKV :label="t('servers.table.owner')">{{ s.ownerUsername || '—' }}</CardKV>
            <CardKV :label="t('servers.table.egg')">{{ s.eggName || '—' }}</CardKV>
          </div>
        </CardTap>
      </template>
    </DataTable>

    <!-- Mobile Action Sheet -->
    <ActionSheet v-model="mobileActionOpen" :title="mobileActionServer?.name">
      <template v-if="mobileActionServer" #info>
        {{ mobileActionServer.ownerUsername || '—' }} · <span :style="{ color: statusColor(mobileActionServer) }">{{ expirationText(mobileActionServer) }}</span>
      </template>
      <template v-if="mobileActionServer">
        <a v-if="mobileActionServer.panelUrl" :href="mobileActionServer.panelUrl" target="_blank" rel="noopener">
          <MsIcon name="link" size="sm" /> {{ t('servers.action.open_panel') }}
        </a>
        <button @click="mobileActionOpen = false; openMobileRenew(mobileActionServer!)">
          <MsIcon name="update" size="sm" /> {{ t('servers.action.renew') }}
        </button>
        <button @click="mobileActionOpen = false; toggleSuspend(mobileActionServer!)">
          <MsIcon :name="mobileActionServer.isSuspended ? 'check_circle' : 'block'" size="sm" />
          {{ mobileActionServer.isSuspended ? t('servers.action.unsuspend') : t('servers.action.suspend') }}
        </button>
        <button v-if="mobileActionServer.ownerUsername" @click="mobileActionOpen = false; router.push({ name: 'users', query: { q: mobileActionServer!.ownerUsername! } })">
          <MsIcon name="person" size="sm" /> {{ mobileActionServer.ownerUsername }}
        </button>
        <button class="action-sheet--danger" @click="mobileActionOpen = false; deleteServer(mobileActionServer!)">
          <MsIcon name="delete" size="sm" /> {{ t('servers.action.delete') }}
        </button>
      </template>
    </ActionSheet>

    <!-- Mobile Renew BottomSheet -->
    <RenewBottomSheet v-model="mobileRenewOpen" :server="mobileRenewServer" @renewed="loadServers(true)" />
  </div>

  <!-- Batch Renew Modal -->
  <BaseModal v-model="batchRenewModalOpen" :title="t('servers.batch.renew')" icon="update" size="sm">
    <p style="margin-bottom: var(--sp-3); color: var(--t2)">
      {{ t('servers.batch.selected', { n: selectedIds.size }) }}
    </p>
    <FormField :label="t('servers.action.renew_days')" density="compact">
      <NumberInput v-model="batchRenewDays" :min="1" :max="3650" />
    </FormField>
    <template #footer>
      <BaseButton @click="batchRenewModalOpen = false">{{ t('common.btn.cancel') }}</BaseButton>
      <BaseButton variant="primary" :loading="loading" @click="doBatchRenew">{{ t('common.btn.confirm') }}</BaseButton>
    </template>
  </BaseModal>

  <!-- Create Server Modal -->
  <CreateServerModal v-model="createModalOpen" :pre-select-username="newForUser" @created="loadServers(true)" />
</template>

<style scoped>
.servers-filter-input {
  flex: 1;
  max-width: 280px;
}

@media (max-width: 768px) {
  .servers-filter-input {
    max-width: none;
    width: 100%;
  }
}

.row-selected {
  background: color-mix(in srgb, var(--ac) 8%, transparent) !important;
}

.col-check { width: 36px; text-align: center !important; }
.col-id { width: 48px; color: var(--t3); font-size: .82rem; }

.toolbar-status {
  font-size: .82rem;
  color: var(--t3);
  white-space: nowrap;
}
.col-name { width: 18%; }
.col-egg { width: 14%; color: var(--t2); font-size: .85rem; }
.col-owner { width: 10%; }
.col-expiry { width: 11%; }
.col-status { width: 6%; }

.server-link,
.owner-link {
  color: var(--ac);
  text-decoration: none;
}
.server-link:hover,
.owner-link:hover {
  text-decoration: underline;
}

.renew-inline {
  display: flex;
  align-items: center;
  gap: 4px;
}

.renew-date-input {
  padding: 3px 6px;
  font-size: .78rem;
  border: 1px solid var(--bd);
  border-radius: 4px;
  background: var(--bg);
  color: var(--t1);
  outline: none;
  font-family: inherit;
}
.renew-date-input:focus {
  border-color: var(--ac);
}

/* Mobile card styles — page-specific */
.card-name {
  font-weight: 600;
  font-size: .92rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.card-id-inline {
  font-size: .78rem;
  font-weight: 400;
  color: var(--t3);
  margin-left: var(--sp-1);
}

.card-kv-label {
  font-size: .72rem;
  color: var(--t3);
  text-transform: uppercase;
  letter-spacing: .03em;
}

/* ── Table row actions ── */
.action-group {
  display: flex;
  gap: var(--sp-2);
  align-items: center;
  flex-wrap: wrap;
}

@media (max-width: 768px) {
  .toolbar-half {
    flex: 1;
    min-width: 0;
  }
}
</style>

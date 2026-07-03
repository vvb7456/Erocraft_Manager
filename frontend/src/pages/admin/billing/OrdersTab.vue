<script setup lang="ts">
/**
 * OrdersTab — 订单列表（AdminBillingPage 子组件）
 *
 * Conventions (mirrors ServersPage / UsersPage):
 *   - SectionToolbar: #start = FilterInput + count, #end = BaseSelects
 *   - DataTable with percentage-based column widths
 *   - Client-side sort via computed, toggleSort updates sortBy/sortOrder
 *   - Badge colors use palette CSS variables
 *   - Server-side pagination (backend: GET /api/admin/billing/orders)
 */
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useApiFetch } from '@/composables/useApiFetch'
import { useConfirm } from '@/composables/useConfirm'
import { useToast } from '@/composables/useToast'
import { useAppStore } from '@/stores/app'
import SectionToolbar from '@/components/ui/SectionToolbar.vue'
import DataTable from '@/components/ui/DataTable.vue'
import FilterInput from '@/components/ui/FilterInput.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import Badge from '@/components/ui/Badge.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import CardTap from '@/components/ui/CardTap.vue'
import ActionSheet from '@/components/ui/ActionSheet.vue'
import MobileFilterSheet from '@/components/ui/MobileFilterSheet.vue'

defineOptions({ name: 'OrdersTab' })

const emit = defineEmits<{ selectOrder: [orderId: number] }>()

interface OrderItem {
  id: number; order_no: string; user_id: number
  owner_username: string | null
  plan_id: number | null; plan_code: string; plan_name: string
  kind: string; period_count: number; total_fen: number; total_days: number
  target_server_id: number | null; target_server_name: string | null
  status: string; received_fen: number; refunded_fen: number
  created_at: string; updated_at: string
}

const { t } = useI18n({ useScope: 'global' })
const { get, post } = useApiFetch()
const { confirm } = useConfirm()
const { toast } = useToast()
const router = useRouter()
const appStore = useAppStore()

// ── Filters ──
const searchTerm = ref('')
const statusFilter = ref('')
const kindFilter = ref('')
const page = ref(1)
const perPage = ref(20)
const sortBy = ref('created_at')
const sortOrder = ref<'asc' | 'desc'>('desc')

const rawOrders = ref<OrderItem[]>([])
const totalCount = ref(0)
const totalPages = computed(() => Math.max(1, Math.ceil(totalCount.value / perPage.value)))
const loading = ref(false)

const statusOptions = [
  { value: '',               label: t('billing.admin.orders.filterAllStatus') },
  { value: 'pending',        label: t('billing.orders.status.pending') },
  { value: 'processing',     label: t('billing.orders.status.processing') },
  { value: 'applied',        label: t('billing.orders.status.applied') },
  { value: 'apply_failed',   label: t('billing.orders.status.apply_failed') },
  { value: 'manual_review',  label: t('billing.orders.status.manual_review') },
  { value: 'refunding',      label: t('billing.orders.status.refunding') },
  { value: 'refunded',       label: t('billing.orders.status.refunded') },
  { value: 'closed',         label: t('billing.orders.status.closed') },
  { value: 'cancelled',      label: t('billing.orders.status.cancelled') },
]

const kindOptions = [
  { value: '',              label: t('billing.admin.orders.filterAllKind') },
  { value: 'new_purchase',  label: t('billing.admin.orders.kindNewPurchase') },
  { value: 'renew',         label: t('billing.admin.orders.kindRenew') },
  { value: 'upgrade',       label: t('billing.admin.orders.kindUpgrade') },
  { value: 'convert',       label: t('billing.admin.orders.kindConvert') },
]

// ── Fetch ──
async function loadOrders() {
  loading.value = true
  const params = new URLSearchParams()
  params.set('limit', String(perPage.value))
  params.set('offset', String((page.value - 1) * perPage.value))
  if (searchTerm.value.trim()) params.set('q', searchTerm.value.trim())
  if (statusFilter.value) params.set('status', statusFilter.value)
  if (kindFilter.value) params.set('kind', kindFilter.value)

  const data = await get<{ items: OrderItem[]; total: number }>(
    `/api/admin/billing/orders?${params}`,
    { silent: true },
  )
  if (data !== null) {
    rawOrders.value = data.items
    totalCount.value = data.total
    if (page.value > totalPages.value) page.value = totalPages.value
  }
  loading.value = false
}

watch([searchTerm, statusFilter, kindFilter], () => {
  if (page.value === 1) {
    void loadOrders()
  } else {
    page.value = 1
  }
})
watch([page, perPage], () => { void loadOrders() }, { immediate: true })

// ── Client-side sort ──
function toggleSort(col: string) {
  if (sortBy.value === col) {
    sortOrder.value = sortOrder.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortBy.value = col
    sortOrder.value = 'asc'
  }
}

const sortedOrders = computed(() => {
  const list = [...rawOrders.value]
  const col = sortBy.value as keyof OrderItem
  const asc = sortOrder.value === 'asc'
  list.sort((a, b) => {
    const va = a[col]
    const vb = b[col]
    if (va == null && vb == null) return 0
    if (va == null) return 1
    if (vb == null) return -1
    const sa = typeof va === 'string' ? va.toLowerCase() : String(va)
    const sb = typeof vb === 'string' ? vb.toLowerCase() : String(vb)
    if (sa < sb) return asc ? -1 : 1
    if (sa > sb) return asc ? 1 : -1
    return 0
  })
  return list
})

// ── Mobile filter sheet ──
const mobileFilterOpen = ref(false)
const sortColumns = computed(() => [
  { key: 'created_at', label: t('billing.admin.orders.col.time') },
  { key: 'order_no', label: t('billing.admin.orders.col.orderNo') },
  { key: 'total_fen', label: t('billing.admin.orders.col.amount') },
  { key: 'user_id', label: t('billing.admin.orders.col.user') },
])
const filterGroups = computed(() => [
  {
    key: 'status',
    label: t('billing.admin.orders.filterStatusPrefix'),
    modelValue: statusFilter.value,
    options: statusOptions,
  },
  {
    key: 'kind',
    label: t('billing.admin.orders.filterKindPrefix'),
    modelValue: kindFilter.value,
    options: kindOptions,
  },
])
function onMobileSort(col: string) {
  toggleSort(col)
}
function onMobileFilter(groupKey: string, value: string | number | boolean) {
  if (groupKey === 'status') statusFilter.value = String(value)
  else if (groupKey === 'kind') kindFilter.value = String(value)
}

// ── Display helpers ──
function fenToYuan(fen: number): string { return (fen / 100).toFixed(2) }

function formatTime(iso: string): string {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '—'
  return d.toLocaleString('zh-CN', { timeZone: appStore.timezone, hour12: false })
}

function statusColor(s: string): string {
  switch (s) {
    case 'pending':       return 'var(--t3)'
    case 'processing':    return 'var(--blue)'
    case 'applied':       return 'var(--green)'
    case 'apply_failed':
    case 'manual_review': return 'var(--red)'
    case 'refunding':     return 'var(--amber)'
    case 'refunded':      return 'var(--t2)'
    case 'closed':
    case 'cancelled':     return 'var(--t3)'
    default:              return 'var(--t3)'
  }
}

function kindColor(k: string): string {
  switch (k) {
    case 'new_purchase': return 'var(--blue)'
    case 'renew':        return 'var(--green)'
    case 'upgrade':      return 'var(--amber)'
    case 'convert':      return 'var(--ac)'
    default:             return 'var(--t3)'
  }
}

function kindLabel(k: string): string {
  if (k === 'new_purchase') return t('billing.admin.orders.kindNewPurchase')
  if (k === 'upgrade') return t('billing.admin.orders.kindUpgrade')
  if (k === 'convert') return t('billing.admin.orders.kindConvert')
  return t('billing.admin.orders.kindRenew')
}

// ── Actions ──
function canForceApply(o: OrderItem): boolean {
  return o.status === 'manual_review' || o.status === 'apply_failed'
}

async function forceApply(o: OrderItem) {
  const ok = await confirm({
    title: t('billing.admin.orders.forceApplyTitle'),
    message: t('billing.admin.orders.forceApplyConfirm', { orderNo: o.order_no }),
    confirmText: t('billing.admin.orders.forceApply'),
  })
  if (!ok) return
  const res = await post<{ result: string }>(`/api/admin/billing/orders/${o.id}/force-apply`, {})
  if (res) {
    toast(t('billing.admin.orders.forceApplyResult', { result: res.result }), res.result === 'applied' ? 'success' : 'error')
    loadOrders()
  }
}

// ── Navigation ──
function goUser(userId: number, username: string | null) {
  router.push({ name: 'users', query: { q: username || String(userId) } })
}

function goServer(serverId: number, serverName: string | null) {
  router.push({ name: 'servers', query: { q: serverName || String(serverId) } })
}

// ── Mobile ──
const mobileOrder = ref<OrderItem | null>(null)
const mobileOpen = ref(false)
function openMobile(o: OrderItem) { mobileOrder.value = o; mobileOpen.value = true }
</script>

<template>
  <SectionToolbar>
    <template #start>
      <div class="tb-search-row">
        <FilterInput
          v-model="searchTerm"
          :placeholder="t('billing.admin.orders.searchPlaceholder')"
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
      <span class="toolbar-count tb-status">
        {{ t('billing.admin.orders.totalCount', { n: totalCount }) }}
      </span>
    </template>
    <template #end>
      <div class="tb-select-group tb-desktop-only">
        <BaseSelect
          v-model="statusFilter"
          :options="statusOptions"
          :prefix="t('billing.admin.orders.filterStatusPrefix') + ': '"
          size="sm"
          fit
        />
        <BaseSelect
          v-model="kindFilter"
          :options="kindOptions"
          :prefix="t('billing.admin.orders.filterKindPrefix') + ': '"
          size="sm"
          fit
        />
      </div>
    </template>
  </SectionToolbar>

  <!-- Mobile filter & sort sheet -->
  <MobileFilterSheet
    v-model:open="mobileFilterOpen"
    :sort-columns="sortColumns"
    :sort-by="sortBy"
    :sort-order="sortOrder"
    :filters="filterGroups"
    @sort="onMobileSort"
    @update:filter="onMobileFilter"
  />

  <div class="orders-table-wrap">
    <DataTable
    :items="sortedOrders"
    :page="page"
    :total-pages="totalPages"
    :per-page="perPage"
    :loading="loading"
    :per-page-label="t('billing.orders.perPage')"
    empty-icon="receipt_long"
    :empty-text="searchTerm
      ? t('billing.admin.orders.emptySearch', { q: searchTerm })
      : t('billing.admin.orders.empty')"
    row-key="id"
    @update:page="page = $event"
    @update:per-page="perPage = $event; page = 1"
  >
    <template #header>
      <th class="col-time sortable" @click="toggleSort('created_at')">
        {{ t('billing.admin.orders.col.time') }}
        <MsIcon v-if="sortBy === 'created_at'" :name="sortOrder === 'asc' ? 'arrow_upward' : 'arrow_downward'" size="xs" />
      </th>
      <th class="col-orderno sortable" @click="toggleSort('order_no')">
        {{ t('billing.admin.orders.col.orderNo') }}
        <MsIcon v-if="sortBy === 'order_no'" :name="sortOrder === 'asc' ? 'arrow_upward' : 'arrow_downward'" size="xs" />
      </th>
      <th class="col-kind">{{ t('billing.admin.orders.col.kind') }}</th>
      <th class="col-plan">{{ t('billing.admin.orders.col.plan') }}</th>
      <th class="col-amount sortable" @click="toggleSort('total_fen')">
        {{ t('billing.admin.orders.col.amount') }}
        <MsIcon v-if="sortBy === 'total_fen'" :name="sortOrder === 'asc' ? 'arrow_upward' : 'arrow_downward'" size="xs" />
      </th>
      <th class="col-status">{{ t('billing.admin.orders.col.status') }}</th>
      <th class="col-user sortable" @click="toggleSort('user_id')">
        {{ t('billing.admin.orders.col.user') }}
        <MsIcon v-if="sortBy === 'user_id'" :name="sortOrder === 'asc' ? 'arrow_upward' : 'arrow_downward'" size="xs" />
      </th>
      <th class="col-server">{{ t('billing.admin.orders.col.server') }}</th>
      <th class="col-actions">{{ t('billing.admin.orders.col.actions') }}</th>
    </template>

    <template #row="{ item: o }">
      <td class="col-time mono">{{ formatTime(o.created_at) }}</td>
      <td class="col-orderno"><a href="#" class="cell-link" @click.prevent="emit('selectOrder', o.id)"><code>{{ o.order_no }}</code></a></td>
      <td class="col-kind">
        <Badge :color="kindColor(o.kind)">{{ kindLabel(o.kind) }}</Badge>
      </td>
      <td class="col-plan">
        <span class="plan-name">{{ o.plan_name }}</span>
      </td>
      <td class="col-amount mono">¥{{ fenToYuan(o.total_fen) }}</td>
      <td class="col-status">
        <span class="status-cell">
          <MsIcon v-if="o.status === 'manual_review' || o.status === 'apply_failed'" name="warning" size="xs" class="status-warn-icon" />
          <Badge :color="statusColor(o.status)">{{ t(`billing.orders.status.${o.status}`) }}</Badge>
        </span>
      </td>
      <td class="col-user">
        <template v-if="o.user_id && o.owner_username">
          <a href="#" class="cell-link" @click.prevent="goUser(o.user_id, o.owner_username)">{{ o.owner_username }}</a>
        </template>
        <span v-else-if="o.user_id" class="cell-deleted">{{ t('billing.admin.orders.deletedUser', { id: o.user_id }) }}</span>
        <span v-else class="cell-muted">—</span>
      </td>
      <td class="col-server">
        <template v-if="o.target_server_id && o.target_server_name">
          <a href="#" class="cell-link" @click.prevent="goServer(o.target_server_id, o.target_server_name)">{{ o.target_server_name }}</a>
        </template>
        <span v-else-if="o.target_server_id" class="cell-deleted">{{ t('billing.admin.orders.deletedServer', { id: o.target_server_id }) }}</span>
        <span v-else class="cell-muted">—</span>
      </td>
      <td class="col-actions">
        <div class="action-group">
          <BaseButton size="sm" @click="emit('selectOrder', o.id)">{{ t('billing.admin.orders.view') }}</BaseButton>
          <BaseButton v-if="canForceApply(o)" size="sm" variant="primary" @click="forceApply(o)">
            <MsIcon name="play_arrow" size="xs" /> {{ t('billing.admin.orders.forceApply') }}
          </BaseButton>
        </div>
      </td>
    </template>

    <template #card="{ item: o }">
      <CardTap @tap="openMobile(o)">
        <div class="card-row--main">
          <span class="card-time-label mono">{{ formatTime(o.created_at) }}</span>
          <Badge :color="statusColor(o.status)" size="sm">
            {{ t(`billing.orders.status.${o.status}`) }}
          </Badge>
        </div>
        <div class="card-detail">
          <span class="card-plan">{{ o.plan_name }}</span>
          <span class="card-meta">
            <Badge :color="kindColor(o.kind)" size="sm">{{ kindLabel(o.kind) }}</Badge>
            <span class="mono">¥{{ fenToYuan(o.total_fen) }}</span>
          </span>
        </div>
        <div class="card-orderno"><code>{{ o.order_no }}</code></div>
      </CardTap>
    </template>
    </DataTable>
  </div>

  <ActionSheet v-model="mobileOpen" :title="mobileOrder?.order_no">
    <template v-if="mobileOrder" #info>
      <span>{{ mobileOrder.plan_name }}</span>
      <span class="mono">¥{{ fenToYuan(mobileOrder.total_fen) }}</span>
    </template>
    <template v-if="mobileOrder">
      <button @click="mobileOpen = false; emit('selectOrder', mobileOrder!.id)">
        <MsIcon name="visibility" size="sm" /> {{ t('billing.admin.orders.view') }}
      </button>
    </template>
  </ActionSheet>
</template>

<style scoped>
.action-group {
  display: flex;
  gap: var(--sp-2);
  align-items: center;
  flex-wrap: wrap;
}

/* ── Cells ── */
code {
  font-family: var(--font-mono, 'IBM Plex Mono', monospace);
  font-size: var(--text-xs);
  background: var(--bg-in);
  padding: 2px 6px;
  border-radius: var(--r-xs);
  color: var(--t1);
}

.mono {
  font-family: var(--font-mono, 'IBM Plex Mono', monospace);
}

.plan-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: block;
  max-width: 140px;
}

.cell-link {
  color: var(--ac);
  text-decoration: none;
}

.cell-link:hover {
  text-decoration: underline;
}

.cell-muted {
  color: var(--t3);
}

/* ── Mobile cards ── */
.card-row--main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-2);
}

.card-time-label {
  font-size: .78rem;
  color: var(--t3);
}

.card-orderno {
  margin-top: var(--sp-1);
}

.card-orderno code {
  font-size: var(--text-xs);
}

.card-detail {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-2);
  margin-top: var(--sp-2);
  font-size: .85rem;
  color: var(--t2);
}

.card-plan {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-meta {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-shrink: 0;
}

@media (max-width: 768px) {
  .toolbar-half {
    flex: 1;
    min-width: 0;
  }
}
</style>

<style>
/* ── OrdersTab column widths (non-scoped — must pierce DataTable slot boundary) ── */
.orders-table-wrap .dt-table {
  table-layout: fixed;
}

.orders-table-wrap .col-time     { width: 12%; white-space: nowrap; font-variant-numeric: tabular-nums; }
.orders-table-wrap .col-orderno  { width: 12%; }
.orders-table-wrap .col-kind     { width: 6%;  white-space: nowrap; }
.orders-table-wrap .col-plan     { width: 12%; }
.orders-table-wrap .col-amount   { width: 7%;  white-space: nowrap; }
.orders-table-wrap .col-status   { width: 8%;  white-space: nowrap; }
.orders-table-wrap .col-user     { width: 10%; }
.orders-table-wrap .col-server   { width: 11%; }
.orders-table-wrap .col-actions  { width: 22%; }

.orders-table-wrap .cell-deleted {
  color: var(--t3);
  font-size: var(--text-xs);
}

.orders-table-wrap .status-cell {
  display: inline-flex; align-items: center; gap: 4px;
}
.orders-table-wrap .status-warn-icon {
  color: var(--amber);
}

.orders-table-wrap .cell-link {
  color: var(--ac);
  text-decoration: none;
}
.orders-table-wrap .cell-link:hover { text-decoration: underline; }
.orders-table-wrap .cell-link code { color: var(--ac); }
</style>

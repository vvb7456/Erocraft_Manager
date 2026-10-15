<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useApiFetch } from '@/composables/useApiFetch'
import { useFormatDate } from '@/composables/useFormatDate'
import SectionToolbar from '@/components/ui/SectionToolbar.vue'
import FilterInput from '@/components/ui/FilterInput.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import DataTable from '@/components/ui/DataTable.vue'
import Badge from '@/components/ui/Badge.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import MobileFilterSheet from '@/components/ui/MobileFilterSheet.vue'
import CardTap from '@/components/ui/CardTap.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import SupportModal from '@/components/billing/SupportModal.vue'
import UserOrderDetailModal from '@/components/billing/UserOrderDetailModal.vue'

defineOptions({ name: 'UserOrdersListTab' })

interface OrderInvoice {
  id: number
  invoice_no: string
  status: string
  total_fen: number
  currency_code: string
  due_at: string | null
  paid_at: string | null
  gateway_code: string | null
  gateway_prepay_id: string | null
  transaction_id: string | null
  code_url: string | null
  pay_url: string | null
  pay_url_h5?: string | null
}

interface Order {
  id: number
  order_no: string
  plan_id: number
  plan_code: string
  plan_name: string
  kind: string
  period_count: number
  discount_pct: number
  total_fen: number
  total_days: number
  currency_code: string
  target_server_id: number | null
  status: string
  received_fen: number
  refunded_fen: number
  created_at: string
  updated_at: string
  applied_at: string | null
  closed_at: string | null
  cancelled_at: string | null
  invoice: OrderInvoice | null
}

const { t } = useI18n({ useScope: 'global' })
const router = useRouter()
const route = useRoute()
const { get } = useApiFetch()
const { formatDateTime: formatDate } = useFormatDate()

const orders = ref<Order[]>([])
const initialLoading = ref(true)
const searchTerm = ref('')
const statusFilter = ref<string>('all')
const page = ref(1)
const perPage = ref(20)
const supportOpen = ref(false)
const detailOrderId = computed(() => {
  const id = Number(route.query.order)
  return Number.isSafeInteger(id) && id > 0 ? id : null
})
const detailOpen = computed({
  get: () => detailOrderId.value !== null,
  set: value => {
    if (!value) void router.replace({ query: { ...route.query, order: undefined } })
  },
})

const TERMINAL_STATES = new Set(['applied', 'closed', 'cancelled', 'refunded'])
let pollTimer: ReturnType<typeof setInterval> | null = null

const hasActiveOrders = computed(() =>
  orders.value.some((o) => !TERMINAL_STATES.has(o.status))
)

function startPolling() {
  if (pollTimer || !hasActiveOrders.value) return
  pollTimer = setInterval(() => {
    if (!hasActiveOrders.value) {
      stopPolling()
      return
    }
    loadOrders(true)
  }, 5000)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function loadOrders(silent = false) {
  const data = await get<Order[]>('/api/user/orders', { silent })
  if (data) {
    orders.value = data
    if (hasActiveOrders.value) startPolling()
    else stopPolling()
  }
  initialLoading.value = false
}

const statusOptions = computed(() => [
  { value: 'all', label: t('billing.orders.filter.all') },
  { value: 'pending', label: t('billing.orders.filter.pending') },
  { value: 'applied', label: t('billing.orders.filter.applied') },
  { value: 'closed', label: t('billing.orders.filter.closed') },
  { value: 'refunded', label: t('billing.orders.filter.refunded') },
])

// ── Mobile filter sheet ──
const mobileFilterOpen = ref(false)
const filterGroups = computed(() => [
  {
    key: 'status',
    label: t('billing.orders.filter.label'),
    modelValue: statusFilter.value,
    options: statusOptions.value,
  },
])
function onMobileFilter(groupKey: string, value: string | number | boolean) {
  if (groupKey === 'status') {
    statusFilter.value = String(value)
    page.value = 1
  }
}

const filtered = computed(() => {
  let list = orders.value
  if (statusFilter.value !== 'all') {
    list = list.filter((o) => statusBucket(o.status) === statusFilter.value)
  }
  const q = searchTerm.value.trim().toLowerCase()
  if (q) {
    list = list.filter(
      (o) =>
        o.order_no.toLowerCase().includes(q) ||
        o.plan_name.toLowerCase().includes(q) ||
        (o.invoice?.invoice_no.toLowerCase().includes(q) ?? false),
    )
  }
  return list
})

function statusBucket(status: string): string {
  if (
    status === 'pending' ||
    status === 'processing' ||
    status === 'apply_failed' ||
    status === 'manual_review' ||
    status === 'refunding'
  ) return 'pending'
  if (status === 'closed' || status === 'cancelled') return 'closed'
  if (status === 'refunded') return 'refunded'
  if (status === 'applied') return 'applied'
  return status
}

const totalPages = computed(() => Math.max(1, Math.ceil(filtered.value.length / perPage.value)))
const paginated = computed(() => {
  const start = (page.value - 1) * perPage.value
  return filtered.value.slice(start, start + perPage.value)
})

function fenToYuan(fen: number): string {
  return (fen / 100).toFixed(2)
}

function statusColor(status: string): string {
  switch (status) {
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

function statusLabel(status: string): string {
  return t(`billing.orders.status.${status}`)
}

function goDetail(o: Order) {
  void router.push({ query: { ...route.query, order: String(o.id) } })
}

onMounted(() => {
  loadOrders()
})

onBeforeUnmount(() => {
  stopPolling()
})
</script>

<template>
  <SectionToolbar>
    <template #start>
      <div class="tb-search-row">
        <FilterInput
          v-model="searchTerm"
          :placeholder="t('billing.orders.searchPlaceholder')"
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
      <span class="support-hint tb-help">
        {{ t('billing.orders.supportHint') }}
        <a href="#" class="support-link" @click.prevent="supportOpen = true">
          {{ t('billing.orders.supportLink') }}
        </a>
      </span>
    </template>
    <template #end>
      <div class="tb-select-group tb-desktop-only">
        <BaseSelect
          v-model="statusFilter"
          :options="statusOptions"
          :prefix="t('billing.orders.filter.label') + ': '"
          size="sm"
          fit
        />
      </div>
    </template>
  </SectionToolbar>

  <MobileFilterSheet
    v-model:open="mobileFilterOpen"
    :sort-columns="[]"
    :sort-by="''"
    :sort-order="'asc'"
    :filters="filterGroups"
    @update:filter="onMobileFilter"
  />

  <DataTable
    :items="paginated"
    :page="page"
    :total-pages="totalPages"
    :per-page="perPage"
    :per-page-label="t('billing.orders.perPage')"
    :loading="initialLoading"
    empty-icon="receipt_long"
    :empty-text="t('billing.orders.empty')"
    row-key="id"
    @update:page="page = $event"
    @update:per-page="perPage = $event; page = 1"
  >
    <template #header>
      <th class="col-no">{{ t('billing.orders.table.orderNo') }}</th>
      <th class="col-plan">{{ t('billing.orders.table.plan') }}</th>
      <th class="col-period">{{ t('billing.orders.table.period') }}</th>
      <th class="col-amount">{{ t('billing.orders.table.amount') }}</th>
      <th class="col-status">{{ t('billing.orders.table.status') }}</th>
      <th class="col-time">{{ t('billing.orders.table.createdAt') }}</th>
      <th class="col-actions">{{ t('billing.orders.table.actions') }}</th>
    </template>

    <template #row="{ item: o }">
      <td class="col-no mono">
        <a class="order-link" href="#" @click.prevent="goDetail(o)">{{ o.order_no }}</a>
      </td>
      <td class="col-plan">{{ o.plan_name }}</td>
      <td class="col-period">{{ t('billing.orders.periodValue', { count: o.period_count, days: o.total_days }) }}</td>
      <td class="col-amount mono">¥{{ fenToYuan(o.total_fen) }}</td>
      <td class="col-status">
        <Badge :color="statusColor(o.status)">{{ statusLabel(o.status) }}</Badge>
      </td>
      <td class="col-time mono">{{ formatDate(o.created_at) }}</td>
      <td class="col-actions">
        <BaseButton size="sm" @click="goDetail(o)">
          {{ t('billing.orders.viewDetail') }}
        </BaseButton>
      </td>
    </template>

    <template #card="{ item: o }">
      <CardTap @tap="goDetail(o)">
        <div class="card-row--main">
          <div class="card-title">
            <span class="card-plan-name">{{ o.plan_name }}</span>
            <span class="card-order-no mono">{{ o.order_no }}</span>
          </div>
          <Badge :color="statusColor(o.status)">{{ statusLabel(o.status) }}</Badge>
        </div>
        <div class="card-meta">
          <span class="card-amount">¥{{ fenToYuan(o.total_fen) }}</span>
          <span class="card-period">{{ t('billing.orders.periodValue', { count: o.period_count, days: o.total_days }) }}</span>
        </div>
        <div class="card-time mono">{{ formatDate(o.created_at) }}</div>
      </CardTap>
    </template>
  </DataTable>

  <UserOrderDetailModal v-model="detailOpen" :order-id="detailOrderId" @updated="loadOrders(true)" @contact="supportOpen = true" />
  <SupportModal v-model="supportOpen" />
</template>

<style scoped>
.order-link {
  color: var(--ac);
  text-decoration: none;
}

.support-hint {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1);
  font-size: var(--text-sm);
  color: var(--t2);
  margin-left: var(--sp-2);
}

.support-link {
  color: var(--ac);
  text-decoration: none;
  cursor: pointer;
}

.support-link:hover { text-decoration: underline; }
.order-link:hover   { text-decoration: underline; }

.mono {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
}

.card-row--main {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--sp-2);
}

.card-title {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.card-plan-name {
  font-weight: 600;
  color: var(--t1);
  font-size: var(--text-md);
}

.card-order-no {
  color: var(--t3);
  font-size: var(--text-xs);
}

.card-meta {
  display: flex;
  align-items: baseline;
  gap: var(--sp-3);
  margin-top: var(--sp-2);
}

.card-amount {
  font-size: 1.15rem;
  font-weight: 700;
  color: var(--ac);
  font-family: var(--font-mono);
}

.card-period {
  font-size: var(--text-sm);
  color: var(--t2);
}

.card-time {
  margin-top: var(--sp-1);
  color: var(--t3);
  font-size: var(--text-xs);
}
</style>

<script setup lang="ts">
/**
 * UserOrdersPage — `/orders`
 *
 * User-side order history. Supports text search, status filter, cancel and
 * pay actions. Layout mirrors UserServersPage: PageHeader → StatCard summary
 * row → SectionToolbar (FilterInput + ChipSelect) → DataTable with row + card
 * slots → ActionSheet for mobile.
 */
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useApiFetch } from '@/composables/useApiFetch'
import { useConfirm } from '@/composables/useConfirm'
import { useToast } from '@/composables/useToast'
import PageHeader from '@/components/layout/PageHeader.vue'
import SectionToolbar from '@/components/ui/SectionToolbar.vue'
import FilterInput from '@/components/ui/FilterInput.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import DataTable from '@/components/ui/DataTable.vue'
import Badge from '@/components/ui/Badge.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import ActionSheet from '@/components/ui/ActionSheet.vue'
import CardTap from '@/components/ui/CardTap.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import SupportModal from '@/components/billing/SupportModal.vue'

defineOptions({ name: 'UserOrdersPage' })

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
const { get, del } = useApiFetch()
const { confirm } = useConfirm()
const { toast } = useToast()

const orders = ref<Order[]>([])
const initialLoading = ref(true)
const searchTerm = ref('')
const statusFilter = ref<string>('all')
const page = ref(1)
const perPage = ref(20)
const cancellingId = ref<number | null>(null)
const supportOpen = ref(false)

// ── Polling: refresh while there are non-terminal orders ──
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

// ── Data ──
async function loadOrders(silent = false) {
  const data = await get<Order[]>('/api/user/orders', { silent })
  if (data) {
    orders.value = data
    if (hasActiveOrders.value) startPolling()
    else stopPolling()
  }
  initialLoading.value = false
}

// ── Status filter options (BaseSelect) ──
const statusOptions = computed(() => [
  { value: 'all', label: t('billing.orders.filter.all') },
  { value: 'pending', label: t('billing.orders.filter.pending') },
  { value: 'applied', label: t('billing.orders.filter.applied') },
  { value: 'closed', label: t('billing.orders.filter.closed') },
  { value: 'refunded', label: t('billing.orders.filter.refunded') },
])

// ── Filtered list ──
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
  if (status === 'pending' || status === 'processing') return 'pending'
  if (status === 'closed' || status === 'cancelled') return 'closed'
  if (status === 'refunded' || status === 'refunding' || status === 'manual_review') return 'refunded'
  if (status === 'applied') return 'applied'
  return status
}

const totalPages = computed(() => Math.max(1, Math.ceil(filtered.value.length / perPage.value)))
const paginated = computed(() => {
  const start = (page.value - 1) * perPage.value
  return filtered.value.slice(start, start + perPage.value)
})

// ── Display helpers ──
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

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '—'
  return d.toLocaleString(undefined, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function canCancel(o: Order): boolean {
  return o.status === 'pending'
}

function canPay(o: Order): boolean {
  return o.status === 'pending'
}

// ── Actions ──
function goPay(o: Order) {
  router.push({ path: `/pay/${o.id}` })
}

async function doCancel(o: Order) {
  const ok = await confirm({
    title: t('billing.orders.cancelConfirmTitle'),
    message: t('billing.orders.cancelConfirmMessage', { orderNo: o.order_no }),
    confirmText: t('billing.orders.cancelConfirm'),
    variant: 'danger',
  })
  if (!ok) return
  cancellingId.value = o.id
  const res = await del<Order>(`/api/user/orders/${o.id}`)
  cancellingId.value = null
  if (res) {
    toast(t('billing.orders.cancelOk'), 'success')
    await loadOrders(true)
  }
}

// ── Mobile action sheet ──
const mobileActionOpen = ref(false)
const mobileActionOrder = ref<Order | null>(null)

function openMobileAction(o: Order) {
  mobileActionOrder.value = o
  mobileActionOpen.value = true
}

function goDetail(o: Order) {
  router.push({ path: `/orders/${o.id}` })
}

onMounted(() => {
  loadOrders()
})

onBeforeUnmount(() => {
  stopPolling()
})
</script>

<template>
  <PageHeader icon="receipt_long" :title="t('billing.orders.pageTitle')" />

  <div class="page-body">
    <!-- Toolbar -->
    <SectionToolbar>
      <template #start>
        <FilterInput
          v-model="searchTerm"
          :placeholder="t('billing.orders.searchPlaceholder')"
          class="filter-input"
        />
        <span class="support-hint">
          {{ t('billing.orders.supportHint') }}
          <a href="#" class="support-link" @click.prevent="supportOpen = true">
            {{ t('billing.orders.supportLink') }}
          </a>
        </span>
      </template>
      <template #end>
        <BaseSelect
          v-model="statusFilter"
          :options="statusOptions"
          :prefix="t('billing.orders.filter.label') + ': '"
          size="sm"
          fit
        />
      </template>
    </SectionToolbar>

    <!-- Table / cards -->
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
          <div class="action-group">
            <BaseButton v-if="canPay(o)" size="sm" variant="primary" @click="goPay(o)">
              <MsIcon name="paid" size="xs" /> {{ t('billing.orders.payNow') }}
            </BaseButton>
            <BaseButton
              v-if="canCancel(o)"
              size="sm"
              variant="danger"
              :loading="cancellingId === o.id"
              @click="doCancel(o)"
            >
              <MsIcon name="cancel" size="xs" /> {{ t('billing.orders.cancel') }}
            </BaseButton>
            <BaseButton v-if="!canPay(o) && !canCancel(o)" size="sm" @click="goDetail(o)">
              {{ t('billing.orders.viewDetail') }}
            </BaseButton>
          </div>
        </td>
      </template>

      <!-- Mobile card -->
      <template #card="{ item: o }">
        <CardTap @tap="openMobileAction(o)">
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

    <!-- Mobile action sheet -->
    <ActionSheet v-model="mobileActionOpen" :title="mobileActionOrder?.order_no">
      <template v-if="mobileActionOrder" #info>
        <Badge :color="statusColor(mobileActionOrder.status)">{{ statusLabel(mobileActionOrder.status) }}</Badge>
        · ¥{{ fenToYuan(mobileActionOrder.total_fen) }}
      </template>
      <template v-if="mobileActionOrder">
        <button @click="mobileActionOpen = false; goDetail(mobileActionOrder!)">
          <MsIcon name="receipt_long" size="sm" /> {{ t('billing.orders.viewDetail') }}
        </button>
        <button v-if="canPay(mobileActionOrder)" @click="mobileActionOpen = false; goPay(mobileActionOrder!)">
          <MsIcon name="paid" size="sm" /> {{ t('billing.orders.payNow') }}
        </button>
        <button
          v-if="canCancel(mobileActionOrder)"
          :disabled="cancellingId === mobileActionOrder.id"
          @click="mobileActionOpen = false; doCancel(mobileActionOrder!)"
        >
          <MsIcon name="cancel" size="sm" /> {{ t('billing.orders.cancel') }}
        </button>
      </template>
    </ActionSheet>

    <SupportModal v-model="supportOpen" />
  </div>
</template>

<style scoped>
.page-body {
  display: flex;
  flex-direction: column;
}

.filter-input {
  flex: 1;
  max-width: 280px;
}

.action-group {
  display: flex;
  gap: var(--sp-2);
  flex-wrap: wrap;
}

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

.support-link:hover {
  text-decoration: underline;
}

.order-link:hover {
  text-decoration: underline;
}

.mono {
  font-family: 'IBM Plex Mono', monospace;
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
  font-family: 'IBM Plex Mono', monospace;
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

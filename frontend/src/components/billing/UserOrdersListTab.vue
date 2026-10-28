<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useApiFetch } from '@/composables/useApiFetch'
import { useConfirm } from '@/composables/useConfirm'
import { useToast } from '@/composables/useToast'
import { useFormatDate } from '@/composables/useFormatDate'
import SectionToolbar from '@/components/ui/SectionToolbar.vue'
import FilterInput from '@/components/ui/FilterInput.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import DataTable from '@/components/ui/DataTable.vue'
import Badge from '@/components/ui/Badge.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import ActionSheet from '@/components/ui/ActionSheet.vue'
import MobileFilterSheet from '@/components/ui/MobileFilterSheet.vue'
import CardTap from '@/components/ui/CardTap.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import SupportModal from '@/components/billing/SupportModal.vue'
import UserOrderDetailModal from '@/components/billing/UserOrderDetailModal.vue'
import type { UserOrder } from '@/types/billing'

defineOptions({ name: 'UserOrdersListTab' })

const { t } = useI18n({ useScope: 'global' })
const router = useRouter()
const route = useRoute()
const { get, post, del, handleError } = useApiFetch()
const { confirm } = useConfirm()
const { toast } = useToast()
const { formatDateTime: formatDate } = useFormatDate()

const orders = ref<UserOrder[]>([])
const initialLoading = ref(true)
const searchTerm = ref('')
const statusFilter = ref<string>('all')
const page = ref(1)
const perPage = ref(20)
const supportOpen = ref(false)
const payingId = ref<number | null>(null)
const cancellingId = ref<number | null>(null)
const busy = computed(() => payingId.value !== null || cancellingId.value !== null)
const mobileActionOpen = ref(false)
const mobileActionOrderId = ref<number | null>(null)
const mobileActionOrder = computed(() => orders.value.find(order => order.id === mobileActionOrderId.value))
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
const detailSummary = computed(() => orders.value.find(order => order.id === detailOrderId.value) ?? null)

const TERMINAL_STATES = new Set(['applied', 'closed', 'cancelled', 'refunded'])
let pollTimer: ReturnType<typeof setInterval> | null = null
let loadRevision = 0

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
    void loadOrders(true).catch(handleError)
  }, 5000)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function loadOrders(silent = false) {
  const revision = ++loadRevision
  const data = await get<UserOrder[]>('/api/user/orders', { silent }).finally(() => { initialLoading.value = false })
  if (revision === loadRevision) {
    orders.value = data
    if (hasActiveOrders.value) startPolling()
    else stopPolling()
  }
}

function updateOrder(order: UserOrder) {
  loadRevision++
  orders.value = orders.value.map(row => row.id === order.id ? order : row)
  if (hasActiveOrders.value) startPolling()
  else stopPolling()
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
  if (status === 'closed' || status === 'cancelled') return 'closed'
  if (status === 'refunding' || status === 'refunded') return 'refunded'
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

function goDetail(o: UserOrder) {
  void router.push({ query: { ...route.query, order: String(o.id) } })
}

function openMobileAction(o: UserOrder) {
  mobileActionOrderId.value = o.id
  mobileActionOpen.value = true
}

async function goPay(o: UserOrder) {
  if (o.status !== 'pending' || busy.value) return
  payingId.value = o.id
  try {
    const payment = await post<{ checkout_url: string }>(`/api/user/orders/${o.id}/payments`, {})
    window.location.assign(payment.checkout_url)
  } catch (error) {
    handleError(error)
    await loadOrders(true).catch(handleError)
  } finally { payingId.value = null }
}

async function doCancel(o: UserOrder) {
  if (o.status !== 'pending' || busy.value) return
  const ok = await confirm({
    title: t('billing.orderDetail.actions.cancelConfirmTitle'),
    message: t('billing.orderDetail.actions.cancelConfirmMessage'),
    confirmText: t('billing.orderDetail.actions.cancelConfirmBtn'),
    variant: 'danger',
  })
  if (!ok) return
  cancellingId.value = o.id
  try {
    const result = await del<UserOrder>(`/api/user/orders/${o.id}`)
    updateOrder(result)
    if (result.status === 'cancelled') toast(t('billing.orderDetail.actions.cancelOk'), 'success')
  } catch (error) {
    handleError(error)
    await loadOrders(true).catch(handleError)
  } finally { cancellingId.value = null }
}

onMounted(() => {
  loadOrders()
})

onBeforeUnmount(() => {
  loadRevision++
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
        <div class="action-group">
          <template v-if="o.status === 'pending'">
            <BaseButton size="sm" variant="primary" :loading="payingId === o.id" :disabled="busy" @click="goPay(o)">
              <MsIcon name="paid" size="xs" /> {{ t('billing.orderDetail.actions.pay') }}
            </BaseButton>
            <BaseButton size="sm" variant="danger" :loading="cancellingId === o.id" :disabled="busy" @click="doCancel(o)">
              <MsIcon name="cancel" size="xs" /> {{ t('billing.orderDetail.actions.cancel') }}
            </BaseButton>
          </template>
          <BaseButton v-else size="sm" @click="goDetail(o)">
            {{ t('billing.orders.viewDetail') }}
          </BaseButton>
        </div>
      </td>
    </template>

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

  <ActionSheet v-model="mobileActionOpen" :title="mobileActionOrder?.order_no">
    <template v-if="mobileActionOrder" #info>
      <Badge :color="statusColor(mobileActionOrder.status)">{{ statusLabel(mobileActionOrder.status) }}</Badge>
      · ¥{{ fenToYuan(mobileActionOrder.total_fen) }}
    </template>
    <template v-if="mobileActionOrder">
      <button @click="mobileActionOpen = false; goDetail(mobileActionOrder)">
        <MsIcon name="receipt_long" size="sm" /> {{ t('billing.orders.viewDetail') }}
      </button>
      <template v-if="mobileActionOrder.status === 'pending'">
        <button :disabled="busy" @click="mobileActionOpen = false; goPay(mobileActionOrder)">
          <MsIcon name="paid" size="sm" /> {{ t('billing.orderDetail.actions.pay') }}
        </button>
        <button :disabled="busy" @click="mobileActionOpen = false; doCancel(mobileActionOrder)">
          <MsIcon name="cancel" size="sm" /> {{ t('billing.orderDetail.actions.cancel') }}
        </button>
      </template>
    </template>
  </ActionSheet>

  <UserOrderDetailModal v-model="detailOpen" :order-id="detailOrderId" :summary="detailSummary" @contact="supportOpen = true" />
  <SupportModal v-model="supportOpen" />
</template>

<style scoped>
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

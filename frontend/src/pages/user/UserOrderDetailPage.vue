<script setup lang="ts">
/**
 * UserOrderDetailPage — `/orders/:id`
 *
 * 单一“账单卡片”视图。设计文档：docs/BILLING_FRONTEND_DESIGN_OrderDetailPage.md
 *
 * 仅显示用户应见字段：套餐 / 周期 / 金额 / 网关大类 / 服务器名（如已开通）。
 * 严格隐藏所有内部 ID（plan_id / server_id / invoice_id / transaction_id /
 * gateway_prepay_id 等）。
 *
 * PageHeader 仅含 title，遵守项目硬规则。
 */
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { useAppStore } from '@/stores/app'
import { useApiFetch } from '@/composables/useApiFetch'
import { useConfirm } from '@/composables/useConfirm'
import { useToast } from '@/composables/useToast'
import { useFormatDate } from '@/composables/useFormatDate'
import PageHeader from '@/components/layout/PageHeader.vue'
import BaseCard from '@/components/ui/BaseCard.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import Badge from '@/components/ui/Badge.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import LoadingCenter from '@/components/ui/LoadingCenter.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import SupportModal from '@/components/billing/SupportModal.vue'

defineOptions({ name: 'UserOrderDetailPage' })

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
  plan_name: string
  kind: string
  period_count: number
  discount_pct: number
  total_fen: number
  total_days: number
  currency_code: string
  target_server_id: number | null
  target_server_name: string | null
  status: string
  received_fen: number
  refunded_fen: number
  created_at: string
  applied_at: string | null
  closed_at: string | null
  cancelled_at: string | null
  invoice: OrderInvoice | null
  coupon_id: number | null
  coupon_code: string | null
  coupon_discount_fen: number | null
}

const { t } = useI18n({ useScope: 'global' })
const route = useRoute()
const router = useRouter()
const { get, del } = useApiFetch()
const { confirm } = useConfirm()
const { toast } = useToast()
const appStore = useAppStore()
const { displayName } = storeToRefs(appStore)
const { formatDate } = useFormatDate()

const order = ref<Order | null>(null)
const loading = ref(true)
const loadFailed = ref(false)
const cancelling = ref(false)
const downloading = ref(false)
const supportOpen = ref(false)

const orderId = computed(() => Number(route.params.id))

const headerBreadcrumbs = computed(() => [
  { label: t('billing.orders.pageTitle'), to: { name: 'user-orders' } },
  { label: order.value?.order_no || t('billing.orderDetail.pageTitle') },
])

async function loadOrder(silent = false) {
  if (!silent) loading.value = true
  loadFailed.value = false
  const data = await get<Order>(`/api/user/orders/${orderId.value}`, { silent })
  if (data) {
    order.value = data
  } else if (!silent) {
    loadFailed.value = true
  }
  loading.value = false
}

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

function gatewayLabel(code: string | null): string {
  if (!code) return t('billing.orderDetail.gateway.unknown')
  const lc = code.toLowerCase()
  if (lc.includes('alipay') || lc.includes('hupijiao')) return t('billing.orderDetail.gateway.alipay')
  if (lc.includes('wx') || lc.includes('wechat')) return t('billing.orderDetail.gateway.wxpay')
  return code
}

function kindLabel(kind: string): string {
  if (kind === 'renew') return t('billing.orderDetail.kindRenew')
  if (kind === 'upgrade') return t('billing.orderDetail.kindUpgrade')
  if (kind === 'convert') return t('billing.orderDetail.kindConvert')
  return t('billing.orderDetail.kindNew')
}

// 折扣前小计：total = subtotal * (1 - discount/100)  →  subtotal = total / (1 - discount/100)
const subtotalFen = computed(() => {
  const o = order.value
  if (!o) return 0
  const pct = Number(o.discount_pct) || 0
  if (pct <= 0) return o.total_fen
  const denom = 1 - pct / 100
  if (denom <= 0) return o.total_fen
  return Math.round(o.total_fen / denom)
})

const discountAmountFen = computed(() => {
  const o = order.value
  if (!o) return 0
  return Math.max(0, subtotalFen.value - o.total_fen)
})

const unitPriceFen = computed(() => {
  const o = order.value
  if (!o) return 0
  if (o.period_count <= 0) return subtotalFen.value
  return Math.round(subtotalFen.value / o.period_count)
})

const showReceived = computed(() => {
  const o = order.value
  if (!o) return false
  return o.received_fen > 0 || !!o.invoice?.paid_at
})

const showRefunded = computed(() => (order.value?.refunded_fen ?? 0) > 0)

const showLinkedServer = computed(() => {
  const o = order.value
  return !!o && o.status === 'applied' && !!o.target_server_name
})

const canPay = computed(() => order.value?.status === 'pending')
const canCancel = computed(() => order.value?.status === 'pending')

// ── Actions ──
function goPay() {
  if (!order.value) return
  router.push({ path: `/pay/${order.value.id}` })
}

function goServer() {
  const o = order.value
  if (!o?.target_server_id) return
  router.push({ path: `/servers/${o.target_server_id}` })
}

async function doCancel() {
  if (!order.value) return
  const ok = await confirm({
    title: t('billing.orderDetail.actions.cancelConfirmTitle'),
    message: t('billing.orderDetail.actions.cancelConfirmMessage'),
    confirmText: t('billing.orderDetail.actions.cancelConfirmBtn'),
    variant: 'danger',
  })
  if (!ok) return
  cancelling.value = true
  const res = await del<Order>(`/api/user/orders/${order.value.id}`)
  cancelling.value = false
  if (res) {
    toast(t('billing.orderDetail.actions.cancelOk'), 'success')
    order.value = res
  }
}

function doPrint() {
  window.print()
}

async function doDownloadPdf() {
  if (!order.value || downloading.value) return
  downloading.value = true
  const card = document.querySelector('.bill-card') as HTMLElement | null
  if (!card) {
    downloading.value = false
    return
  }
  card.classList.add('bill-card--print-mode')
  try {
    const mod = await import('html2pdf.js')
    const html2pdf = (mod as any).default ?? mod
    await html2pdf()
      .set({
        margin: 10,
        filename: `order-${order.value.order_no}.pdf`,
        image: { type: 'jpeg', quality: 0.95 },
        html2canvas: { scale: 2, backgroundColor: '#ffffff', useCORS: true },
        jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' },
      })
      .from(card)
      .save()
  } finally {
    card.classList.remove('bill-card--print-mode')
    downloading.value = false
  }
}

onMounted(loadOrder)
</script>

<template>
  <PageHeader icon="receipt_long" :title="t('billing.orderDetail.pageTitle')" :breadcrumbs="headerBreadcrumbs" />

  <div class="page-body">
    <LoadingCenter v-if="loading" />

    <EmptyState
      v-else-if="loadFailed || !order"
      icon="error_outline"
      :text="t('billing.orderDetail.loadFailed')"
    >
      <BaseButton variant="primary" size="sm" @click="loadOrder()">
        {{ t('billing.orderDetail.retry') }}
      </BaseButton>
    </EmptyState>

    <div v-else class="bill-wrap">
      <BaseCard class="bill-card" variant="bg2">
        <!-- Header -->
        <header class="bill-head">
          <div class="bill-title">
            {{ t('billing.orderDetail.title') }}<span class="bill-title-id"> #{{ order.id }}</span>
          </div>
          <div class="bill-meta">
            <div class="bill-meta-row">
              <span class="bill-meta-label">{{ t('billing.orderDetail.payee') }}</span>
              <span class="bill-meta-value">{{ displayName }}</span>
            </div>
            <div class="bill-meta-row">
              <span class="bill-meta-label">{{ t('billing.orderDetail.orderNo') }}</span>
              <span class="bill-meta-value mono">{{ order.order_no }}</span>
            </div>
            <div class="bill-meta-row">
              <span class="bill-meta-label">{{ t('billing.orderDetail.createdDate') }}</span>
              <span class="bill-meta-value">{{ formatDate(order.created_at) }}</span>
            </div>
            <div v-if="order.invoice?.paid_at" class="bill-meta-row">
              <span class="bill-meta-label">{{ t('billing.orderDetail.paidDate') }}</span>
              <span class="bill-meta-value">{{ formatDate(order.invoice.paid_at) }}</span>
            </div>
          </div>
          <div class="bill-status">
            <Badge :color="statusColor(order.status)">
              {{ t(`billing.orderDetail.status.${order.status}`) }}
            </Badge>
          </div>
        </header>

        <!-- Items table -->
        <table class="bill-table">
          <thead>
            <tr>
              <th class="col-item">{{ t('billing.orderDetail.table.item') }}</th>
              <th class="col-qty">{{ t('billing.orderDetail.table.qty') }}</th>
              <th class="col-price">{{ t('billing.orderDetail.table.unitPrice') }}</th>
              <th class="col-sub">{{ t('billing.orderDetail.table.subtotal') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td class="col-item">
                <div class="item-name">{{ order.plan_name }}（{{ kindLabel(order.kind) }}）</div>
                <div class="item-desc">
                  <template v-if="order.kind === 'upgrade'">{{ kindLabel('upgrade') }}</template>
                  <template v-else>{{ t('billing.orderDetail.table.lineDesc', { count: order.period_count, days: order.total_days }) }}</template>
                </div>
              </td>
              <td class="col-qty">{{ order.period_count }}</td>
              <td class="col-price mono">¥{{ fenToYuan(unitPriceFen) }}</td>
              <td class="col-sub mono">¥{{ fenToYuan(subtotalFen) }}</td>
            </tr>
          </tbody>
        </table>

        <!-- Totals -->
        <div class="bill-totals">
          <div v-if="discountAmountFen > 0" class="bill-totals-row">
            <span class="t-label">
              {{ t('billing.orderDetail.totals.discount') }}（-{{ Number(order.discount_pct).toFixed(0) }}%）
            </span>
            <span class="t-value mono">−¥{{ fenToYuan(discountAmountFen) }}</span>
          </div>
          <div v-if="order.coupon_id && order.coupon_discount_fen" class="bill-totals-row">
            <span class="t-label">
              {{ t('billing.coupons.applyHint') }}
              <span v-if="order.coupon_code" class="t-label-sub mono">({{ order.coupon_code }})</span>
            </span>
            <span class="t-value mono">−¥{{ fenToYuan(order.coupon_discount_fen) }}</span>
          </div>
          <div class="bill-totals-row bill-totals-row--strong">
            <span class="t-label">{{ t('billing.orderDetail.totals.amount') }}</span>
            <span class="t-value mono">¥{{ fenToYuan(order.total_fen) }}</span>
          </div>
          <div v-if="showReceived" class="bill-totals-row">
            <span class="t-label">{{ t('billing.orderDetail.totals.received') }}</span>
            <span class="t-value mono">¥{{ fenToYuan(order.received_fen) }}</span>
          </div>
          <div v-if="showRefunded" class="bill-totals-row">
            <span class="t-label">{{ t('billing.orderDetail.totals.refunded') }}</span>
            <span class="t-value mono">¥{{ fenToYuan(order.refunded_fen) }}</span>
          </div>
        </div>

        <!-- Meta lines -->
        <div v-if="order.invoice?.paid_at || showLinkedServer" class="bill-meta-extra">
          <div v-if="order.invoice?.paid_at" class="bill-meta-extra-row">
            <span class="ex-label">{{ t('billing.orderDetail.meta.payMethod') }}：</span>
            <span class="ex-value">{{ gatewayLabel(order.invoice.gateway_code) }}</span>
          </div>
          <div v-if="showLinkedServer" class="bill-meta-extra-row">
            <span class="ex-label">{{ t('billing.orderDetail.meta.linkedServer') }}：</span>
            <a class="ex-link" href="#" @click.prevent="goServer">
              {{ order.target_server_name }}
              <MsIcon name="arrow_forward" size="xs" />
            </a>
          </div>
        </div>

        <!-- Actions footer -->
        <div class="bill-actions">
          <BaseButton size="sm" @click="doDownloadPdf" :loading="downloading">
            <MsIcon name="download" size="xs" /> {{ t('billing.orderDetail.actions.downloadPdf') }}
          </BaseButton>
          <BaseButton size="sm" @click="doPrint">
            <MsIcon name="print" size="xs" /> {{ t('billing.orderDetail.actions.print') }}
          </BaseButton>
          <BaseButton v-if="canPay" size="sm" variant="primary" @click="goPay">
            <MsIcon name="paid" size="xs" /> {{ t('billing.orderDetail.actions.pay') }}
          </BaseButton>
          <BaseButton v-if="canCancel" size="sm" variant="danger" :loading="cancelling" @click="doCancel">
            <MsIcon name="cancel" size="xs" /> {{ t('billing.orderDetail.actions.cancel') }}
          </BaseButton>
          <BaseButton size="sm" @click="supportOpen = true">
            <MsIcon name="support_agent" size="xs" /> {{ t('billing.orderDetail.actions.contactSupport') }}
          </BaseButton>
        </div>
      </BaseCard>
    </div>

    <SupportModal v-model="supportOpen" />
  </div>
</template>

<style scoped>
.bill-wrap {
  max-width: 760px;
  margin: 0 auto;
}

.bill-card {
  position: relative;
  padding: var(--sp-6) var(--sp-7);
}

/* Header */
.bill-head {
  position: relative;
  display: grid;
  grid-template-columns: 1fr auto;
  grid-template-areas:
    "title status"
    "meta  meta";
  gap: var(--sp-3) var(--sp-5);
  padding-bottom: var(--sp-5);
  border-bottom: 1px solid var(--bd);
  margin-bottom: var(--sp-5);
}

.bill-title {
  grid-area: title;
  font-size: 1.8rem;
  font-weight: 700;
  letter-spacing: 6px;
  color: var(--t1);
  align-self: center;
}

.bill-title-id {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 1rem;
  font-weight: 500;
  letter-spacing: 0;
  color: var(--t3);
  margin-left: var(--sp-2);
}

.bill-meta {
  grid-area: meta;
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
  align-items: flex-end;
  font-size: var(--text-sm);
}

.bill-meta-row {
  display: flex;
  gap: var(--sp-3);
}

.bill-meta-label {
  color: var(--t3);
}

.bill-meta-value {
  color: var(--t1);
  min-width: 0;
}

.bill-status {
  grid-area: status;
  align-self: start;
  justify-self: end;
}

.bill-status :deep(.badge) {
  font-size: var(--text-base);
  padding: var(--sp-1) var(--sp-3);
}

/* Items table */
.bill-table {
  width: 100%;
  border-collapse: collapse;
  margin-bottom: var(--sp-4);
}

.bill-table thead th {
  text-align: left;
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--t3);
  padding: var(--sp-2) var(--sp-2);
  border-bottom: 1px solid var(--bd);
}

.bill-table .col-qty,
.bill-table .col-price,
.bill-table .col-sub {
  text-align: right;
  width: 1%;
  white-space: nowrap;
}

.bill-table tbody td {
  padding: var(--sp-3) var(--sp-2);
  border-bottom: 1px solid var(--bd);
  vertical-align: top;
  color: var(--t1);
}

.item-name {
  font-weight: 500;
  margin-bottom: var(--sp-1);
}

.item-desc {
  color: var(--t3);
  font-size: var(--text-xs);
}

/* Totals */
.bill-totals {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
  align-items: flex-end;
  padding: var(--sp-3) var(--sp-2) var(--sp-4);
  border-bottom: 1px solid var(--bd);
  margin-bottom: var(--sp-4);
}

.bill-totals-row {
  display: flex;
  gap: var(--sp-5);
  font-size: var(--text-sm);
  color: var(--t2);
}

.bill-totals-row .t-value {
  min-width: 100px;
  text-align: right;
  color: var(--t1);
}

.bill-totals-row--strong {
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--t1);
}

.bill-totals-row--strong .t-label,
.bill-totals-row--strong .t-value {
  color: var(--t1);
}

.t-label-sub {
  color: var(--t3);
  font-size: .85em;
  margin-left: var(--sp-1);
}

/* Meta extra */
.bill-meta-extra {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  padding-bottom: var(--sp-4);
  border-bottom: 1px solid var(--bd);
  margin-bottom: var(--sp-4);
  font-size: var(--text-sm);
}

.ex-label {
  color: var(--t3);
}

.ex-value {
  color: var(--t1);
}

.ex-link {
  color: var(--ac);
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1);
}

.ex-link:hover {
  text-decoration: underline;
}

/* Actions */
.bill-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
  justify-content: flex-end;
}

.mono {
  font-family: 'IBM Plex Mono', monospace;
}

/* ── Print mode (used by both window.print() and html2pdf) ── */
.bill-card--print-mode,
.bill-card--print-mode :deep(*) {
  background: #ffffff !important;
  color: #111 !important;
  border-color: #ddd !important;
  box-shadow: none !important;
}
.bill-card--print-mode .bill-title,
.bill-card--print-mode .item-name,
.bill-card--print-mode .bill-totals-row--strong,
.bill-card--print-mode .ex-value,
.bill-card--print-mode .bill-meta-value {
  color: #111 !important;
}
.bill-card--print-mode .bill-actions {
  display: none !important;
}

@media print {
  :global(body *) { visibility: hidden !important; }
  :global(.bill-card),
  :global(.bill-card *) { visibility: visible !important; }
  :global(.bill-card) {
    position: absolute !important;
    inset: 0 auto auto 0;
    width: 100%;
    background: #ffffff !important;
    color: #111 !important;
    border: none !important;
    box-shadow: none !important;
    padding: 16mm 14mm !important;
    max-width: none !important;
  }
  :global(.bill-card *) {
    color: #111 !important;
    background: transparent !important;
    border-color: #ddd !important;
  }
  :global(.bill-actions) { display: none !important; }
}

/* ── Responsive ── */
@media (max-width: 640px) {
  .bill-card { padding: var(--sp-4); }
  .bill-head {
    grid-template-columns: 1fr;
    grid-template-areas:
      "title"
      "status"
      "meta";
  }
  .bill-meta { align-items: flex-start; }
  .bill-status { justify-self: start; }
  .bill-title { font-size: 1.4rem; letter-spacing: 4px; }
  .bill-actions { justify-content: stretch; }
}
</style>

<script setup lang="ts">
/**
 * OrderDetailModal — 订单详情弹窗
 *
 * Desktop: BaseModal size="xl". Mobile: full-width.
 * Sections: 概览 / 发票与交易 / 业务效果 / 退款记录 / 操作按钮.
 */
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useConfirm } from '@/composables/useConfirm'
import { useToast } from '@/composables/useToast'
import { useAppStore } from '@/stores/app'
import { useRouter } from 'vue-router'
import BaseModal from '@/components/ui/BaseModal.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import Badge from '@/components/ui/Badge.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import LoadingCenter from '@/components/ui/LoadingCenter.vue'
import EmptyState from '@/components/ui/EmptyState.vue'

defineOptions({ name: 'OrderDetailModal' })

interface Transaction {
  id: number; invoice_id: number; gateway_code: string; transaction_id: string
  amount_fen: number; refunded_fen: number; status: string
  created_at: string; updated_at: string
}

interface Invoice {
  id: number; invoice_no: string; status: string; total_fen: number
  currency_code: string; due_at: string | null; paid_at: string | null
  gateway_code: string | null; gateway_prepay_id: string | null
  code_url: string | null; pay_url: string | null; pay_url_h5?: string | null
  created_at: string; updated_at: string
}

interface Effect {
  order_id: number; effect_type: string; server_id: number
  days: number; prev_expiration_date: string | null
  new_expiration_date: string; effect_committed_at: string
  post_actions_done_at: string | null
}

interface Refund {
  id: number; refund_no: string; transaction_id: number; amount_fen: number
  status: string; reason: string | null; previous_order_status: string
  gateway_refund_id: string | null; retry_count: number; last_error: string | null
  initiated_by: number | null; initiated_by_username: string | null
  created_at: string; updated_at: string
}

interface OrderDetail {
  id: number; order_no: string; user_id: number
  owner_username: string | null
  plan_id: number | null; plan_snapshot: Record<string, any>
  kind: string; period_count: number; discount_pct: number
  total_fen: number; total_days: number
  target_server_id: number | null; target_server_name: string | null
  reserved_node_id: number | null; reserved_allocation_id: number | null
  status: string; received_fen: number; refunded_fen: number
  apply_retry_count: number; next_apply_at: string | null
  last_apply_error: string | null
  applied_at: string | null; closed_at: string | null; cancelled_at: string | null
  created_at: string; updated_at: string
  invoices: Invoice[]; transactions: Transaction[]
  effect: Effect | null; refunds: Refund[]
}

const props = defineProps<{
  modelValue: boolean
  orderId: number | null
}>()

const emit = defineEmits<{
  'update:modelValue': [v: boolean]
  saved: []
}>()

const { t } = useI18n({ useScope: 'global' })
const { get, post, loading } = useApiFetch()
const { confirm } = useConfirm()
const { toast } = useToast()
const router = useRouter()
const appStore = useAppStore()

interface Incident {
  id: number; kind: string
  order_id: number | null; invoice_id: number | null
  transaction_id: number | null; server_id: number | null
  payload: Record<string, any>
  detected_at: string; status: string
  resolution_note: string | null; resolved_by: number | null
  resolved_at: string | null
}

const order = ref<OrderDetail | null>(null)
const incidents = ref<Incident[]>([])
const loadFailed = ref(false)

watch(() => props.orderId, (id) => {
  if (id != null && props.modelValue) loadOrder()
})

watch(() => props.modelValue, (v) => {
  if (v && props.orderId != null) loadOrder()
})

async function loadOrder() {
  if (props.orderId == null) return
  loadFailed.value = false
  const [orderData, incData] = await Promise.all([
    get<OrderDetail>(`/api/admin/billing/orders/${props.orderId}`, { silent: true }),
    get<Incident[]>(`/api/admin/billing/incidents?order_id=${props.orderId}&limit=20`, { silent: true }),
  ])
  if (orderData) order.value = orderData
  else loadFailed.value = true
  if (incData) incidents.value = incData
}

function incidentLabel(inc: Incident): string {
  const sub = inc.payload?.subkind
  if (sub) return t('billing.admin.incidents.subkind.' + sub)
  return t('billing.admin.incidents.kind.' + inc.kind)
}

function close() { emit('update:modelValue', false) }

function goUser(userId: number, username: string | null) { close(); router.push({ name: 'users', query: { q: username || String(userId) } }) }
function goServer(serverId: number, name: string | null) { close(); router.push({ name: 'servers', query: { q: name || String(serverId) } }) }

// ── Display helpers ──
function fenToYuan(fen: number): string { return (fen / 100).toFixed(2) }

function fmtTs(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('zh-CN', { timeZone: appStore.timezone, hour12: false })
}

function fmtDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('zh-CN', { timeZone: appStore.timezone })
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

function kindLabel(k: string): string {
  if (k === 'new_purchase') return t('billing.admin.orders.kindNewPurchase')
  if (k === 'upgrade') return t('billing.admin.orders.kindUpgrade')
  if (k === 'convert') return t('billing.admin.orders.kindConvert')
  return t('billing.admin.orders.kindRenew')
}

function kindColor(k: string): string {
  if (k === 'new_purchase') return 'var(--blue)'
  if (k === 'renew') return 'var(--green)'
  if (k === 'upgrade') return 'var(--amber)'
  if (k === 'convert') return 'var(--ac)'
  return 'var(--t3)'
}

// ── Action conditions ──
function canRefund(): boolean {
  if (!order.value) return false
  const s = order.value.status
  return (s === 'applied' || s === 'apply_failed' || s === 'manual_review')
    && order.value.received_fen > order.value.refunded_fen
}

function canForceApply(): boolean {
  if (!order.value) return false
  return order.value.status === 'manual_review' || order.value.status === 'apply_failed'
}

function canForceClose(): boolean {
  if (!order.value) return false
  return order.value.status === 'manual_review' || order.value.status === 'apply_failed'
}

function canCleanup(): boolean {
  if (!order.value) return false
  return order.value.effect === null && order.value.target_server_id != null
}

// ── Actions ──
async function doForceApply() {
  if (!order.value) return
  const ok = await confirm({
    title: t('billing.admin.detail.forceApply'),
    message: t('billing.admin.detail.forceApplyConfirm', { orderNo: order.value.order_no }),
    confirmText: t('billing.admin.detail.forceApply'),
  })
  if (!ok) return
  const res = await post<{ result: string }>(`/api/admin/billing/orders/${order.value.id}/force-apply`, {})
  if (res) {
    toast(res.result === 'applied' ? t('billing.admin.detail.forceApplyOk') : t('billing.admin.detail.forceApplyFail'), res.result === 'applied' ? 'success' : 'error')
    loadOrder(); emit('saved')
  }
}

async function doForceClose() {
  if (!order.value) return
  const note = prompt(t('billing.admin.detail.forceCloseNote'))
  if (!note) return
  const res = await post(`/api/admin/billing/orders/${order.value.id}/force-close`, { note })
  if (res) { toast(t('billing.admin.detail.forceCloseOk'), 'success'); close(); emit('saved') }
}

async function doCleanup() {
  if (!order.value) return
  const ok = await confirm({
    title: t('billing.admin.detail.cleanup'),
    message: t('billing.admin.detail.cleanupConfirm'),
    variant: 'danger',
    confirmText: t('billing.admin.detail.cleanup'),
  })
  if (!ok) return
  const res = await post(`/api/admin/billing/orders/${order.value.id}/cleanup-placeholder`, {})
  if (res) { toast(t('billing.admin.detail.cleanupOk'), 'success'); loadOrder(); emit('saved') }
}

// ── Refund (全额退款唯一动作) ──
const refundOpen = ref(false)
const refundReason = ref('')

function openRefund() {
  if (!order.value) return
  const tx = order.value.transactions.find(tx => tx.status === 'succeeded')
  if (!tx) return
  refundReason.value = ''
  refundOpen.value = true
}

const refundTx = computed(() =>
  order.value?.transactions.find(tx => tx.status === 'succeeded') || null
)

const refundAmount = computed(() =>
  refundTx.value ? refundTx.value.amount_fen - (refundTx.value.refunded_fen || 0) : 0
)

async function doRefund() {
  if (!order.value || !refundTx.value || refundAmount.value <= 0) return
  const ok = await confirm({
    title: t('billing.admin.detail.refund'),
    message: t('billing.admin.detail.refundConfirm', { amount: fenToYuan(refundAmount.value) }),
    variant: 'danger',
    confirmText: t('billing.admin.detail.refund'),
  })
  if (!ok) return
  const res = await post(`/api/admin/billing/orders/${order.value.id}/refund`, {
    transaction_id: refundTx.value.id,
    reason: refundReason.value || undefined,
  })
  if (res) {
    toast(t('billing.admin.detail.refundOk'), 'success')
    refundOpen.value = false
    loadOrder()
    emit('saved')
  }
}
</script>

<template>
  <BaseModal
    :model-value="props.modelValue"
    :title="order?.order_no || t('billing.admin.detail.title')"
    icon="receipt_long"
    size="xl"
    :close-on-overlay="true"
    :close-on-esc="true"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <template #header>
      <div v-if="order" class="modal-header-row">
        <code class="modal-header-code">{{ order.order_no }}</code>
        <Badge :color="statusColor(order.status)">{{ t(`billing.orders.status.${order.status}`) }}</Badge>
      </div>
    </template>

    <LoadingCenter v-if="loading && !order" />

    <EmptyState
      v-else-if="loadFailed"
      icon="error_outline"
      :text="t('billing.orderDetail.loadFailed')"
    >
      <BaseButton size="sm" variant="primary" @click="loadOrder">
        {{ t('billing.orderDetail.retry') }}
      </BaseButton>
    </EmptyState>

    <template v-else-if="order">
      <!-- ═══ Overview ═══ -->
      <div class="sec">
        <h4 class="sec-title">{{ t('billing.admin.detail.overview') }}</h4>
        <dl class="dl dl--dual">
          <dt>{{ t('billing.admin.orders.col.kind') }}</dt>
          <dd><Badge :color="kindColor(order.kind)">{{ kindLabel(order.kind) }}</Badge></dd>

          <dt>{{ t('billing.admin.orders.col.user') }}</dt>
          <dd>
            <template v-if="order.user_id && order.owner_username">
              <a href="#" class="link" @click.prevent="goUser(order.user_id, order.owner_username)">{{ order.owner_username }}</a>
            </template>
            <span v-else-if="order.user_id" class="muted">{{ t('billing.admin.orders.deletedUser', { id: order.user_id }) }}</span>
            <span v-else class="muted">—</span>
          </dd>

          <dt>{{ t('billing.admin.orders.col.plan') }}</dt>
          <dd>{{ order.plan_snapshot?.plan_name || '—' }} <span class="muted">({{ order.plan_snapshot?.plan_code }})</span></dd>

          <dt>{{ t('billing.admin.orders.col.amount') }}</dt>
          <dd class="mono">¥{{ fenToYuan(order.total_fen) }} <span v-if="order.discount_pct > 0" class="muted">(−{{ order.discount_pct }}%)</span></dd>

          <dt>{{ t('billing.admin.detail.periodCount') }}</dt>
          <dd>{{ order.period_count }} · {{ order.total_days }} {{ t('billing.admin.plans.dayUnit') }}</dd>

          <dt>{{ t('billing.admin.detail.received') }}</dt>
          <dd class="mono">¥{{ fenToYuan(order.received_fen) }}</dd>

          <dt>{{ t('billing.admin.detail.refunded') }}</dt>
          <dd class="mono">¥{{ fenToYuan(order.refunded_fen) }}</dd>

          <dt>{{ t('billing.admin.orders.col.server') }}</dt>
          <dd>
            <template v-if="order.target_server_id && order.target_server_name">
              <a href="#" class="link" @click.prevent="goServer(order.target_server_id, order.target_server_name)">{{ order.target_server_name }}</a>
            </template>
            <span v-else-if="order.target_server_id" class="muted">{{ t('billing.admin.orders.deletedServer', { id: order.target_server_id }) }}</span>
            <span v-else class="muted">—</span>
          </dd>

          <dt>{{ t('billing.admin.detail.retries') }}</dt>
          <dd>{{ order.apply_retry_count }} <span v-if="order.next_apply_at" class="muted"> / {{ t('billing.admin.detail.nextApply') }} {{ fmtTs(order.next_apply_at) }}</span></dd>

          <dt>{{ t('billing.admin.detail.created') }}</dt>
          <dd>{{ fmtTs(order.created_at) }}</dd>

          <dt>{{ t('billing.admin.detail.updated') }}</dt>
          <dd>{{ fmtTs(order.updated_at) }}</dd>

          <dt>{{ t('billing.admin.detail.applied') }}</dt>
          <dd>{{ fmtTs(order.applied_at) }}</dd>

          <template v-if="order.closed_at">
            <dt>{{ t('billing.admin.detail.closed') }}</dt>
            <dd>{{ fmtTs(order.closed_at) }}</dd>
          </template>

          <template v-if="order.cancelled_at">
            <dt>{{ t('billing.admin.detail.cancelled') }}</dt>
            <dd>{{ fmtTs(order.cancelled_at) }}</dd>
          </template>
        </dl>

        <div v-if="order.last_apply_error" class="err-block">{{ order.last_apply_error }}</div>
      </div>

      <!-- ═══ Invoices ═══ -->
      <div v-if="order.invoices.length" class="sec">
        <h4 class="sec-title">{{ t('billing.admin.detail.invoices') }}</h4>
        <div v-for="inv in order.invoices" :key="inv.id" class="subcard">
          <dl class="dl dl--dual">
            <dt>{{ t('billing.admin.detail.invoiceNo') }}</dt>
            <dd><code>{{ inv.invoice_no }}</code></dd>

            <dt>{{ t('billing.admin.detail.invoiceStatus') }}</dt>
            <dd><Badge :color="inv.status === 'paid' ? 'var(--green)' : inv.status === 'void' ? 'var(--t3)' : 'var(--t3)'">{{ t('billing.admin.detail.invoiceStatus_' + inv.status) }}</Badge></dd>

            <dt>{{ t('billing.admin.orders.col.amount') }}</dt>
            <dd class="mono">¥{{ fenToYuan(inv.total_fen) }}</dd>

            <dt>{{ t('billing.admin.detail.invoiceGateway') }}</dt>
            <dd>{{ inv.gateway_code || '—' }}</dd>

            <dt>{{ t('billing.admin.detail.invoicePrepayId') }}</dt>
            <dd><code v-if="inv.gateway_prepay_id">{{ inv.gateway_prepay_id }}</code><span v-else class="muted">—</span></dd>

            <dt>{{ t('billing.admin.detail.invoiceDue') }}</dt>
            <dd>{{ fmtTs(inv.due_at) }}</dd>

            <dt>{{ t('billing.admin.detail.invoicePaidAt') }}</dt>
            <dd>{{ fmtTs(inv.paid_at) }}</dd>
          </dl>

          <table v-if="order.transactions.some(tx => tx.invoice_id === inv.id)" class="tx-table">
            <thead>
              <tr>
                <th>{{ t('billing.admin.detail.txId') }}</th>
                <th class="r">{{ t('billing.admin.orders.col.amount') }}</th>
                <th class="r">{{ t('billing.admin.detail.refunded') }}</th>
                <th>{{ t('billing.admin.orders.col.status') }}</th>
                <th>{{ t('billing.admin.orders.col.time') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="tx in order.transactions.filter(tx => tx.invoice_id === inv.id)" :key="tx.id">
                <td><code>{{ tx.transaction_id }}</code></td>
                <td class="mono r">¥{{ fenToYuan(tx.amount_fen) }}</td>
                <td class="mono r">{{ tx.refunded_fen > 0 ? '¥' + fenToYuan(tx.refunded_fen) : '—' }}</td>
                <td><Badge :color="tx.status === 'succeeded' ? 'var(--green)' : tx.status === 'refunded' ? 'var(--t2)' : 'var(--red)'">{{ t('billing.admin.detail.txStatus_' + tx.status) }}</Badge></td>
                <td>{{ fmtTs(tx.created_at) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- ═══ Effect ═══ -->
      <div v-if="order.effect" class="sec">
        <h4 class="sec-title">{{ t('billing.admin.detail.effect') }}</h4>
        <dl class="dl dl--dual">
          <dt>{{ t('billing.admin.orders.col.kind') }}</dt>
          <dd><Badge :color="kindColor(order.effect.effect_type)">{{ kindLabel(order.effect.effect_type) }}</Badge></dd>

          <dt>{{ t('billing.admin.orders.col.server') }}</dt>
          <dd>
            <template v-if="order.effect.server_id && order.target_server_name">
              <a href="#" class="link" @click.prevent="goServer(order.effect.server_id, order.target_server_name)">{{ order.target_server_name }}</a>
            </template>
            <span v-else-if="order.effect.server_id" class="muted">{{ t('billing.admin.orders.deletedServer', { id: order.effect.server_id }) }}</span>
            <span v-else class="muted">—</span>
          </dd>

          <dt>{{ t('billing.admin.detail.effectDays') }}</dt>
          <dd>{{ order.effect.days }}</dd>

          <dt>{{ t('billing.admin.detail.effectExpiry') }}</dt>
          <dd>{{ order.effect.prev_expiration_date || '—' }} → {{ order.effect.new_expiration_date }}</dd>

          <dt>{{ t('billing.admin.detail.effectCommitted') }}</dt>
          <dd>{{ fmtTs(order.effect.effect_committed_at) }}</dd>

          <dt>{{ t('billing.admin.detail.effectPostActions') }}</dt>
          <dd>
            <span v-if="order.effect.post_actions_done_at">{{ fmtTs(order.effect.post_actions_done_at) }}</span>
            <Badge v-else color="var(--amber)">{{ t('billing.admin.detail.effectPostActionsPending') }}</Badge>
          </dd>
        </dl>
      </div>

      <!-- ═══ Refunds ═══ -->
      <div v-if="order.refunds.length" class="sec">
        <h4 class="sec-title">{{ t('billing.admin.detail.refunds') }}</h4>
        <div v-for="r in order.refunds" :key="r.id" class="subcard">
          <dl class="dl dl--dual">
            <dt>{{ t('billing.admin.detail.refundNo') }}</dt>
            <dd><code>{{ r.refund_no }}</code></dd>

            <dt>{{ t('billing.admin.orders.col.amount') }}</dt>
            <dd class="mono">¥{{ fenToYuan(r.amount_fen) }}</dd>

            <dt>{{ t('billing.admin.orders.col.status') }}</dt>
            <dd><Badge :color="r.status === 'succeeded' ? 'var(--green)' : r.status === 'failed' ? 'var(--red)' : 'var(--amber)'">{{ t('billing.admin.detail.refundStatus_' + r.status) }}</Badge></dd>

            <dt>{{ t('billing.admin.detail.refundReason') }}</dt>
            <dd>{{ r.reason || '—' }}</dd>

            <dt>{{ t('billing.admin.detail.refundGatewayId') }}</dt>
            <dd><code v-if="r.gateway_refund_id">{{ r.gateway_refund_id }}</code><span v-else class="muted">—</span></dd>

            <dt>{{ t('billing.admin.detail.refundRetries') }}</dt>
            <dd>{{ r.retry_count }}</dd>

            <dt>{{ t('billing.admin.detail.refundInitiatedBy') }}</dt>
            <dd>{{ r.initiated_by_username || '—' }}</dd>

            <dt>{{ t('billing.admin.orders.col.time') }}</dt>
            <dd>{{ fmtTs(r.created_at) }}</dd>
          </dl>
          <div v-if="r.last_error" class="err-block">{{ r.last_error }}</div>
        </div>
      </div>

      <!-- ═══ Incidents ═══ -->
      <div v-if="incidents.length" class="sec">
        <h4 class="sec-title">{{ t('billing.admin.tabIncidents') }}</h4>
        <div v-for="inc in incidents" :key="inc.id" class="incident-row">
          <Badge :color="inc.status === 'open' ? 'var(--red)' : inc.status === 'investigating' ? 'var(--amber)' : 'var(--t3)'">
            {{ t('billing.admin.incidents.status.' + inc.status) }}
          </Badge>
          <Badge :color="inc.kind === 'manual_review_required' || inc.kind === 'placeholder_leak' ? 'var(--amber)' : 'var(--red)'">
            {{ incidentLabel(inc) }}
          </Badge>
          <span class="muted incident-time">{{ fmtTs(inc.detected_at) }}</span>
        </div>
      </div>

      <!-- ═══ Actions ═══ -->
      <div v-if="canRefund() || canForceApply() || canForceClose() || canCleanup()" class="sec">
        <h4 class="sec-title">{{ t('billing.admin.detail.actionsTitle') }}</h4>
        <div class="actions-row">
          <BaseButton v-if="canForceApply()" size="sm" variant="primary" @click="doForceApply">
            <MsIcon name="play_arrow" size="xs" /> {{ t('billing.admin.detail.forceApply') }}
          </BaseButton>
          <BaseButton v-if="canRefund()" size="sm" variant="danger" @click="openRefund">
            <MsIcon name="payments" size="xs" /> {{ t('billing.admin.detail.refund') }}
          </BaseButton>
          <BaseButton v-if="canForceClose()" size="sm" @click="doForceClose">
            <MsIcon name="cancel" size="xs" /> {{ t('billing.admin.detail.forceClose') }}
          </BaseButton>
          <BaseButton v-if="canCleanup()" size="sm" variant="warning" @click="doCleanup">
            <MsIcon name="delete" size="xs" /> {{ t('billing.admin.detail.cleanup') }}
          </BaseButton>
        </div>
      </div>
    </template>
  </BaseModal>

  <BaseModal v-model="refundOpen" :title="t('billing.admin.detail.refund')" icon="payments" size="sm">
    <div class="refund-form">
      <div class="refund-tx-info mono">
        <span class="muted">{{ t('billing.admin.detail.txId') }}</span>
        <code>{{ refundTx?.transaction_id }}</code>
        <span class="muted">{{ t('billing.admin.detail.refundFullAmount') }}</span>
        <span class="mono">¥{{ fenToYuan(refundAmount) }}</span>
      </div>
      <div class="form-row">
        <label>{{ t('billing.admin.detail.refundReason') }}</label>
        <input v-model="refundReason" class="form-input" maxlength="255" :placeholder="t('billing.admin.detail.refundReasonPlaceholder')" />
      </div>
    </div>
    <template #footer>
      <div class="footer-actions">
        <BaseButton size="sm" @click="refundOpen = false">{{ t('common.btn.cancel') }}</BaseButton>
        <BaseButton size="sm" variant="danger" :disabled="refundAmount <= 0" @click="doRefund">
          <MsIcon name="payments" size="xs" /> {{ t('billing.admin.detail.refund') }}
        </BaseButton>
      </div>
    </template>
  </BaseModal>
</template>

<style scoped>
/* ── Header ── */
.modal-header-row { display: flex; align-items: center; gap: var(--sp-3); }
.modal-header-code { font-size: var(--text-md); }

/* ── Sections ── */
.sec { margin-bottom: var(--sp-5); }
.sec-title {
  font-size: var(--text-sm); font-weight: 600; color: var(--t2);
  text-transform: uppercase; letter-spacing: .3px;
  margin-bottom: var(--sp-3); padding-bottom: var(--sp-2);
  border-bottom: 1px solid var(--bd);
}

/* ── Definition list (key-value rows) ── */
.dl {
  display: grid;
  grid-template-columns: 110px 1fr;
  gap: var(--sp-1) var(--sp-4);
  font-size: .85rem;
}
.dl--dual {
  grid-template-columns: 110px 1fr 110px 1fr;
}
.dl dt { color: var(--t3); font-weight: 500; }
.dl dd { color: var(--t1); min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* ── Sub-card (invoice / refund) ── */
.subcard {
  background: var(--bg-in); border: 1px solid var(--bd);
  border-radius: var(--r-sm); padding: var(--sp-3); margin-bottom: var(--sp-3);
}

/* ── Transaction table ── */
.tx-table { width: 100%; border-collapse: collapse; font-size: .82rem; margin-top: var(--sp-3); }
.tx-table th { text-align: left; font-size: .72rem; font-weight: 600; color: var(--t3); padding: var(--sp-1) var(--sp-2); border-bottom: 1px solid var(--bd); }
.tx-table td { padding: var(--sp-1) var(--sp-2); border-bottom: 1px solid var(--bd); }
.tx-table .r { text-align: right; }

/* ── Incidents ── */
.incident-row {
  display: flex; align-items: center; gap: var(--sp-3);
  padding: var(--sp-2) var(--sp-3); margin-bottom: var(--sp-1);
  background: var(--bg-in); border-radius: var(--r-sm);
  font-size: .85rem;
}
.incident-time { font-size: .78rem; margin-left: auto; }

/* ── Actions ── */
.actions-row { display: flex; gap: var(--sp-2); flex-wrap: wrap; }

/* ── Refund form ── */
.refund-form { display: flex; flex-direction: column; gap: var(--sp-4); }
.refund-tx-info {
  display: grid; grid-template-columns: auto 1fr;
  gap: var(--sp-1) var(--sp-3); align-items: center;
  padding: var(--sp-3); background: var(--bg-in); border-radius: var(--r-sm);
  font-size: .85rem;
}
.form-row { display: flex; flex-direction: column; gap: var(--sp-1); }
.form-row label { font-size: var(--text-sm); color: var(--t2); font-weight: 500; }

.footer-actions { display: flex; gap: var(--sp-2); flex-wrap: wrap; justify-content: flex-end; }

/* ── Shared ── */
code {
  font-family: var(--font-mono, 'IBM Plex Mono', monospace);
  font-size: var(--text-xs); background: var(--bg-in);
  padding: 1px 5px; border-radius: var(--r-xs); color: var(--t1);
}
.mono  { font-family: var(--font-mono, 'IBM Plex Mono', monospace); }
.muted { color: var(--t3); }
.link  { color: var(--ac); text-decoration: none; }
.link:hover { text-decoration: underline; }
.err-block { margin-top: var(--sp-2); color: var(--red); font-size: .78rem; padding: var(--sp-2); background: color-mix(in srgb, var(--red) 8%, transparent); border-radius: var(--r-xs); }

@media (max-width: 640px) {
  .dl, .dl--dual { grid-template-columns: 100px 1fr; }
  .dl dt { margin-top: var(--sp-1); }
  .footer-actions { flex-direction: column; }
}
</style>

<script setup lang="ts">
/**
 * UserPayPage — full-screen payment page at /pay/:id (blank layout).
 *
 * Single-tab flow: after order creation in CreateOrderModal we
 * ``router.push('/pay/:id')`` here. This page renders the QR code, polls
 * ``GET /api/user/orders/:id`` and auto-advances to /servers when the
 * order reaches a paid state.
 *
 * Visual shell: AuthShell (theme + language toggle in top-right, no
 * sidebar/exit) so the experience matches the login page.
 *
 * No self-service cancel/refund here — users with problems open the
 * SupportModal and contact a human.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import AuthShell from '@/components/auth/AuthShell.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import Badge from '@/components/ui/Badge.vue'
import Spinner from '@/components/ui/Spinner.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import SupportModal from '@/components/billing/SupportModal.vue'
import { useToast } from '@/composables/useToast'
import { useOrderPolling } from '@/composables/useOrderPolling'

defineOptions({ name: 'UserPayPage' })

const route = useRoute()
const router = useRouter()
const { t } = useI18n({ useScope: 'global' })
const { toast } = useToast()

// ── Order id ──
const orderId = computed(() => {
  const raw = route.params.id
  return Array.isArray(raw) ? raw[0] : raw
})

// ── Polling ──
const { data, refresh, stop } = useOrderPolling(orderId)

const order = computed(() => data.value ?? null)
const invoice = computed(() => data.value?.invoice ?? null)

// ── State machine derived from order.status / countdown ──
type Phase = 'loading' | 'pending' | 'processing' | 'paid' | 'expired' | 'closed'

const now = ref(Date.now())
let tickTimer: ReturnType<typeof setInterval> | null = null

const dueAtMs = computed(() => {
  const due = invoice.value?.due_at
  if (!due) return null
  const ts = Date.parse(due)
  return Number.isNaN(ts) ? null : ts
})

const remainingMs = computed(() => {
  if (dueAtMs.value === null) return null
  return Math.max(0, dueAtMs.value - now.value)
})

const isExpired = computed(() => remainingMs.value === 0)

const phase = computed<Phase>(() => {
  if (!order.value) return 'loading'
  const s = order.value.status
  if (s === 'paid' || s === 'applied') return 'paid'
  // 'processing' = 网关回调已到、apply_engine 正在为用户开通服务。
  // 这个阶段资金已到账，倒计时完全不适用（不能误显“已过期”）。
  if (s === 'processing') return 'processing'
  if (
    s === 'closed' ||
    s === 'cancelled' ||
    s === 'refunded' ||
    s === 'refunding' ||
    s === 'manual_review'
  ) {
    return 'closed'
  }
  if (isExpired.value) return 'expired'
  return 'pending'
})

const countdownLabel = computed(() => {
  if (remainingMs.value === null) return ''
  const total = Math.floor(remainingMs.value / 1000)
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
})

// ── Status badge ──
const statusColor = computed(() => {
  switch (phase.value) {
    case 'paid':
      return 'var(--green)'
    case 'processing':
      return 'var(--blue)'
    case 'pending':
      return 'var(--amber)'
    case 'expired':
      return 'var(--t3)'
    case 'closed':
      return 'var(--t3)'
    default:
      return 'var(--t2)'
  }
})

const statusLabel = computed(() => {
  switch (phase.value) {
    case 'pending':
      return t('billing.pay.statusPending')
    case 'processing':
      return t('billing.pay.statusProcessing')
    case 'paid':
      return t('billing.pay.statusPaid')
    case 'expired':
      return t('billing.pay.statusExpired')
    case 'closed':
      return t('billing.pay.statusClosed')
    default:
      return t('billing.pay.statusLoading')
  }
})

// ── QR image ──
// Hupijiao 文档：`url_qrcode` 字段本身就是已渲染好的 PC 端二维码图片地址，
// 直接 <img src> 展示即可，不要再做二次 QR 编码。
// 支付宝直连（alipay_direct）走 alipay.trade.page.pay：返回的是收银台跳转
// URL,无预渲染 QR，前端直接「同窗口跳转」到支付页面 (付完支付宝点「返回
// 商户」跳回 return_url = /#/pay/:id，原页继续轮询)。
const qrImageUrl = computed(() => invoice.value?.code_url ?? null)
const qrError = ref(false)

function onQrImageError() {
  qrError.value = true
}

function onQrImageLoad() {
  qrError.value = false
}

// ── PC vs mobile detection ──
// hupijiao: 移动端在浏览器内打开支付宝 H5 收银台；PC 端展示二维码图片。
// alipay_direct: 不分 PC/H5，支付宝 page.pay 按 UA 自动切换收银台形态，
// 都走同窗口跳转 (return_url 跳回 /pay/:id)。
const isMobile = (() => {
  if (typeof navigator === 'undefined') return false
  const ua = navigator.userAgent || ''
  if (/Android|iPhone|iPad|iPod|Mobile|Opera Mini|IEMobile/i.test(ua)) return true
  if (typeof window !== 'undefined' && window.matchMedia?.('(pointer: coarse)').matches && window.innerWidth < 768) return true
  return false
})()

// 前端按 isMobile 选 PC(page.pay) 或 H5(wap.pay) 收银台 URL
const payUrl = computed(() => {
  if (!invoice.value) return null
  if (isMobile && invoice.value.pay_url_h5) return invoice.value.pay_url_h5
  return invoice.value.pay_url ?? null
})
const h5Launched = ref(false)
const redirecting = ref(false)

function launchH5Pay() {
  if (!payUrl.value) return
  h5Launched.value = true
  // PC: 新标签打开, 原页继续轮询, 付完自动捕获到账。
  // 移动端: iOS Safari 拦截 setTimeout 后的 window.open, 只能同窗口跳;
  //         付完支付宝「返回商户」跳回 return_url=/#/pay/:id 恢复轮询。
  if (isMobile) {
    window.location.href = payUrl.value
  } else {
    window.open(payUrl.value, '_blank')
  }
}

// 所有平台统一: 拿到 pay_url 后先显示「正在跳转到支付宝…」600ms 再跳,
// 让用户有时间看清页面。手动按钮始终 enabled, 用户可随时点跳过等待。
const REDIRECT_DELAY_MS = 600
watch(payUrl, (url) => {
  if (!url) return
  if (h5Launched.value) return
  if (phase.value !== 'pending') return
  if (!isMobile && qrImageUrl.value) return  // hupijiao PC: 展示 QR 不跳
  redirecting.value = true
  setTimeout(() => {
    if (!h5Launched.value && phase.value === 'pending' && payUrl.value) {
      launchH5Pay()
    }
  }, REDIRECT_DELAY_MS)
})

// 副标题: 唯一主提示, 按状态切换
const subtitleText = computed(() => {
  if (!order.value || redirecting.value) return t('billing.pay.redirecting')
  switch (phase.value) {
    case 'paid': return t('billing.pay.successTitle')
    case 'processing': return t('billing.pay.processingTitle')
    case 'expired': return t('billing.pay.expiredTitle')
    case 'closed': return t('billing.pay.closedTitle')
    default:
      return qrImageUrl.value
        ? t('billing.pay.subtitleQR')
        : t('billing.pay.subtitleRedirect')
  }
})

// ── Auto-redirect on success ──
const redirectCountdown = ref(5)
let redirectTimer: ReturnType<typeof setInterval> | null = null

watch(phase, (p, prev) => {
  if (p === 'paid' && prev !== 'paid') {
    redirectCountdown.value = 5
    redirectTimer = setInterval(() => {
      redirectCountdown.value -= 1
      if (redirectCountdown.value <= 0) goToServers()
    }, 1000)
  }
})

function goToServers() {
  if (redirectTimer !== null) {
    clearInterval(redirectTimer)
    redirectTimer = null
  }
  router.push('/servers')
}

function goToPlans() {
  router.push('/plans')
}

// ── Copy order no ──
async function copyOrderNo() {
  if (!order.value?.order_no) return
  try {
    await navigator.clipboard.writeText(order.value.order_no)
    toast(t('billing.pay.orderNoCopied'), 'success')
  } catch {
    toast(t('billing.pay.copyFailed'), 'error')
  }
}

// ── Support modal ──
const supportOpen = ref(false)

// ── Lifecycle ──
onMounted(() => {
  tickTimer = setInterval(() => {
    now.value = Date.now()
  }, 1000)
})

onBeforeUnmount(() => {
  if (tickTimer !== null) clearInterval(tickTimer)
  if (redirectTimer !== null) clearInterval(redirectTimer)
  stop()
})

// ── Helpers ──
function fenToYuan(fen: number | null | undefined): string {
  if (fen == null) return '0.00'
  return (fen / 100).toFixed(2)
}
</script>

<template>
  <AuthShell icon="receipt_long" :subtitle="subtitleText">
    <div class="pay-content">
      <!-- QR (hupijiao PC, pending only) -->
      <div v-if="phase === 'pending' && qrImageUrl && !isMobile" class="qr-wrap">
        <img v-if="!qrError" :src="qrImageUrl" alt="QR" class="qr-image" width="240" height="240" @load="onQrImageLoad" @error="onQrImageError" />
        <div v-else class="qr-error">
          <MsIcon name="error_outline" size="lg" />
          <p>{{ t('billing.pay.qrError') }}</p>
          <BaseButton size="sm" variant="ghost" @click="refresh">{{ t('billing.pay.retry') }}</BaseButton>
        </div>
      </div>

      <!-- Button (loading + non-QR pending) -->
      <div v-else-if="phase === 'loading' || phase === 'pending'" class="pay-action">
        <BaseButton variant="primary" :disabled="!payUrl || phase !== 'pending'" @click="launchH5Pay">
          <MsIcon name="open_in_new" size="sm" />
          {{ h5Launched ? t('billing.pay.buttonReopen') : t('billing.pay.buttonOpen') }}
        </BaseButton>
      </div>

      <!-- Terminal states (all platforms unified) -->
      <div v-else-if="phase === 'paid'" class="pay-status pay-status--success">
        <MsIcon name="check_circle" size="lg" />
        <p class="status-sub">{{ t('billing.pay.successCountdown', { n: redirectCountdown }) }}</p>
      </div>
      <div v-else-if="phase === 'processing'" class="pay-status pay-status--processing">
        <Spinner />
        <p class="status-sub">{{ t('billing.pay.processingSub') }}</p>
      </div>
      <div v-else-if="phase === 'expired'" class="pay-status pay-status--expired">
        <MsIcon name="error_outline" size="lg" />
        <p class="status-sub">{{ t('billing.pay.expiredTitle') }}</p>
      </div>
      <div v-else-if="phase === 'closed'" class="pay-status pay-status--closed">
        <MsIcon name="error_outline" size="lg" />
        <p class="status-sub">{{ t('billing.pay.closedTitle') }}</p>
      </div>

      <!-- Amount -->
      <div v-if="order" class="amount-row">
        <span class="amount-label">{{ t('billing.pay.amountLabel') }}</span>
        <span class="amount">¥{{ fenToYuan(order.total_fen) }}</span>
      </div>

      <div class="divider" />

      <!-- Summary -->
      <dl v-if="order" class="summary">
        <div class="summary-row">
          <dt>{{ t('billing.pay.summaryPlan') }}</dt>
          <dd>{{ order.plan_name }}</dd>
        </div>
        <div class="summary-row">
          <dt>{{ t('billing.pay.summaryDuration') }}</dt>
          <dd>{{ t('billing.pay.summaryDays', { days: order.total_days }) }}</dd>
        </div>
        <div v-if="order.coupon_id && order.coupon_discount_fen" class="summary-row">
          <dt>{{ t('billing.coupons.applyHint') }}</dt>
          <dd>
            <span v-if="order.coupon_code" class="mono">{{ order.coupon_code }}</span>
            <span class="discount-amount mono">−¥{{ fenToYuan(order.coupon_discount_fen) }}</span>
          </dd>
        </div>
        <div class="summary-row">
          <dt>{{ t('billing.pay.summaryOrderNo') }}</dt>
          <dd class="order-no-cell">
            <span class="mono">{{ order.order_no }}</span>
            <button class="copy-btn" :title="t('billing.pay.copy')" @click="copyOrderNo">
              <MsIcon name="content_copy" size="sm" />
            </button>
          </dd>
        </div>
        <div class="summary-row">
          <dt>{{ t('billing.pay.summaryStatus') }}</dt>
          <dd class="status-cell">
            <Badge :color="statusColor">{{ statusLabel }}</Badge>
            <span v-if="phase === 'pending' && remainingMs !== null" class="countdown mono">
              {{ countdownLabel }}
            </span>
          </dd>
        </div>
      </dl>

      <div class="divider" />

      <!-- Actions -->
      <div class="actions">
        <BaseButton v-if="phase === 'paid'" variant="primary" @click="goToServers">
          {{ t('billing.pay.btnGoServersNow') }}
        </BaseButton>
        <BaseButton v-else-if="phase === 'expired' || phase === 'closed'" variant="primary" @click="goToPlans">
          {{ t('billing.pay.btnReorder') }}
        </BaseButton>
        <BaseButton variant="ghost" @click="goToServers">
          <MsIcon name="home" size="sm" />
          {{ t('billing.pay.btnDashboard') }}
        </BaseButton>
      </div>

      <p class="support-hint">
        {{ t('billing.pay.supportHint') }}
        <a href="#" class="support-link" @click.prevent="supportOpen = true">
          {{ t('billing.pay.supportLink') }}
        </a>
      </p>
    </div>

    <SupportModal v-model="supportOpen" />
  </AuthShell>
</template>

<style scoped>
.pay-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--sp-3);
}

/* ── QR (hupijiao PC) ── */
.qr-wrap {
  position: relative;
  width: 240px;
  height: 240px;
  background: #fff;
  border-radius: var(--r-md);
  padding: var(--sp-2);
  box-sizing: content-box;
  display: flex;
  align-items: center;
  justify-content: center;
}
.qr-image {
  display: block;
  width: 240px;
  height: 240px;
  object-fit: contain;
  background: #fff;
}
.qr-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--sp-2);
  text-align: center;
  color: var(--red);
}

/* ── Button (loading + non-QR pending) ── */
.pay-action {
  display: flex;
  justify-content: center;
  min-height: 44px;
  align-items: center;
}

/* ── Terminal states (all platforms) ── */
.pay-status {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--sp-2);
  text-align: center;
  padding: var(--sp-4) 0;
  min-height: 80px;
  justify-content: center;
}
.pay-status :deep(.ms-icon) {
  font-size: 36px;
  line-height: 1;
}
.pay-status--success :deep(.ms-icon) { color: var(--green); }
.pay-status--processing :deep(.ms-icon) { color: var(--blue); }
.pay-status--expired :deep(.ms-icon),
.pay-status--closed :deep(.ms-icon) { color: var(--t3); }
.status-sub {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--t2);
}

/* ── Amount ── */
.amount-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  width: 100%;
  margin-top: var(--sp-2);
}
.amount-label {
  color: var(--t2);
  font-size: var(--text-sm);
}
.amount {
  font-family: 'IBM Plex Mono', monospace;
  font-size: var(--text-xl);
  font-weight: 700;
  color: var(--ac);
  text-align: right;
}

.divider {
  width: 100%;
  height: 1px;
  background: var(--bd);
  margin: var(--sp-2) 0;
}

.summary {
  width: 100%;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.summary-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
}
.summary-row dt {
  color: var(--t2);
  font-size: var(--text-sm);
  margin: 0;
}
.summary-row dd {
  color: var(--t1);
  font-size: var(--text-sm);
  margin: 0;
  text-align: right;
  min-width: 0;
  word-break: break-all;
}
.order-no-cell {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1);
}
.discount-amount {
  color: var(--green);
  margin-left: var(--sp-2);
}
.copy-btn {
  background: transparent;
  border: none;
  color: var(--t2);
  cursor: pointer;
  padding: 2px;
  border-radius: var(--r-xs);
  display: inline-flex;
  align-items: center;
}
.copy-btn:hover {
  background: var(--bg-in);
  color: var(--ac);
}
.status-cell {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
}
.countdown {
  color: var(--t2);
  font-size: var(--text-xs);
}
.mono {
  font-family: 'IBM Plex Mono', monospace;
}

.actions {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.support-hint {
  margin: var(--sp-2) 0 0;
  text-align: center;
  color: var(--t3);
  font-size: var(--text-xs);
}
.support-link {
  color: var(--ac);
  text-decoration: none;
  cursor: pointer;
}
.support-link:hover {
  text-decoration: underline;
}
</style>

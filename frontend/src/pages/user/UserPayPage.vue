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
const qrImageUrl = computed(() => invoice.value?.code_url ?? null)
const qrError = ref(false)

function onQrImageError() {
  qrError.value = true
}

function onQrImageLoad() {
  qrError.value = false
}

// ── Mobile H5 detection ──
// 移动端无法扫自己屏幕的二维码；改为直接跳转网关返回的 pay_url（H5 收银台）。
// 检测以 UA 为准，pointer:coarse 作为辅助。
const isMobile = (() => {
  if (typeof navigator === 'undefined') return false
  const ua = navigator.userAgent || ''
  if (/Android|iPhone|iPad|iPod|Mobile|Opera Mini|IEMobile/i.test(ua)) return true
  if (typeof window !== 'undefined' && window.matchMedia?.('(pointer: coarse)').matches && window.innerWidth < 768) return true
  return false
})()

const payUrl = computed(() => invoice.value?.pay_url ?? null)
const h5Launched = ref(false)

function launchH5Pay() {
  if (!payUrl.value) return
  h5Launched.value = true
  // 同窗口跳转，体验最接近原生「唤起支付宝」
  window.location.href = payUrl.value
}

// 移动端订单首次加载到 pay_url 后自动唤起一次
watch(payUrl, (url) => {
  if (!isMobile) return
  if (!url) return
  if (h5Launched.value) return
  if (phase.value !== 'pending') return
  launchH5Pay()
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
  <AuthShell icon="receipt_long" :subtitle="t('billing.pay.subtitle')">
    <div v-if="phase === 'loading' && !order" class="loading">
      <Spinner />
    </div>

    <div v-else-if="order" class="pay-content">
      <!-- Mobile H5 panel: 直接唤起支付宝 -->
      <div v-if="isMobile" class="h5-wrap">
        <div v-if="phase === 'pending'" class="h5-card">
          <MsIcon name="smartphone" size="lg" />
          <p class="h5-title">{{ t('billing.pay.h5Title') }}</p>
          <p class="h5-sub">{{ t('billing.pay.h5Sub') }}</p>
          <BaseButton variant="primary" :disabled="!payUrl" @click="launchH5Pay">
            <MsIcon name="open_in_new" size="sm" />
            {{ h5Launched ? t('billing.pay.h5Relaunch') : t('billing.pay.h5Launch') }}
          </BaseButton>
        </div>
        <div v-else-if="phase === 'paid'" class="h5-card h5-card--success">
          <MsIcon name="check_circle" size="lg" />
          <p class="h5-title">{{ t('billing.pay.successTitle') }}</p>
          <p class="h5-sub">{{ t('billing.pay.successCountdown', { n: redirectCountdown }) }}</p>
        </div>
        <div v-else-if="phase === 'processing'" class="h5-card h5-card--processing">
          <Spinner />
          <p class="h5-title">{{ t('billing.pay.processingTitle') }}</p>
          <p class="h5-sub">{{ t('billing.pay.processingSub') }}</p>
        </div>
        <div v-else-if="phase === 'expired'" class="h5-card h5-card--expired">
          <MsIcon name="error_outline" size="lg" />
          <p class="h5-title">{{ t('billing.pay.expiredTitle') }}</p>
        </div>
        <div v-else-if="phase === 'closed'" class="h5-card h5-card--closed">
          <MsIcon name="error_outline" size="lg" />
          <p class="h5-title">{{ t('billing.pay.closedTitle') }}</p>
        </div>
      </div>

      <!-- Desktop QR area with overlay states -->
      <div v-else class="qr-wrap">
        <img
          v-if="qrImageUrl"
          :src="qrImageUrl"
          alt="QR"
          class="qr-image"
          :class="{ 'qr-image--dim': phase !== 'pending' }"
          width="240"
          height="240"
          @load="onQrImageLoad"
          @error="onQrImageError"
        />
        <div v-else class="qr-placeholder" />

        <div v-if="!qrImageUrl && !qrError && phase === 'pending'" class="qr-loading">
          <Spinner />
        </div>

        <div v-if="qrError && phase === 'pending'" class="qr-overlay qr-overlay--error">
          <MsIcon name="error_outline" size="lg" />
          <p>{{ t('billing.pay.qrError') }}</p>
          <BaseButton size="sm" variant="ghost" @click="refresh">
            {{ t('billing.pay.retry') }}
          </BaseButton>
        </div>

        <div v-if="phase === 'paid'" class="qr-overlay qr-overlay--success">
          <MsIcon name="check_circle" size="lg" />
          <p class="overlay-title">{{ t('billing.pay.successTitle') }}</p>
          <p class="overlay-sub">
            {{ t('billing.pay.successCountdown', { n: redirectCountdown }) }}
          </p>
        </div>

        <div v-if="phase === 'processing'" class="qr-overlay qr-overlay--processing">
          <Spinner />
          <p class="overlay-title">{{ t('billing.pay.processingTitle') }}</p>
          <p class="overlay-sub">{{ t('billing.pay.processingSub') }}</p>
        </div>

        <div v-if="phase === 'expired'" class="qr-overlay qr-overlay--expired">
          <MsIcon name="error_outline" size="lg" />
          <p class="overlay-title">{{ t('billing.pay.expiredTitle') }}</p>
        </div>

        <div v-if="phase === 'closed'" class="qr-overlay qr-overlay--closed">
          <MsIcon name="error_outline" size="lg" />
          <p class="overlay-title">{{ t('billing.pay.closedTitle') }}</p>
        </div>
      </div>

      <!-- Amount -->
      <div class="amount-row">
        <span class="amount">¥{{ fenToYuan(order.total_fen) }}</span>
        <span class="amount-hint">{{ isMobile ? t('billing.pay.h5AmountHint') : t('billing.pay.scanHint') }}</span>
      </div>

      <div class="divider" />

      <!-- Summary -->
      <dl class="summary">
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
.loading {
  padding: var(--sp-6) 0;
  display: flex;
  justify-content: center;
}

.pay-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--sp-3);
}

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
.qr-image--dim {
  opacity: 0.18;
  filter: grayscale(1);
}
.qr-placeholder {
  width: 240px;
  height: 240px;
}
.qr-loading {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}
.qr-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--sp-2);
  text-align: center;
  padding: var(--sp-3);
  border-radius: var(--r-md);
}
.qr-overlay--success {
  background: color-mix(in srgb, var(--green) 92%, transparent);
  color: #fff;
}
.qr-overlay--processing {
  background: color-mix(in srgb, var(--blue) 92%, transparent);
  color: #fff;
}
.qr-overlay--expired,
.qr-overlay--closed {
  background: color-mix(in srgb, var(--bg) 88%, transparent);
  color: var(--t2);
}
.qr-overlay--error {
  background: color-mix(in srgb, var(--bg) 88%, transparent);
  color: var(--red);
}
.overlay-title {
  margin: 0;
  font-size: var(--text-md);
  font-weight: 600;
}
.overlay-sub {
  margin: 0;
  font-size: var(--text-sm);
  opacity: 0.85;
}

.h5-wrap {
  width: 100%;
  display: flex;
  justify-content: center;
}
.h5-card {
  width: 100%;
  max-width: 320px;
  padding: var(--sp-5) var(--sp-4);
  background: color-mix(in srgb, var(--ac) 6%, var(--bg-in));
  border: 1px solid color-mix(in srgb, var(--ac) 25%, transparent);
  border-radius: var(--r-md);
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: var(--sp-2);
  color: var(--t1);
}
.h5-card :deep(.ms-icon) {
  color: var(--ac);
}
.h5-card--success :deep(.ms-icon) { color: var(--green); }
.h5-card--processing :deep(.ms-icon) { color: var(--blue); }
.h5-card--expired :deep(.ms-icon),
.h5-card--closed :deep(.ms-icon) { color: var(--t3); }
.h5-title {
  margin: 0;
  font-size: var(--text-md);
  font-weight: 600;
}
.h5-sub {
  margin: 0 0 var(--sp-2);
  font-size: var(--text-sm);
  color: var(--t2);
}

.amount-row {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--sp-1);
  margin-top: var(--sp-2);
}
.amount {
  font-family: 'IBM Plex Mono', monospace;
  font-size: var(--text-xl);
  font-weight: 700;
  color: var(--ac);
}
.amount-hint {
  font-size: var(--text-xs);
  color: var(--t2);
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

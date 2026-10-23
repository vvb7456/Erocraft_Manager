<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import AuthShell from '@/components/auth/AuthShell.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import SupportModal from '@/components/billing/SupportModal.vue'
import { useApiFetch } from '@/composables/useApiFetch'
import { useConfirm } from '@/composables/useConfirm'
import { useOrderPolling } from '@/composables/useOrderPolling'
import { useToast } from '@/composables/useToast'

const route = useRoute()
const router = useRouter()
const { t } = useI18n({ useScope: 'global' })
const { get, post, del, handleError } = useApiFetch()
const { confirm } = useConfirm()
const { toast } = useToast()
const orderId = ref<string | number | null>(route.params.id ? String(route.params.id) : null)
const { data: order, error, refresh } = useOrderPolling(orderId)
const resolveFailed = ref(false)
const busy = ref(false)
const supportOpen = ref(false)
const countdown = ref(5)
let redirectTimer: ReturnType<typeof setInterval> | undefined

const paid = computed(() => order.value?.invoice?.status === 'paid'
  && !['closed', 'cancelled', 'refunding', 'refunded', 'manual_review'].includes(order.value.status))
const subtitle = computed(() => {
  if (error.value || resolveFailed.value) return t('billing.pay.queryFailed')
  if (!order.value) return t('billing.pay.statusLoading')
  if (paid.value) return t('billing.pay.successTitle')
  return order.value.status === 'pending' ? t('billing.pay.incompleteTitle') : t('billing.pay.closedTitle')
})

watch(paid, success => {
  clearInterval(redirectTimer)
  if (!success) return
  countdown.value = 5
  redirectTimer = setInterval(() => {
    countdown.value--
    if (countdown.value <= 0) goToServers()
  }, 1000)
})
onBeforeUnmount(() => clearInterval(redirectTimer))

function goToServers() {
  clearInterval(redirectTimer)
  void router.push('/servers')
}

async function continuePayment() {
  if (!order.value || busy.value) return
  busy.value = true
  try {
    const payment = await post<{ checkout_url: string }>(`/api/user/orders/${order.value.id}/payments`, {})
    window.location.assign(payment.checkout_url)
  } catch (failure) { handleError(failure); await refresh() }
  finally { busy.value = false }
}

async function copyOrderNo() {
  if (!order.value) return
  try {
    await navigator.clipboard.writeText(order.value.order_no)
    toast(t('billing.pay.orderNoCopied'), 'success')
  } catch { toast(t('billing.pay.copyFailed'), 'error') }
}

async function cancelOrder() {
  if (!order.value || busy.value) return
  if (!await confirm({
    title: t('billing.orderDetail.actions.cancelConfirmTitle'),
    message: t('billing.orderDetail.actions.cancelConfirmMessage'),
    confirmText: t('billing.orderDetail.actions.cancelConfirmBtn'),
    variant: 'danger',
  })) return
  busy.value = true
  try { await del(`/api/user/orders/${order.value.id}`) }
  catch (failure) { handleError(failure) }
  finally { await refresh(); busy.value = false }
}

async function resolveOrder() {
  if (orderId.value !== null) { await refresh(); return }
  resolveFailed.value = false
  try {
    const query = new URLSearchParams()
    if (route.query.business_order_id) query.set('business_order_id', String(route.query.business_order_id))
    else if (route.query.payment_id) query.set('payment_id', String(route.query.payment_id))
    const result = await get<{ id: number }>(`/api/user/orders/resolve?${query}`)
    orderId.value = result.id
    await router.replace(`/pay/${result.id}`)
  } catch (failure) { resolveFailed.value = true; handleError(failure) }
}

onMounted(() => { if (orderId.value === null) void resolveOrder() })
</script>

<template>
  <AuthShell icon="receipt_long" :subtitle="subtitle">
    <div class="pay-content">
      <div class="pay-status" :class="{ 'pay-status--success': paid }">
        <MsIcon v-if="order || error || resolveFailed" :name="paid ? 'check_circle' : 'error_outline'" size="lg" />
        <p v-if="paid" class="status-sub">{{ t('billing.pay.successCountdown', { n: countdown }) }}</p>
        <BaseButton v-if="error || resolveFailed" size="sm" variant="ghost" @click="resolveOrder">{{ t('billing.pay.retry') }}</BaseButton>
      </div>

      <template v-if="order">
        <div class="amount-row">
          <span class="amount-label">{{ t('billing.pay.amountLabel') }}</span>
          <span class="amount">¥{{ (order.total_fen / 100).toFixed(2) }}</span>
        </div>
        <div class="divider" />
        <dl class="summary">
          <div class="summary-row"><dt>{{ t('billing.pay.summaryPlan') }}</dt><dd>{{ order.plan_name }}</dd></div>
          <div class="summary-row"><dt>{{ t('billing.pay.summaryDuration') }}</dt><dd>{{ t('billing.pay.summaryDays', { days: order.total_days }) }}</dd></div>
          <div v-if="order.coupon_id && order.coupon_discount_fen" class="summary-row">
            <dt>{{ t('billing.coupons.applyHint') }}</dt>
            <dd><span v-if="order.coupon_code" class="mono">{{ order.coupon_code }}</span><span class="discount-amount mono">−¥{{ (order.coupon_discount_fen / 100).toFixed(2) }}</span></dd>
          </div>
          <div class="summary-row">
            <dt>{{ t('billing.pay.summaryOrderNo') }}</dt>
            <dd class="order-no-cell">
              <span class="mono">{{ order.order_no }}</span>
              <button class="copy-btn" :title="t('billing.pay.copy')" @click="copyOrderNo"><MsIcon name="content_copy" size="sm" /></button>
            </dd>
          </div>
        </dl>
        <div class="divider" />
      </template>

      <div class="actions">
        <BaseButton v-if="paid" variant="primary" @click="goToServers">{{ t('billing.pay.btnGoServersNow') }}</BaseButton>
        <BaseButton v-else-if="order?.status === 'pending'" variant="primary" :loading="busy" @click="continuePayment">{{ t('billing.orderDetail.actions.pay') }}</BaseButton>
        <BaseButton v-else-if="order" variant="primary" @click="router.push('/plans')">{{ t('billing.pay.btnReorder') }}</BaseButton>
        <BaseButton v-if="order?.status === 'pending'" variant="ghost" :disabled="busy" @click="cancelOrder">{{ t('billing.orderDetail.actions.cancel') }}</BaseButton>
        <BaseButton v-if="!paid" variant="ghost" @click="goToServers"><MsIcon name="home" size="sm" />{{ t('billing.pay.btnDashboard') }}</BaseButton>
      </div>
      <p class="support-hint">{{ t('billing.pay.supportHint') }} <a href="#" class="support-link" @click.prevent="supportOpen = true">{{ t('billing.pay.supportLink') }}</a></p>
    </div>
    <SupportModal v-model="supportOpen" />
  </AuthShell>
</template>

<style scoped>
.pay-content { display: flex; flex-direction: column; align-items: center; gap: var(--sp-3); }
.pay-status { display: flex; flex-direction: column; align-items: center; gap: var(--sp-2); text-align: center; padding: var(--sp-4) 0; min-height: 80px; justify-content: center; color: var(--t3); }
.pay-status :deep(.ms-icon) { font-size: 36px; line-height: 1; }
.pay-status--success :deep(.ms-icon) { color: var(--green); }
.status-sub { margin: 0; font-size: var(--text-sm); color: var(--t2); }
.amount-row { display: flex; align-items: baseline; justify-content: space-between; width: 100%; margin-top: var(--sp-2); }
.amount-label { color: var(--t2); font-size: var(--text-sm); }
.amount { font-family: var(--font-mono); font-size: var(--text-xl); font-weight: 700; color: var(--ac); text-align: right; }
.divider { width: 100%; height: 1px; background: var(--bd); margin: var(--sp-2) 0; }
.summary { width: 100%; margin: 0; display: flex; flex-direction: column; gap: var(--sp-2); }
.summary-row { display: flex; align-items: center; justify-content: space-between; gap: var(--sp-3); }
.summary-row dt { color: var(--t2); font-size: var(--text-sm); margin: 0; }
.summary-row dd { color: var(--t1); font-size: var(--text-sm); margin: 0; text-align: right; min-width: 0; word-break: break-all; }
.order-no-cell { display: inline-flex; align-items: center; gap: var(--sp-1); }
.discount-amount { color: var(--green); margin-left: var(--sp-2); }
.copy-btn { background: transparent; border: none; color: var(--t2); cursor: pointer; padding: 2px; border-radius: var(--r-xs); display: inline-flex; align-items: center; }
.copy-btn:hover { background: var(--bg-in); color: var(--ac); }
.mono { font-family: var(--font-mono); }
.actions { width: 100%; display: flex; flex-direction: column; gap: var(--sp-2); }
.support-hint { margin: var(--sp-2) 0 0; text-align: center; color: var(--t3); font-size: var(--text-xs); }
.support-link { color: var(--ac); text-decoration: none; cursor: pointer; }
.support-link:hover { text-decoration: underline; }
</style>

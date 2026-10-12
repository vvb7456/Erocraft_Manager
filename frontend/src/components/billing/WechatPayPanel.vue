<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import QRCode from 'qrcode'
import BaseButton from '@/components/ui/BaseButton.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'

const props = withDefaults(defineProps<{
  orderId: string
  scene: string | null
  codeUrl: string | null
  autoStart?: boolean
  disabled?: boolean
}>(), { autoStart: true, disabled: false })
const emit = defineEmits<{ refresh: [] }>()
const { t } = useI18n()
const { post, error } = useApiFetch()
const { toast } = useToast()
const busy = ref(false)
const launched = ref(false)
const image = ref('')
const link = ref('')
const code = ref(props.codeUrl || '')
const inWechat = /MicroMessenger/i.test(navigator.userAgent)
const mobile = /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent) || (navigator.maxTouchPoints > 1 && /Macintosh/.test(navigator.userAgent))
const selectedScene = computed(() => props.scene || (inWechat ? 'jsapi' : mobile ? 'miniprogram' : 'native'))
interface PaymentParameters { appId: string; timeStamp: string; nonceStr: string; package: string; signType: string; paySign: string }
interface Prepared { code_url?: string; authorize_url?: string; url_link?: string; parameters?: PaymentParameters }
interface Bridge { invoke(method: string, params: PaymentParameters, callback: (result: { err_msg: string }) => void): void }
let alive = true
let queryTimer: ReturnType<typeof setInterval> | null = null
let launchTimer: ReturnType<typeof setTimeout> | null = null
let querying = false
let clearBridgeWait: (() => void) | null = null

function waitForBridge(): Promise<Bridge> {
  const current = () => (window as Window & { WeixinJSBridge?: Bridge }).WeixinJSBridge
  if (current()) return Promise.resolve(current()!)
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { cleanup(); reject(new Error(t('wechat.bridgeUnavailable'))) }, 8000)
    const ready = () => { const bridge = current(); if (bridge) { cleanup(); resolve(bridge) } }
    const cleanup = () => { clearTimeout(timer); document.removeEventListener('WeixinJSBridgeReady', ready); clearBridgeWait = null }
    clearBridgeWait = () => { cleanup(); reject(new Error(t('wechat.bridgeUnavailable'))) }
    document.addEventListener('WeixinJSBridgeReady', ready)
  })
}
async function checkPayment(silent = false) {
  if (querying) return
  querying = true
  try {
    if (silent) {
      await fetch(`/api/payments/wechat/orders/${props.orderId}/refresh`, { method: 'POST' })
    } else {
      await post(`/api/payments/wechat/orders/${props.orderId}/refresh`)
    }
    if (alive) emit('refresh')
  } finally { querying = false }
}
async function pay() {
  if (!alive || props.disabled || busy.value) return
  if (launchTimer !== null) {
    clearTimeout(launchTimer)
    launchTimer = null
  }
  if (selectedScene.value === 'jsapi' && !inWechat) { toast(t('wechat.originalBrowser'), 'error'); return }
  if (link.value) { launched.value = true; window.location.assign(link.value); return }
  busy.value = true
  try {
    const data = await post<Prepared>(`/api/payments/wechat/orders/${props.orderId}/prepare`, { scene: selectedScene.value })
    if (!data || !alive || props.disabled) return
    if (data.code_url) code.value = data.code_url
    if (data.authorize_url) { launched.value = true; window.location.assign(data.authorize_url); return }
    if (data.url_link) {
      link.value = data.url_link
      launched.value = true
      window.location.assign(link.value)
      return
    }
    if (data.parameters) {
      const bridge = await waitForBridge()
      if (!alive || props.disabled) return
      launched.value = true
      const result = await new Promise<string>(resolve => bridge.invoke('getBrandWCPayRequest', data.parameters!, r => resolve(r.err_msg)))
      if (!alive) return
      toast(t(result.endsWith(':cancel') ? 'wechat.cancelled' : result.endsWith(':ok') ? 'wechat.confirming' : 'wechat.failed'), result.endsWith(':fail') ? 'error' : 'info')
      await checkPayment()
    }
    emit('refresh')
  } catch (e) {
    if (alive) toast(e instanceof Error ? e.message : t('wechat.failed'), 'error')
  } finally { busy.value = false }
}
watch(() => props.codeUrl, value => { if (value) code.value = value })
watch(code, async value => {
  image.value = value ? await QRCode.toDataURL(value, { width: 240, margin: 2 }) : ''
}, { immediate: true })
function visible() { if (document.visibilityState === 'visible') void checkPayment(true) }
onMounted(() => {
  if (props.autoStart) {
    if (selectedScene.value === 'native') {
      if (!code.value) void pay()
    } else {
      launchTimer = setTimeout(() => { void pay() }, 600)
    }
  }
  queryTimer = setInterval(() => { if (document.visibilityState === 'visible') void checkPayment(true) }, 10000)
  document.addEventListener('visibilitychange', visible)
})
onBeforeUnmount(() => {
  alive = false
  if (queryTimer) clearInterval(queryTimer)
  if (launchTimer !== null) clearTimeout(launchTimer)
  clearBridgeWait?.()
  document.removeEventListener('visibilitychange', visible)
})
</script>

<template>
  <section class="wechat-pay">
    <template v-if="image">
      <img :src="image" :alt="t('wechat.scan')" width="240" height="240" />
      <p>{{ t(mobile ? 'wechat.scanOtherPhone' : 'wechat.scan') }}</p>
    </template>
    <BaseButton v-else variant="primary" :disabled="busy || disabled" @click="pay">
      <MsIcon name="open_in_new" size="sm" />
      {{ busy ? t('wechat.preparing') : launched ? t('wechat.reopen') : t('wechat.pay') }}
    </BaseButton>
    <p v-if="error" class="error">{{ error }}</p>
    <BaseButton variant="ghost" size="sm" @click="checkPayment()">{{ t('wechat.check') }}</BaseButton>
  </section>
</template>

<style scoped>
.wechat-pay { display: flex; flex-direction: column; gap: var(--sp-3); align-items: center; text-align: center; width: 100%; }
.wechat-pay img { max-width: 100%; border-radius: var(--r-md); }
p { margin: 0; color: var(--t2); font-size: var(--text-sm); }
.error { color: var(--red); }
</style>

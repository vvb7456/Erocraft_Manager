import { onBeforeUnmount, onMounted, ref, type Ref } from 'vue'
import { useApiFetch } from '@/composables/useApiFetch'

/**
 * useOrderPolling — polls ``GET /api/user/orders/:id`` on a tunable timer.
 *
 * - 3s while page is visible (covers payment-callback latency and the
 *   apply happy path — typically <5s, or ~65s after one retry).
 * - When the order has been ``processing`` for more than
 *   ``PROCESSING_TAIL_MS`` we assume the apply engine has entered its
 *   long retry chain (5min/15min/1h/4h) and downshift to 10s. There is
 *   nothing time-sensitive on the UI in that window.
 * - When ``document.visibilityState === 'hidden'``, downshifts to 10s
 *   regardless of state, to conserve battery / quota.
 * - Returns to fast cadence on ``visibilitychange → visible`` and
 *   triggers one immediate fetch (covers the mobile flow where the
 *   user goes off to Alipay's app and comes back).
 * - Stops automatically when the order enters a terminal state.
 *
 * Returns reactive ``order`` / ``loading`` / ``error`` plus ``stop()`` /
 * ``refresh()`` helpers.
 */

interface OrderInvoice {
  id: number
  invoice_no: string
  status: string
  total_fen: number
  currency_code: string
  due_at: string | null
  paid_at: string | null
  gateway_code: string
  gateway_prepay_id: string | null
  transaction_id: string | null
  code_url: string | null
  pay_url: string | null
}

export interface OrderDetail {
  id: number
  order_no: string
  plan_name: string
  plan_code: string
  total_fen: number
  total_days: number
  currency_code: string
  status: string
  period_count: number
  created_at: string
  updated_at: string
  applied_at: string | null
  closed_at: string | null
  invoice: OrderInvoice | null
  coupon_id: number | null
  coupon_code: string | null
  coupon_discount_fen: number | null
}

const TERMINAL_STATUSES = new Set([
  'paid',
  'applied',
  'closed',
  'cancelled',
  'refunded',
  'refunding',
  'manual_review',
])

const VISIBLE_INTERVAL_MS = 3000
const HIDDEN_INTERVAL_MS = 10000
const PROCESSING_TAIL_MS = 30000
/**
 * After the order has been seen in ``processing`` for this long, treat it
 * as having entered the apply-engine retry chain (``RETRY_DELAYS`` starts
 * at 60s) and stretch the polling interval. The happy path normally
 * resolves well under this threshold.
 */

export function useOrderPolling(orderId: Ref<number | string | null>) {
  const { get } = useApiFetch()

  const data = ref<OrderDetail | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  let timer: ReturnType<typeof setTimeout> | null = null
  let stopped = false
  let processingSince: number | null = null

  function clear() {
    if (timer !== null) {
      clearTimeout(timer)
      timer = null
    }
  }

  function isTerminal(): boolean {
    const status = data.value?.status
    return status ? TERMINAL_STATUSES.has(status) : false
  }

  async function fetchOnce(): Promise<void> {
    if (stopped || orderId.value == null) return
    loading.value = true
    try {
      const res = await get<OrderDetail>(
        `/api/user/orders/${orderId.value}`,
        { silent: true },
      )
      if (res) {
        data.value = res
        error.value = null
        if (res.status === 'processing') {
          if (processingSince === null) processingSince = Date.now()
        } else {
          processingSince = null
        }
      } else {
        error.value = 'fetch_failed'
      }
    } finally {
      loading.value = false
    }
  }

  function schedule(): void {
    clear()
    if (stopped || isTerminal()) return
    const hidden =
      typeof document !== 'undefined' && document.visibilityState === 'hidden'
    const inProcessingTail =
      data.value?.status === 'processing' &&
      processingSince !== null &&
      Date.now() - processingSince >= PROCESSING_TAIL_MS
    const interval = hidden || inProcessingTail
      ? HIDDEN_INTERVAL_MS
      : VISIBLE_INTERVAL_MS
    timer = setTimeout(async () => {
      await fetchOnce()
      schedule()
    }, interval)
  }

  function onVisibilityChange(): void {
    if (stopped) return
    if (document.visibilityState === 'visible') {
      // Fire an immediate refresh when the user comes back, then resume.
      fetchOnce().finally(() => schedule())
    } else {
      // Re-arm with the slower interval right away.
      schedule()
    }
  }

  async function refresh(): Promise<void> {
    await fetchOnce()
    schedule()
  }

  function stop(): void {
    stopped = true
    clear()
  }

  onMounted(() => {
    document.addEventListener('visibilitychange', onVisibilityChange)
    refresh()
  })

  onBeforeUnmount(() => {
    document.removeEventListener('visibilitychange', onVisibilityChange)
    stop()
  })

  return {
    data,
    loading,
    error,
    refresh,
    stop,
  }
}

import { onBeforeUnmount, ref, watch, type Ref } from 'vue'
import { useApiFetch } from '@/composables/useApiFetch'
import type { UserOrder } from '@/types/billing'

export function useOrderPolling(orderId: Ref<number | string | null | undefined>) {
  const { get } = useApiFetch()
  const data = ref<UserOrder | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  let timer: ReturnType<typeof setTimeout> | undefined
  let revision = 0
  let stopped = false

  function schedule() {
    clearTimeout(timer)
    if (stopped || orderId.value == null) return
    const order = data.value
    const active = !order || order.status === 'pending'
    if (active) timer = setTimeout(() => refresh(), document.visibilityState === 'hidden' ? 10000 : 3000)
  }

  async function refresh() {
    if (stopped || orderId.value == null) return
    clearTimeout(timer)
    const current = ++revision
    loading.value = true
    try {
      const result = await get<UserOrder>(`/api/user/orders/${orderId.value}`, { silent: true })
      if (current !== revision || stopped) return
      data.value = result
      error.value = null
    } catch (failure) {
      if (current === revision) error.value = String(failure)
    } finally {
      if (current === revision) { loading.value = false; schedule() }
    }
  }

  function stop() { stopped = true; revision++; clearTimeout(timer) }
  function visible() { if (document.visibilityState === 'visible') void refresh() }
  watch(orderId, () => { revision++; data.value = null; void refresh() }, { immediate: true })
  document.addEventListener('visibilitychange', visible)
  onBeforeUnmount(() => { stop(); document.removeEventListener('visibilitychange', visible) })
  return { data, loading, error, refresh, stop }
}

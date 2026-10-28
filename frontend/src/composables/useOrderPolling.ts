import { onBeforeUnmount, ref, watch, type Ref } from 'vue'
import { useApiFetch } from '@/composables/useApiFetch'
import type { UserOrder } from '@/types/billing'

export function useOrderPolling(orderId: Ref<number | string | null | undefined>) {
  const { get } = useApiFetch()
  const data = ref<UserOrder | null>(null)
  const error = ref(false)
  let timer: ReturnType<typeof setTimeout> | undefined
  let revision = 0
  let stopped = false

  function schedule() {
    clearTimeout(timer)
    if (stopped || orderId.value == null) return
    const order = data.value
    const active = !order || ['pending', 'processing'].includes(order.status)
    if (active) timer = setTimeout(() => refresh(), document.visibilityState === 'hidden' ? 10000 : 3000)
  }

  async function refresh() {
    if (stopped || orderId.value == null) return
    clearTimeout(timer)
    const current = ++revision
    try {
      const result = await get<UserOrder>(`/api/user/orders/${orderId.value}`, { silent: true })
      if (current !== revision || stopped) return
      data.value = result
      error.value = false
    } catch {
      if (current === revision && !stopped) error.value = data.value === null
    } finally {
      if (current === revision) schedule()
    }
  }

  function setOrder(order: UserOrder) {
    revision++
    data.value = order
    error.value = false
    schedule()
  }

  function stop() { stopped = true; revision++; clearTimeout(timer) }
  function visible() {
    if (document.visibilityState === 'visible' && (!data.value || ['pending', 'processing'].includes(data.value.status))) void refresh()
  }
  watch(orderId, () => { revision++; clearTimeout(timer); data.value = null; error.value = false; void refresh() }, { immediate: true })
  document.addEventListener('visibilitychange', visible)
  onBeforeUnmount(() => { stop(); document.removeEventListener('visibilitychange', visible) })
  return { data, error, refresh, setOrder }
}

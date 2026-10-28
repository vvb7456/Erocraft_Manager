import { onBeforeUnmount, onMounted, readonly, ref, toValue, watch, type MaybeRefOrGetter, type WatchStopHandle } from 'vue'
import { createSupportConnection, type SupportConnectionStatus } from '@/utils/supportConnection'

const listeners = new Set<() => void>()
const status = ref<SupportConnectionStatus>('connecting')
export const supportConnectionStatus = readonly(status)

function notify() {
  for (const listener of listeners) listener()
}

export function useSupportConnection(identity: MaybeRefOrGetter<string>, onExpired: () => void) {
  let stop: WatchStopHandle | undefined
  let disconnect: (() => void) | undefined
  onMounted(() => {
    stop = watch(() => toValue(identity), value => {
      disconnect?.()
      status.value = 'connecting'
      disconnect = value ? createSupportConnection({
        change: notify,
        status: value => { status.value = value },
        expired: onExpired,
      }) : undefined
    }, { immediate: true, flush: 'sync' })
  })
  onBeforeUnmount(() => { stop?.(); disconnect?.() })
}

export function useSupportEvents(onChange: () => void, enabled: MaybeRefOrGetter<boolean> = true) {
  let stop: WatchStopHandle | undefined
  function unsubscribe() {
    listeners.delete(onChange)
  }
  onMounted(() => {
    stop = watch(() => toValue(enabled), value => {
      if (!value) { unsubscribe(); return }
      listeners.add(onChange)
    }, { immediate: true })
  })
  onBeforeUnmount(() => {
    stop?.()
    unsubscribe()
  })
}

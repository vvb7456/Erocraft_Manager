import { onBeforeUnmount, onMounted } from 'vue'

const listeners = new Set<() => void>()
let source: EventSource | null = null

function notify() {
  for (const listener of listeners) listener()
}

function disconnect() {
  source?.close()
  source = null
}

function connect() {
  if (source || !listeners.size || document.visibilityState !== 'visible') return
  source = new EventSource('/api/support/events')
  source.addEventListener('change', notify)
  source.addEventListener('expired', () => {
    disconnect()
    notify()
  })
}

function onVisibilityChange() {
  if (document.visibilityState === 'visible') connect()
  else disconnect()
}

export function useSupportEvents(onChange: () => void) {
  onMounted(() => {
    if (!listeners.size) document.addEventListener('visibilitychange', onVisibilityChange)
    listeners.add(onChange)
    connect()
  })
  onBeforeUnmount(() => {
    listeners.delete(onChange)
    if (!listeners.size) {
      disconnect()
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
  })
}

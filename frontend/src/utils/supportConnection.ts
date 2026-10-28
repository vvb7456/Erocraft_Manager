export type SupportConnectionStatus = 'connecting' | 'connected' | 'reconnecting' | 'offline' | 'disconnected'

interface Callbacks {
  change: () => void
  status: (value: SupportConnectionStatus) => void
  expired: () => void
}

export function createSupportConnection(callbacks: Callbacks) {
  const source = new EventSource('/api/support/events')
  source.addEventListener('open', () => {
    callbacks.status('connected')
    callbacks.change()
  })
  source.addEventListener('change', callbacks.change)
  source.addEventListener('error', () => {
    if (source.readyState === EventSource.CLOSED) {
      callbacks.status('disconnected')
      callbacks.expired()
    } else callbacks.status(navigator.onLine ? 'reconnecting' : 'offline')
  })
  return () => source.close()
}

export type SupportConnectionStatus = 'connecting' | 'connected' | 'reconnecting' | 'offline' | 'disconnected'

interface Callbacks {
  change: () => void
  status: (value: SupportConnectionStatus) => void
  expired: () => void
}

// Server sends a heartbeat every 15s; 3 missed intervals indicate a half-open socket or sleep resume.
const STALE_MS = 45_000
const CHECK_MS = 15_000

export function createSupportConnection(callbacks: Callbacks) {
  let source: EventSource | null = null
  let retryTimer: ReturnType<typeof setTimeout> | undefined
  let retryDelay = 3_000
  let lastActivity = 0
  let disposed = false

  function close() {
    clearTimeout(retryTimer)
    retryTimer = undefined
    source?.close()
    source = null
  }

  function touch() {
    lastActivity = Date.now()
    retryDelay = 3_000
    callbacks.status('connected')
  }

  function scheduleReconnect() {
    if (disposed || retryTimer || navigator.onLine === false) return
    retryTimer = setTimeout(() => {
      retryTimer = undefined
      connect()
    }, retryDelay)
    retryDelay = Math.min(retryDelay * 2, 30_000)
  }

  function connect() {
    if (disposed) return
    if (navigator.onLine === false) {
      close()
      callbacks.status('offline')
      return
    }
    close()
    lastActivity = Date.now()
    const current = new EventSource('/api/support/events')
    source = current
    // Initial sync is driven by the server's opening `change` frame to avoid duplicate fetches on connect.
    current.addEventListener('open', () => {
      if (source === current) touch()
    })
    current.addEventListener('change', () => {
      if (source !== current) return
      touch()
      callbacks.change()
    })
    current.addEventListener('heartbeat', () => {
      if (source === current) touch()
    })
    current.addEventListener('error', () => {
      if (source !== current) return
      if (navigator.onLine === false) {
        close()
        callbacks.status('offline')
        return
      }
      if (current.readyState === EventSource.CLOSED) {
        close()
        callbacks.status('reconnecting')
        callbacks.expired()
        // EventSource permanently stops on non-200 responses (e.g. 502 during backend restart); keep retrying unless logged out.
        scheduleReconnect()
      } else {
        callbacks.status('reconnecting')
      }
    })
  }

  function check() {
    if (disposed || retryTimer || document.visibilityState !== 'visible' || navigator.onLine === false) return
    if (!source || source.readyState === EventSource.CLOSED || Date.now() - lastActivity > STALE_MS) {
      callbacks.status('reconnecting')
      connect()
    }
  }

  function onOnline() {
    retryDelay = 3_000
    callbacks.status('reconnecting')
    connect()
  }

  function onOffline() {
    close()
    callbacks.status('offline')
  }

  const watchdog = setInterval(check, CHECK_MS)
  window.addEventListener('online', onOnline)
  window.addEventListener('offline', onOffline)
  window.addEventListener('focus', check)
  window.addEventListener('pageshow', check)
  document.addEventListener('visibilitychange', check)
  connect()

  return () => {
    disposed = true
    clearInterval(watchdog)
    close()
    window.removeEventListener('online', onOnline)
    window.removeEventListener('offline', onOffline)
    window.removeEventListener('focus', check)
    window.removeEventListener('pageshow', check)
    document.removeEventListener('visibilitychange', check)
  }
}

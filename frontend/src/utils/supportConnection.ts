export type SupportConnectionStatus = 'connecting' | 'connected' | 'reconnecting' | 'offline' | 'disconnected'

interface Callbacks {
  change: () => void
  status: (value: SupportConnectionStatus) => void
  expired: () => void
}
type Signal = { type: 'status' | 'change' | 'hello' | 'expired'; status: SupportConnectionStatus; at: number }

export function createSupportConnection(identity: string, callbacks: Callbacks) {
  const name = `support-events:${identity}`
  let source: EventSource | null = null
  let channel: BroadcastChannel | null = null
  let pending: AbortController | null = null
  let release: (() => void) | null = null
  let timer: ReturnType<typeof setInterval> | undefined
  let state: SupportConnectionStatus = 'connecting'
  let active = false
  let disposed = false
  let leader = false
  let expired = false
  let lastLeader = 0
  let lastReceived = 0

  function publish(type: Signal['type']) {
    channel?.postMessage({ type, status: state, at: Date.now() } satisfies Signal)
  }
  function status(value: SupportConnectionStatus) {
    state = value
    callbacks.status(value)
  }
  function disconnect() {
    source?.close()
    source = null
  }
  function connect() {
    if (source || !active || expired) return
    const current = new EventSource('/api/support/events')
    source = current
    lastReceived = Date.now()
    function received() {
      lastReceived = Date.now()
      status('connected')
    }
    current.addEventListener('open', () => {
      if (source !== current) return
      received()
      if (leader) publish('change')
      callbacks.change()
    })
    current.addEventListener('change', () => {
      if (source !== current) return
      received()
      if (leader) publish('change')
      callbacks.change()
    })
    current.addEventListener('heartbeat', () => {
      if (source !== current) return
      received()
      if (leader) publish('status')
    })
    current.addEventListener('error', () => {
      if (source !== current) return
      status(navigator.onLine === false ? 'offline' : 'reconnecting')
      if (leader) publish('status')
    })
    current.addEventListener('expired', () => {
      if (source !== current) return
      expired = true
      disconnect()
      status('disconnected')
      if (leader) publish('expired')
      callbacks.expired()
    })
  }
  function maintain() {
    if (!active || expired) return
    if (source && (Date.now() - lastReceived > 15_000 || source.readyState === EventSource.CLOSED)) {
      disconnect()
      status('reconnecting')
    }
    // A frozen leader may not release its lock on every browser. A live tab can temporarily take over reception.
    if (leader || !channel || Date.now() - lastLeader > 12_000) connect()
  }
  function start() {
    if (active || disposed || expired) return
    if (navigator.onLine === false) { status('offline'); return }
    active = true
    lastLeader = Date.now()
    status(state === 'connecting' ? 'connecting' : 'reconnecting')
    if (typeof BroadcastChannel !== 'undefined' && navigator.locks) {
      try { channel = new BroadcastChannel(name) } catch { /* Private browser contexts may disable cross-tab coordination. */ }
    }
    if (channel) {
      const currentChannel = channel
      currentChannel.onmessage = (event: MessageEvent<Signal>) => {
        if (channel !== currentChannel || leader) {
          if (channel === currentChannel && event.data?.type === 'hello') publish('status')
          return
        }
        const data = event.data
        if (!data || data.type === 'hello' || !Number.isFinite(data.at) || Date.now() - data.at > 12_000) return
        lastLeader = data.at
        disconnect()
        const previous = state
        status(data.status)
        if (data.type === 'expired') { expired = true; callbacks.expired() }
        else if (data.type === 'change' || (previous !== 'connected' && state === 'connected')) callbacks.change()
      }
      const request = new AbortController()
      pending = request
      void navigator.locks.request(name, { signal: request.signal }, async () => {
        if (!active || request.signal.aborted) return
        leader = true
        connect()
        publish('status')
        await new Promise<void>(resolve => { release = resolve })
      }).catch(() => {
        if (active && !request.signal.aborted) {
          channel?.close()
          channel = null
          connect()
        }
      })
      publish('hello')
    } else connect()
    timer = setInterval(maintain, 5_000)
  }
  function pause() {
    active = false
    clearInterval(timer)
    pending?.abort()
    pending = null
    release?.()
    release = null
    leader = false
    disconnect()
    channel?.close()
    channel = null
  }
  function recover() {
    if (document.visibilityState !== 'visible') return
    start()
    maintain()
    callbacks.change()
  }
  function offline() { pause(); status('offline') }
  function online() { start(); maintain(); callbacks.change() }
  function suspend() { pause(); status('reconnecting') }
  window.addEventListener('online', online)
  window.addEventListener('offline', offline)
  window.addEventListener('focus', recover)
  window.addEventListener('pageshow', online)
  window.addEventListener('pagehide', suspend)
  document.addEventListener('visibilitychange', recover)
  document.addEventListener('freeze', suspend)
  document.addEventListener('resume', online)
  start()

  return () => {
    disposed = true
    pause()
    window.removeEventListener('online', online)
    window.removeEventListener('offline', offline)
    window.removeEventListener('focus', recover)
    window.removeEventListener('pageshow', online)
    window.removeEventListener('pagehide', suspend)
    document.removeEventListener('visibilitychange', recover)
    document.removeEventListener('freeze', suspend)
    document.removeEventListener('resume', online)
  }
}

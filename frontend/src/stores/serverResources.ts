import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export interface ServerResource {
  state: string
  isSuspended: boolean
  cpu: number
  memoryBytes: number
  diskBytes: number
  networkRx: number
  networkTx: number
  uptime: number
  updatedAt: number
  /** True when resource polling fails (Wings unreachable) */
  stale: boolean
}

interface Subscriber {
  serverIds: number[] | 'all'
  interval: number
}

export const useServerResourceStore = defineStore('serverResources', () => {
  const resources = ref<Record<number, ServerResource>>({})
  const subscribers = ref<Map<string, Subscriber>>(new Map())

  let pollTimer: ReturnType<typeof setInterval> | null = null

  // ── Computed: effective polling interval (smallest among subscribers) ──
  const effectiveInterval = computed(() => {
    let min = Infinity
    for (const sub of subscribers.value.values()) {
      min = Math.min(min, sub.interval)
    }
    return min === Infinity ? 10000 : min
  })

  // ── Computed: union of all subscribed server IDs ──
  const activeServerIds = computed(() => {
    const ids = new Set<number>()
    for (const sub of subscribers.value.values()) {
      if (sub.serverIds === 'all') continue
      sub.serverIds.forEach(id => ids.add(id))
    }
    return [...ids]
  })

  const hasAllSubscriber = computed(() => {
    for (const sub of subscribers.value.values()) {
      if (sub.serverIds === 'all') return true
    }
    return false
  })

  // ── Fetch resources for given server IDs ──
  async function fetchResources(serverIds: number[]) {
    await Promise.allSettled(serverIds.map(async (id) => {
      try {
        const res = await fetch(`/api/user/servers/${id}/resources`)
        if (!res.ok) {
          // Mark stale on failure
          const existing = resources.value[id]
          if (existing) {
            existing.stale = true
          } else {
            resources.value[id] = {
              state: 'offline', isSuspended: false,
              cpu: 0, memoryBytes: 0, diskBytes: 0,
              networkRx: 0, networkTx: 0, uptime: 0,
              updatedAt: Date.now(), stale: true,
            }
          }
          return
        }
        const data = await res.json()
        const utilization = data.resources || data.utilization || {}
        resources.value[id] = {
          state: data.state || 'offline',
          isSuspended: !!data.isSuspended,
          cpu: utilization.cpu_absolute ?? 0,
          memoryBytes: utilization.memory_bytes ?? 0,
          diskBytes: utilization.disk_bytes ?? 0,
          networkRx: utilization.network?.rx_bytes ?? utilization.network_rx_bytes ?? 0,
          networkTx: utilization.network?.tx_bytes ?? utilization.network_tx_bytes ?? 0,
          uptime: utilization.uptime ?? 0,
          updatedAt: Date.now(),
          stale: false,
        }
      } catch {
        // Mark stale on network error
        const existing = resources.value[id]
        if (existing) {
          existing.stale = true
        } else {
          resources.value[id] = {
            state: 'offline', isSuspended: false,
            cpu: 0, memoryBytes: 0, diskBytes: 0,
            networkRx: 0, networkTx: 0, uptime: 0,
            updatedAt: Date.now(), stale: true,
          }
        }
      }
    }))
  }

  // ── Poll tick ──
  async function pollTick() {
    const ids = activeServerIds.value
    if (ids.length > 0) {
      await fetchResources(ids)
    }
  }

  // ── Restart polling with current effective interval ──
  function restartPolling() {
    if (pollTimer) clearInterval(pollTimer)
    if (subscribers.value.size === 0) return
    pollTimer = setInterval(pollTick, effectiveInterval.value)
  }

  // ── Subscribe: register a polling subscriber ──
  function subscribe(key: string, serverIds: number[] | 'all', interval = 10000) {
    const prev = subscribers.value.get(key)
    subscribers.value.set(key, { serverIds, interval })

    // Trigger immediate fetch for new IDs
    if (serverIds !== 'all') {
      const prevIds = new Set(prev?.serverIds === 'all' ? [] : (prev?.serverIds ?? []))
      const newIds = serverIds.filter(id => !prevIds.has(id))
      if (newIds.length > 0) fetchResources(newIds)
    }

    restartPolling()
  }

  // ── Unsubscribe: remove a polling subscriber ──
  function unsubscribe(key: string) {
    subscribers.value.delete(key)
    if (subscribers.value.size === 0) {
      if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
    } else {
      restartPolling()
    }
  }

  // ── Update one server's resources directly (e.g., from WebSocket) ──
  function updateOne(serverId: number, data: Partial<ServerResource>) {
    const existing = resources.value[serverId]
    resources.value[serverId] = {
      state: data.state ?? existing?.state ?? 'offline',
      isSuspended: data.isSuspended ?? existing?.isSuspended ?? false,
      cpu: data.cpu ?? existing?.cpu ?? 0,
      memoryBytes: data.memoryBytes ?? existing?.memoryBytes ?? 0,
      diskBytes: data.diskBytes ?? existing?.diskBytes ?? 0,
      networkRx: data.networkRx ?? existing?.networkRx ?? 0,
      networkTx: data.networkTx ?? existing?.networkTx ?? 0,
      uptime: data.uptime ?? existing?.uptime ?? 0,
      updatedAt: Date.now(),
      stale: data.stale ?? false,
    }
  }

  // ── Convenience getter for state ──
  function getState(serverId: number): string {
    return resources.value[serverId]?.state ?? 'offline'
  }

  function isStale(serverId: number): boolean {
    return resources.value[serverId]?.stale ?? false
  }

  // ── Cleanup ──
  function $reset() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
    subscribers.value.clear()
    resources.value = {}
  }

  return {
    resources,
    subscribe,
    unsubscribe,
    updateOne,
    fetchResources,
    getState,
    isStale,
    $reset,
    activeServerIds,
    effectiveInterval,
  }
})

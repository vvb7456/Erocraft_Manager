import { defineStore } from 'pinia'
import { reactive, watch } from 'vue'
import { useServerResourceStore } from './serverResources'
import type { ToastAPI } from '@/composables/useToast'
import i18n from '@/i18n/vue-i18n'
import router from '@/router'

export type PowerAction = 'start' | 'stop' | 'restart' | 'kill'

interface PendingPower {
  action: PowerAction
  timestamp: number
  timeoutId: ReturnType<typeof setTimeout>
  /** State when pending was set — used to ignore the initial unchanged state */
  initialState: string
  /** Set to true once we observe a state different from initialState */
  stateChanged: boolean
}

/**
 * Per-server power action pending state.
 *
 * Set when a power command is sent; cleared when the expected stable state
 * arrives via resourceStore (WS or polling), when the action fails, or after
 * a timeout.
 *
 * Key design:
 * - Records initialState to avoid clearing on the pre-existing state
 *   (e.g. start from offline → don't immediately abnormal-clear on offline)
 * - restart uses staged approach: pending covers the offline gap, clears on
 *   'starting' so natural UI takes over ("启动中…")
 * - Provides sendPower() as the single entry point for all power actions
 *
 * See docs/POWER_RACE_CONDITION_REPORT.md §4–§5 for full design.
 */
export const usePowerPendingStore = defineStore('powerPending', () => {
  const pending = reactive<Map<number, PendingPower>>(new Map())
  const { t, te } = i18n.global

  let _redirecting = false
  function redirectToLogin() {
    if (_redirecting) return
    _redirecting = true
    router.push({ name: 'login' }).finally(() => { _redirecting = false })
  }

  const TIMEOUT_MS: Record<PowerAction, number> = {
    start:   60_000,
    restart: 60_000,
    stop:    60_000,
    kill:    30_000,
  }

  // ── Expected stable states per action ──
  // For start and restart: 'starting' is added as a staged clear — once the
  // server begins starting, the natural UI shows "启动中…" with kill button,
  // and pending is no longer needed.
  const STABLE_STATES: Record<PowerAction, string[]> = {
    start:   ['running', 'starting'],
    restart: ['running', 'starting'],
    stop:    ['offline', 'stopped'],
    kill:    ['offline', 'stopped'],
  }

  // ── Abnormal-clear: states that mean the action definitely won't reach
  //    its expected outcome, so we release pending early. ──
  const ABNORMAL_CLEAR: Record<PowerAction, string[]> = {
    start:   ['offline', 'stopped'],  // start failed → back to offline
    restart: [],                      // restart intermediate offline is expected; staged clear handles normal path
    stop:    [],                      // stop goes stopping→offline naturally
    kill:    ['running', 'starting'], // kill ineffective (pre-boot) → server still running/starting
  }

  // ── Watch resourceStore for state changes and resolve pending ──
  let watcherSetup = false

  function ensureWatcher() {
    if (watcherSetup) return
    watcherSetup = true

    const resourceStore = useServerResourceStore()

    watch(
      () => {
        // Build a snapshot of { serverId: state } for all servers that have pending
        const snap: Record<number, string> = {}
        for (const [id] of pending) {
          snap[id] = resourceStore.resources[id]?.state ?? 'offline'
        }
        return snap
      },
      (states) => {
        for (const [idStr, state] of Object.entries(states)) {
          const id = Number(idStr)
          resolvePendingIfDone(id, state)
        }
      },
      { deep: true },
    )
  }

  function resolvePendingIfDone(serverId: number, newState: string) {
    const p = pending.get(serverId)
    if (!p) return

    // If state hasn't changed from initial, skip all checks.
    // This prevents the watcher from immediately clearing pending
    // on the pre-existing state (e.g. start from offline → offline
    // would hit abnormal clear without this guard).
    if (!p.stateChanged) {
      if (newState === p.initialState) return
      p.stateChanged = true
    }

    // Stable state reached → action succeeded
    const stableStates = STABLE_STATES[p.action]
    if (stableStates.includes(newState)) {
      clearPending(serverId)
      return
    }

    // Abnormal clear → action definitely failed
    const abnormal = ABNORMAL_CLEAR[p.action]
    if (abnormal.length && abnormal.includes(newState)) {
      clearPending(serverId)
    }
  }

  function clearPending(serverId: number) {
    const p = pending.get(serverId)
    if (p) {
      clearTimeout(p.timeoutId)
      pending.delete(serverId)
    }
  }

  /**
   * Set pending state for a server.
   * Captures current state from resourceStore as initialState.
   */
  function setPending(serverId: number, action: PowerAction) {
    ensureWatcher()

    // Clear any existing pending for this server
    const existing = pending.get(serverId)
    if (existing) clearTimeout(existing.timeoutId)

    const resourceStore = useServerResourceStore()
    const initialState = resourceStore.resources[serverId]?.state ?? 'offline'

    const timeoutId = setTimeout(() => {
      pending.delete(serverId)
    }, TIMEOUT_MS[action])

    pending.set(serverId, {
      action,
      timestamp: Date.now(),
      timeoutId,
      initialState,
      stateChanged: false,
    })
  }

  /** Get the pending action for a server, if any. */
  function get(serverId: number): PowerAction | null {
    return pending.get(serverId)?.action ?? null
  }

  /** Check if a server has a pending power action. */
  function has(serverId: number): boolean {
    return pending.has(serverId)
  }

  /**
   * Check if a specific action is allowed given current pending state.
   * Per doc §5: only kill is allowed when pending=stop (to accelerate shutdown).
   */
  function isActionAllowed(serverId: number, action: PowerAction): boolean {
    const p = pending.get(serverId)
    if (!p) return true

    // pending=stop allows kill (user wants to accelerate)
    if (p.action === 'stop' && action === 'kill') return true

    // All other cases: blocked while pending
    return false
  }

  /** Translate structured error codes (same logic as useApiFetch) */
  function translateError(msg: string): string {
    if (/^[a-z_]+\.[a-z_]+$/.test(msg)) {
      const key = `common.apiErrors.${msg}`
      if (te(key)) return t(key)
    }
    return msg
  }

  /**
   * Centralized power action sender.
   * Sets pending, calls API via raw fetch, clears on failure.
   * Returns the raw error key (e.g. "server.startup_credentials_required")
   * if the API returns an error, or null on success / network error.
   * Callers can intercept known error keys before the toast fires.
   * @param toastFn - Toast function from useToast() for error display
   * @param suppressErrors - Error keys to suppress from toast (caller will handle)
   */
  async function sendPower(
    serverId: number,
    action: PowerAction,
    toastFn?: ToastAPI['toast'],
    suppressErrors?: string[],
  ): Promise<string | null> {
    if (!isActionAllowed(serverId, action)) return null

    setPending(serverId, action)
    try {
      const res = await fetch(`/api/user/servers/${serverId}/power`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action }),
      })
      if (!res.ok) {
        clearPending(serverId)
        if (res.status === 401) {
          redirectToLogin()
          return null
        }
        let msg = `HTTP ${res.status}`
        try {
          const body = await res.json()
          msg = body.error || body.message || msg
        } catch { /* ignore parse error */ }
        if (suppressErrors?.includes(msg)) return msg
        if (toastFn) toastFn(translateError(msg), 'error')
        return msg
      }
      return null
    } catch {
      clearPending(serverId)
      if (toastFn) toastFn(t('common.apiErrors.network'), 'error')
      return null
    }
  }

  function $reset() {
    for (const [, p] of pending) clearTimeout(p.timeoutId)
    pending.clear()
  }

  return {
    pending,
    setPending,
    clearPending,
    get,
    has,
    isActionAllowed,
    sendPower,
    $reset,
  }
})

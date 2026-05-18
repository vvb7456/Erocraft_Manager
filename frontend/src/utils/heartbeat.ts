/**
 * Heartbeat-based online/offline classification.
 *
 * Single source of truth for "is this host alive?" — derived from
 * `manager_hosts.last_seen_at` (updated by the 60s metrics scheduler).
 * Thresholds match the existing HostStatusPanel heartbeat chip:
 *
 *   age <= 90s   → online   (green)
 *   age <= 300s  → warning  (amber, late but not declared dead)
 *   age >  300s  → offline  (red)
 *   no heartbeat → unconfigured (never spoken back)
 *   disabled     → disabled
 */

export type HostStatusKey =
  | 'online'
  | 'warning'
  | 'offline'
  | 'disabled'
  | 'unconfigured'

export type HeartbeatTone = 'green' | 'amber' | 'red' | 'muted'

/** Seconds since `lastSeenAt`, or null if missing/unparseable. */
export function heartbeatAgeSec(lastSeenAt: string | null | undefined): number | null {
  if (!lastSeenAt) return null
  const hasTz = /Z|[+-]\d{2}:?\d{2}$/.test(lastSeenAt)
  const t = new Date(hasTz ? lastSeenAt : lastSeenAt + 'Z').getTime()
  if (Number.isNaN(t)) return null
  return Math.max(0, Math.round((Date.now() - t) / 1000))
}

export function heartbeatTone(
  enabled: boolean,
  ageSec: number | null,
): HeartbeatTone {
  if (!enabled) return 'muted'
  if (ageSec == null) return 'muted'
  if (ageSec <= 90) return 'green'
  if (ageSec <= 300) return 'amber'
  return 'red'
}

export function classifyHostStatus(
  enabled: boolean,
  lastSeenAt: string | null | undefined,
): HostStatusKey {
  if (!enabled) return 'disabled'
  const age = heartbeatAgeSec(lastSeenAt)
  if (age == null) return 'unconfigured'
  if (age <= 90) return 'online'
  if (age <= 300) return 'warning'
  return 'offline'
}

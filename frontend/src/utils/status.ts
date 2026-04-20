export type StatusDotKey = 'running' | 'loading' | 'error' | 'stopped'

/**
 * Map server state → StatusDot status key.
 * Centralised logic used across ConsolePage, ServerDetailPage, UserServersPage, AppSidebar.
 */
export function getStatusDotKey(
  state: string,
  isSuspended: boolean,
  isInstalling: boolean,
  isStale = false,
): StatusDotKey {
  if (isStale) return 'error'
  if (isSuspended) return 'error'
  if (isInstalling) return 'loading'
  if (state === 'running') return 'running'
  if (state === 'starting' || state === 'stopping' || state === 'installing') return 'loading'
  return 'stopped'
}

/**
 * Map server state → CSS color variable string.
 */
export function getStatusColor(
  state: string,
  isSuspended: boolean,
  isInstalling: boolean,
  isStale = false,
): string {
  if (isStale) return 'var(--t3)'
  if (isSuspended) return 'var(--red)'
  if (isInstalling) return 'var(--amber)'
  if (state === 'running') return 'var(--green)'
  if (state === 'starting' || state === 'stopping' || state === 'installing') return 'var(--amber)'
  return 'var(--t3)'
}

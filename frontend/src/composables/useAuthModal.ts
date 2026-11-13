import { ref, type Ref } from 'vue'
import type { LocationQuery, Router } from 'vue-router'
import { useAppStore } from '@/stores/app'

export type AuthMode = 'login' | 'register' | 'forgot-password'

export interface OpenAuthOptions {
  redirect?: string | null
  invite?: string
  onSuccess?: () => void
}

type AuthModalState = {
  open: Ref<boolean>
  mode: Ref<AuthMode>
  redirect: Ref<string | null>
  inviteCode: Ref<string>
  onSuccess: (() => void) | null
}

const g = globalThis as typeof globalThis & {
  __erocraftAuthModalState?: AuthModalState
}

const state: AuthModalState = g.__erocraftAuthModalState ?? {
  open: ref(false),
  mode: ref<AuthMode>('login'),
  redirect: ref<string | null>(null),
  inviteCode: ref(''),
  onSuccess: null,
}

g.__erocraftAuthModalState = state

let sessionExpiredRedirecting = false

function parseSafeRedirect(router: Router, raw: unknown) {
  if (typeof raw !== 'string') return null
  if (!raw.startsWith('/') || raw.startsWith('//') || raw.includes('\\')) return null
  const resolved = router.resolve(raw)
  if (!resolved.matched.length || resolved.meta.authEntry) return null
  return resolved
}

export function resolveSafeRedirect(router: Router, raw: unknown): string | null {
  return parseSafeRedirect(router, raw)?.fullPath ?? null
}

export function resolveSafeRedirectTarget(
  router: Router,
  raw: unknown,
): { path: string; query: LocationQuery; hash: string; replace: true } | null {
  const resolved = parseSafeRedirect(router, raw)
  if (!resolved) return null
  return {
    path: resolved.path,
    query: resolved.query,
    hash: resolved.hash,
    replace: true,
  }
}

export function resolvePostAuthRoute(
  user: { is_admin?: boolean; has_owned_server?: boolean } | null | undefined,
): { name: 'dashboard' | 'user-home' | 'user-plans' } {
  if (user?.is_admin) return { name: 'dashboard' }
  if (user?.has_owned_server) return { name: 'user-home' }
  return { name: 'user-plans' }
}

export function handleSessionExpired(router: Router): void {
  const app = useAppStore()
  app.markSessionExpired()
  if (sessionExpiredRedirecting) return
  const current = router.currentRoute.value
  if (current.meta.public) return
  const redirect = current.name === 'user-plans' || current.meta.authEntry
    ? null
    : current.fullPath
  useAuthModal().openAuth('login', { redirect })
  if (current.name !== 'user-plans') {
    sessionExpiredRedirecting = true
    void router.replace({ name: 'user-plans' }).finally(() => {
      sessionExpiredRedirecting = false
    })
  }
}

export function useAuthModal() {
  function openAuth(mode: AuthMode = 'login', opts: OpenAuthOptions = {}) {
    useAppStore().closeMobileSidebar()
    state.mode.value = mode
    state.redirect.value = opts.redirect ?? null
    if (opts.invite !== undefined) {
      state.inviteCode.value = opts.invite.trim().toUpperCase()
    }
    state.onSuccess = opts.onSuccess ?? null
    state.open.value = true
  }

  function switchMode(mode: AuthMode) {
    state.mode.value = mode
  }

  function closeAuth() {
    state.open.value = false
    state.redirect.value = null
    state.onSuccess = null
  }

  function consumeSuccessHandler() {
    const redirect = state.redirect.value
    const onSuccess = state.onSuccess
    state.redirect.value = null
    state.onSuccess = null
    state.open.value = false
    return { redirect, onSuccess }
  }

  return {
    open: state.open,
    mode: state.mode,
    redirect: state.redirect,
    inviteCode: state.inviteCode,
    openAuth,
    switchMode,
    closeAuth,
    consumeSuccessHandler,
  }
}

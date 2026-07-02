import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useToast } from './useToast'
import router from '@/router'
import { useAppStore } from '@/stores/app'

let _redirecting = false
function redirectToLogin() {
  if (_redirecting) return
  _redirecting = true
  router.push({ name: 'login' }).finally(() => { _redirecting = false })
}

/**
 * Unified HTTP client composable.
 * Wraps fetch with loading/error state, JSON parsing, and toast on error.
 *
 * If the backend returns a structured error code (e.g. "file.destination_exists"),
 * it will attempt to find a translation at `apiErrors.{code}` before displaying.
 */
export function useApiFetch() {
  const loading = ref(false)
  const error = ref<string | null>(null)
  const { toast } = useToast()
  const { t, te } = useI18n({ useScope: 'global' })
  const app = useAppStore()

  /** Translate a structured error code to i18n, fallback to raw message. */
  function translateError(msg: string): string {
    if (/^[a-z_]+\.[a-z_]+$/.test(msg)) {
      const key = `common.apiErrors.${msg}`
      if (te(key)) return t(key)
    }
    return msg
  }

  async function request<T = unknown>(
    url: string,
    opts: RequestInit & { silent?: boolean } = {},
  ): Promise<T | null> {
    loading.value = true
    error.value = null
    const { silent, ...fetchOpts } = opts
    try {
      const res = await fetch(url, {
        headers: { 'Content-Type': 'application/json', ...fetchOpts.headers as Record<string, string> },
        ...fetchOpts,
      })
      if (!res.ok) {
        // 401: session expired — redirect to login
        if (res.status === 401) {
          app.clearSessionUser()
          redirectToLogin()
          return null
        }
        let msg = `HTTP ${res.status}`
        try {
          const body = await res.json()
          msg = body.error || body.message || msg
        } catch { /* ignore parse error */ }
        error.value = msg
        if (!silent) toast(translateError(msg), 'error')
        return null
      }
      // Handle 204 No Content
      if (res.status === 204) return {} as T
      return await res.json() as T
    } catch {
      const msg = t('common.apiErrors.network')
      error.value = msg
      if (!silent) toast(msg, 'error')
      return null
    } finally {
      loading.value = false
    }
  }

  async function get<T = unknown>(url: string, opts?: { silent?: boolean }): Promise<T | null> {
    return request<T>(url, { method: 'GET', ...opts })
  }

  async function post<T = unknown>(url: string, body?: Record<string, unknown> | unknown[]): Promise<T | null> {
    return request<T>(url, {
      method: 'POST',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  }

  async function put<T = unknown>(url: string, body?: Record<string, unknown> | unknown[]): Promise<T | null> {
    return request<T>(url, {
      method: 'PUT',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  }

  async function patch<T = unknown>(url: string, body?: Record<string, unknown> | unknown[]): Promise<T | null> {
    return request<T>(url, {
      method: 'PATCH',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  }

  async function del<T = unknown>(url: string, body?: Record<string, unknown>): Promise<T | null> {
    return request<T>(url, {
      method: 'DELETE',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  }

  /** Raw fetch without JSON parsing (for file uploads, etc.).
   *
   * 401 always triggers session-clear + redirect (even with ``silent``).
   * ``silent`` suppresses toasts on other non-OK statuses so the caller can
   * inspect status codes (e.g. 409) and present its own message. The raw
   * response (including non-OK!) is returned in that case so the caller can
   * read the body. (Audit FM1.)
   */
  async function raw(
    url: string,
    opts: RequestInit & { silent?: boolean } = {},
  ): Promise<Response | null> {
    loading.value = true
    error.value = null
    const { silent, ...fetchOpts } = opts
    try {
      const res = await fetch(url, fetchOpts)
      if (res.status === 401) {
        app.clearSessionUser()
        redirectToLogin()
        return null
      }
      if (!res.ok) {
        let msg = `HTTP ${res.status}`
        if (!silent) {
          try {
            const cloned = res.clone()
            const body = await cloned.json()
            msg = body.error || body.message || msg
          } catch { /* ignore */ }
          error.value = msg
          toast(translateError(msg), 'error')
          return null
        }
        // silent: surface the response so caller handles non-OK itself.
        error.value = msg
        return res
      }
      return res
    } catch {
      const msg = t('common.apiErrors.network')
      error.value = msg
      if (!silent) toast(msg, 'error')
      return null
    } finally {
      loading.value = false
    }
  }

  return { loading, error, get, post, put, patch, del, raw }
}

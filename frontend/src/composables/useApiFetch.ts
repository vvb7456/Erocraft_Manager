import { ref } from 'vue'
import router from '@/router'
import { useAppStore } from '@/stores/app'
import { ApiError, apiErrorMessage, fetchApi, readApiJson } from './apiClient'
import { useToast } from './useToast'

let redirecting = false

type RequestOptions = RequestInit & { silent?: boolean }

export function useApiFetch() {
  const loading = ref(false)
  const error = ref<string | null>(null)
  const app = useAppStore()
  const { toast } = useToast()
  let pending = 0

  async function perform<T>(url: string, opts: RequestOptions, read: (response: Response) => Promise<T>): Promise<T> {
    pending++
    loading.value = true
    error.value = null
    const { silent = false, ...options } = opts
    try {
      return await read(await fetchApi(url, options))
    } catch (failure) {
      if (failure instanceof ApiError) {
        failure.silent = silent
        error.value = apiErrorMessage(failure)
        if (failure.status === 401 && failure.code === 'auth.session_required') {
          failure.silent = true
          app.clearSessionUser()
          if (!redirecting && router.currentRoute.value.name !== 'login') {
            redirecting = true
            void router.push({ name: 'login', query: { redirect: router.currentRoute.value.fullPath } })
              .finally(() => { redirecting = false })
          }
        }
      }
      throw failure
    } finally {
      loading.value = --pending > 0
    }
  }

  async function request<T>(url: string, options: RequestOptions): Promise<T> {
    return perform(url, options, readApiJson<T>)
  }

  function raw(url: string, options: RequestOptions = {}): Promise<Response> {
    return perform(url, options, response => Promise.resolve(response))
  }

  function get<T = unknown>(url: string, opts?: { silent?: boolean }): Promise<T> {
    return request<T>(url, { method: 'GET', ...opts })
  }

  function write<T>(method: string, url: string, body?: Record<string, unknown> | unknown[]): Promise<T> {
    return request<T>(url, {
      method, headers: { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  }

  const post = <T = unknown>(url: string, body?: Record<string, unknown> | unknown[]) => write<T>('POST', url, body)
  const put = <T = unknown>(url: string, body?: Record<string, unknown> | unknown[]) => write<T>('PUT', url, body)
  const patch = <T = unknown>(url: string, body?: Record<string, unknown> | unknown[]) => write<T>('PATCH', url, body)
  const del = <T = unknown>(url: string, body?: Record<string, unknown>) => write<T>('DELETE', url, body)

  function handleError(failure: unknown): void {
    if (failure instanceof ApiError) {
      if (!failure.silent) toast(apiErrorMessage(failure), 'error')
      return
    }
    if (failure instanceof DOMException && failure.name === 'AbortError') return
    throw failure
  }

  return { loading, error, get, post, put, patch, del, raw, handleError }
}

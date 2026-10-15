import i18n from '@/i18n/vue-i18n'
import type { ErrorInfo, ProblemDetails } from '@/types/api'

export class ApiError extends Error {
  constructor(
    public readonly problem: ErrorInfo & Partial<ProblemDetails>,
    public readonly status?: number,
    public silent = false,
  ) {
    super(problem.detail || problem.code)
    this.name = 'ApiError'
  }

  get code() { return this.problem.code }
}

export function apiErrorMessage(error: unknown): string {
  const { t, te } = i18n.global
  if (error instanceof ApiError) {
    const key = `common.apiErrors.${error.code}`
    if (error.problem.detail && ['request.invalid', 'request.validation_failed', 'resource.conflict', 'resource.not_found', 'dependency.failed'].includes(error.code)) return error.problem.detail
    if (te(key)) return t(key, error.problem.params || {})
    return t('common.apiErrors.client.http_error', { status: error.status ?? '?' })
  }
  return error instanceof Error ? error.message : t('common.apiErrors.system.internal_error')
}

export function errorInfoMessage(error: ErrorInfo): string {
  return apiErrorMessage(new ApiError(error))
}

export async function fetchApi(url: string, options: RequestInit = {}): Promise<Response> {
  let response: Response
  try {
    response = await fetch(url, options)
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiError({ code: 'client.network_error' })
  }
  if (!response.ok) {
    let problem: ProblemDetails
    try {
      problem = await response.json()
      if (!problem || typeof problem.code !== 'string') throw new Error('Missing problem code')
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') throw error
      throw new ApiError({ code: 'client.http_error', params: { status: response.status } }, response.status)
    }
    throw new ApiError({ ...problem, status: response.status }, response.status)
  }
  return response
}

export async function readApiJson<T>(response: Response): Promise<T> {
  if (response.status === 204) return undefined as T
  try {
    return await response.json() as T
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiError({ code: 'client.invalid_response' }, response.status)
  }
}

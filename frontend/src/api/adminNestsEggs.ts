import { fetchApi, readApiJson } from '@/composables/apiClient'
import type { AdminMessageResponse } from './adminNodesLocations'

export const RESERVED_ENV_NAMES = new Set([
  'SERVER_MEMORY',
  'SERVER_IP',
  'SERVER_PORT',
  'ENV',
  'HOME',
  'USER',
  'STARTUP',
  'SERVER_UUID',
  'UUID',
])

export const ENV_VAR_PATTERN = /^[A-Za-z0-9_]{1,191}$/

export interface NestOut {
  id: number
  uuid: string
  author: string
  name: string
  description: string | null
  eggs_count: number
  servers_count: number
  created_at: string | null
  updated_at: string | null
}

export interface NestListResponse {
  nests: NestOut[]
}

export interface NestCreateIn {
  name: string
  description?: string | null
}

export interface NestUpdateIn {
  name?: string | null
  description?: string | null
}

export interface EggRef {
  id: number
  name: string
}

export interface EggSummaryOut {
  id: number
  uuid: string
  nest_id: number
  nest_name: string
  author: string
  name: string
  description: string | null
  docker_images: Record<string, string>
  servers_count: number
  plans_count: number
  variables_count: number
  created_at: string | null
  updated_at: string | null
}

export interface EggListResponse {
  eggs: EggSummaryOut[]
}

export interface EggEffectiveConfig {
  config_files: string | null
  config_startup: string | null
  config_logs: string | null
  config_stop: string | null
  features: string[]
  file_denylist: string[]
}

export interface EggEffectiveScripts {
  script_install: string | null
  script_container: string
  script_entry: string
  script_is_privileged: boolean
}

export interface EggVariableOut {
  id: number
  egg_id: number
  name: string
  description: string
  env_variable: string
  default_value: string
  user_viewable: boolean
  user_editable: boolean
  rules: string
  created_at: string | null
  updated_at: string | null
}

export interface EggDetailOut {
  id: number
  uuid: string
  nest_id: number
  nest_name: string
  author: string
  name: string
  description: string | null
  features: string[] | null
  docker_images: Record<string, string>
  file_denylist: string[]
  update_url: string | null
  config_files: string | null
  config_startup: string | null
  config_logs: string | null
  config_stop: string | null
  config_from: number | null
  startup: string | null
  script_container: string
  copy_script_from: number | null
  script_entry: string
  script_is_privileged: boolean
  script_install: string | null
  force_outgoing_ip: boolean
  created_at: string | null
  updated_at: string | null

  effective_config: EggEffectiveConfig
  effective_scripts: EggEffectiveScripts
  config_from_candidates: EggRef[]
  copy_script_from_candidates: EggRef[]
  dependent_config_eggs: EggRef[]
  dependent_script_eggs: EggRef[]
  variables: EggVariableOut[]
  servers_count: number
  plans_count: number
  in_special_registry: boolean
}

export interface EggCreateIn {
  nest_id: number
  name: string
  description?: string | null
  features?: string[] | null
  docker_images: Record<string, string>
  file_denylist?: string[] | null
  update_url?: string | null
  startup: string
  config_from?: number | null
  config_stop?: string | null
  config_startup?: string | null
  config_logs?: string | null
  config_files?: string | null
  force_outgoing_ip?: boolean
  script_install?: string | null
  script_is_privileged?: boolean
  script_container?: string
  script_entry?: string
  copy_script_from?: number | null
}

export interface EggUpdateIn {
  name?: string | null
  description?: string | null
  features?: string[] | null
  docker_images?: Record<string, string> | null
  file_denylist?: string[] | null
  update_url?: string | null
  startup?: string | null
  config_from?: number | null
  config_stop?: string | null
  config_startup?: string | null
  config_logs?: string | null
  config_files?: string | null
  force_outgoing_ip?: boolean | null
}

export interface EggScriptsUpdateIn {
  script_install?: string | null
  script_is_privileged?: boolean | null
  script_container?: string | null
  script_entry?: string | null
  copy_script_from?: number | null
}

export interface EggVariableCreateIn {
  name: string
  description?: string | null
  env_variable: string
  default_value?: string | null
  user_viewable?: boolean
  user_editable?: boolean
  rules: string
}

export interface EggVariableUpdateIn {
  name?: string | null
  description?: string | null
  env_variable?: string | null
  default_value?: string | null
  user_viewable?: boolean | null
  user_editable?: boolean | null
  rules?: string | null
}

export interface AffectedPlanWarning {
  id: number
  code: string
  name: string
  is_active: boolean
  reason: string
}

export interface EggMutationResponse {
  egg: EggDetailOut
  affected_plans: AffectedPlanWarning[]
}

export interface EggVariableMutationResponse {
  variable: EggVariableOut
  affected_plans: AffectedPlanWarning[]
}

export interface EggVariableDeleteResponse {
  message: string
  affected_plans: AffectedPlanWarning[]
}

async function jsonRequest<T>(url: string, init: RequestInit = {}): Promise<T> {
  const res = await fetchApi(url, init)
  return readApiJson<T>(res)
}

function writeJson<T>(method: string, url: string, body?: unknown): Promise<T> {
  return jsonRequest<T>(url, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

export function listNests(): Promise<NestListResponse> {
  return jsonRequest<NestListResponse>('/api/admin/nests')
}

export function createNest(body: NestCreateIn): Promise<NestOut> {
  return writeJson<NestOut>('POST', '/api/admin/nests', body)
}

export function updateNest(nestId: number, body: NestUpdateIn): Promise<NestOut> {
  return writeJson<NestOut>('PATCH', `/api/admin/nests/${nestId}`, body)
}

export function deleteNest(nestId: number): Promise<AdminMessageResponse> {
  return writeJson<AdminMessageResponse>('DELETE', `/api/admin/nests/${nestId}`)
}

export function listEggs(nestId?: number): Promise<EggListResponse> {
  const qs = nestId != null ? `?nest_id=${nestId}` : ''
  return jsonRequest<EggListResponse>(`/api/admin/eggs${qs}`)
}

export function createEgg(body: EggCreateIn): Promise<EggDetailOut> {
  return writeJson<EggDetailOut>('POST', '/api/admin/eggs', body)
}

export function getEgg(eggId: number): Promise<EggDetailOut> {
  return jsonRequest<EggDetailOut>(`/api/admin/eggs/${eggId}`)
}

export function updateEgg(eggId: number, body: EggUpdateIn): Promise<EggMutationResponse> {
  return writeJson<EggMutationResponse>('PATCH', `/api/admin/eggs/${eggId}`, body)
}

export function updateEggScripts(eggId: number, body: EggScriptsUpdateIn): Promise<EggDetailOut> {
  return writeJson<EggDetailOut>('PATCH', `/api/admin/eggs/${eggId}/scripts`, body)
}

export function deleteEgg(eggId: number): Promise<AdminMessageResponse> {
  return writeJson<AdminMessageResponse>('DELETE', `/api/admin/eggs/${eggId}`)
}

export function importEggFile(nestId: number, file: File): Promise<EggDetailOut> {
  const form = new FormData()
  form.append('nest_id', String(nestId))
  form.append('file', file)
  return jsonRequest<EggDetailOut>('/api/admin/eggs/import', {
    method: 'POST',
    body: form,
  })
}

export function overwriteImportEggFile(eggId: number, file: File): Promise<EggMutationResponse> {
  const form = new FormData()
  form.append('file', file)
  return jsonRequest<EggMutationResponse>(`/api/admin/eggs/${eggId}/import`, {
    method: 'PUT',
    body: form,
  })
}

export async function exportEggDownload(eggId: number, fallbackSlug = `egg-${eggId}`): Promise<void> {
  const res = await fetchApi(`/api/admin/eggs/${eggId}/export`)
  const blob = await res.blob()
  const disposition = res.headers.get('content-disposition') || ''
  const match = disposition.match(/filename="?([^";]+)"?/i)
  const filename = match?.[1] || `${fallbackSlug}.json`

  const url = URL.createObjectURL(blob)
  try {
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
  } finally {
    URL.revokeObjectURL(url)
  }
}

export function createEggVariable(
  eggId: number,
  body: EggVariableCreateIn,
): Promise<EggVariableMutationResponse> {
  return writeJson<EggVariableMutationResponse>('POST', `/api/admin/eggs/${eggId}/variables`, body)
}

export function updateEggVariable(
  eggId: number,
  varId: number,
  body: EggVariableUpdateIn,
): Promise<EggVariableMutationResponse> {
  return writeJson<EggVariableMutationResponse>(
    'PATCH',
    `/api/admin/eggs/${eggId}/variables/${varId}`,
    body,
  )
}

export function deleteEggVariable(
  eggId: number,
  varId: number,
): Promise<EggVariableDeleteResponse> {
  return writeJson<EggVariableDeleteResponse>(
    'DELETE',
    `/api/admin/eggs/${eggId}/variables/${varId}`,
  )
}

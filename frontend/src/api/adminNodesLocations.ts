import { fetchApi, readApiJson } from '@/composables/apiClient'

export interface LocationOut {
  id: number
  short: string
  long: string | null
  nodes_count: number
  servers_count: number
  created_at: string | null
  updated_at: string | null
}

export interface LocationListResponse {
  locations: LocationOut[]
}

export interface LocationCreateIn {
  short: string
  long?: string | null
}

export interface LocationUpdateIn {
  short?: string | null
  long?: string | null
}

export interface NodeLocationBrief {
  id: number
  short: string
  long: string | null
}

export interface NodeOut {
  id: number
  uuid: string
  public: boolean
  name: string
  description: string | null
  location_id: number
  location: NodeLocationBrief | null
  fqdn: string
  scheme: 'http' | 'https' | string
  behind_proxy: boolean
  maintenance_mode: boolean
  memory: number
  memory_overallocate: number
  disk: number
  disk_overallocate: number
  upload_size: number
  daemon_token_id: string
  daemon_listen: number
  daemon_sftp: number
  daemon_base: string
  servers_count: number
  plans_count: number
  host_id: number | null
  host_name: string | null
  created_at: string | null
  updated_at: string | null
}

export interface NodeListResponse {
  nodes: NodeOut[]
}

export interface NodeCreateIn {
  name: string
  description?: string | null
  location_id: number
  fqdn: string
  scheme: 'http' | 'https'
  public: boolean
  behind_proxy: boolean
  maintenance_mode: boolean
  memory: number
  memory_overallocate: number
  disk: number
  disk_overallocate: number
  upload_size: number
  daemon_listen: number
  daemon_sftp: number
  daemon_base: string
}

export interface NodeConfigurationOut {
  node_id: number
  node_name: string
  remote: string
  config: Record<string, unknown>
  yaml: string
  warnings: string[]
}

export interface AdminMessageResponse {
  message: string
}

export interface AllocationServerBrief {
  id: number
  uuid_short: string
  name: string
  owner_id: number
  owner_name: string | null
}

export interface AllocationOut {
  id: number
  ip: string
  alias: string | null
  port: number
  notes: string | null
  server: AllocationServerBrief | null
}

export interface AllocationUpdateIn {
  alias?: string | null
  notes?: string | null
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

export function listLocations(): Promise<LocationListResponse> {
  return jsonRequest<LocationListResponse>('/api/admin/locations')
}

export function createLocation(body: LocationCreateIn): Promise<LocationOut> {
  return writeJson<LocationOut>('POST', '/api/admin/locations', body)
}

export function updateLocation(locationId: number, body: LocationUpdateIn): Promise<LocationOut> {
  return writeJson<LocationOut>('PATCH', `/api/admin/locations/${locationId}`, body)
}

export function deleteLocation(locationId: number): Promise<AdminMessageResponse> {
  return writeJson<AdminMessageResponse>('DELETE', `/api/admin/locations/${locationId}`)
}

export function listNodes(): Promise<NodeListResponse> {
  return jsonRequest<NodeListResponse>('/api/admin/nodes')
}

export function createNode(body: NodeCreateIn): Promise<NodeOut> {
  return writeJson<NodeOut>('POST', '/api/admin/nodes', body)
}

export function getNodeConfiguration(nodeId: number): Promise<NodeConfigurationOut> {
  return jsonRequest<NodeConfigurationOut>(`/api/admin/nodes/${nodeId}/configuration`)
}

export function getHostWingsConfiguration(hostId: number): Promise<NodeConfigurationOut> {
  return jsonRequest<NodeConfigurationOut>(`/api/admin/hosts/${hostId}/wings-configuration`)
}

export function deleteNode(nodeId: number): Promise<AdminMessageResponse> {
  return writeJson<AdminMessageResponse>('DELETE', `/api/admin/nodes/${nodeId}`)
}

export function updateHostAllocation(
  hostId: number,
  allocationId: number,
  body: AllocationUpdateIn,
): Promise<AllocationOut> {
  return writeJson<AllocationOut>(
    'PATCH',
    `/api/admin/hosts/${hostId}/allocations/${allocationId}`,
    body,
  )
}

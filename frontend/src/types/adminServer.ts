// Admin server detail types — mirrors app/schemas/admin_server_detail.py.
// Field names use camelCase to match the backend's `populate_by_name` aliases.

export interface ServerOwnerSummary {
  id: number
  uuid: string
  username: string
  email: string
}

export interface ServerNodeSummary {
  id: number
  name: string
  fqdn: string
  scheme: string
  daemonListen: number
  daemonSftp: number
}

export interface ServerNestSummary {
  id: number
  name: string
}

export interface DockerImageOption {
  label: string
  value: string
}

export interface ServerEggSummary {
  id: number
  name: string
  nestId: number
  startup: string | null
  dockerImages: DockerImageOption[]
}

export interface ManagerHostSummary {
  id: number
  name: string
  agentUrl: string
  enabled: boolean
}

export interface ServerAllocationSummary {
  id: number
  nodeId: number
  ip: string
  ipAlias: string | null
  port: number
  notes: string | null
  isPrimary: boolean
}

export interface ServerVariableSummary {
  id: number
  name: string
  description: string
  envVariable: string
  defaultValue: string
  value: string
  rules: string | null
  userViewable: boolean
  userEditable: boolean
}

export interface AdminServerSummary {
  id: number
  uuid: string
  uuidShort: string
  externalId: string | null
  name: string
  description: string
  status: string | null
  isSuspended: boolean
  isInstalling: boolean
  ownerId: number
  nodeId: number
  nestId: number
  eggId: number
  allocationId: number
  memory: number
  swap: number
  disk: number
  io: number
  cpu: number
  threads: string | null
  oomDisabled: boolean
  allocationLimit: number | null
  databaseLimit: number | null
  backupLimit: number
  image: string
  startup: string
  skipScripts: boolean
  createdAt: string | null
  updatedAt: string | null
  installedAt: string | null
  expirationDate: string | null
  isTrial: boolean
  planId: number | null
  planCode: string | null
  planName: string | null
  planType: string | null
}

export interface AdminServerDetailResponse {
  server: AdminServerSummary
  owner: ServerOwnerSummary
  node: ServerNodeSummary
  nest: ServerNestSummary | null
  egg: ServerEggSummary
  managerHost: ManagerHostSummary | null
  allocations: ServerAllocationSummary[]
  variables: ServerVariableSummary[]
  hiddenVariableCount: number
}

export interface ServerRuntimeResources {
  cpu_absolute?: number
  memory_bytes?: number
  memory_limit_bytes?: number
  disk_bytes?: number
  network?: { rx_bytes?: number; tx_bytes?: number }
  uptime?: number
  state?: string
  [key: string]: unknown
}

export interface ServerRuntimeResponse {
  state: string | null
  isSuspended: boolean | null
  resources: ServerRuntimeResources | null
  raw: Record<string, unknown>
}

export type AdminServerStatusKey =
  | 'installing'
  | 'install_failed'
  | 'suspended'
  | 'running'
  | 'offline'
  | 'starting'
  | 'stopping'
  | 'unknown'

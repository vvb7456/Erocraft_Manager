// Shared type definitions for the host management UI.
// Mirrors the backend `HostOut` schema in app/api/routers/admin_hosts.py.

export interface HostDetail {
  id: number
  name: string
  kind: 'wings_node' | 'nginx_proxy' | 'nas' | 'generic_linux' | string
  hostname: string
  agent_url: string
  pterodactyl_node_id: number | null
  extra_metadata: Record<string, unknown> | null
  enabled: boolean
  inbound_reachable: boolean
  last_seen_at: string | null
  last_status_at: string | null
  created_at: string | null
  updated_at: string | null
}

export type HostStatusKey = 'online' | 'offline' | 'disabled' | 'unconfigured'

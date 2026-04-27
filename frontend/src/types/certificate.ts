export interface CertificateDeployment {
  id: number
  certificate_id: number
  host_id: number
  host_name: string | null
  host_kind: string | null
  target_name: string
  target_cert_path: string | null
  target_key_path: string | null
  target_path_error: string | null
  deployed_fingerprint_sha256: string | null
  deployed_not_after: string | null
  last_check_at: string | null
  last_check_error: string | null
  last_deploy_at: string | null
  last_deploy_attempt_at: string | null
  last_deploy_error: string | null
  status: 'synced' | 'outdated' | 'deploy_failed' | 'unreachable' | 'unknown' | string
  created_at: string | null
  updated_at: string | null
}

export interface ManagedCertificate {
  id: number
  name: string
  domains: string[]
  source_type: string
  source_path: string
  source_fingerprint_sha256: string | null
  source_not_before: string | null
  source_not_after: string | null
  source_last_seen_at: string | null
  source_last_error: string | null
  alert_threshold_days: number
  enabled: boolean
  created_at: string | null
  updated_at: string | null
  deployments: CertificateDeployment[]
}

export interface AcmeCertificate {
  domain: string
  alt_names: string[]
  is_ecc: boolean
  conf_path: string
  cert_dir: string
  source_path: string | null
  source_compatible: boolean
  fullchain_path: string | null
  key_path: string | null
  cert_create_time_iso: string | null
  next_renew_time_iso: string | null
  ca: string | null
  webroot: string | null
  reload_cmd_set: boolean
  fingerprint_sha256: string | null
  not_before: string | null
  not_after: string | null
  source_error: string | null
  registered_certificate_id: number | null
}

export interface AcmeStatus {
  home: string
  binary: string
  home_exists: boolean
  binary_exists: boolean
  binary_executable: boolean
  certificate_count: number
  registered_count: number
  certificates: AcmeCertificate[]
}

export interface CertTarget {
  name: string
  type: 'file' | 'synology_dsm' | string
  exists: boolean | null
  paths: { cert: string; key: string } | null
  certificate_desc: string | null
  dsm_cert_id: string | null
  is_default: boolean | null
  domains: string[] | null
  services: Record<string, unknown>[] | null
  current_cert: Record<string, unknown> | null
  error: string | null
}

export interface CertTargetsResponse {
  targets: CertTarget[]
  wings_yaml_paths: Record<string, string | null> | null
}

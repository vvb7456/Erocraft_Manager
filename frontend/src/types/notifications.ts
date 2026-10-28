export const notificationCategories = ['support', 'monitoring', 'certificate', 'billing', 'system'] as const
export type NotificationCategory = typeof notificationCategories[number]
export type NotificationRuleCategory = NotificationCategory | 'lifecycle'
export type NotificationChannel = 'email' | 'wecom'

export interface MetricRule {
  enabled?: boolean | null
  threshold?: number | null
  warning_threshold?: number | null
  critical_threshold?: number | null
  sustain_min?: number | null
}

export interface NotificationSettings {
  WECOM_ENABLED: boolean
  WECOM_CORP_ID: string
  WECOM_AGENT_ID: string
  WECOM_SECRET: string
  NOTIFY_SUPPORT_DELAY: number
  SMTP_HOST: string
  SMTP_PORT: number
  SMTP_USE_SSL: boolean
  SMTP_PASSWORD: string
  SENDER_EMAIL: string
  EMAIL_SEND_DELAY: number
  AUTOMATION_EMAIL_RUN_HOUR: number
  AUTOMATION_EMAIL_RUN_MINUTE: number
  TIMEZONE: string
}

export interface NotificationGroup {
  id: string
  name: string
  all_admins: boolean
  admin_ids: number[]
  wecom_ids: string[]
}

export interface NotificationRule {
  email: boolean
  wecom: boolean
  email_group: string
  wecom_group: string
  min_severity: string
  email_resolved: boolean
  wecom_resolved: boolean
  cooldown_min: number
}

export interface NotificationConfig {
  settings: NotificationSettings
  policy: {
    groups: NotificationGroup[]
    routes: Record<NotificationCategory, NotificationRule>
    monitoring: Record<string, MetricRule>
    lifecycle: Record<string, boolean>
  }
  certificates: { id: number; name: string; days: number }[]
  admins: { value: number; label: string }[]
  hosts: { id: number; name: string; kind: string }[]
}

export interface NotificationAlert {
  key: string
  category: string
  severity: string
  title: string
  body: string
  path: string
  created_at: string
  state: string
  muted_until: string | null
}

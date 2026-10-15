export const wecomTemplateKeys = [
  'support', 'alert_fired', 'alert_resolved', 'certificate',
  'billing_incident', 'billing_apply', 'audit_failure', 'task_failure',
] as const

export type WecomTemplateKey = typeof wecomTemplateKeys[number]

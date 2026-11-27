import { useI18n } from 'vue-i18n'
import type { ErrorInfo, OperationResult } from '@/types/api'

export interface ActivityLogDetail {
  status: 'success' | 'failed'
  detailKey?: string | null
  detailParams?: Record<string, unknown> | null
}

export function useActivityLog() {
  const { t, te, tm, rt } = useI18n({ useScope: 'global' })

  function duration(sec: number): string {
    sec = Math.max(0, Math.round(sec))
    if (sec < 60) return t('logs.duration.seconds', { n: sec })
    const m = Math.floor(sec / 60)
    const s = sec % 60
    if (m < 60) return s ? t('logs.duration.minutesSeconds', { m, s }) : t('logs.duration.minutes', { n: m })
    const h = Math.floor(m / 60)
    return m % 60 ? t('logs.duration.hoursMinutes', { h, m: m % 60 }) : t('logs.duration.hours', { n: h })
  }

  function errorText(error: ErrorInfo): string {
    return error.detail || t(`common.apiErrors.${error.code}`, error.params || {})
  }

  function operationText(operation: OperationResult): string {
    const names = tm('logs.operation') as Record<string, string>
    const label = names[operation.action] ? rt(names[operation.action]) : operation.action
    const target = Object.entries(operation.target || {}).map(([key, value]) => {
      const name = te(`logs.target.${key}`) ? t(`logs.target.${key}`) : key
      return `${name} ${value}`
    }).join(', ')
    let text = `${label}${target ? ` (${target})` : ''}：${t(`logs.status_label.${operation.outcome}`)}`
    if (operation.facts?.valid === false) text += `；${t('logs.result.invalidCertificate')}`
    if (operation.error) text += `；${errorText(operation.error)}`
    return [text, ...(operation.children || []).map(operationText)].join('；')
  }

  function detailLabel(log: ActivityLogDetail): string {
    if (!log.detailKey) return '—'
    const params = { ...(log.detailParams || {}) }
    const operation = params.operation as OperationResult | undefined
    params.operation_result = t(`logs.status_label.${operation?.outcome || log.status}`)
    params.error = operation?.error ? errorText(operation.error) : params.error || params.agent_error || params.wings_error || ''
    for (const [field, prefix] of Object.entries({ template: 'emailTemplates', type: 'logs.reminderType', kind: 'hosts.kind', language: 'logs.language', alert_type: 'hosts.setting.alerting.types', severity: 'logs.severity' })) {
      const value = params[field]
      if (typeof value !== 'string') continue
      const key = `${prefix}.${value}${field === 'template' ? '.title' : ''}`
      if (te(key)) params[field] = t(key)
    }
    if (typeof params.duration_seconds === 'number') params.duration_human = duration(params.duration_seconds)
    if (typeof params.old_root_admin === 'boolean') params.old_root_admin = t(params.old_root_admin ? 'users.role.admin' : 'users.role.user')
    if (typeof params.new_root_admin === 'boolean') params.new_root_admin = t(params.new_root_admin ? 'users.role.admin' : 'users.role.user')
    if (typeof params.enabled === 'boolean' || params.enabled === 'true' || params.enabled === 'false') {
      const enabledKey = String(params.enabled)
      if (te(`logs.enabledState.${enabledKey}`)) params.enabled = t(`logs.enabledState.${enabledKey}`)
    }
    if (typeof params.order_kind === 'string' && te(`logs.orderKind.${params.order_kind}`)) params.order_kind = t(`logs.orderKind.${params.order_kind}`)
    if (typeof params.source === 'string' && te(`logs.applySource.${params.source}`)) params.source = t(`logs.applySource.${params.source}`)
    if (typeof params.result === 'string' && te(`logs.applyResult.${params.result}`)) params.result = t(`logs.applyResult.${params.result}`)
    if (typeof params.outcome === 'string' && te(`logs.refundResult.${params.outcome}`)) params.outcome = t(`logs.refundResult.${params.outcome}`)
    if (typeof params.action === 'string' && te(`logs.alertAction.${params.action}`)) params.action = t(`logs.alertAction.${params.action}`)
    if (log.detailKey === 'notification.alert.acknowledge_all' && typeof params.category === 'string') {
      if (params.category === 'all') {
        params.category = t('notifications.center.allCategories')
      } else if (te(`notifications.category.${params.category}`)) {
        params.category = t(`notifications.category.${params.category}`)
      }
    }
    const messages = tm('logs.detail') as Record<string, string>
    const resolvedKey = (
      log.detailKey === 'register_request'
      && typeof params.email === 'string'
      && (!params.username || params.username === params.email)
    )
      ? 'register_code_sent'
      : log.detailKey
    let text = messages[resolvedKey] ? rt(messages[resolvedKey], params) : t('logs.detail.unknown', { key: log.detailKey })
    if (operation?.error) {
      const reason = errorText(operation.error)
      if (!text.includes(reason)) text += `；${reason}`
    }
    if (operation?.facts?.local_record_removed) text += `；${t('logs.result.localRecordRemoved')}`
    if (operation?.failed !== undefined && (params.success === undefined || params.failed === undefined)) {
      text += `；${t('logs.result.counts', { succeeded: operation.succeeded || 0, failed: operation.failed })}`
    }
    if (operation?.children?.length) text += `；${operation.children.map(operationText).join('；')}`
    return text
  }

  return { detailLabel }
}

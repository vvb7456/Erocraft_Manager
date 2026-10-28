import { computed, onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from './useApiFetch'
import { useToast } from './useToast'
import { useDirtyFormSection, type DirtyFormGroup } from './useDirtyForm'
import type { NotificationConfig } from '@/types/notifications'
import { formSnapshot, sameFormValue } from '@/utils/formState'

type EditableConfig = Pick<NotificationConfig, 'settings' | 'policy' | 'certificates'>

function snapshot(value: EditableConfig) {
  const textKeys = ['WECOM_CORP_ID', 'WECOM_AGENT_ID', 'WECOM_SECRET', 'SMTP_HOST', 'SMTP_PASSWORD', 'SENDER_EMAIL', 'TIMEZONE']
  const settings = Object.fromEntries(Object.entries(value.settings).map(([key, entry]) => [key, textKeys.includes(key) ? String(entry ?? '') : entry]))
  const policy = { ...value.policy, groups: value.policy.groups.map(group => ({
    ...group, admin_ids: [...new Set(group.admin_ids)].sort((a, b) => a - b), wecom_ids: [...new Set(group.wecom_ids)].sort(),
  })) }
  return formSnapshot({ settings, policy, certificates: value.certificates })
}

export function useNotificationConfig(group?: DirtyFormGroup) {
  const { get, put } = useApiFetch()
  const { toast } = useToast()
  const { t } = useI18n()
  const data = ref<NotificationConfig | null>(null)
  const original = ref('')
  const loading = ref(true)
  const saving = ref(false)
  const dirty = computed(() => !!data.value && snapshot(data.value) !== original.value)
  let alive = true

  async function load() {
    loading.value = true
    const result = await get<NotificationConfig>('/api/admin/notifications/center').finally(() => { loading.value = false })
    if (!alive) return
    if (result) { data.value = result; original.value = snapshot(result) }
  }

  async function save() {
    if (!data.value || saving.value) return false
    if (!dirty.value) return true
    saving.value = true
    const submitted = JSON.parse(snapshot(data.value)) as EditableConfig
    try {
      const before = JSON.parse(original.value) as EditableConfig
      const settings = Object.fromEntries(Object.entries(submitted.settings).filter(([key, value]) => !sameFormValue(value, before.settings[key as keyof typeof before.settings])))
      const certificates = Object.fromEntries(submitted.certificates.filter(cert => cert.days !== before.certificates.find(old => old.id === cert.id)?.days).map(cert => [cert.id, cert.days]))
      const result = await put<NotificationConfig>('/api/admin/notifications/center', {
        settings, certificates,
        policy: sameFormValue(submitted.policy, before.policy) ? null : submitted.policy,
      })
      if (!result || !alive) return false
      const current = JSON.parse(snapshot(data.value)) as EditableConfig
      const later = Object.fromEntries((['settings', 'policy', 'certificates'] as const)
        .filter(key => !sameFormValue(current[key], submitted[key])).map(key => [key, data.value![key]]))
      original.value = snapshot(result)
      data.value = { ...result, ...later }
      toast(t('notifications.saved'), 'success')
      return !dirty.value
    } finally { saving.value = false }
  }

  function discard() {
    if (data.value && original.value) Object.assign(data.value, JSON.parse(original.value))
  }
  useDirtyFormSection({ name: 'notification-config', isDirty: dirty, save, discard }, group)
  onBeforeUnmount(() => { alive = false })
  return { data, loading, saving, dirty, load, save, discard }
}

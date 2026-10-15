<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useDirtyFormSection } from '@/composables/useDirtyForm'
import BaseCard from '@/components/ui/BaseCard.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import NumberInput from '@/components/form/NumberInput.vue'
import FormField from '@/components/form/FormField.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import LoadingCenter from '@/components/ui/LoadingCenter.vue'
import SectionHeader from '@/components/ui/SectionHeader.vue'
import ToggleSwitch from '@/components/ui/ToggleSwitch.vue'
import MetricRulesEditor from '@/components/notifications/MetricRulesEditor.vue'
import type { MetricRule } from '@/types/notifications'
import { formSnapshot, sameFormValue } from '@/utils/formState'

const props = withDefaults(defineProps<{ hostId: number; hostKind: string; connectionOnly?: boolean; wecom?: { enabled: boolean; resolved: boolean; group: string } }>(), { connectionOnly: false })
const { t } = useI18n()
const { get, put, handleError } = useApiFetch()
interface HostSettings {
  email_enabled: boolean | null; email_recipients: number[] | null; min_severity: string | null
  notify_resolve: boolean | null; cooldown_min: number | null; agent_pull_timeout: number | null; agent_pull_attempts: number | null
}
interface Payload { settings: HostSettings; rules: (MetricRule & { alert_type: string })[]; defaults: HostSettings & { rules: Record<string, MetricRule> } }
const data = ref<Payload | null>(null)
const baseline = ref('')
const original = computed<Payload | null>(() => baseline.value ? JSON.parse(baseline.value) : null)
const loading = ref(true)
const saving = ref(false)
const admins = ref<{ value: number; label: string }[]>([])
const severityOptions = computed(() => ['info', 'warning', 'critical'].map(value => ({ value, label: t(`notifications.severity.${value}`) })))
const selectingRecipients = ref(false)
const recipientMode = computed({
  get: () => selectingRecipients.value || data.value?.settings.email_recipients?.length ? 'selected' : data.value?.settings.email_recipients === null ? 'inherit' : 'all',
  set: (value: string) => {
    if (!data.value) return
    selectingRecipients.value = value === 'selected'
    data.value.settings.email_recipients = value === 'inherit' ? null : value === 'all' ? [] : data.value.settings.email_recipients || []
  },
})
const recipientModes = computed(() => [
  { value: 'inherit', label: t('notifications.center.globalRecipients') }, { value: 'all', label: t('notifications.center.allAdmins') },
  { value: 'selected', label: t('notifications.center.selectedAdmins') },
])
const invalidRecipients = computed(() => recipientMode.value === 'selected' && !data.value?.settings.email_recipients?.length)
function setSetting<K extends Exclude<keyof HostSettings, 'email_recipients'>>(key: K, value: NonNullable<HostSettings[K]>) {
  if (!data.value || !original.value) return
  const previous = original.value.settings[key]
  const fallback = data.value.defaults[key] ?? (key === 'min_severity' ? 'warning' : key === 'cooldown_min' ? 30 : key.startsWith('agent_pull_') ? 1 : false)
  data.value.settings[key] = value === (previous ?? fallback) ? previous : value
}
function setRecipients(value: unknown) {
  if (!data.value) return
  const next = Array.isArray(value) ? value.map(Number) : []
  const previous = original.value?.settings.email_recipients
  data.value.settings.email_recipients = previous && sameFormValue([...previous].sort(), [...next].sort()) ? [...previous] : next
}
const rules = computed<Record<string, MetricRule>>({
  get: () => Object.fromEntries((data.value?.rules || []).map(({ alert_type, ...rule }) => [alert_type, rule])),
  set: value => {
    if (!data.value || !original.value) return
    const restored = Object.entries(value).flatMap(([alert_type, rule]) => {
      const previous = original.value!.rules.find(item => item.alert_type === alert_type)
      const fields = Object.fromEntries(Object.entries(rule).flatMap(([field, next]) => {
        const key = field as keyof MetricRule
        const old = previous?.[key]
        if (next !== (old ?? data.value!.defaults.rules[alert_type]?.[key])) return [[field, next]]
        return old === undefined ? [] : [[field, old]]
      }))
      return previous || Object.keys(fields).length ? [{ alert_type, ...fields }] : []
    })
    data.value.rules = restored.sort((a, b) => a.alert_type.localeCompare(b.alert_type))
  },
})
const dirty = computed(() => !!data.value && (formSnapshot(data.value) !== baseline.value || invalidRecipients.value))
async function load() {
  loading.value = true
  try {
    const results = await Promise.allSettled([get<Payload>(`/api/admin/hosts/${props.hostId}/alerts`), props.connectionOnly ? null : get<{ admins: typeof admins.value }>('/api/admin/notifications/center')])
    const [result, center] = results
    if (result.status === 'fulfilled') {
      result.value.rules.sort((a, b) => a.alert_type.localeCompare(b.alert_type))
      data.value = result.value
      baseline.value = formSnapshot(result.value)
      selectingRecipients.value = false
    }
    if (center.status === 'fulfilled' && center.value) admins.value = center.value.admins
    for (const result of results) if (result.status === 'rejected') handleError(result.reason)
  } finally { loading.value = false }
}
async function save() {
  if (!data.value || saving.value || invalidRecipients.value) return false
  saving.value = true
  const edited = JSON.parse(JSON.stringify(data.value)) as Payload
  const submitted = JSON.parse(JSON.stringify(data.value)) as Payload
  try {
    if (props.connectionOnly) {
      const latest = await get<Payload>(`/api/admin/hosts/${props.hostId}/alerts`)
      if (!latest) return false
      submitted.rules = latest.rules
      submitted.settings = { ...latest.settings, agent_pull_timeout: submitted.settings.agent_pull_timeout, agent_pull_attempts: submitted.settings.agent_pull_attempts }
    }
    const result = await put<Payload>(`/api/admin/hosts/${props.hostId}/alerts`, { settings: submitted.settings, rules: submitted.rules })
    if (!result) return false
    const later = Object.fromEntries((['settings', 'rules'] as const)
      .filter(key => !sameFormValue(data.value![key], edited[key]))
      .map(key => [key, data.value![key]]))
    result.rules.sort((a, b) => a.alert_type.localeCompare(b.alert_type))
    baseline.value = formSnapshot(result)
    data.value = { ...result, ...later }
    return !dirty.value
  } finally { saving.value = false }
}
function discard() { if (baseline.value) data.value = JSON.parse(baseline.value); selectingRecipients.value = false }
useDirtyFormSection({ name: 'host-alerting', isDirty: dirty, save, discard })
onMounted(load)
</script>

<template>
  <LoadingCenter v-if="loading" />
  <BaseButton v-else-if="!data" @click="load">{{ t('notifications.reload') }}</BaseButton>
  <fieldset v-else :disabled="saving" :inert="saving" class="host-alert-settings">
    <BaseCard v-if="connectionOnly" variant="bg2" density="compact">
        <SectionHeader icon="monitoring" :subtitle="t('hosts.setting.alerting.pullDesc')" flush>{{ t('hosts.setting.alerting.pullSection') }}</SectionHeader>
        <FormField v-for="key in (['agent_pull_timeout', 'agent_pull_attempts'] as const)" :key="key" :label="t(key === 'agent_pull_timeout' ? 'hosts.setting.alerting.fields.pullTimeout' : 'hosts.setting.alerting.fields.pullAttempts')" layout="horizontal">
          <NumberInput :model-value="data.settings[key] ?? data.defaults[key] ?? 1" :min="1" :max="key === 'agent_pull_timeout' ? 60 : 5" @update:model-value="setSetting(key, $event)" />
        </FormField>
    </BaseCard>
    <template v-else>
      <BaseCard variant="bg2" density="compact">
        <SectionHeader icon="notifications" :subtitle="t('notifications.center.subtitles.hostDelivery')" flush>{{ t('notifications.center.delivery') }}</SectionHeader>
        <FormField :label="t('notifications.center.email')" layout="horizontal">
          <ToggleSwitch :model-value="data.settings.email_enabled ?? data.defaults.email_enabled ?? false" size="sm" @update:model-value="setSetting('email_enabled', $event)" />
        </FormField>
        <FormField :label="t('notifications.center.emailRecipients')" layout="horizontal"><BaseSelect v-model="recipientMode" :options="recipientModes" teleport /></FormField>
        <FormField v-if="recipientMode === 'selected'" :label="t('notifications.center.selectedAdmins')" :error="invalidRecipients ? t('notifications.center.selectAdmin') : undefined" layout="horizontal">
          <BaseSelect :model-value="data.settings.email_recipients || []" multiple searchable teleport :options="admins" @update:model-value="setRecipients" />
        </FormField>
        <FormField :label="t('notifications.center.emailResolved')" layout="horizontal">
          <ToggleSwitch :model-value="data.settings.notify_resolve ?? data.defaults.notify_resolve ?? false" size="sm" @update:model-value="setSetting('notify_resolve', $event)" />
        </FormField>
        <FormField v-if="wecom" :label="t('notifications.center.wecom')" layout="horizontal">
          <span class="field-value">{{ t(wecom.enabled ? 'hosts.setting.alerting.on' : 'hosts.setting.alerting.off') }}<template v-if="wecom.enabled"> · {{ wecom.group }}</template></span>
        </FormField>
        <FormField v-if="wecom?.enabled" :label="t('notifications.center.wecomResolved')" layout="horizontal"><span class="field-value">{{ t(wecom.resolved ? 'hosts.setting.alerting.on' : 'hosts.setting.alerting.off') }}</span></FormField>
      </BaseCard>
      <BaseCard variant="bg2" density="compact">
        <SectionHeader icon="tune" :subtitle="t('notifications.center.subtitles.reminderPolicy')" flush>{{ t('notifications.center.reminderPolicy') }}</SectionHeader>
        <FormField :label="t('notifications.minSeverity')" layout="horizontal">
          <BaseSelect :model-value="data.settings.min_severity ?? data.defaults.min_severity ?? 'warning'" :options="severityOptions" teleport @update:model-value="setSetting('min_severity', String($event))" />
        </FormField>
        <FormField :label="t('notifications.center.cooldown')" layout="horizontal">
          <NumberInput :model-value="data.settings.cooldown_min ?? data.defaults.cooldown_min ?? 30" :min="1" :max="1440" @update:model-value="setSetting('cooldown_min', $event)" />
        </FormField>
      </BaseCard>
      <BaseCard variant="bg2" density="compact">
        <SectionHeader icon="monitoring" :subtitle="t('notifications.center.subtitles.conditions')" flush>{{ t('notifications.center.conditions') }}</SectionHeader>
        <MetricRulesEditor v-model="rules" :defaults="data.defaults.rules" :host-kind="hostKind" />
      </BaseCard>
    </template>
  </fieldset>
</template>

<style scoped>
.host-alert-settings { border: 0; padding: 0; margin: 0; min-width: 0; display: flex; flex-direction: column; gap: var(--sp-4); }
.field-value { font-size: var(--text-base); color: var(--t2); }
</style>

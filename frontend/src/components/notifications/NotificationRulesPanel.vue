<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import BaseCard from '@/components/ui/BaseCard.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import FormField from '@/components/form/FormField.vue'
import NumberInput from '@/components/form/NumberInput.vue'
import ToggleSwitch from '@/components/ui/ToggleSwitch.vue'
import SectionHeader from '@/components/ui/SectionHeader.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Badge from '@/components/ui/Badge.vue'
import MetricRulesEditor from './MetricRulesEditor.vue'
import HostAlertingSection from '@/pages/host/sections/HostAlertingSection.vue'
import { TIMEZONE_OPTIONS } from '@/config/timezones'
import { type NotificationConfig, type NotificationRuleCategory } from '@/types/notifications'

const data = defineModel<NotificationConfig>({ required: true })
const props = defineProps<{ category: NotificationRuleCategory; hostId: number }>()
const { t } = useI18n()
const host = computed(() => data.value.hosts.find(h => h.id === props.hostId))
const rule = computed(() => props.category === 'lifecycle' ? null : data.value.policy.routes[props.category])
const groups = computed(() => data.value.policy.groups.map(g => ({ value: g.id, label: g.name })))
const severities = computed(() => ['info', 'warning', 'critical'].map(value => ({ value, label: t(`notifications.severity.${value}`) })))
const inheritedWecom = computed(() => {
  const monitoring = data.value.policy.routes.monitoring
  return { enabled: monitoring.wecom && Boolean(data.value.settings.WECOM_ENABLED), resolved: monitoring.wecom_resolved,
    group: data.value.policy.groups.find(g => g.id === monitoring.wecom_group)?.name || '—' }
})
</script>

<template>
  <h3 class="panel-title">{{ category === 'monitoring' ? host?.name || t('notifications.center.globalRules') : t(category === 'lifecycle' ? 'notifications.center.lifecycle' : `notifications.category.${category}`) }}</h3>

  <template v-if="category === 'lifecycle'">
    <BaseCard variant="bg2" density="compact">
      <SectionHeader icon="mail" :subtitle="t('notifications.center.subtitles.lifecycle')" flush>{{ t('notifications.center.lifecycle') }}</SectionHeader>
      <FormField :label="t('notifications.center.recipient')" layout="horizontal"><span class="field-value">{{ t('notifications.center.serverOwner') }}</span></FormField>
      <FormField v-for="key in ['expiry', 'expired', 'pre_delete', 'installed']" :key="key" :label="t(`notifications.center.lifecycleTypes.${key}`)" layout="horizontal" keep-horizontal>
        <ToggleSwitch v-model="data.policy.lifecycle[key]" size="sm" />
      </FormField>
    </BaseCard>
    <BaseCard v-if="data.policy.lifecycle.expiry || data.policy.lifecycle.expired || data.policy.lifecycle.pre_delete" variant="bg2" density="compact">
      <SectionHeader icon="schedule" :subtitle="t('notifications.center.subtitles.reminderSchedule')" flush>{{ t('notifications.center.reminderSchedule') }}</SectionHeader>
      <FormField :label="t('settings.automation.email.runHour')" layout="horizontal"><NumberInput v-model="data.settings.AUTOMATION_EMAIL_RUN_HOUR" :min="0" :max="23" /></FormField>
      <FormField :label="t('settings.automation.email.runMinute')" layout="horizontal"><NumberInput v-model="data.settings.AUTOMATION_EMAIL_RUN_MINUTE" :min="0" :max="59" /></FormField>
      <FormField :label="t('settings.automation.timezone')" layout="horizontal"><BaseSelect v-model="data.settings.TIMEZONE" :options="TIMEZONE_OPTIONS as any" searchable teleport /></FormField>
    </BaseCard>
  </template>

  <HostAlertingSection
    v-else-if="category === 'monitoring' && host" :key="host.id" :host-id="host.id" :host-kind="host.kind" :wecom="inheritedWecom"
  />

  <template v-else-if="rule">
    <BaseCard variant="bg2" density="compact">
      <SectionHeader icon="notifications" :subtitle="t('notifications.center.subtitles.delivery')" flush>{{ t('notifications.center.delivery') }}</SectionHeader>
      <template v-for="channel in (['email', 'wecom'] as const)" :key="channel">
        <FormField :label="t(`notifications.center.${channel}`)" layout="horizontal" keep-horizontal>
          <template #label>{{ t(`notifications.center.${channel}`) }}<Badge v-if="channel === 'wecom' && !data.settings.WECOM_ENABLED">{{ t('notifications.center.channelDisabled') }}</Badge></template>
          <ToggleSwitch v-model="rule[channel]" size="sm" />
        </FormField>
        <FormField v-if="rule[channel]" :label="t(`notifications.center.${channel}Group`)" layout="horizontal">
          <BaseSelect v-model="rule[`${channel}_group`]" :options="groups" teleport />
        </FormField>
        <FormField v-if="category === 'monitoring' && rule[channel]" :label="t(`notifications.center.${channel}Resolved`)" layout="horizontal" keep-horizontal>
          <ToggleSwitch v-model="rule[`${channel}_resolved`]" size="sm" />
        </FormField>
      </template>
    </BaseCard>
    <BaseCard variant="bg2" density="compact">
      <SectionHeader icon="tune" :subtitle="t(category === 'support' ? 'notifications.center.subtitles.supportPolicy' : 'notifications.center.subtitles.reminderPolicy')" flush>{{ t('notifications.center.reminderPolicy') }}</SectionHeader>
      <FormField v-if="category !== 'support'" :label="t('notifications.minSeverity')" layout="horizontal"><BaseSelect v-model="rule.min_severity" :options="severities" teleport /></FormField>
      <FormField v-if="category === 'monitoring'" :label="t('notifications.center.cooldown')" layout="horizontal"><NumberInput v-model="rule.cooldown_min" :min="1" :max="1440" /></FormField>
      <FormField v-if="category === 'support'" :label="t('notifications.supportDelay')" layout="horizontal"><NumberInput v-model="data.settings.NOTIFY_SUPPORT_DELAY" :min="5" :max="300" /></FormField>
    </BaseCard>
    <BaseCard v-if="category === 'monitoring'" variant="bg2" density="compact">
      <SectionHeader icon="monitoring" :subtitle="t('notifications.center.subtitles.conditions')" flush>{{ t('notifications.center.conditions') }}</SectionHeader>
      <MetricRulesEditor v-model="data.policy.monitoring" />
    </BaseCard>
    <BaseCard v-if="category === 'certificate'" variant="bg2" density="compact">
      <SectionHeader icon="verified_user" :subtitle="t('notifications.center.subtitles.certificateDays')" flush>{{ t('notifications.center.certificateDays') }}</SectionHeader>
      <FormField v-for="cert in data.certificates" :key="cert.id" :label="cert.name" layout="horizontal"><NumberInput v-model="cert.days" :min="1" :max="90" /></FormField>
      <EmptyState v-if="!data.certificates.length" icon="verified_user" :title="t('common.empty')" density="compact" />
    </BaseCard>
  </template>
</template>

<style scoped>
.panel-title { margin: 0; font-size: var(--text-md); font-weight: 600; }
.field-value { font-size: var(--text-base); color: var(--t2); }
</style>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import BaseCard from '@/components/ui/BaseCard.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import NumberInput from '@/components/form/NumberInput.vue'
import FormField from '@/components/form/FormField.vue'
import SecretInput from '@/components/ui/SecretInput.vue'
import ToggleSwitch from '@/components/ui/ToggleSwitch.vue'
import SectionHeader from '@/components/ui/SectionHeader.vue'
import type { NotificationConfig, NotificationChannel } from '@/types/notifications'

const data = defineModel<NotificationConfig>({ required: true })
const props = defineProps<{ dirty: boolean; saving: boolean; channel: NotificationChannel }>()
const { t } = useI18n()
const { post } = useApiFetch()
const { toast } = useToast()
const testGroup = ref('')
const testEmail = ref('')
const testing = ref(false)
const groups = computed(() => data.value.policy.groups.filter(g => g.wecom_ids.length).map(g => ({ value: g.id, label: g.name })))
watch(groups, options => { if (!options.some(g => g.value === testGroup.value)) testGroup.value = options[0]?.value || '' }, { immediate: true })
async function test() {
  if (testing.value || props.dirty || props.saving) return
  testing.value = true
  try {
    if (props.channel === 'wecom') await post('/api/admin/notifications/center/test', { group: testGroup.value })
    else await post('/api/admin/test-email', { recipient: testEmail.value })
    toast(t('notifications.center.testSuccess'), 'success')
  } finally { testing.value = false }
}
</script>

<template>
  <BaseCard variant="bg2" density="compact">
    <SectionHeader :icon="channel === 'email' ? 'mail' : 'notifications'" :subtitle="t(`notifications.center.subtitles.${channel}`)" flush>{{ t(`notifications.center.${channel}`) }}</SectionHeader>
    <template v-if="channel === 'wecom'">
      <FormField :label="t('notifications.enabled')" layout="horizontal" keep-horizontal><ToggleSwitch v-model="data.settings.WECOM_ENABLED" size="sm" /></FormField>
      <FormField :label="t('notifications.corpId')" layout="horizontal"><BaseInput v-model="data.settings.WECOM_CORP_ID" autocomplete="off" /></FormField>
      <FormField :label="t('notifications.agentId')" layout="horizontal"><BaseInput v-model="data.settings.WECOM_AGENT_ID" /></FormField>
      <FormField :label="t('notifications.secret')" layout="horizontal"><SecretInput v-model="data.settings.WECOM_SECRET" is-password /></FormField>
    </template>
    <template v-else>
      <FormField :label="t('settings.smtp.host')" layout="horizontal"><BaseInput v-model="data.settings.SMTP_HOST" /></FormField>
      <FormField :label="t('settings.smtp.port')" layout="horizontal"><NumberInput v-model="data.settings.SMTP_PORT" :min="1" :max="65535" /></FormField>
      <FormField :label="t('settings.smtp.sender')" layout="horizontal"><BaseInput v-model="data.settings.SENDER_EMAIL" type="email" /></FormField>
      <FormField :label="t('settings.smtp.password')" layout="horizontal"><SecretInput v-model="data.settings.SMTP_PASSWORD" /></FormField>
      <FormField :label="t('settings.smtp.ssl')" layout="horizontal" keep-horizontal><ToggleSwitch v-model="data.settings.SMTP_USE_SSL" size="sm" /></FormField>
      <FormField :label="t('settings.smtp.delay')" layout="horizontal"><NumberInput v-model="data.settings.EMAIL_SEND_DELAY" :min="0" :max="60" /></FormField>
    </template>
  </BaseCard>
  <BaseCard variant="bg2" density="compact">
    <SectionHeader icon="network_check" :subtitle="t('notifications.center.subtitles.channelTest')" flush>{{ t('notifications.center.channelTest') }}</SectionHeader>
    <FormField v-if="channel === 'wecom'" :label="t('notifications.center.recipientGroup')" layout="horizontal"><BaseSelect v-model="testGroup" :options="groups" teleport /></FormField>
    <FormField v-else :label="t('settings.smtp.testRecipient')" layout="horizontal"><BaseInput v-model="testEmail" type="email" /></FormField>
    <div class="test-actions">
      <BaseButton size="sm" :loading="testing" :disabled="dirty || saving || (channel === 'wecom' ? !data.settings.WECOM_ENABLED || !testGroup : !testEmail)" @click="test">{{ t('notifications.test') }}</BaseButton>
    </div>
  </BaseCard>
</template>

<style scoped>
.test-actions { display: flex; justify-content: flex-end; }
</style>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import BaseCard from '@/components/ui/BaseCard.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import FormField from '@/components/form/FormField.vue'
import ToggleSwitch from '@/components/ui/ToggleSwitch.vue'
import CollapsibleGroup from '@/components/ui/CollapsibleGroup.vue'
import SectionToolbar from '@/components/ui/SectionToolbar.vue'
import PageHeaderActions from '@/components/layout/PageHeaderActions.vue'
import Badge from '@/components/ui/Badge.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import { notificationCategories, type NotificationConfig } from '@/types/notifications'

const data = defineModel<NotificationConfig>({ required: true })
defineProps<{ disabled?: boolean }>()
const { t } = useI18n()
const initialGroups = new Set(data.value.policy.groups.map(g => g.id))
function usedBy(id: string) { return notificationCategories.filter(category => {
  const rule = data.value.policy.routes[category]
  return rule.email_group === id || rule.wecom_group === id
}) }
function addGroup() {
  data.value.policy.groups.push({ id: `g_${crypto.randomUUID().replace(/-/g, '').slice(0, 16)}`, name: t('notifications.center.newGroup'), all_admins: false, admin_ids: [], wecom_ids: [] })
}
function removeGroup(id: string) {
  if (!usedBy(id).length) data.value.policy.groups = data.value.policy.groups.filter(g => g.id !== id)
}
</script>

<template>
  <PageHeaderActions>
    <BaseButton size="sm" variant="primary" :disabled="disabled" @click="addGroup"><MsIcon name="add" size="sm" />{{ t('notifications.center.addGroup') }}</BaseButton>
  </PageHeaderActions>
  <SectionToolbar>
    <template #start><span class="toolbar-status">{{ t('notifications.center.groupCount', { count: data.policy.groups.length }) }}</span></template>
  </SectionToolbar>
  <BaseCard v-for="(group, index) in data.policy.groups" :key="group.id" variant="bg2" density="compact">
    <CollapsibleGroup :title="group.name || t('notifications.center.newGroup')" :subtitle="t('notifications.center.subtitles.recipientGroup')" icon="group" :default-open="index === 0 || !initialGroups.has(group.id)">
      <FormField :label="t('notifications.center.groupName')" layout="horizontal"><BaseInput v-model="group.name" maxlength="60" /></FormField>
      <FormField :label="t('notifications.center.allAdmins')" layout="horizontal" keep-horizontal><ToggleSwitch v-model="group.all_admins" size="sm" /></FormField>
      <FormField v-if="!group.all_admins" :label="t('notifications.center.emailRecipients')" layout="horizontal"><BaseSelect v-model="group.admin_ids" :options="data.admins" multiple searchable teleport /></FormField>
      <FormField :label="t('notifications.recipients')" layout="horizontal"><BaseInput :model-value="group.wecom_ids.join(', ')" @update:model-value="group.wecom_ids = $event.split(/[,;\s，；]+/).filter(Boolean)" /></FormField>
      <FormField v-if="usedBy(group.id).length" :label="t('notifications.center.usedBy')" layout="horizontal"><div class="group-usage"><Badge v-for="category in usedBy(group.id)" :key="category">{{ t(`notifications.category.${category}`) }}</Badge></div></FormField>
      <div class="group-actions"><BaseButton size="sm" variant="danger" :disabled="!!usedBy(group.id).length" @click="removeGroup(group.id)">{{ t('notifications.center.deleteGroup') }}</BaseButton></div>
    </CollapsibleGroup>
  </BaseCard>
</template>

<style scoped>
.group-usage { display: flex; flex-wrap: wrap; gap: var(--sp-2); }
.group-actions { display: flex; justify-content: flex-end; }
</style>

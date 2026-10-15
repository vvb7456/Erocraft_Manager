<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { provideDirtyForm } from '@/composables/useDirtyForm'
import { useNotificationConfig } from '@/composables/useNotificationConfig'
import PageHeader from '@/components/layout/PageHeader.vue'
import WorkspacePage from '@/components/layout/WorkspacePage.vue'
import SettingsWorkspace from '@/components/layout/SettingsWorkspace.vue'
import type { SettingsNavItem } from '@/components/layout/SettingsNavigation.vue'
import TabSwitcher from '@/components/ui/TabSwitcher.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import LoadingCenter from '@/components/ui/LoadingCenter.vue'
import DirtyBar from '@/components/ui/DirtyBar.vue'
import NotificationAlertsPanel from '@/components/notifications/NotificationAlertsPanel.vue'
import NotificationRulesPanel from '@/components/notifications/NotificationRulesPanel.vue'
import EmailTemplatesPage from '@/pages/EmailTemplatesPage.vue'
import WecomTemplatesPanel from '@/components/notifications/WecomTemplatesPanel.vue'
import { notificationCategories, type NotificationRuleCategory } from '@/types/notifications'
import { emailTemplateKeys, type EmailTemplateKey } from '@/types/emailTemplates'
import { wecomTemplateKeys, type WecomTemplateKey } from '@/types/wecomTemplates'

defineOptions({ name: 'NotificationsPage' })

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const tab = computed(() => ['rules', 'templates', 'wecomTemplates'].includes(String(route.query.tab)) ? String(route.query.tab) : 'alerts')
const tabs = computed(() => [
  { key: 'alerts', icon: 'notifications', label: t('notifications.center.alerts') },
  { key: 'rules', icon: 'tune', label: t('notifications.center.rules') },
  { key: 'templates', icon: 'mail', label: t('notifications.center.templates') },
  { key: 'wecomTemplates', icon: 'chat', label: t('notifications.center.wecomTemplates') },
])
const templateKey = computed<EmailTemplateKey>(() => emailTemplateKeys.includes(route.query.template as EmailTemplateKey) ? route.query.template as EmailTemplateKey : 'bulk')
const wecomTemplateKey = computed<WecomTemplateKey>(() => wecomTemplateKeys.includes(route.query.template as WecomTemplateKey) ? route.query.template as WecomTemplateKey : 'support')
const category = computed<NotificationRuleCategory>(() => {
  const value = String(route.query.category)
  return [...notificationCategories, 'lifecycle'].includes(value) ? value as NotificationRuleCategory : 'monitoring'
})
const dirtyForm = provideDirtyForm()
dirtyForm.attachLeaveGuard({
  update: (to, from) => {
    if (from.query.tab === 'templates' || from.query.tab === 'wecomTemplates') return to.query.tab !== from.query.tab
    if (from.query.tab === 'rules' && (!from.query.category || from.query.category === 'monitoring') && Number(from.query.host)) {
      return to.query.tab !== 'rules' || (to.query.category && to.query.category !== 'monitoring') || Number(to.query.host) !== Number(from.query.host)
    }
    return false
  },
})
const { data, loading, load } = useNotificationConfig(dirtyForm)
const navItems = computed<SettingsNavItem[]>(() => tab.value === 'templates'
  ? emailTemplateKeys.map(key => ({ key: `templates:${key}`, label: t(`emailTemplates.${key}.title`) }))
  : tab.value === 'wecomTemplates'
  ? wecomTemplateKeys.map(key => ({ key: `wecomTemplates:${key}`, label: t(`notifications.wecomTemplates.types.${key}`) }))
  : [
    ...notificationCategories.map(key => ({ key: `rules:${key}`, label: t(`notifications.category.${key}`), children: key === 'monitoring' ? [
      { key: 'host:0', label: t('notifications.center.globalRules') },
      ...(data.value?.hosts || []).map(host => ({ key: `host:${host.id}`, label: host.name })),
    ] : undefined })),
    { key: 'rules:lifecycle', label: t('notifications.center.lifecycle') },
  ])
const selectedNav = computed(() => tab.value === 'templates' ? `templates:${templateKey.value}`
  : tab.value === 'wecomTemplates' ? `wecomTemplates:${wecomTemplateKey.value}`
  : category.value === 'monitoring' ? `host:${Number(route.query.host) || 0}` : `rules:${category.value}`)

function navigate(query: Record<string, string | number | undefined>) {
  void router.push({ query: { ...route.query, ...query } })
}
function selectTab(value: string) {
  navigate({ tab: value, category: undefined, host: undefined, template: undefined })
}
function selectNav(key: string) {
  const [section, value] = key.split(':')
  if (section === 'host') navigate({ category: 'monitoring', host: Number(value) || undefined })
  else if (section === 'templates' || section === 'wecomTemplates') navigate({ template: value })
  else navigate({ category: value, host: undefined })
}
onMounted(load)
</script>

<template>
  <WorkspacePage :contained="tab !== 'alerts'">
    <template #header>
      <PageHeader icon="notifications" :title="t('notifications.title')">
        <TabSwitcher :tabs="tabs" :model-value="tab" @update:model-value="selectTab" />
      </PageHeader>
    </template>
    <NotificationAlertsPanel v-if="tab === 'alerts'" />
    <SettingsWorkspace v-else :key="tab" :items="navItems" :model-value="selectedNav" :label="t(`notifications.center.${tab}`)" :storage-key="`notifications-${tab}`" :wide="tab === 'templates' || tab === 'wecomTemplates'" :disabled="dirtyForm.saving.value" @update:model-value="selectNav">
      <EmailTemplatesPage v-if="tab === 'templates'" :template-key="templateKey" />
      <WecomTemplatesPanel v-else-if="tab === 'wecomTemplates'" :template-key="wecomTemplateKey" />
      <LoadingCenter v-else-if="loading" />
      <BaseButton v-else-if="!data" @click="load">{{ t('notifications.reload') }}</BaseButton>
      <fieldset v-else class="st-panel" :disabled="dirtyForm.saving.value" :inert="dirtyForm.saving.value">
        <NotificationRulesPanel v-model="data" :category="category" :host-id="Number(route.query.host) || 0" />
      </fieldset>
    </SettingsWorkspace>
  </WorkspacePage>
  <DirtyBar :dirty="dirtyForm.isDirty.value" :saving="dirtyForm.saving.value" @save="dirtyForm.save" @discard="dirtyForm.discard" />
</template>

<style scoped>
.st-panel { margin: 0; padding: 0; border: 0; min-width: 0; display: flex; flex-direction: column; gap: var(--sp-4); }
</style>

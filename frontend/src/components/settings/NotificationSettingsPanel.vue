<script setup lang="ts">
import { onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useNotificationConfig } from '@/composables/useNotificationConfig'
import { useParentDirtyForm } from '@/composables/useDirtyForm'
import NotificationChannelsPanel from '@/components/notifications/NotificationChannelsPanel.vue'
import NotificationRecipientsPanel from '@/components/notifications/NotificationRecipientsPanel.vue'
import LoadingCenter from '@/components/ui/LoadingCenter.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import type { NotificationChannel } from '@/types/notifications'

defineProps<{ section: 'channels' | 'recipients'; channel: NotificationChannel }>()
const { t } = useI18n()
const dirtyForm = useParentDirtyForm()
const { data, loading, dirty, load } = useNotificationConfig()
onMounted(load)
</script>

<template>
  <LoadingCenter v-if="loading" />
  <BaseButton v-else-if="!data" @click="load">{{ t('notifications.reload') }}</BaseButton>
  <div v-else class="notification-settings" :inert="dirtyForm.saving.value">
    <NotificationChannelsPanel v-if="section === 'channels'" v-model="data" :channel="channel" :dirty="dirty" :saving="dirtyForm.saving.value" />
    <NotificationRecipientsPanel v-else v-model="data" :disabled="dirtyForm.saving.value" />
  </div>
</template>

<style scoped>
.notification-settings { display: flex; flex-direction: column; gap: var(--sp-4); }
</style>

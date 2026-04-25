<script setup lang="ts">
import { computed, inject, ref, watch, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'
import BaseCard from '@/components/ui/BaseCard.vue'
import SectionHeader from '@/components/ui/SectionHeader.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseModal from '@/components/ui/BaseModal.vue'
import AlertBanner from '@/components/ui/AlertBanner.vue'
import FormField from '@/components/form/FormField.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import ToggleSwitch from '@/components/ui/ToggleSwitch.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import type { AdminServerDetailResponse } from '@/types/adminServer'

defineOptions({ name: 'AdminServerLifecyclePane' })

const { t } = useI18n({ useScope: 'global' })
const router = useRouter()
const { post, del, loading } = useApiFetch()
const { toast } = useToast()
const { confirm } = useConfirm()

const detail = inject<Ref<AdminServerDetailResponse | null>>('adminServerDetail')!
const serverId = inject<Ref<number | null>>('adminServerId')!
const reload = inject<() => Promise<void>>('reloadAdminServer', async () => {})

const renewDate = ref('')
const deleteModalOpen = ref(false)
const deleteConfirmName = ref('')
const deleteForce = ref(false)
const deleteAcknowledge = ref(false)
const deleteSubmitting = ref(false)

const server = computed(() => detail.value?.server ?? null)
const serverName = computed(() => server.value?.name ?? '')
const isSuspended = computed(() => server.value?.isSuspended ?? false)
const isInstalling = computed(() => server.value?.isInstalling ?? false)

const daysLeft = computed<number | null>(() => {
  const exp = server.value?.expirationDate
  if (!exp) return null
  const expDate = new Date(`${exp}T00:00:00`)
  if (Number.isNaN(expDate.getTime())) return null
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  return Math.floor((expDate.getTime() - today.getTime()) / 86_400_000)
})

function addDays(base: Date, days: number): string {
  const next = new Date(base)
  next.setDate(next.getDate() + days)
  return next.toISOString().slice(0, 10)
}

function calcDefaultRenewDate(): string {
  const exp = server.value?.expirationDate
  const today = new Date()
  if (!exp || (daysLeft.value !== null && daysLeft.value < 0)) {
    return addDays(today, 30)
  }
  return addDays(new Date(`${exp}T00:00:00`), 30)
}

function resetRenewDate() {
  renewDate.value = calcDefaultRenewDate()
}

function quickRenew(days: number) {
  const exp = server.value?.expirationDate
  const today = new Date()
  const base = !exp || (daysLeft.value !== null && daysLeft.value < 0)
    ? today
    : new Date(`${exp}T00:00:00`)
  renewDate.value = addDays(base, days)
}

function expirationText(): string {
  if (!server.value) return '—'
  if (!server.value.expirationDate) return t('adminServer.overview.values.permanent')
  if (daysLeft.value === null) return server.value.expirationDate
  if (daysLeft.value < 0) return t('adminServer.lifecycle.expiration.expired', { date: server.value.expirationDate })
  if (daysLeft.value === 0) return t('adminServer.lifecycle.expiration.today', { date: server.value.expirationDate })
  return t('adminServer.lifecycle.expiration.daysLeft', { date: server.value.expirationDate, n: daysLeft.value })
}

const expirationColor = computed(() => {
  if (!server.value || server.value.expirationDate === null) return 'var(--t2)'
  if (daysLeft.value === null) return 'var(--t2)'
  if (daysLeft.value <= 0) return 'var(--red)'
  if (daysLeft.value <= 7) return 'var(--amber)'
  return 'var(--green)'
})

const canSubmitDelete = computed(() => {
  return deleteConfirmName.value.trim() === serverName.value && (!deleteForce.value || deleteAcknowledge.value)
})

async function doToggleSuspend() {
  if (!server.value || !serverId.value) return
  const suspended = isSuspended.value
  const ok = await confirm({
    title: suspended
      ? t('adminServer.lifecycle.suspend.unsuspendTitle')
      : t('adminServer.lifecycle.suspend.suspendTitle'),
    message: suspended
      ? t('adminServer.lifecycle.suspend.unsuspendMessage', { name: server.value.name })
      : t('adminServer.lifecycle.suspend.suspendMessage', { name: server.value.name }),
    confirmText: suspended
      ? t('adminServer.lifecycle.suspend.unsuspendAction')
      : t('adminServer.lifecycle.suspend.suspendAction'),
    variant: suspended ? 'default' : 'danger',
  })
  if (!ok) return
  const res = await post<{ message: string; isSuspended: boolean }>(`/api/admin/servers/${serverId.value}/suspend`)
  if (!res) return
  toast(res.message, 'success')
  await reload()
}

async function doRenew() {
  if (!server.value || !serverId.value || !renewDate.value) return
  const res = await post<{ message: string }>(`/api/admin/servers/${serverId.value}/renew`, { date: renewDate.value })
  if (!res) return
  toast(res.message, 'success')
  await reload()
  resetRenewDate()
}

async function doReinstall() {
  if (!server.value || !serverId.value) return
  const ok = await confirm({
    title: t('adminServer.lifecycle.reinstall.title'),
    message: t('adminServer.lifecycle.reinstall.confirmMessage', { name: server.value.name }),
    confirmText: t('adminServer.lifecycle.reinstall.action'),
    variant: 'danger',
  })
  if (!ok) return
  const res = await post<{ message: string }>(`/api/admin/servers/${serverId.value}/reinstall`)
  if (!res) return
  toast(res.message, 'success')
  await reload()
}

function openDeleteModal(force = false) {
  deleteConfirmName.value = ''
  deleteAcknowledge.value = false
  deleteForce.value = force
  deleteModalOpen.value = true
}

async function doDelete() {
  if (!server.value || !serverId.value || !canSubmitDelete.value) return
  deleteSubmitting.value = true
  try {
    const query = deleteForce.value ? '?force=true' : ''
    const res = await del<{ message: string }>(`/api/admin/servers/${serverId.value}${query}`)
    if (!res) return
    toast(res.message, deleteForce.value ? 'warning' : 'success')
    deleteModalOpen.value = false
    router.push({ name: 'servers' })
  } finally {
    deleteSubmitting.value = false
  }
}

watch(detail, () => {
  resetRenewDate()
}, { immediate: true })
</script>

<template>
  <div v-if="server" class="lifecycle-panel">
    <BaseCard variant="bg2" class="lifecycle-card">
      <SectionHeader icon="pause_circle" flush>{{ t('adminServer.lifecycle.suspend.sectionTitle') }}</SectionHeader>
      <div class="card-actions">
        <BaseButton :variant="isSuspended ? 'success' : 'danger'" :loading="loading" @click="doToggleSuspend">
          <MsIcon :name="isSuspended ? 'play_arrow' : 'pause'" size="xs" />
          {{ isSuspended ? t('adminServer.lifecycle.suspend.unsuspendAction') : t('adminServer.lifecycle.suspend.suspendAction') }}
        </BaseButton>
      </div>
    </BaseCard>

    <BaseCard variant="bg2" class="lifecycle-card">
      <SectionHeader icon="update" flush>{{ t('adminServer.lifecycle.renew.sectionTitle') }}</SectionHeader>
      <div class="renew-current">
        <span class="renew-current__label">{{ t('adminServer.lifecycle.renew.currentExpiration') }}</span>
        <span class="renew-current__value" :style="{ color: expirationColor }">{{ expirationText() }}</span>
      </div>
      <FormField class="renew-field" :label="t('adminServer.lifecycle.renew.targetDate')" layout="horizontal">
        <input v-model="renewDate" class="date-input" type="date">
      </FormField>
      <div class="quick-row">
        <BaseButton size="sm" variant="default" @click="quickRenew(7)">{{ t('adminServer.lifecycle.renew.quickDays', { n: 7 }) }}</BaseButton>
        <BaseButton size="sm" variant="default" @click="quickRenew(30)">{{ t('adminServer.lifecycle.renew.quickDays', { n: 30 }) }}</BaseButton>
        <BaseButton size="sm" variant="default" @click="quickRenew(365)">{{ t('adminServer.lifecycle.renew.quickDays', { n: 365 }) }}</BaseButton>
      </div>
      <div class="card-actions">
        <BaseButton variant="primary" :loading="loading" @click="doRenew">
          <MsIcon name="update" size="xs" />
          {{ t('adminServer.lifecycle.renew.action') }}
        </BaseButton>
      </div>
    </BaseCard>

    <BaseCard variant="bg2" class="lifecycle-card">
      <SectionHeader icon="autorenew" flush>{{ t('adminServer.lifecycle.reinstall.sectionTitle') }}</SectionHeader>
      <AlertBanner v-if="isInstalling" tone="warning" dense>
        {{ t('adminServer.lifecycle.reinstall.installingHint') }}
      </AlertBanner>
      <div class="card-actions">
        <BaseButton variant="warning" :disabled="isInstalling" :loading="loading" @click="doReinstall">
          <MsIcon name="autorenew" size="xs" />
          {{ t('adminServer.lifecycle.reinstall.action') }}
        </BaseButton>
      </div>
    </BaseCard>

    <BaseCard variant="bg2" class="lifecycle-card lifecycle-card--danger">
      <SectionHeader icon="delete_forever" flush>{{ t('adminServer.lifecycle.delete.sectionTitle') }}</SectionHeader>
      <AlertBanner tone="danger" dense>
        {{ t('adminServer.lifecycle.delete.warning') }}
      </AlertBanner>
      <div class="card-actions card-actions--danger">
        <BaseButton variant="danger" :loading="deleteSubmitting" @click="openDeleteModal(false)">
          <MsIcon name="delete" size="xs" />
          {{ t('adminServer.lifecycle.delete.action') }}
        </BaseButton>
        <BaseButton variant="danger" :loading="deleteSubmitting" @click="openDeleteModal(true)">
          <MsIcon name="delete_forever" size="xs" />
          {{ t('adminServer.lifecycle.delete.forceAction') }}
        </BaseButton>
      </div>
    </BaseCard>

    <BaseModal v-model="deleteModalOpen" :title="deleteForce ? t('adminServer.lifecycle.delete.forceModalTitle') : t('adminServer.lifecycle.delete.modalTitle')" icon="warning" size="sm" tone="danger">
      <div class="delete-modal">
        <p class="delete-message">
          {{ deleteForce ? t('adminServer.lifecycle.delete.forceConfirmMessage', { name: serverName }) : t('adminServer.lifecycle.delete.confirmMessage', { name: serverName }) }}
        </p>
        <FormField :label="t('adminServer.lifecycle.delete.inputLabel', { name: serverName })" layout="vertical">
          <BaseInput v-model="deleteConfirmName" :placeholder="serverName" />
        </FormField>
        <FormField v-if="deleteForce" :label="t('adminServer.lifecycle.delete.forceAcknowledge')" layout="horizontal">
          <ToggleSwitch v-model="deleteAcknowledge" size="sm" />
        </FormField>
      </div>
      <template #footer>
        <BaseButton @click="deleteModalOpen = false">{{ t('common.btn.cancel') }}</BaseButton>
        <BaseButton variant="danger" :disabled="!canSubmitDelete" :loading="deleteSubmitting" @click="doDelete">
          {{ deleteForce ? t('adminServer.lifecycle.delete.forceAction') : t('adminServer.lifecycle.delete.action') }}
        </BaseButton>
      </template>
    </BaseModal>
  </div>
</template>

<style scoped>
.lifecycle-panel {
  margin-top: var(--sp-4);
  max-width: 720px;
  margin-left: auto;
  margin-right: auto;
}

.lifecycle-panel > * + * {
  margin-top: var(--sp-5);
}

.card-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--sp-2);
  margin-top: var(--sp-4);
}

.card-actions--danger {
  flex-wrap: wrap;
}

.renew-current {
  display: flex;
  align-items: center;
  gap: var(--sp-1);
  margin-top: var(--sp-4);
  white-space: nowrap;
  overflow: hidden;
}

.renew-field {
  margin-top: var(--sp-4);
}

.renew-current__label {
  color: var(--t2);
  font-size: var(--text-sm);
  flex: 0 0 auto;
}

.renew-current__value {
  font-size: var(--text-sm);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.quick-row {
  display: flex;
  gap: var(--sp-2);
  margin-top: var(--sp-3);
}

.quick-row :deep(.base-btn) {
  flex: 1 1 0;
}

.date-input {
  width: 100%;
  padding: var(--sp-3);
  background: var(--bg3);
  border: 1px solid var(--bd);
  border-radius: var(--r-md);
  color: var(--t1);
  font-size: .88rem;
  -webkit-appearance: none;
}

.date-input:focus {
  border-color: var(--bd-f);
  outline: none;
}

.lifecycle-card--danger {
  border-color: color-mix(in srgb, var(--red) 22%, var(--bd));
}

.delete-modal {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

.delete-message {
  margin: 0;
  color: var(--t1);
  line-height: 1.6;
}

@media (max-width: 768px) {
  .card-actions {
    flex-wrap: wrap;
  }

  .card-actions :deep(.base-btn) {
    width: 100%;
  }

  .renew-current {
    white-space: normal;
    flex-wrap: wrap;
  }
}
</style>

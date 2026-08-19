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
import AlertBanner from '@/components/ui/AlertBanner.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import PlanChangeModal from '@/components/servers/PlanChangeModal.vue'
import { useToday } from '@/composables/useToday'
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
const deleteSubmitting = ref(false)

const server = computed(() => detail.value?.server ?? null)
const serverName = computed(() => server.value?.name ?? '')
const isSuspended = computed(() => server.value?.isSuspended ?? false)
const isInstalling = computed(() => server.value?.isInstalling ?? false)

const today = useToday()

const daysLeft = computed<number | null>(() => {
  const exp = server.value?.expirationDate
  if (!exp) return null
  // Pure date-string difference (both YYYY-MM-DD), no timezone conversion.
  const expMs = new Date(`${exp}T00:00:00Z`).getTime()
  const todayMs = new Date(`${today.value}T00:00:00Z`).getTime()
  if (Number.isNaN(expMs) || Number.isNaN(todayMs)) return null
  return Math.round((expMs - todayMs) / 86_400_000)
})

function addDays(base: string, days: number): string {
  const d = new Date(base + 'T00:00:00Z')
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}

function calcDefaultRenewDate(): string {
  const exp = server.value?.expirationDate
  if (!exp || (daysLeft.value !== null && daysLeft.value < 0)) {
    return addDays(today.value, 30)
  }
  return addDays(exp, 30)
}

function resetRenewDate() {
  renewDate.value = calcDefaultRenewDate()
}

function quickRenew(days: number) {
  const exp = server.value?.expirationDate
  const base = !exp || (daysLeft.value !== null && daysLeft.value < 0)
    ? today.value
    : exp
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
  if (!server.value || !serverId.value) return
  const trimmed = renewDate.value?.trim() ?? ''
  if (!trimmed) {
    const ok = await confirm({
      title: t('adminServer.lifecycle.renew.clearConfirmTitle'),
      message: t('adminServer.lifecycle.renew.clearConfirmMessage', { name: server.value.name }),
      confirmText: t('adminServer.lifecycle.renew.clearAction'),
      variant: 'danger',
    })
    if (!ok) return
  }
  const res = await post<{ message: string }>(
    `/api/admin/servers/${serverId.value}/renew`,
    { date: trimmed || null },
  )
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
  void confirmDelete(force)
}

async function confirmDelete(force: boolean) {
  if (!server.value || !serverId.value) return
  const ok = await confirm({
    title: force
      ? t('adminServer.lifecycle.delete.forceConfirmTitle')
      : t('adminServer.lifecycle.delete.confirmTitle'),
    message: force
      ? t('adminServer.lifecycle.delete.forceConfirmMessage', { name: serverName.value })
      : t('adminServer.lifecycle.delete.confirmMessage', { name: serverName.value }),
    confirmText: force
      ? t('adminServer.lifecycle.delete.forceAction')
      : t('adminServer.lifecycle.delete.action'),
    variant: 'danger',
  })
  if (!ok) return
  deleteSubmitting.value = true
  try {
    const query = force ? '?force=true' : ''
    const res = await del<{ message: string }>(`/api/admin/servers/${serverId.value}${query}`)
    if (!res) return
    toast(res.message, force ? 'warning' : 'success')
    router.push({ name: 'servers' })
  } finally {
    deleteSubmitting.value = false
  }
}

watch(detail, () => {
  resetRenewDate()
}, { immediate: true })

// ── Plan Change ──
const planModalOpen = ref(false)
const currentPlanId = computed(() => server.value?.planId ?? null)
const currentPlanName = computed(() => server.value?.planName ?? null)

async function onPlanModalConfirmed(planId: number | null) {
  if (!serverId.value) return
  try {
    const res = await fetch(`/api/admin/servers/${serverId.value}/plan`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ planId }),
    })
    if (res.ok) {
      toast(t('servers.toast.plan_updated'), 'success')
      planModalOpen.value = false
      await reload()
    } else {
      let msg = `HTTP ${res.status}`
      try {
        const body = await res.json()
        msg = body.detail || body.error || body.message || msg
      } catch { /* ignore */ }
      toast(msg, 'error')
    }
  } catch {
    toast(t('common.apiErrors.network'), 'error')
  }
}
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
      <SectionHeader icon="swap_horiz" flush>{{ t('adminServer.lifecycle.plan.sectionTitle') }}</SectionHeader>
      <div class="plan-current">
        <span class="plan-current__label">{{ t('adminServer.lifecycle.plan.currentBinding') }}</span>
        <span class="plan-current__value" :class="{ 'plan-current__value--none': !currentPlanName }">
          {{ currentPlanName ?? '—' }}
        </span>
      </div>
      <div class="card-actions">
        <BaseButton variant="primary" @click="planModalOpen = true">
          <MsIcon name="swap_horiz" size="xs" />
          {{ t('adminServer.lifecycle.plan.action') }}
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

    <PlanChangeModal
      v-model="planModalOpen"
      :server-name="serverName"
      :current-plan-id="currentPlanId"
      :current-plan-name="currentPlanName"
      @confirmed="onPlanModalConfirmed"
    />
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

.plan-current {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin-top: var(--sp-4);
  margin-bottom: var(--sp-3);
}

.plan-current__label {
  color: var(--t2);
  font-size: var(--text-sm);
}

.plan-current__value {
  color: var(--ac2);
  font-weight: 500;
  font-size: var(--text-sm);
}

.plan-current__value--none {
  color: var(--t3);
  font-weight: 400;
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

<script setup lang="ts">
import { computed, inject, onMounted, ref, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'
import { useFormatDate } from '@/composables/useFormatDate'
import BaseCard from '@/components/ui/BaseCard.vue'
import SectionHeader from '@/components/ui/SectionHeader.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import LoadingCenter from '@/components/ui/LoadingCenter.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import AlertBanner from '@/components/ui/AlertBanner.vue'
import UsageBar from '@/components/ui/UsageBar.vue'
import SecretInput from '@/components/ui/SecretInput.vue'
import Badge from '@/components/ui/Badge.vue'

defineOptions({ name: 'AdminServerLlmPane' })

const { t } = useI18n({ useScope: 'global' })
const { get, post, loading } = useApiFetch()
const { toast } = useToast()
const { confirm } = useConfirm()
const { formatDateTime: fmtTime } = useFormatDate()

const serverId = inject<Ref<number | null>>('adminServerId')!
const refreshTabState = inject<() => Promise<void>>('refreshAdminServerLlm', async () => {})

interface AdminLlmUsage {
  provisioned: boolean
  status: string | null
  tokenId: number | null
  userId: number | null
  apiKey: string | null
  apiBaseUrl: string
  quotaGrant: number
  quotaUsed: number
  quotaAvailable: number
  nextResetAt: string | null
  newapiPlanId: number | null
  newapiSubscriptionId: number | null
  lastSyncedAt: string | null
  createdAt: string | null
  usageQueryFailed: boolean
}

const data = ref<AdminLlmUsage | null>(null)
const loadFailed = ref(false)

const usedPercent = computed(() => {
  const d = data.value
  if (!d || d.quotaGrant <= 0) return 0
  return Math.round((d.quotaUsed / d.quotaGrant) * 100)
})

function credits(v: number): string {
  return `$${(v / 500000).toFixed(2)}`
}

async function load() {
  if (!serverId.value) return
  const res = await get<AdminLlmUsage>(`/api/admin/servers/${serverId.value}/llm`)
  if (res) {
    data.value = res
    loadFailed.value = false
  } else {
    loadFailed.value = true
  }
}

onMounted(() => {
  load()
})

async function toggleStatus() {
  if (!serverId.value || !data.value) return
  const enabling = data.value.status !== 'active'
  const res = await post<AdminLlmUsage>(`/api/admin/servers/${serverId.value}/llm/status`, {
    enabled: enabling,
  })
  if (res) {
    data.value = res
    toast(enabling ? t('adminServer.llm.toast.enabled') : t('adminServer.llm.toast.disabled'), 'success')
  }
}

async function resetUsage() {
  if (!serverId.value) return
  const ok = await confirm({
    title: t('adminServer.llm.resetUsage.title'),
    message: t('adminServer.llm.resetUsage.message'),
    confirmText: t('adminServer.llm.resetUsage.confirm'),
  })
  if (!ok) return
  const res = await post<AdminLlmUsage>(`/api/admin/servers/${serverId.value}/llm/reset-usage`, {})
  if (res) {
    data.value = res
    toast(t('adminServer.llm.toast.usageReset'), 'success')
  }
}

async function revokeKey() {
  if (!serverId.value) return
  const ok = await confirm({
    title: t('adminServer.llm.revoke.title'),
    message: t('adminServer.llm.revoke.message'),
    variant: 'danger',
    confirmText: t('adminServer.llm.revoke.confirm'),
  })
  if (!ok) return
  const res = await post<{ message: string }>(`/api/admin/servers/${serverId.value}/llm/revoke`, {})
  if (res) {
    toast(t('adminServer.llm.toast.revoked'), 'success')
    await load()
    await refreshTabState()
  }
}

async function provision() {
  if (!serverId.value) return
  const ok = await confirm({
    title: t('adminServer.llm.provision.confirmTitle'),
    message: t('adminServer.llm.provision.confirmMessage'),
    confirmText: t('adminServer.llm.provision.confirm'),
  })
  if (!ok) return
  const res = await post<AdminLlmUsage>(`/api/admin/servers/${serverId.value}/llm/provision`, {})
  if (res) {
    data.value = res
    toast(t('adminServer.llm.provision.toast'), 'success')
    await refreshTabState()
  } else {
    toast(t('adminServer.llm.provision.failedToast'), 'error')
    await load()
  }
}

const statusColor = computed(() => {
  switch (data.value?.status) {
    case 'active': return 'var(--ac)'
    case 'exhausted': return '#f59e0b'
    default: return undefined  // disabled / revoked -> muted
  }
})
</script>

<template>
  <div class="llm-pane">
    <LoadingCenter v-if="loading && !data" />

    <BaseCard v-else-if="loadFailed" variant="bg2">
      <EmptyState icon="error" :title="t('adminServer.llm.loadFailed')" />
    </BaseCard>

    <BaseCard v-else-if="data && !data.provisioned" variant="bg2" class="llm-card">
      <SectionHeader icon="smart_toy" flush>{{ t('adminServer.llm.provision.title') }}</SectionHeader>
      <AlertBanner tone="warning">
        {{ t('adminServer.llm.provision.hint') }}
      </AlertBanner>
      <div class="provision-actions">
        <BaseButton @click="provision" :disabled="loading">
          {{ t('adminServer.llm.provision.btn') }}
        </BaseButton>
      </div>
    </BaseCard>

    <template v-else-if="data">
      <!-- ─── Status & usage ─── -->
      <BaseCard variant="bg2" class="llm-card">
        <SectionHeader icon="smart_toy" flush>{{ t('adminServer.llm.statusSection') }}</SectionHeader>

        <div class="status-row">
          <Badge :color="statusColor">{{ t(`adminServer.llm.statuses.${data.status}`) }}</Badge>
          <span class="status-row__meta">Token #{{ data.tokenId }} · User #{{ data.userId }}</span>
        </div>

        <AlertBanner v-if="data.usageQueryFailed" tone="warning" class="usage-warn">
          {{ t('adminServer.llm.usageQueryFailed') }}
        </AlertBanner>

        <div class="usage-block">
          <div class="usage-block__top">
            <span class="usage-block__label">{{ t('adminServer.llm.used') }}</span>
            <span class="usage-block__val">{{ usedPercent }}%</span>
          </div>
          <UsageBar :percent="usedPercent" :height="8" />
          <div class="usage-block__nums">
            <span>{{ t('adminServer.llm.usedAmount') }}: {{ credits(data.quotaUsed) }}</span>
            <span>{{ t('adminServer.llm.available') }}: {{ credits(data.quotaAvailable) }}</span>
            <span>{{ t('adminServer.llm.grant') }}: {{ credits(data.quotaGrant) }}</span>
          </div>
        </div>

        <div class="meta-grid">
          <div><span class="meta-grid__k">{{ t('adminServer.llm.nextReset') }}</span><span>{{ fmtTime(data.nextResetAt) }}</span></div>
          <div><span class="meta-grid__k">{{ t('adminServer.llm.created') }}</span><span>{{ fmtTime(data.createdAt) }}</span></div>
        </div>
      </BaseCard>

      <!-- ─── API config ─── -->
      <BaseCard variant="bg2" class="llm-card">
        <SectionHeader icon="key" flush>{{ t('adminServer.llm.configSection') }}</SectionHeader>
        <FormField :label="t('adminServer.llm.apiBaseUrl')" layout="horizontal">
          <SecretInput :modelValue="data.apiBaseUrl" :revealed="true" readonly copyable :toggleable="false" />
        </FormField>
        <FormField :label="t('adminServer.llm.apiKey')" layout="horizontal">
          <SecretInput :modelValue="data.apiKey || ''" readonly copyable :toggleable="true" :masked-length="36" />
        </FormField>
      </BaseCard>

      <!-- ─── Actions ─── -->
      <BaseCard variant="bg2" class="llm-card">
        <SectionHeader icon="build" flush>{{ t('adminServer.llm.actionsSection') }}</SectionHeader>

        <div class="op-row">
          <div class="op-row__info">
            <p class="op-row__title">{{ t('adminServer.llm.toggle.title') }}</p>
            <p class="op-row__desc">{{ t('adminServer.llm.toggle.desc') }}</p>
          </div>
          <BaseButton size="sm" @click="toggleStatus">
            {{ data.status === 'active' ? t('adminServer.llm.toggle.disable') : t('adminServer.llm.toggle.enable') }}
          </BaseButton>
        </div>

        <div class="op-row">
          <div class="op-row__info">
            <p class="op-row__title">{{ t('adminServer.llm.resetUsage.rowTitle') }}</p>
            <p class="op-row__desc">{{ t('adminServer.llm.resetUsage.rowDesc') }}</p>
          </div>
          <BaseButton size="sm" @click="resetUsage">{{ t('adminServer.llm.resetUsage.btn') }}</BaseButton>
        </div>

        <div class="op-row op-row--danger">
          <div class="op-row__info">
            <p class="op-row__title">{{ t('adminServer.llm.revoke.rowTitle') }}</p>
            <p class="op-row__desc">{{ t('adminServer.llm.revoke.rowDesc') }}</p>
          </div>
          <BaseButton size="sm" variant="danger" @click="revokeKey">{{ t('adminServer.llm.revoke.btn') }}</BaseButton>
        </div>
      </BaseCard>
    </template>
  </div>
</template>

<style scoped>
.llm-pane {
  max-width: 760px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}

.llm-card {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

.status-row {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
}

.status-row__meta {
  font-size: var(--text-sm);
  color: var(--t3);
  font-variant-numeric: tabular-nums;
}

.usage-warn {
  margin: 0;
}

.usage-block {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.usage-block__top {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}

.usage-block__label {
  font-size: var(--text-sm);
  color: var(--t3);
}

.usage-block__val {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--t1);
  font-variant-numeric: tabular-nums;
}

.usage-block__nums {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-3);
  font-size: .8rem;
  color: var(--t2);
  font-variant-numeric: tabular-nums;
}

.meta-grid {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
  padding-top: var(--sp-2);
  border-top: 1px solid color-mix(in srgb, var(--bd) 50%, transparent);
  font-size: .82rem;
  color: var(--t2);
}

.meta-grid > div {
  display: flex;
  gap: var(--sp-2);
}

.meta-grid__k {
  min-width: 84px;
  color: var(--t3);
}

.op-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  padding: var(--sp-2) 0;
  border-top: 1px solid color-mix(in srgb, var(--bd) 40%, transparent);
}

.op-row:first-of-type {
  border-top: none;
}

.op-row__info {
  min-width: 0;
}

.op-row__title {
  margin: 0 0 2px;
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--t1);
}

.op-row__desc {
  margin: 0;
  font-size: .8rem;
  color: var(--t3);
  line-height: 1.4;
}

.op-row--danger .op-row__title {
  color: var(--red);
}

.provision-actions {
  display: flex;
  justify-content: center;
  padding: var(--sp-2) 0;
}
</style>

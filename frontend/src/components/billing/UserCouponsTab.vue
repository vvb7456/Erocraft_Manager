<script setup lang="ts">
/**
 * UserCouponsTab — coupon wallet shown inside the orders page.
 *
 * Status filter sits in a SectionToolbar. Renders a DataTable
 * (desktop) / CardTap list (mobile). No actions other than copy code —
 * coupons are applied automatically during checkout via the CreateOrder
 * modal's coupon picker (data source: GET /api/user/coupons with order
 * context).
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import SectionToolbar from '@/components/ui/SectionToolbar.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import DataTable from '@/components/ui/DataTable.vue'
import Badge from '@/components/ui/Badge.vue'
import CardTap from '@/components/ui/CardTap.vue'
import CardKV from '@/components/ui/CardKV.vue'
import MsIcon from '@/components/ui/MsIcon.vue'

defineOptions({ name: 'UserCouponsTab' })

interface Coupon {
  id: number
  code: string
  template_id: number
  template_name: string | null
  status: string
  source: string
  discount_fen: number
  min_order_fen: number
  applicable_plan_ids: number[] | null
  applicable_order_kinds: string[] | null
  issued_at: string
  expires_at: string
  used_at: string | null
  used_order_id: number | null
  actual_discount_fen: number | null
  reserved_order_id: number | null
}

interface CouponListResponse {
  items: Coupon[]
  total: number
}

const { t, te } = useI18n({ useScope: 'global' })
const { get } = useApiFetch()
const { toast } = useToast()

const activeBucket = ref<'unused' | 'used' | 'expired'>('unused')
const loading = ref(true)
const coupons = ref<Coupon[]>([])

const page = ref(1)
const perPage = ref(20)

const buckets = computed(() => {
  const now = Date.now()
  const isPastExpiry = (iso: string) => {
    const tt = new Date(iso).getTime()
    return !isNaN(tt) && tt <= now
  }
  return {
    unused: coupons.value.filter(
      (c) => (c.status === 'unused' || c.status === 'reserved') && !isPastExpiry(c.expires_at),
    ),
    used: coupons.value.filter((c) => c.status === 'used'),
    expired: coupons.value.filter(
      (c) => c.status === 'revoked' || (c.status === 'unused' && isPastExpiry(c.expires_at)),
    ),
  }
})

const statusOptions = computed(() => [
  { value: 'unused',  label: `${t('billing.coupons.tabs.unused')} (${buckets.value.unused.length})` },
  { value: 'used',    label: `${t('billing.coupons.tabs.used')} (${buckets.value.used.length})` },
  { value: 'expired', label: `${t('billing.coupons.tabs.expired')} (${buckets.value.expired.length})` },
])

const filtered = computed(() => buckets.value[activeBucket.value] ?? [])
const totalCount = computed(() => coupons.value.length)
const totalPages = computed(() => Math.max(1, Math.ceil(filtered.value.length / perPage.value)))
const visible = computed(() => {
  const start = (page.value - 1) * perPage.value
  return filtered.value.slice(start, start + perPage.value)
})

watch(activeBucket, () => { page.value = 1 })
watch(totalPages, (n) => { if (page.value > n) page.value = n })

async function load() {
  loading.value = true
  // No status filter — backend returns all statuses; we bucket locally.
  const data = await get<CouponListResponse>('/api/user/coupons', { silent: true })
  if (data?.items) coupons.value = data.items
  loading.value = false
}

onMounted(load)

function fenToYuan(fen: number): string {
  return (fen / 100).toFixed(2)
}

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '—'
  return d.toLocaleDateString(undefined, { year: 'numeric', month: '2-digit', day: '2-digit' })
}

function daysLeft(iso: string): number {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return 0
  return Math.max(0, Math.ceil((d.getTime() - Date.now()) / 86_400_000))
}

function isExpiringSoon(iso: string): boolean {
  return daysLeft(iso) <= 7
}

function constraintLabel(c: Coupon): string {
  if (c.min_order_fen > 0) {
    return t('billing.coupons.minOrder', { amount: fenToYuan(c.min_order_fen) })
  }
  return t('billing.coupons.noThreshold')
}

function statusColor(s: string): string {
  switch (s) {
    case 'unused':   return 'var(--green)'
    case 'reserved': return 'var(--amber)'
    case 'used':     return 'var(--blue)'
    case 'expired':  return 'var(--t3)'
    case 'revoked':  return 'var(--red)'
    default:         return 'var(--t3)'
  }
}

function statusLabel(s: string): string {
  const key = `billing.admin.coupons.status.${s}`
  return te(key) ? t(key) : s
}

async function copyCode(code: string) {
  try {
    await navigator.clipboard.writeText(code)
    toast(t('common.clipboard.copied'), 'success')
  } catch {
    toast(t('common.clipboard.failed'), 'error')
  }
}
</script>

<template>
  <SectionToolbar>
      <template #start>
        <span class="toolbar-status tb-status">
          {{ t('billing.coupons.totalCount', { n: totalCount }) }}
        </span>
      </template>
      <template #end>
        <div class="tb-select-group">
          <BaseSelect
            v-model="activeBucket"
            :options="statusOptions"
            :prefix="t('billing.coupons.statusFilterLabel') + ': '"
            size="sm"
            fit
          />
        </div>
      </template>
    </SectionToolbar>

    <DataTable
      :items="visible"
      :page="page"
      :total-pages="totalPages"
      :per-page="perPage"
      :loading="loading"
      empty-icon="confirmation_number"
      :empty-text="t(`billing.coupons.empty.${activeBucket}`)"
      row-key="id"
      @update:page="page = $event"
      @update:per-page="perPage = $event; page = 1"
    >
      <template #header>
        <th class="col-code">{{ t('billing.coupons.code') }}</th>
        <th class="col-name">{{ t('billing.admin.coupons.col.template') }}</th>
        <th class="col-discount">{{ t('billing.admin.coupons.col.discount') }}</th>
        <th class="col-rule">{{ t('billing.coupons.rule') }}</th>
        <th class="col-status">{{ t('billing.admin.coupons.col.status') }}</th>
        <th class="col-expiry">{{ t('billing.coupons.expiry') }}</th>
        <th class="col-actions">{{ t('billing.admin.coupons.col.actions') }}</th>
      </template>
      <template #row="{ item: c }">
        <td class="col-code"><code>{{ c.code }}</code></td>
        <td class="col-name">{{ c.template_name || `#${c.template_id}` }}</td>
        <td class="col-discount mono">−¥{{ fenToYuan(c.discount_fen) }}</td>
        <td class="col-rule">{{ constraintLabel(c) }}</td>
        <td class="col-status">
          <Badge :color="statusColor(c.status)">{{ statusLabel(c.status) }}</Badge>
        </td>
        <td class="col-expiry">
          <span v-if="activeBucket === 'unused'" :class="{ 'expiry-warning': isExpiringSoon(c.expires_at) }">
            <MsIcon v-if="isExpiringSoon(c.expires_at)" name="schedule" size="xs" />
            {{ t('billing.coupons.daysLeft', { days: daysLeft(c.expires_at) }) }}
            · {{ formatDate(c.expires_at) }}
          </span>
          <span v-else>{{ formatDate(c.expires_at) }}</span>
        </td>
        <td class="col-actions">
          <BaseButton size="sm" :disabled="activeBucket !== 'unused'" @click="copyCode(c.code)">
            <MsIcon name="content_copy" size="xs" />
            {{ t('billing.coupons.copyCode') }}
          </BaseButton>
        </td>
      </template>
      <template #card="{ item: c }">
        <CardTap @tap="copyCode(c.code)">
          <div class="card-row--main">
            <span class="card-name"><code>{{ c.code }}</code></span>
            <Badge :color="statusColor(c.status)" size="sm">{{ statusLabel(c.status) }}</Badge>
          </div>
          <div class="card-detail">
            <CardKV :label="t('billing.admin.coupons.col.template')">{{ c.template_name || `#${c.template_id}` }}</CardKV>
            <CardKV :label="t('billing.admin.coupons.col.discount')"><span class="mono">−¥{{ fenToYuan(c.discount_fen) }}</span></CardKV>
            <CardKV :label="t('billing.coupons.rule')">{{ constraintLabel(c) }}</CardKV>
            <CardKV :label="t('billing.coupons.expiry')">{{ formatDate(c.expires_at) }}</CardKV>
          </div>
        </CardTap>
      </template>
    </DataTable>
</template>

<style scoped>
:deep(.col-code)     { width: 14%; }
:deep(.col-name)     { width: 22%; }
:deep(.col-discount) { width: 10%; white-space: nowrap; }
:deep(.col-rule)     { width: 16%; color: var(--t2); font-size: var(--text-sm); }
:deep(.col-status)   { width: 9%;  white-space: nowrap; }
:deep(.col-expiry)   { width: 16%; color: var(--t2); font-size: var(--text-sm); }
:deep(.col-actions)  { width: 12%; }

.mono { font-family: var(--font-mono, 'IBM Plex Mono', monospace); }
code {
  font-family: var(--font-mono, 'IBM Plex Mono', monospace);
  font-size: var(--text-xs);
  background: var(--bg-in);
  padding: 2px 6px;
  border-radius: var(--r-xs);
  color: var(--t1);
}
.expiry-warning { color: var(--amber); display: inline-flex; align-items: center; gap: 4px; }
.card-name { font-weight: 600; font-size: .92rem; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>

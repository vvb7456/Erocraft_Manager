<script setup lang="ts">
/**
 * AdminCouponsTab — list issued coupons, manual grant, revoke.
 *
 * Filters: user_id (number), status (unused/reserved/used/revoked/expired),
 * template_id. Manual grant uses a tiny inline modal with FormField + BaseInput.
 */
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useConfirm } from '@/composables/useConfirm'
import { useToast } from '@/composables/useToast'
import { useFormatDate } from '@/composables/useFormatDate'
import SectionToolbar from '@/components/ui/SectionToolbar.vue'
import DataTable from '@/components/ui/DataTable.vue'
import FilterInput from '@/components/ui/FilterInput.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import Badge from '@/components/ui/Badge.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import CardTap from '@/components/ui/CardTap.vue'
import CardKV from '@/components/ui/CardKV.vue'
import ActionSheet from '@/components/ui/ActionSheet.vue'
import MobileFilterSheet from '@/components/ui/MobileFilterSheet.vue'
import BaseModal from '@/components/ui/BaseModal.vue'
import FormField from '@/components/form/FormField.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import AlertBanner from '@/components/ui/AlertBanner.vue'
import type { CouponTemplate } from '@/components/billing/CouponTemplateEditorModal.vue'

defineOptions({ name: 'AdminCouponsTab' })

const props = defineProps<{
  /** If non-null on first mount, open the grant modal automatically (?action=grant). */
  initialAction?: 'grant' | null
}>()

const { t, te } = useI18n({ useScope: 'global' })
const { get, raw } = useApiFetch()
const { confirm } = useConfirm()
const { toast } = useToast()
const { formatDateTime: fmtDate } = useFormatDate()

interface Coupon {
  id: number
  code: string
  template_id: number
  template_name: string | null
  user_id: number
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
  reserved_at: string | null
  revoked_at: string | null
  revoke_reason: string | null
}

const items = ref<Coupon[]>([])
const total = ref(0)
const tableLoading = ref(false)

const statusFilter = ref<string>('all')
const templateFilter = ref<string>('all')
const searchQuery = ref<string>('')

const limit = ref(50)
const offset = ref(0)
const page = computed({
  get: () => Math.floor(offset.value / limit.value) + 1,
  set: (p: number) => { offset.value = Math.max(0, (p - 1) * limit.value) },
})
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / limit.value)))

const statusOptions = computed(() => [
  { value: 'all',      label: t('billing.admin.coupons.filterAllStatus') },
  { value: 'unused',   label: t('billing.admin.coupons.status.unused') },
  { value: 'reserved', label: t('billing.admin.coupons.status.reserved') },
  { value: 'used',     label: t('billing.admin.coupons.status.used') },
  { value: 'expired',  label: t('billing.admin.coupons.status.expired') },
  { value: 'revoked',  label: t('billing.admin.coupons.status.revoked') },
])

const templates = ref<CouponTemplate[]>([])
const templateOptions = computed(() => [
  { value: 'all', label: t('billing.admin.coupons.filterAllTemplate') },
  ...templates.value.map((tpl) => ({ value: String(tpl.id), label: `${tpl.code} · ${tpl.name}` })),
])

// ── Mobile filter sheet ──
const mobileFilterOpen = ref(false)
const filterGroups = computed(() => [
  {
    key: 'status',
    label: t('billing.admin.coupons.statusFilterLabel'),
    modelValue: statusFilter.value,
    options: statusOptions.value,
  },
  {
    key: 'template',
    label: t('billing.admin.coupons.templateFilterLabel'),
    modelValue: templateFilter.value,
    options: templateOptions.value,
  },
])
function onMobileFilter(groupKey: string, value: string | number | boolean) {
  if (groupKey === 'status') statusFilter.value = String(value)
  else if (groupKey === 'template') templateFilter.value = String(value)
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
function sourceLabel(s: string): string {
  const key = `billing.admin.coupons.source.${s}`
  return te(key) ? t(key) : s
}

function fenToYuan(fen: number): string { return (fen / 100).toFixed(2) }

async function loadList() {
  tableLoading.value = true
  const qs = new URLSearchParams()
  if (searchQuery.value.trim()) qs.set('q', searchQuery.value.trim())
  if (statusFilter.value !== 'all') qs.set('status', statusFilter.value)
  if (templateFilter.value !== 'all') qs.set('template_id', templateFilter.value)
  qs.set('limit', String(limit.value))
  qs.set('offset', String(offset.value))
  const data = await get<{ items: Coupon[]; total: number }>(
    `/api/admin/billing/coupons?${qs.toString()}`,
    { silent: true },
  )
  if (data) { items.value = data.items; total.value = data.total }
  tableLoading.value = false
}

async function loadTemplates() {
  const data = await get<CouponTemplate[]>(
    '/api/admin/billing/coupon-templates?include_inactive=true',
    { silent: true },
  )
  if (data) templates.value = data
}

onMounted(async () => {
  await loadTemplates()
  await loadList()
  if (props.initialAction === 'grant') grantOpen.value = true
})

watch([searchQuery, statusFilter, templateFilter], () => {
  offset.value = 0
  void loadList()
})

watch(page, () => { void loadList() })

// ── Revoke ──
async function doRevoke(c: Coupon) {
  const ok = await confirm({
    title: t('billing.admin.coupons.revoke'),
    message: t('billing.admin.coupons.revokeConfirm', { code: c.code }),
    variant: 'danger',
    confirmText: t('billing.admin.coupons.revoke'),
  })
  if (!ok) return
  const res = await raw(`/api/admin/billing/coupons/${c.id}/revoke`, {
    method: 'POST',
    body: JSON.stringify({ reason: 'admin revoked' }),
    headers: { 'Content-Type': 'application/json' },
    silent: true,
  })
  if (res && res.ok) {
    const updated = await res.json() as Coupon
    const idx = items.value.findIndex((x) => x.id === updated.id)
    if (idx >= 0) items.value.splice(idx, 1, updated)
    toast(t('billing.admin.coupons.revokeOk'), 'success')
  } else if (res) {
    let msg = `HTTP ${res.status}`
    try { const body = await res.json(); msg = body.detail || body.message || msg } catch { /* ignore */ }
    toast(msg, 'error')
  }
}

// ── Mobile actions ──
const mobileTarget = ref<Coupon | null>(null)
const mobileOpen = ref(false)
function openMobile(c: Coupon) { mobileTarget.value = c; mobileOpen.value = true }

// ── Manual grant modal ──
const grantOpen = ref(false)
const grantUserId = ref<number | ''>('')
const grantTemplateId = ref<number | ''>('')
const grantSaving = ref(false)
const grantError = ref<string | null>(null)

interface AdminUserOption { id: number; username: string; email?: string | null }
const grantUsers = ref<AdminUserOption[]>([])
const grantUsersLoading = ref(false)

const grantUserOptions = computed(() =>
  grantUsers.value.map((u) => ({
    value: u.id,
    label: u.email ? `${u.username} · ${u.email} · #${u.id}` : `${u.username} · #${u.id}`,
  })),
)

async function loadGrantUsers() {
  if (grantUsers.value.length) return
  grantUsersLoading.value = true
  try {
    const data = await get<{ users: AdminUserOption[] }>('/api/admin/users?page=1&perPage=200', { silent: true })
    if (data?.users) grantUsers.value = data.users
  } finally {
    grantUsersLoading.value = false
  }
}

const grantTemplateOptions = computed(() =>
  templates.value
    .filter((t) => t.is_active)
    .map((tpl) => ({ value: tpl.id, label: `${tpl.code} · ${tpl.name}` })),
)

const grantCanSave = computed(() => {
  if (grantSaving.value) return false
  if (typeof grantUserId.value !== 'number' || grantUserId.value <= 0) return false
  if (typeof grantTemplateId.value !== 'number') return false
  return true
})

function openGrant() {
  grantUserId.value = ''
  grantTemplateId.value = ''
  grantError.value = null
  grantOpen.value = true
  void loadGrantUsers()
}

async function doGrant() {
  if (!grantCanSave.value) return
  grantSaving.value = true
  grantError.value = null
  try {
    const res = await raw('/api/admin/billing/coupons/grant', {
      method: 'POST',
      body: JSON.stringify({
        user_id: Number(grantUserId.value),
        template_id: Number(grantTemplateId.value),
      }),
      headers: { 'Content-Type': 'application/json' },
      silent: true,
    })
    if (res && res.ok) {
      toast(t('billing.admin.coupons.grantOk'), 'success')
      grantOpen.value = false
      await loadList()
    } else if (res) {
      let msg = `HTTP ${res.status}`
      try { const body = await res.json(); msg = body.detail || body.message || msg } catch { /* ignore */ }
      grantError.value = String(msg)
    } else {
      grantError.value = 'Network error'
    }
  } finally {
    grantSaving.value = false
  }
}
</script>

<template>
  <SectionToolbar>
    <template #start>
      <div class="tb-search-row">
        <FilterInput
          v-model="searchQuery"
          :placeholder="t('billing.admin.coupons.searchPlaceholder')"
          class="tb-search"
        />
        <button
          class="tb-filter-btn"
          :title="t('common.filterSort.title')"
          @click="mobileFilterOpen = true"
        >
          <MsIcon name="tune" size="sm" />
          </button>
      </div>
      <span class="toolbar-status tb-status">
        {{ t('billing.admin.coupons.totalCount', { n: total }) }}
      </span>
    </template>
    <template #end>
      <div class="tb-select-group tb-desktop-only">
        <BaseSelect
          v-model="statusFilter"
          :options="statusOptions"
          :prefix="t('billing.admin.coupons.statusFilterLabel') + ': '"
          size="sm"
          fit
        />
        <BaseSelect
          v-model="templateFilter"
          :options="templateOptions"
          :prefix="t('billing.admin.coupons.templateFilterLabel') + ': '"
          size="sm"
          fit
        />
      </div>
      <div class="tb-btn-group">
        <BaseButton size="sm" variant="primary" @click="openGrant">
          <MsIcon name="card_giftcard" size="xs" /> {{ t('billing.admin.coupons.grant') }}
        </BaseButton>
      </div>
    </template>
  </SectionToolbar>

  <MobileFilterSheet
    v-model:open="mobileFilterOpen"
    :sort-columns="[]"
    :sort-by="''"
    :sort-order="'asc'"
    :filters="filterGroups"
    @update:filter="onMobileFilter"
  />

  <DataTable
    :items="items"
    :page="page"
    :total-pages="totalPages"
    :per-page="limit"
    :loading="tableLoading"
    empty-icon="confirmation_number"
    :empty-text="t('billing.admin.coupons.empty')"
    row-key="id"
    @update:page="page = $event"
    @update:per-page="limit = $event; offset = 0"
  >
    <template #header>
      <th class="col-id">#</th>
      <th class="col-code">{{ t('billing.admin.coupons.col.code') }}</th>
      <th class="col-tpl">{{ t('billing.admin.coupons.col.template') }}</th>
      <th class="col-user">{{ t('billing.admin.coupons.col.user') }}</th>
      <th class="col-status">{{ t('billing.admin.coupons.col.status') }}</th>
      <th class="col-discount">{{ t('billing.admin.coupons.col.discount') }}</th>
      <th class="col-issued">{{ t('billing.admin.coupons.col.issuedAt') }}</th>
      <th class="col-expires">{{ t('billing.admin.coupons.col.expiresAt') }}</th>
      <th class="col-actions">{{ t('billing.admin.coupons.col.actions') }}</th>
    </template>
    <template #row="{ item: c }">
      <td class="col-id">{{ c.id }}</td>
      <td class="col-code"><code>{{ c.code }}</code></td>
      <td class="col-tpl">
        <div>{{ c.template_name || `#${c.template_id}` }}</div>
        <div class="name-sub">{{ sourceLabel(c.source) }}</div>
      </td>
      <td class="col-user mono">#{{ c.user_id }}</td>
      <td class="col-status">
        <Badge :color="statusColor(c.status)">
          {{ statusLabel(c.status) }}
        </Badge>
      </td>
      <td class="col-discount mono">−¥{{ fenToYuan(c.discount_fen) }}</td>
      <td class="col-issued">{{ fmtDate(c.issued_at) }}</td>
      <td class="col-expires">{{ fmtDate(c.expires_at) }}</td>
      <td class="col-actions">
        <BaseButton
          size="sm"
          variant="danger"
          :disabled="c.status === 'used' || c.status === 'revoked' || c.status === 'expired'"
          @click="doRevoke(c)"
        >
          <MsIcon name="block" size="xs" /> {{ t('billing.admin.coupons.revoke') }}
        </BaseButton>
      </td>
    </template>
    <template #card="{ item: c }">
      <CardTap @tap="openMobile(c)">
        <div class="card-row--main">
          <span class="card-name"><code>{{ c.code }}</code> <span class="card-id-inline">#{{ c.id }}</span></span>
          <Badge :color="statusColor(c.status)" size="sm">
            {{ statusLabel(c.status) }}
          </Badge>
        </div>
        <div class="card-detail">
          <CardKV :label="t('billing.admin.coupons.col.template')">{{ c.template_name || `#${c.template_id}` }}</CardKV>
          <CardKV :label="t('billing.admin.coupons.col.user')"><span class="mono">#{{ c.user_id }}</span></CardKV>
          <CardKV :label="t('billing.admin.coupons.col.discount')"><span class="mono">−¥{{ fenToYuan(c.discount_fen) }}</span></CardKV>
          <CardKV :label="t('billing.admin.coupons.col.expiresAt')">{{ fmtDate(c.expires_at) }}</CardKV>
        </div>
      </CardTap>
    </template>
  </DataTable>

  <ActionSheet v-model="mobileOpen" :title="mobileTarget?.code">
    <template v-if="mobileTarget">
      <button
        class="action-sheet--danger"
        :disabled="mobileTarget.status === 'used' || mobileTarget.status === 'revoked' || mobileTarget.status === 'expired'"
        @click="mobileOpen = false; doRevoke(mobileTarget!)"
      >
        <MsIcon name="block" size="sm" /> {{ t('billing.admin.coupons.revoke') }}
      </button>
    </template>
  </ActionSheet>

  <BaseModal v-model="grantOpen" :title="t('billing.admin.coupons.grantTitle')" icon="card_giftcard" size="sm">
    <div class="grant-form">
      <AlertBanner v-if="grantError" tone="danger">{{ grantError }}</AlertBanner>
      <FormField :label="t('billing.admin.coupons.grantUserId')">
        <BaseSelect v-model="grantUserId"
                    :options="grantUserOptions"
                    searchable
                    teleport
                    :placeholder="grantUsersLoading ? t('common.loading') : t('billing.admin.coupons.grantUserPlaceholder')" />
      </FormField>
      <FormField :label="t('billing.admin.coupons.grantTemplate')">
        <BaseSelect v-model="grantTemplateId" :options="grantTemplateOptions"
                    searchable
                    teleport
                    :placeholder="t('billing.admin.coupons.grantTemplatePlaceholder')" />
      </FormField>
    </div>
    <template #footer>
      <BaseButton @click="grantOpen = false">{{ t('common.btn.cancel') }}</BaseButton>
      <BaseButton variant="primary" :loading="grantSaving" :disabled="!grantCanSave" @click="doGrant">
        {{ t('billing.admin.coupons.grant') }}
      </BaseButton>
    </template>
  </BaseModal>
</template>

<style scoped>
:deep(.col-id)       { width: 4%;  color: var(--t3); }
:deep(.col-code)     { width: 11%; }
:deep(.col-tpl)      { width: 16%; }
:deep(.col-user)     { width: 7%;  white-space: nowrap; }
:deep(.col-status)   { width: 9%;  white-space: nowrap; }
:deep(.col-discount) { width: 10%; white-space: nowrap; }
:deep(.col-issued)   { width: 13%; color: var(--t2); font-size: var(--text-sm); }
:deep(.col-expires)  { width: 13%; color: var(--t2); font-size: var(--text-sm); }
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
.name-sub { color: var(--t3); font-size: var(--text-xs); margin-top: 2px; }
.card-name { font-weight: 600; font-size: .92rem; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.card-id-inline { font-size: .78rem; font-weight: 400; color: var(--t3); margin-left: var(--sp-1); }
.grant-form { display: flex; flex-direction: column; gap: var(--sp-3); }
</style>

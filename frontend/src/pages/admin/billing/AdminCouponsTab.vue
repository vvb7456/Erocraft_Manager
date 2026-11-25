<script setup lang="ts">
/**
 * AdminCouponsTab — list issued coupons, manual grant, revoke.
 *
 * Filters: user_id (number), status (unused/reserved/used/revoked/expired),
 * template_id. Manual grant uses a tiny inline modal with FormField + BaseInput.
 */
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { apiErrorMessage } from '@/composables/apiClient'
import { useConfirm } from '@/composables/useConfirm'
import { useToast } from '@/composables/useToast'
import { useFormatDate } from '@/composables/useFormatDate'
import SectionToolbar from '@/components/ui/SectionToolbar.vue'
import PageHeaderActions from '@/components/layout/PageHeaderActions.vue'
import DataTable from '@/components/ui/DataTable.vue'
import SortTh from '@/components/ui/SortTh.vue'
import { useTableSort } from '@/composables/useTableSort'
import { useServerPagination } from '@/composables/useTablePagination'
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
const { get, raw, handleError } = useApiFetch()
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

const statusFilter = ref<string>('all')
const templateFilter = ref<string>('all')
const searchQuery = ref<string>('')

const { sortBy, sortOrder, toggleSort } = useTableSort({
  defaultBy: 'issued_at',
  defaultOrder: 'desc',
  descColumns: ['user_id', 'discount_fen', 'issued_at', 'expires_at'],
})

const {
  page,
  perPage: limit,
  total,
  totalPages,
  loading: tableLoading,
  reload: loadList,
  setPerPage,
} = useServerPagination(
  async ({ perPage, offset, isCurrent }) => {
    const qs = new URLSearchParams()
    if (searchQuery.value.trim()) qs.set('q', searchQuery.value.trim())
    if (statusFilter.value !== 'all') qs.set('status', statusFilter.value)
    if (templateFilter.value !== 'all') qs.set('template_id', templateFilter.value)
    if (sortBy.value) {
      qs.set('sort_by', sortBy.value)
      qs.set('sort_order', sortOrder.value)
    }
    qs.set('limit', String(perPage))
    qs.set('offset', String(offset))
    const data = await get<{ items: Coupon[]; total: number }>(
      `/api/admin/billing/coupons?${qs.toString()}`,
      { silent: true },
    )
    if (!data || !isCurrent()) return null
    items.value = data.items
    return { total: data.total }
  },
  {
    initialPerPage: 50,
    filters: [statusFilter, templateFilter, sortBy, sortOrder],
    search: searchQuery,
    onError: handleError,
  },
)

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
const sortColumns = computed(() => [
  { key: 'code', label: t('billing.admin.coupons.col.code') },
  { key: 'user_id', label: t('billing.admin.coupons.col.user') },
  { key: 'status', label: t('billing.admin.coupons.col.status') },
  { key: 'discount_fen', label: t('billing.admin.coupons.col.discount') },
  { key: 'issued_at', label: t('billing.admin.coupons.col.issuedAt') },
  { key: 'expires_at', label: t('billing.admin.coupons.col.expiresAt') },
])
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

async function loadTemplates() {
  const data = await get<CouponTemplate[]>(
    '/api/admin/billing/coupon-templates?include_inactive=true',
    { silent: true },
  )
  if (data) templates.value = data
}

onMounted(async () => {
  await loadTemplates().catch(handleError)
  await loadList()
  if (props.initialAction === 'grant') grantOpen.value = true
})

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
  })
  if (res && res.ok) {
    const updated = await res.json() as Coupon
    const idx = items.value.findIndex((x) => x.id === updated.id)
    if (idx >= 0) items.value.splice(idx, 1, updated)
    toast(t('billing.admin.coupons.revokeOk'), 'success')
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
  void loadGrantUsers().catch(handleError)
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
    }
  } catch (error) {
    grantError.value = apiErrorMessage(error)
  } finally {
    grantSaving.value = false
  }
}
</script>

<template>
  <PageHeaderActions>
    <BaseButton size="sm" variant="primary" @click="openGrant"><MsIcon name="card_giftcard" size="xs" />{{ t('billing.admin.coupons.grant') }}</BaseButton>
  </PageHeaderActions>
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
    </template>
  </SectionToolbar>

  <MobileFilterSheet
    v-model:open="mobileFilterOpen"
    :sort-columns="sortColumns"
    :sort-by="sortBy"
    :sort-order="sortOrder"
    :filters="filterGroups"
    @sort="toggleSort"
    @update:filter="onMobileFilter"
  />

  <div class="coupons-table-wrap">
  <DataTable
    :items="items"
    :page="page"
    :total-pages="totalPages"
    :per-page="limit"
    :per-page-label="t('billing.orders.perPage')"
    :loading="tableLoading"
    empty-icon="confirmation_number"
    :empty-text="t('billing.admin.coupons.empty')"
    row-key="id"
    @update:page="page = $event"
    @update:per-page="setPerPage"
  >
    <template #header>
      <SortTh class="col-code" col="code" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('billing.admin.coupons.col.code') }}</SortTh>
      <th class="col-tpl">{{ t('billing.admin.coupons.col.template') }}</th>
      <SortTh class="col-user" col="user_id" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('billing.admin.coupons.col.user') }}</SortTh>
      <SortTh class="col-discount" col="discount_fen" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('billing.admin.coupons.col.discount') }}</SortTh>
      <SortTh class="col-issued" col="issued_at" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('billing.admin.coupons.col.issuedAt') }}</SortTh>
      <SortTh class="col-expires" col="expires_at" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('billing.admin.coupons.col.expiresAt') }}</SortTh>
      <SortTh class="col-status" col="status" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('billing.admin.coupons.col.status') }}</SortTh>
      <th class="col-actions">{{ t('billing.admin.coupons.col.actions') }}</th>
    </template>
    <template #row="{ item: c }">
      <td class="col-code"><code>{{ c.code }}</code></td>
      <td class="col-tpl">
        <div>{{ c.template_name || `#${c.template_id}` }}</div>
        <div class="name-sub">{{ sourceLabel(c.source) }}</div>
      </td>
      <td class="col-user mono">#{{ c.user_id }}</td>
      <td class="col-discount mono">−¥{{ fenToYuan(c.discount_fen) }}</td>
      <td class="col-issued">{{ fmtDate(c.issued_at) }}</td>
      <td class="col-expires">{{ fmtDate(c.expires_at) }}</td>
      <td class="col-status">
        <Badge :color="statusColor(c.status)">
          {{ statusLabel(c.status) }}
        </Badge>
      </td>
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
  </div>

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
.coupons-table-wrap :deep(.col-user)     { white-space: nowrap; }
.coupons-table-wrap :deep(.col-discount) { white-space: nowrap; }
.coupons-table-wrap :deep(.col-issued)   { color: var(--t2); font-size: var(--text-sm); }
.coupons-table-wrap :deep(.col-expires)  { color: var(--t2); font-size: var(--text-sm); }
.coupons-table-wrap :deep(.col-status)   { white-space: nowrap; }

.mono { font-family: var(--font-mono); }
code {
  font-family: var(--font-mono);
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

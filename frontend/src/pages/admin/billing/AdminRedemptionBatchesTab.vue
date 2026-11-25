<script setup lang="ts">
/**
 * AdminRedemptionBatchesTab — list/create/export/void redemption batches and inspect plaintext codes.
 *
 * Follows AdminCouponTemplatesTab / AdminCouponsTab conventions:
 * PageHeaderActions + SectionToolbar + MobileFilterSheet + DataTable + ActionSheet + BaseModal.
 */
import { ref, computed, onMounted, watch } from 'vue'
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
import RedemptionBatchDetailModal, {
  type RedemptionBatchSummary,
} from '@/pages/admin/billing/RedemptionBatchDetailModal.vue'

defineOptions({ name: 'AdminRedemptionBatchesTab' })

interface PlanLite {
  id: number
  code: string
  display_name: string
  price_fen: number
  days: number
  plan_type?: string
  is_active: boolean
}

const { t } = useI18n({ useScope: 'global' })
const { get, raw, handleError } = useApiFetch()
const { confirm } = useConfirm()
const { toast } = useToast()
const { formatDateTime: fmtDate } = useFormatDate()

const items = ref<RedemptionBatchSummary[]>([])
const plans = ref<PlanLite[]>([])

const searchQuery = ref('')
const sourceFilter = ref('all')
const planFilter = ref('all')

const { sortBy, sortOrder, toggleSort } = useTableSort({
  defaultBy: 'created_at',
  defaultOrder: 'desc',
  descColumns: ['amount_fen', 'quantity', 'expires_at', 'created_at'],
})

const {
  page,
  perPage: limit,
  total,
  totalPages,
  loading: tableLoading,
  reload: loadBatches,
  setPerPage,
  resetStateWithoutFetch,
} = useServerPagination(
  async ({ perPage, offset, isCurrent }) => {
    const qs = new URLSearchParams({
      limit: String(perPage),
      offset: String(offset),
    })
    if (sourceFilter.value !== 'all') qs.set('source', sourceFilter.value)
    if (planFilter.value !== 'all') qs.set('plan_id', planFilter.value)
    if (searchQuery.value.trim()) qs.set('q', searchQuery.value.trim())
    if (sortBy.value) {
      qs.set('sort_by', sortBy.value)
      qs.set('sort_order', sortOrder.value)
    }
    const data = await get<{ items: RedemptionBatchSummary[]; total: number }>(
      `/api/admin/billing/redemption/batches?${qs.toString()}`,
      { silent: true },
    )
    if (!data || !isCurrent()) return null
    items.value = data.items
    return { total: data.total }
  },
  {
    initialPerPage: 20,
    filters: [sourceFilter, planFilter, sortBy, sortOrder],
    search: searchQuery,
    onError: handleError,
  },
)

const sourceOptions = computed(() => [
  { value: 'all', label: t('billing.admin.redemption.filterAllSource') },
  { value: 'manual', label: t('billing.admin.redemption.sourceManual') },
  { value: 'api', label: t('billing.admin.redemption.sourceApi') },
])

const standardPlans = computed(() =>
  plans.value.filter((p) => (p.plan_type ?? 'standard') === 'standard'),
)

const planFilterOptions = computed(() => [
  { value: 'all', label: t('billing.admin.redemption.filterAllPlan') },
  ...standardPlans.value.map((p) => ({
    value: String(p.id),
    label: `${p.display_name} (${p.code})`,
  })),
])

const channelOptions = computed(() => [
  { value: 'taobao', label: t('billing.channel.taobao') },
  { value: 'xianyu', label: t('billing.channel.xianyu') },
  { value: 'other', label: t('billing.channel.other') },
])

// ── Mobile filter sheet ──
const mobileFilterOpen = ref(false)
const sortColumns = computed(() => [
  { key: 'name', label: t('billing.admin.redemption.col.name') },
  { key: 'plan_id', label: t('billing.admin.redemption.col.plan') },
  { key: 'amount_fen', label: t('billing.admin.redemption.col.price') },
  { key: 'quantity', label: t('billing.admin.redemption.col.progress') },
  { key: 'expires_at', label: t('billing.admin.redemption.col.expiresAt') },
  { key: 'created_at', label: t('billing.admin.redemption.col.createdAt') },
])
const filterGroups = computed(() => [
  {
    key: 'source',
    label: t('billing.admin.redemption.sourceFilterLabel'),
    modelValue: sourceFilter.value,
    options: sourceOptions.value,
  },
  {
    key: 'plan',
    label: t('billing.admin.redemption.planFilterLabel'),
    modelValue: planFilter.value,
    options: planFilterOptions.value,
  },
])
function onMobileFilter(groupKey: string, value: string | number | boolean) {
  if (groupKey === 'source') sourceFilter.value = String(value)
  else if (groupKey === 'plan') planFilter.value = String(value)
}

function fenToYuan(fen: number): string {
  return (fen / 100).toFixed(2)
}

async function loadPlans() {
  const data = await get<PlanLite[]>('/api/admin/billing/plans?include_inactive=true', { silent: true })
  if (data) plans.value = data
}

onMounted(async () => {
  await Promise.all([loadPlans().catch(handleError), loadBatches()])
})

// ── Create batch modal ──
const createOpen = ref(false)
const createSaving = ref(false)
const createError = ref<string | null>(null)
const formName = ref('')
const formPlanId = ref<number | ''>('')
const formDays = ref('30')
const formAmountYuan = ref('0.00')
const formChannel = ref<'taobao' | 'xianyu' | 'other'>('taobao')
const formQuantity = ref('50')
const formValidDays = ref('')

const createPlanOptions = computed(() =>
  standardPlans.value.map((p) => ({
    value: p.id,
    label: `${p.display_name} · ¥${fenToYuan(p.price_fen)} / ${p.days}d`,
  })),
)

watch(formPlanId, (newId) => {
  if (typeof newId !== 'number') return
  const p = standardPlans.value.find((x) => x.id === newId)
  if (p) {
    formDays.value = String(p.days)
    formAmountYuan.value = fenToYuan(p.price_fen)
  }
})

const canCreate = computed(() => {
  if (createSaving.value) return false
  if (!formName.value.trim()) return false
  if (typeof formPlanId.value !== 'number' || formPlanId.value <= 0) return false
  const d = Number(formDays.value)
  const q = Number(formQuantity.value)
  const amt = Number(formAmountYuan.value)
  if (!Number.isInteger(d) || d < 1 || d > 3650) return false
  if (!Number.isInteger(q) || q < 1 || q > 1000) return false
  if (Number.isNaN(amt) || amt < 0) return false
  if (formValidDays.value.trim() !== '') {
    const vd = Number(formValidDays.value)
    if (!Number.isInteger(vd) || vd < 1 || vd > 3650) return false
  }
  return true
})

function openCreate() {
  formName.value = ''
  const firstPlan = standardPlans.value.find((p) => p.is_active) ?? standardPlans.value[0]
  formPlanId.value = firstPlan ? firstPlan.id : ''
  formDays.value = firstPlan ? String(firstPlan.days) : '30'
  formAmountYuan.value = firstPlan ? fenToYuan(firstPlan.price_fen) : '0.00'
  formChannel.value = 'taobao'
  formQuantity.value = '50'
  formValidDays.value = ''
  createError.value = null
  createOpen.value = true
}

async function doCreateBatch() {
  if (!canCreate.value) return
  createSaving.value = true
  createError.value = null
  try {
    let expiresAt: string | null = null
    if (formValidDays.value.trim() !== '') {
      const vd = Number(formValidDays.value)
      expiresAt = new Date(Date.now() + vd * 86400 * 1000).toISOString()
    }
    const res = await raw('/api/admin/billing/redemption/batches', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: formName.value.trim(),
        plan_id: Number(formPlanId.value),
        days: Number(formDays.value),
        amount_fen: Math.round(Number(formAmountYuan.value) * 100),
        channel: formChannel.value,
        quantity: Number(formQuantity.value),
        expires_at: expiresAt,
      }),
      silent: true,
    })
    const created = (await res.json()) as RedemptionBatchSummary
    toast(t('billing.admin.redemption.batchCreatedOk', { count: created.quantity }), 'success')
    createOpen.value = false
    resetStateWithoutFetch()
    await loadBatches()
    openDetail(created)
  } catch (err) {
    createError.value = apiErrorMessage(err)
  } finally {
    createSaving.value = false
  }
}

// ── Detail / Export / Void ──
const detailOpen = ref(false)
const detailBatchId = ref<number | null>(null)

function openDetail(b: RedemptionBatchSummary) {
  detailBatchId.value = b.id
  detailOpen.value = true
}

async function doQuickExport(b: RedemptionBatchSummary) {
  try {
    const res = await raw(`/api/admin/billing/redemption/batches/${b.id}/export`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    })
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `redemption_batch_${b.id}.txt`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
    toast(t('billing.admin.redemption.exportAllOk'), 'success')
    await loadBatches()
  } catch (err) {
    handleError(err)
  }
}

async function doVoidBatch(b: RedemptionBatchSummary) {
  const ok = await confirm({
    title: t('billing.admin.redemption.voidBatch'),
    message: t('billing.admin.redemption.voidBatchConfirm', { name: b.name, count: b.unused_count }),
    variant: 'danger',
    confirmText: t('billing.admin.redemption.voidBatch'),
  })
  if (!ok) return
  try {
    const res = await raw(`/api/admin/billing/redemption/batches/${b.id}/void`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: t('billing.admin.redemption.detail.voidReasonDefault') }),
    })
    const data = (await res.json()) as { voided_count: number }
    toast(t('billing.admin.redemption.voidBatchOk', { count: data.voided_count }), 'success')
    await loadBatches()
  } catch (err) {
    handleError(err)
  }
}

// ── Mobile action sheet ──
const mobileTarget = ref<RedemptionBatchSummary | null>(null)
const mobileOpen = ref(false)
function openMobile(b: RedemptionBatchSummary) {
  mobileTarget.value = b
  mobileOpen.value = true
}
</script>

<template>
  <PageHeaderActions>
    <BaseButton size="sm" variant="primary" @click="openCreate">
      <MsIcon name="add" size="xs" />{{ t('billing.admin.redemption.createBatch') }}
    </BaseButton>
  </PageHeaderActions>

  <SectionToolbar>
    <template #start>
      <div class="tb-search-row">
        <FilterInput
          v-model="searchQuery"
          :placeholder="t('billing.admin.redemption.searchBatchPlaceholder')"
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
        {{ t('billing.admin.redemption.totalBatches', { n: total }) }}
      </span>
    </template>
    <template #end>
      <div class="tb-select-group tb-desktop-only">
        <BaseSelect
          v-model="sourceFilter"
          :options="sourceOptions"
          :prefix="t('billing.admin.redemption.sourceFilterLabel') + ': '"
          size="sm"
          fit
        />
        <BaseSelect
          v-model="planFilter"
          :options="planFilterOptions"
          :prefix="t('billing.admin.redemption.planFilterLabel') + ': '"
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

  <div class="batches-table-wrap">
  <DataTable
    :items="items"
    :page="page"
    :total-pages="totalPages"
    :per-page="limit"
    :per-page-label="t('billing.orders.perPage')"
    :loading="tableLoading"
    empty-icon="redeem"
    :empty-text="t('billing.admin.redemption.emptyBatches')"
    row-key="id"
    @update:page="page = $event"
    @update:per-page="setPerPage"
  >
    <template #header>
      <SortTh class="col-name" col="name" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('billing.admin.redemption.col.name') }}</SortTh>
      <SortTh class="col-plan" col="plan_id" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('billing.admin.redemption.col.plan') }}</SortTh>
      <SortTh class="col-price" col="amount_fen" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('billing.admin.redemption.col.price') }}</SortTh>
      <SortTh class="col-progress" col="quantity" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('billing.admin.redemption.col.progress') }}</SortTh>
      <SortTh class="col-expires" col="expires_at" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('billing.admin.redemption.col.expiresAt') }}</SortTh>
      <SortTh class="col-created" col="created_at" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('billing.admin.redemption.col.createdAt') }}</SortTh>
      <th class="col-actions">{{ t('billing.admin.redemption.col.actions') }}</th>
    </template>
    <template #row="{ item: b }">
      <td class="col-name">
        <div class="name-main">{{ b.name }}</div>
        <div class="name-sub">
          <Badge :color="b.source === 'api' ? 'var(--blue)' : 'var(--ac)'" size="sm">
            {{ b.source === 'api' ? t('billing.admin.redemption.sourceApi') : t('billing.admin.redemption.sourceManual') }}
          </Badge>
        </div>
      </td>
      <td class="col-plan">
        <div>{{ b.plan_name || `#${b.plan_id}` }}</div>
        <div class="name-sub">{{ t('billing.admin.redemption.daysValue', { days: b.days }) }}</div>
      </td>
      <td class="col-price">
        <div class="mono">¥{{ fenToYuan(b.amount_fen) }}</div>
        <div class="name-sub">{{ t(`billing.channel.${b.channel}`) }}</div>
      </td>
      <td class="col-progress">
        <div>{{ t('billing.admin.redemption.progressText', { redeemed: b.redeemed_count, unused: b.unused_count, total: b.quantity }) }}</div>
        <div v-if="b.source === 'manual'" class="name-sub">
          {{ t('billing.admin.redemption.exportedShort', { exported: b.exported_count }) }}
        </div>
      </td>
      <td class="col-expires">
        {{ b.expires_at ? fmtDate(b.expires_at) : t('billing.admin.redemption.neverExpire') }}
      </td>
      <td class="col-created">{{ fmtDate(b.created_at) }}</td>
      <td class="col-actions">
        <div class="row-actions">
          <BaseButton size="sm" @click="openDetail(b)">
            <MsIcon name="visibility" size="xs" /> {{ t('billing.admin.redemption.viewDetail') }}
          </BaseButton>
          <BaseButton
            v-if="b.source === 'manual'"
            size="sm"
            :disabled="b.exportable_count <= 0"
            @click="doQuickExport(b)"
          >
            <MsIcon name="download" size="xs" /> {{ t('billing.admin.redemption.exportTxt') }}
          </BaseButton>
          <BaseButton
            size="sm"
            variant="danger"
            :disabled="b.unused_count <= 0"
            @click="doVoidBatch(b)"
          >
            <MsIcon name="block" size="xs" /> {{ t('billing.admin.redemption.void') }}
          </BaseButton>
        </div>
      </td>
    </template>
    <template #card="{ item: b }">
      <CardTap @tap="openMobile(b)">
        <div class="card-row--main">
          <span class="card-name">{{ b.name }} <span class="card-id-inline">#{{ b.id }}</span></span>
          <Badge :color="b.source === 'api' ? 'var(--blue)' : 'var(--ac)'" size="sm">
            {{ b.source === 'api' ? t('billing.admin.redemption.sourceApi') : t('billing.admin.redemption.sourceManual') }}
          </Badge>
        </div>
        <div class="card-detail">
          <CardKV :label="t('billing.admin.redemption.col.plan')">
            {{ b.plan_name || `#${b.plan_id}` }} · {{ t('billing.admin.redemption.daysValue', { days: b.days }) }}
          </CardKV>
          <CardKV :label="t('billing.admin.redemption.col.price')">
            <span class="mono">¥{{ fenToYuan(b.amount_fen) }}</span> · {{ t(`billing.channel.${b.channel}`) }}
          </CardKV>
          <CardKV :label="t('billing.admin.redemption.col.progress')">
            {{ t('billing.admin.redemption.progressText', { redeemed: b.redeemed_count, unused: b.unused_count, total: b.quantity }) }}
          </CardKV>
        </div>
      </CardTap>
    </template>
  </DataTable>
  </div>

  <ActionSheet v-model="mobileOpen" :title="mobileTarget?.name">
    <template v-if="mobileTarget">
      <button @click="mobileOpen = false; openDetail(mobileTarget!)">
        <MsIcon name="visibility" size="sm" /> {{ t('billing.admin.redemption.viewDetail') }}
      </button>
      <button
        v-if="mobileTarget.source === 'manual'"
        :disabled="mobileTarget.exportable_count <= 0"
        @click="mobileOpen = false; doQuickExport(mobileTarget!)"
      >
        <MsIcon name="download" size="sm" /> {{ t('billing.admin.redemption.exportTxt') }}
      </button>
      <button
        class="action-sheet--danger"
        :disabled="mobileTarget.unused_count <= 0"
        @click="mobileOpen = false; doVoidBatch(mobileTarget!)"
      >
        <MsIcon name="block" size="sm" /> {{ t('billing.admin.redemption.voidBatch') }}
      </button>
    </template>
  </ActionSheet>

  <BaseModal
    v-model="createOpen"
    :title="t('billing.admin.redemption.createBatchTitle')"
    icon="redeem"
    size="md"
  >
    <div class="modal-form">
      <AlertBanner v-if="createError" tone="danger">{{ createError }}</AlertBanner>
      <FormField :label="t('billing.admin.redemption.field.name')" required>
        <BaseInput v-model="formName" />
      </FormField>
      <FormField :label="t('billing.admin.redemption.field.plan')" required>
        <BaseSelect
          v-model="formPlanId"
          :options="createPlanOptions"
          searchable
          teleport
          :placeholder="t('billing.admin.redemption.field.planPlaceholder')"
        />
      </FormField>
      <div class="form-grid-2">
        <FormField :label="t('billing.admin.redemption.field.days')" required>
          <BaseInput v-model="formDays" type="number" mono />
        </FormField>
        <FormField :label="t('billing.admin.redemption.field.quantity')" required>
          <BaseInput v-model="formQuantity" type="number" mono />
        </FormField>
      </div>
      <div class="form-grid-2">
        <FormField :label="t('billing.admin.redemption.field.amountYuan')" required>
          <BaseInput v-model="formAmountYuan" type="number" mono />
        </FormField>
        <FormField :label="t('billing.admin.redemption.field.channel')" required>
          <BaseSelect v-model="formChannel" :options="channelOptions" teleport />
        </FormField>
      </div>
      <FormField :label="t('billing.admin.redemption.field.validDays')">
        <BaseInput
          v-model="formValidDays"
          type="number"
          mono
          :placeholder="t('billing.admin.redemption.field.validDaysPlaceholder')"
        />
      </FormField>
    </div>
    <template #footer>
      <BaseButton @click="createOpen = false">{{ t('common.btn.cancel') }}</BaseButton>
      <BaseButton variant="primary" :loading="createSaving" :disabled="!canCreate" @click="doCreateBatch">
        {{ t('billing.admin.redemption.createBatch') }}
      </BaseButton>
    </template>
  </BaseModal>

  <RedemptionBatchDetailModal
    v-model="detailOpen"
    :batch-id="detailBatchId"
    @updated="() => void loadBatches()"
  />
</template>

<style scoped>
.batches-table-wrap :deep(.col-price)    { white-space: nowrap; }
.batches-table-wrap :deep(.col-expires)  { color: var(--t2); font-size: var(--text-sm); }
.batches-table-wrap :deep(.col-created)  { color: var(--t2); font-size: var(--text-sm); }

.row-actions { display: flex; align-items: center; gap: var(--sp-2); flex-wrap: wrap; }
.mono { font-family: var(--font-mono); }
.name-main { font-weight: 500; color: var(--t1); overflow: hidden; text-overflow: ellipsis; }
.name-sub { display: flex; align-items: center; gap: var(--sp-1); color: var(--t3); font-size: var(--text-xs); margin-top: 2px; }
.card-name { font-weight: 600; font-size: .92rem; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.card-id-inline { font-size: .78rem; font-weight: 400; color: var(--t3); margin-left: var(--sp-1); }
.modal-form { display: flex; flex-direction: column; gap: var(--sp-3); }
.form-grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: var(--sp-3); }
@media (max-width: 560px) {
  .form-grid-2 { grid-template-columns: 1fr; }
}
</style>

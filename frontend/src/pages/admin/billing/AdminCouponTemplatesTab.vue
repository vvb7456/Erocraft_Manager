<script setup lang="ts">
/**
 * AdminCouponTemplatesTab — list/create/edit/delete coupon templates.
 *
 * Embedded inside AdminBillingPage (TabSwitcher). Follows AdminPlansPage
 * conventions: SectionToolbar → DataTable with percentage column widths,
 * per-row BaseButtons, mobile ActionSheet, ConfirmDialog for destructive
 * operations.
 */
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { ApiError, apiErrorMessage } from '@/composables/apiClient'
import { useConfirm } from '@/composables/useConfirm'
import { useToast } from '@/composables/useToast'
import SectionToolbar from '@/components/ui/SectionToolbar.vue'
import PageHeaderActions from '@/components/layout/PageHeaderActions.vue'
import DataTable from '@/components/ui/DataTable.vue'
import SortTh from '@/components/ui/SortTh.vue'
import { useTableSort } from '@/composables/useTableSort'
import { useClientPagination } from '@/composables/useTablePagination'
import FilterInput from '@/components/ui/FilterInput.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import Badge from '@/components/ui/Badge.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import CardTap from '@/components/ui/CardTap.vue'
import CardKV from '@/components/ui/CardKV.vue'
import ActionSheet from '@/components/ui/ActionSheet.vue'
import MobileFilterSheet from '@/components/ui/MobileFilterSheet.vue'
import CouponTemplateEditorModal, {
  type CouponTemplate,
  type CouponTemplateEditorMode,
} from '@/components/billing/CouponTemplateEditorModal.vue'

defineOptions({ name: 'AdminCouponTemplatesTab' })

const { t } = useI18n({ useScope: 'global' })
const { get, raw } = useApiFetch()
const { confirm } = useConfirm()
const { toast } = useToast()

const templates = ref<CouponTemplate[]>([])
const tableLoading = ref(true)

const searchTerm = ref('')
const statusFilter = ref<'all' | 'active' | 'inactive'>('all')

const statusOptions = computed(() => [
  { value: 'all',      label: t('billing.admin.couponTemplates.filterAll') },
  { value: 'active',   label: t('billing.admin.couponTemplates.filterActive') },
  { value: 'inactive', label: t('billing.admin.couponTemplates.filterInactive') },
])

// ── Mobile filter sheet ──
const mobileFilterOpen = ref(false)
const sortColumns = computed(() => [
  { key: 'is_active', label: t('billing.admin.couponTemplates.col.status') },
  { key: 'code', label: t('billing.admin.couponTemplates.col.code') },
  { key: 'name', label: t('billing.admin.couponTemplates.col.name') },
  { key: 'discount_fen', label: t('billing.admin.couponTemplates.col.discount') },
  { key: 'valid_days', label: t('billing.admin.couponTemplates.col.validDays') },
])
const filterGroups = computed(() => [
  {
    key: 'status',
    label: t('billing.admin.couponTemplates.statusFilterLabel'),
    modelValue: statusFilter.value,
    options: statusOptions.value,
  },
])
function onMobileFilter(groupKey: string, value: string | number | boolean) {
  if (groupKey === 'status') {
    statusFilter.value = String(value) as 'all' | 'active' | 'inactive'
  }
}

const editorOpen = ref(false)
const editorMode = ref<CouponTemplateEditorMode>('create')
const editorTemplate = ref<CouponTemplate | null>(null)

const { sortBy, sortOrder, toggleSort, sortItems } = useTableSort({
  descColumns: ['is_active', 'discount_fen', 'valid_days'],
})

const mobileActionTpl = ref<CouponTemplate | null>(null)
const mobileActionOpen = ref(false)

const filtered = computed(() => {
  const q = searchTerm.value.trim().toLowerCase()
  return templates.value.filter((tpl) => {
    if (statusFilter.value === 'active' && !tpl.is_active) return false
    if (statusFilter.value === 'inactive' && tpl.is_active) return false
    if (q) {
      const haystack = [tpl.code, tpl.name, tpl.description ?? ''].join(' ').toLowerCase()
      if (!haystack.includes(q)) return false
    }
    return true
  })
})

const sorted = computed(() =>
  sortItems(filtered.value, {
    is_active: (tpl) => tpl.is_active,
    code: (tpl) => tpl.code,
    name: (tpl) => tpl.name,
    discount_fen: (tpl) => tpl.discount_fen,
    valid_days: (tpl) => tpl.valid_days,
  }, {
    tieBreaker: (a, b) => b.id - a.id,
  }),
)

const { page, perPage, totalPages, paginated, setPerPage } = useClientPagination(sorted, {
  resetDeps: [searchTerm, statusFilter, sortBy, sortOrder],
})

function fenToYuan(fen: number): string { return (fen / 100).toFixed(2) }

async function loadAll() {
  tableLoading.value = true
  const data = await get<CouponTemplate[]>(
    '/api/admin/billing/coupon-templates?include_inactive=true',
    { silent: true },
  ).finally(() => { tableLoading.value = false })
  if (data) templates.value = data
}

onMounted(loadAll)

function openCreate() {
  editorMode.value = 'create'
  editorTemplate.value = null
  editorOpen.value = true
}

function openEdit(tpl: CouponTemplate) {
  editorMode.value = 'edit'
  editorTemplate.value = tpl
  editorOpen.value = true
}

function onSaved(saved: CouponTemplate) {
  const idx = templates.value.findIndex((t) => t.id === saved.id)
  if (idx >= 0) templates.value.splice(idx, 1, saved)
  else templates.value.unshift(saved)
}

async function doDelete(tpl: CouponTemplate) {
  if (tpl.is_builtin) {
    toast(t('billing.admin.couponTemplates.deleteBuiltin'), 'error')
    return
  }
  const ok = await confirm({
    title: t('billing.admin.couponTemplates.delete'),
    message: t('billing.admin.couponTemplates.deleteConfirm', { code: tpl.code }),
    variant: 'danger',
    confirmText: t('billing.admin.couponTemplates.delete'),
  })
  if (!ok) return
  try {
    await raw(`/api/admin/billing/coupon-templates/${tpl.id}`, { method: 'DELETE' })
    templates.value = templates.value.filter((t) => t.id !== tpl.id)
    toast(t('billing.admin.couponTemplates.deleteOk'), 'success')
  } catch (error) {
    toast(error instanceof ApiError && error.status === 409 ? t('billing.admin.couponTemplates.deleteConflict') : apiErrorMessage(error), 'error')
  }
}

function openMobileAction(tpl: CouponTemplate) {
  mobileActionTpl.value = tpl
  mobileActionOpen.value = true
}

function fmtScope(tpl: CouponTemplate): string {
  const kinds = tpl.applicable_order_kinds ?? []
  const plans = tpl.applicable_plan_ids ?? []
  if (!kinds.length && !plans.length) return t('billing.admin.couponTemplates.scopeAll')
  const parts: string[] = []
  if (kinds.length) parts.push(kinds.join('/'))
  if (plans.length) parts.push(`#${plans.join(',')}`)
  return parts.join(' · ')
}
</script>

<template>
  <PageHeaderActions>
    <BaseButton size="sm" variant="primary" @click="openCreate"><MsIcon name="add" size="xs" />{{ t('billing.admin.couponTemplates.create') }}</BaseButton>
  </PageHeaderActions>
  <SectionToolbar>
    <template #start>
      <div class="tb-search-row">
        <FilterInput
          v-model="searchTerm"
          :placeholder="t('billing.admin.couponTemplates.searchPlaceholder')"
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
        {{ t('billing.admin.couponTemplates.totalCount', { n: filtered.length }) }}
      </span>
    </template>
    <template #end>
      <div class="tb-select-group tb-desktop-only">
        <BaseSelect
          v-model="statusFilter"
          :options="statusOptions"
          :prefix="t('billing.admin.couponTemplates.statusFilterLabel') + ': '"
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

  <div class="templates-table-wrap">
  <DataTable
    :items="paginated"
    :page="page"
    :total-pages="totalPages"
    :per-page="perPage"
    :loading="tableLoading"
    :per-page-label="t('billing.admin.couponTemplates.perPageLabel')"
    empty-icon="confirmation_number"
    :empty-text="searchTerm
      ? t('billing.admin.couponTemplates.emptySearch', { q: searchTerm })
      : t('billing.admin.couponTemplates.empty')"
    row-key="id"
    @update:page="page = $event"
    @update:per-page="setPerPage"
  >
    <template #header>
      <SortTh class="col-name" col="name" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('billing.admin.couponTemplates.col.name') }}</SortTh>
      <SortTh class="col-code" col="code" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('billing.admin.couponTemplates.col.code') }}</SortTh>
      <SortTh class="col-discount" col="discount_fen" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('billing.admin.couponTemplates.col.discount') }}</SortTh>
      <th class="col-scope">{{ t('billing.admin.couponTemplates.col.scope') }}</th>
      <SortTh class="col-valid" col="valid_days" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('billing.admin.couponTemplates.col.validDays') }}</SortTh>
      <SortTh class="col-status" col="is_active" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('billing.admin.couponTemplates.col.status') }}</SortTh>
      <th class="col-actions">{{ t('billing.admin.couponTemplates.col.actions') }}</th>
    </template>
    <template #row="{ item: tpl }">
      <td class="col-name">
        <div class="name-main">{{ tpl.name }}</div>
        <div v-if="tpl.description" class="name-sub">{{ tpl.description }}</div>
      </td>
      <td class="col-code"><code>{{ tpl.code }}</code></td>
      <td class="col-discount mono">
        <div>−¥{{ fenToYuan(tpl.discount_fen) }}</div>
        <div v-if="tpl.min_order_fen > 0" class="name-sub">
          {{ t('billing.admin.couponTemplates.minOrderShort', { amount: fenToYuan(tpl.min_order_fen) }) }}
        </div>
      </td>
      <td class="col-scope">{{ fmtScope(tpl) }}</td>
      <td class="col-valid">{{ tpl.valid_days }} {{ t('billing.admin.couponTemplates.dayUnit') }}</td>
      <td class="col-status">
        <Badge :color="tpl.is_active ? 'var(--green)' : 'var(--red)'">
          {{ tpl.is_active ? t('billing.admin.couponTemplates.statusActive') : t('billing.admin.couponTemplates.statusInactive') }}
        </Badge>
        <Badge v-if="tpl.is_builtin" color="var(--blue)" class="builtin-tag">
          {{ t('billing.admin.couponTemplates.builtin') }}
        </Badge>
      </td>
      <td class="col-actions">
        <div class="action-group">
          <BaseButton size="sm" @click="openEdit(tpl)">
            <MsIcon name="edit" size="xs" /> {{ t('common.btn.edit') }}
          </BaseButton>
          <BaseButton size="sm" variant="danger" :disabled="tpl.is_builtin" @click="doDelete(tpl)">
            <MsIcon name="delete" size="xs" /> {{ t('billing.admin.couponTemplates.delete') }}
          </BaseButton>
        </div>
      </td>
    </template>
    <template #card="{ item: tpl }">
      <CardTap @tap="openMobileAction(tpl)">
        <div class="card-row--main">
          <span class="card-name">{{ tpl.name }} <span class="card-id-inline">#{{ tpl.id }}</span></span>
          <Badge :color="tpl.is_active ? 'var(--green)' : 'var(--red)'" size="sm">
            {{ tpl.is_active ? t('billing.admin.couponTemplates.statusActive') : t('billing.admin.couponTemplates.statusInactive') }}
          </Badge>
        </div>
        <div class="card-detail">
          <CardKV :label="t('billing.admin.couponTemplates.col.code')"><code>{{ tpl.code }}</code></CardKV>
          <CardKV :label="t('billing.admin.couponTemplates.col.discount')">
            <span class="mono">−¥{{ fenToYuan(tpl.discount_fen) }}</span>
          </CardKV>
          <CardKV :label="t('billing.admin.couponTemplates.col.validDays')">{{ tpl.valid_days }} {{ t('billing.admin.couponTemplates.dayUnit') }}</CardKV>
          <CardKV :label="t('billing.admin.couponTemplates.col.scope')">{{ fmtScope(tpl) }}</CardKV>
        </div>
      </CardTap>
    </template>
  </DataTable>
  </div>

  <ActionSheet v-model="mobileActionOpen" :title="mobileActionTpl?.name">
    <template v-if="mobileActionTpl" #info>
      <code>{{ mobileActionTpl.code }}</code> ·
      <span class="mono">−¥{{ fenToYuan(mobileActionTpl.discount_fen) }}</span>
    </template>
    <template v-if="mobileActionTpl">
      <button @click="mobileActionOpen = false; openEdit(mobileActionTpl!)">
        <MsIcon name="edit" size="sm" /> {{ t('common.btn.edit') }}
      </button>
      <button
        class="action-sheet--danger"
        :disabled="mobileActionTpl.is_builtin"
        @click="mobileActionOpen = false; doDelete(mobileActionTpl!)"
      >
        <MsIcon name="delete" size="sm" /> {{ t('billing.admin.couponTemplates.delete') }}
      </button>
    </template>
  </ActionSheet>

  <CouponTemplateEditorModal
    v-model="editorOpen"
    :mode="editorMode"
    :template="editorTemplate"
    @saved="onSaved"
  />
</template>

<style scoped>
.templates-table-wrap :deep(.col-discount) { white-space: nowrap; }
.templates-table-wrap :deep(.col-scope)    { color: var(--t2); font-size: var(--text-sm); }
.templates-table-wrap :deep(.col-valid)    { white-space: nowrap; }
.templates-table-wrap :deep(.col-status)   { white-space: nowrap; }

.mono { font-family: var(--font-mono); }
code {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  background: var(--bg-in);
  padding: 2px 6px;
  border-radius: var(--r-xs);
  color: var(--t1);
}
.name-main { color: var(--t1); font-weight: 500; overflow: hidden; text-overflow: ellipsis; }
.name-sub { color: var(--t3); font-size: var(--text-xs); margin-top: 2px; overflow: hidden; text-overflow: ellipsis; }
.builtin-tag { margin-left: var(--sp-1); }
.action-group { display: flex; gap: var(--sp-2); flex-wrap: wrap; }
.card-name { font-weight: 600; font-size: .92rem; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.card-id-inline { font-size: .78rem; font-weight: 400; color: var(--t3); margin-left: var(--sp-1); }
</style>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useFormatDate } from '@/composables/useFormatDate'
import { useConfirm } from '@/composables/useConfirm'
import { useToast } from '@/composables/useToast'
import PageHeaderActions from '@/components/layout/PageHeaderActions.vue'
import SectionToolbar from '@/components/ui/SectionToolbar.vue'
import FilterInput from '@/components/ui/FilterInput.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseModal from '@/components/ui/BaseModal.vue'
import DataTable from '@/components/ui/DataTable.vue'
import SortTh from '@/components/ui/SortTh.vue'
import { useTableSort } from '@/composables/useTableSort'
import { useServerPagination } from '@/composables/useTablePagination'
import Badge from '@/components/ui/Badge.vue'
import CardTap from '@/components/ui/CardTap.vue'
import FormField from '@/components/form/FormField.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import MobileFilterSheet from '@/components/ui/MobileFilterSheet.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import { notificationCategories, type NotificationAlert } from '@/types/notifications'

const { t } = useI18n()
const { get, post } = useApiFetch()
const { formatDateTime } = useFormatDate()
const { confirm } = useConfirm()
const { toast } = useToast()
const router = useRouter()
const route = useRoute()
const categories = notificationCategories.filter(c => c !== 'support')
const categoryFilter = ref(categories.some(c => c === route.query.category) ? String(route.query.category) : 'all')
const stateFilter = ref('all')
const search = ref('')
const items = ref<NotificationAlert[]>([])
const failed = ref(false)
const busy = ref(false)
const ackAllBusy = ref(false)
const selected = ref<NotificationAlert | null>(null)
const detailOpen = ref(false)
const filterOpen = ref(false)
const { sortBy, sortOrder, toggleSort } = useTableSort({
  descColumns: ['created_at', 'severity'],
})
const sortColumns = computed(() => [
  { key: 'created_at', label: t('notifications.center.createdAt') },
  { key: 'category', label: t('notifications.center.type') },
  { key: 'title', label: t('notifications.center.alert') },
  { key: 'severity', label: t('notifications.center.severity') },
  { key: 'state', label: t('notifications.center.status') },
])
const counts = ref<Record<string, number>>({ open: 0, acknowledged: 0, muted: 0 })
const categoryOptions = computed(() => [{ value: 'all', label: t('notifications.center.allCategories') }, ...categories.map(value => ({ value, label: t(`notifications.category.${value}`) }))])
const stateOptions = computed(() => ['all', 'open', 'acknowledged', 'muted'].map(value => ({ value,
  label: t(`notifications.center.state.${value}`) + (value === 'all' ? '' : ` (${counts.value[value] || 0})`),
})))
const filters = computed(() => [
  { key: 'category', label: t('notifications.center.notificationType'), modelValue: categoryFilter.value, options: categoryOptions.value },
  { key: 'state', label: t('notifications.center.status'), modelValue: stateFilter.value, options: stateOptions.value },
])
let appliedSearch = ''
let timer: ReturnType<typeof setInterval> | undefined

const {
  page,
  perPage,
  total,
  totalPages,
  loading,
  reload,
  setPerPage,
} = useServerPagination(
  async ({ page: reqPage, perPage: reqPerPage, offset, isCurrent }) => {
    const q = search.value.trim()
    appliedSearch = q
    const params = new URLSearchParams({
      category: categoryFilter.value,
      state: stateFilter.value,
      q,
      offset: String(offset),
      limit: String(reqPerPage),
    })
    if (sortBy.value) {
      params.set('sort_by', sortBy.value)
      params.set('sort_order', sortOrder.value)
    }
    const result = await get<{ items: NotificationAlert[]; total: number; counts: Record<string, number> }>(
      `/api/admin/notifications/alerts?${params}`,
      { silent: true },
    )
    if (!isCurrent()) return null
    failed.value = false
    counts.value = result.counts
    if (reqPage > Math.max(1, Math.ceil(result.total / reqPerPage))) return { total: result.total }
    items.value = result.items
    if (detailOpen.value && selected.value) {
      selected.value = result.items.find(item => item.key === selected.value?.key) || selected.value
    }
    return { total: result.total }
  },
  {
    initialPerPage: 30,
    filters: [categoryFilter, stateFilter, sortBy, sortOrder],
    search,
    onError: () => {
      failed.value = true
    },
  },
)

function setFilter(key: string, value: string | number | boolean) {
  if (key === 'category') categoryFilter.value = String(value)
  else stateFilter.value = String(value)
}
function showDetails(alert: NotificationAlert) { selected.value = alert; detailOpen.value = true }
function severityColor(value: string) { return value === 'critical' ? 'var(--red)' : value === 'warning' ? 'var(--amber)' : 'var(--blue)' }
function stateColor(value: string) { return value === 'open' ? 'var(--amber)' : value === 'acknowledged' ? 'var(--ac)' : undefined }
async function act(action: string) {
  if (!selected.value || busy.value) return
  busy.value = true
  try {
    if (await post('/api/admin/notifications/alerts/action', { key: selected.value.key, action })) {
      detailOpen.value = false
      await reload()
    }
  } finally { busy.value = false }
}
async function acknowledgeAll() {
  const openCount = counts.value.open || 0
  if (openCount <= 0 || ackAllBusy.value) return
  const ok = await confirm({
    title: t('notifications.center.acknowledgeAllTitle'),
    message: t('notifications.center.acknowledgeAllConfirm', { count: openCount }),
    confirmText: t('notifications.center.acknowledgeAll'),
  })
  if (!ok) return
  ackAllBusy.value = true
  try {
    const res = await post<{ ok: boolean; acknowledged_count: number }>(
      '/api/admin/notifications/alerts/acknowledge-all',
      { category: 'all' },
    )
    if (res) {
      toast(t('notifications.center.acknowledgeAllSuccess', { count: res.acknowledged_count }), 'success')
      await reload()
    }
  } finally { ackAllBusy.value = false }
}
onMounted(() => {
  void reload()
  timer = setInterval(() => {
    if (
      document.visibilityState === 'visible' &&
      !loading.value &&
      !busy.value &&
      !ackAllBusy.value &&
      !detailOpen.value &&
      search.value.trim() === appliedSearch
    ) {
      void reload({ silent: true })
    }
  }, 30000)
})
onBeforeUnmount(() => { if (timer) clearInterval(timer) })
</script>

<template>
  <PageHeaderActions>
    <BaseButton
      size="sm"
      variant="primary"
      :disabled="(counts.open || 0) <= 0 || ackAllBusy"
      :loading="ackAllBusy"
      @click="acknowledgeAll"
    >
      <MsIcon name="done_all" size="xs" /> {{ t('notifications.center.acknowledgeAll') }}
    </BaseButton>
  </PageHeaderActions>

  <SectionToolbar>
    <template #start>
      <div class="tb-search-row">
        <FilterInput v-model="search" :placeholder="t('notifications.center.search')" class="tb-search" />
        <button class="tb-filter-btn" :title="t('common.filterSort.title')" @click="filterOpen = true"><MsIcon name="tune" size="sm" /></button>
      </div>
      <span class="toolbar-status tb-status">{{ t('notifications.center.alertCount', { count: total }) }}</span>
    </template>
    <template #end>
      <div class="tb-select-group tb-desktop-only">
        <BaseSelect v-model="categoryFilter" :options="categoryOptions" :prefix="t('notifications.center.type') + ': '" size="sm" fit />
        <BaseSelect v-model="stateFilter" :options="stateOptions" :prefix="t('notifications.center.status') + ': '" size="sm" fit />
      </div>
    </template>
  </SectionToolbar>
  <MobileFilterSheet v-model:open="filterOpen" :sort-columns="sortColumns" :sort-by="sortBy" :sort-order="sortOrder" :filters="filters" @sort="toggleSort" @update:filter="setFilter" />

  <EmptyState v-if="failed && !loading" icon="error_outline" :title="t('notifications.center.loadFailed')"><BaseButton size="sm" @click="reload()">{{ t('notifications.reload') }}</BaseButton></EmptyState>
  <div v-else class="alerts-table">
  <DataTable :items="items" :page="page" :total-pages="totalPages" :per-page="perPage" :max-per-page="100" :loading="loading"
    row-key="key" empty-icon="check_circle" :empty-text="t('notifications.center.noAlerts')" :per-page-label="t('notifications.center.perPage')"
    @update:page="page = $event" @update:per-page="setPerPage">
    <template #colgroup>
      <colgroup>
        <col class="col-time" />
        <col class="col-category" />
        <col class="col-content" />
        <col class="col-description" />
        <col class="col-severity" />
        <col class="col-state" />
        <col class="col-action" />
      </colgroup>
    </template>
    <template #header>
      <SortTh col="created_at" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('notifications.center.createdAt') }}</SortTh>
      <SortTh col="category" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('notifications.center.type') }}</SortTh>
      <SortTh col="title" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('notifications.center.alert') }}</SortTh>
      <th>{{ t('notifications.center.description') }}</th>
      <SortTh col="severity" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('notifications.center.severity') }}</SortTh>
      <SortTh col="state" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('notifications.center.status') }}</SortTh>
      <th class="alert-action">{{ t('notifications.center.actions') }}</th>
    </template>
    <template #row="{ item }">
      <td class="alert-time"><time :datetime="item.created_at">{{ formatDateTime(item.created_at) }}</time></td>
      <td class="alert-category">{{ t(`notifications.category.${item.category}`) }}</td>
      <td class="alert-cell">
        <button class="alert-link" :title="item.title" @click="showDetails(item)">{{ item.title }}</button>
      </td>
      <td class="alert-description"><span class="alert-summary" :title="item.body">{{ item.body || '—' }}</span></td>
      <td><Badge :color="severityColor(item.severity)">{{ t(`notifications.center.alertSeverity.${item.severity}`) }}</Badge></td>
      <td><Badge :color="stateColor(item.state)">{{ t(`notifications.center.state.${item.state}`) }}</Badge></td>
      <td class="alert-action">
        <div class="action-group">
          <BaseButton size="sm" @click="showDetails(item)">
            <MsIcon name="edit" size="xs" /> {{ t('common.btn.edit') }}
          </BaseButton>
        </div>
      </td>
    </template>
    <template #card="{ item }">
      <CardTap @tap="showDetails(item)">
        <div class="card-heading"><Badge :color="severityColor(item.severity)">{{ t(`notifications.center.alertSeverity.${item.severity}`) }}</Badge><Badge :color="stateColor(item.state)">{{ t(`notifications.center.state.${item.state}`) }}</Badge></div>
        <div class="card-title">{{ item.title }}</div>
        <div v-if="item.body" class="card-description alert-summary">{{ item.body }}</div>
        <div class="card-meta"><span>{{ t(`notifications.category.${item.category}`) }}</span><time>{{ formatDateTime(item.created_at) }}</time></div>
      </CardTap>
    </template>
  </DataTable>
  </div>

  <BaseModal v-model="detailOpen" :title="selected?.title" icon="notifications" size="lg" :persistent="busy">
    <template v-if="selected">
      <FormField :label="t('notifications.center.status')" layout="horizontal"><Badge :color="stateColor(selected.state)">{{ t(`notifications.center.state.${selected.state}`) }}</Badge></FormField>
      <FormField :label="t('notifications.center.createdAt')" layout="horizontal"><span class="detail-value">{{ formatDateTime(selected.created_at) }}</span></FormField>
      <FormField v-if="selected.state === 'muted'" :label="t('notifications.center.mutedUntil')" layout="horizontal"><span class="detail-value">{{ formatDateTime(selected.muted_until) }}</span></FormField>
      <p class="alert-message">{{ selected.body }}</p>
    </template>
    <template v-if="selected" #footer>
      <BaseButton v-if="selected.state === 'open'" size="sm" :disabled="busy" @click="act('acknowledge')">{{ t('notifications.center.acknowledge') }}</BaseButton>
      <BaseButton size="sm" :disabled="busy" @click="act(selected.state === 'muted' ? 'unmute' : 'mute')">{{ t(selected.state === 'muted' ? 'notifications.center.unmute' : 'notifications.center.mute') }}</BaseButton>
      <BaseButton v-if="selected.category === 'system'" size="sm" variant="primary" :loading="busy" @click="act('close')">{{ t('notifications.center.close') }}</BaseButton>
      <BaseButton size="sm" :variant="selected.category === 'system' ? 'default' : 'primary'" :disabled="busy" @click="router.push(selected.path)">{{ t('notifications.center.details') }}</BaseButton>
    </template>
  </BaseModal>
</template>

<style scoped>
.alerts-table :deep(.dt-table) { table-layout: fixed; min-width: 1040px; }
.col-time { width: 14%; }
.col-category { width: 11%; }
.col-content { width: 19%; }
.col-description { width: 25%; }
.col-severity { width: 9%; }
.col-state { width: 10%; }
.col-action { width: 12%; }
.alerts-table :deep(.alert-cell), .alerts-table :deep(.alert-category), .alerts-table :deep(.alert-description) { white-space: normal; }
.alert-category, .alert-description { color: var(--t2); }
.alert-summary { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; overflow-wrap: anywhere; white-space: normal; line-height: 1.5; }
.alert-link { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; max-width: 100%; border: 0; padding: 0; background: none; color: var(--t1); font: inherit; font-weight: 500; line-height: 1.5; text-align: left; cursor: pointer; overflow-wrap: anywhere; white-space: normal; }
.alert-link:hover { color: var(--ac); }
.alerts-table :deep(.alert-time) { color: var(--t2); font-variant-numeric: tabular-nums; white-space: nowrap; }
.alerts-table :deep(.alert-action) { white-space: normal; }
.action-group { display: flex; align-items: center; gap: var(--sp-2); flex-wrap: wrap; }
.alert-description { font-size: .82rem; }
.card-heading, .card-meta { display: flex; align-items: center; justify-content: space-between; gap: var(--sp-2); }
.card-title { margin: var(--sp-2) 0; font-size: var(--text-base); color: var(--t1); overflow-wrap: anywhere; }
.card-description { margin-bottom: var(--sp-3); color: var(--t2); font-size: .82rem; }
.card-meta { font-size: var(--text-sm); color: var(--t3); flex-wrap: wrap; }
.detail-value, .alert-message { font-size: var(--text-base); color: var(--t2); }
.alert-message { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.6; margin: var(--sp-4) 0 0; }
</style>

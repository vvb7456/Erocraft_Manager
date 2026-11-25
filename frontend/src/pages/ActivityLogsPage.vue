<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useFormatDate } from '@/composables/useFormatDate'
import { useActivityLog } from '@/composables/useActivityLog'
import PageHeader from '@/components/layout/PageHeader.vue'
import SectionToolbar from '@/components/ui/SectionToolbar.vue'
import FilterInput from '@/components/ui/FilterInput.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import Badge from '@/components/ui/Badge.vue'
import DataTable from '@/components/ui/DataTable.vue'
import SortTh from '@/components/ui/SortTh.vue'
import { useTableSort } from '@/composables/useTableSort'
import { useServerPagination } from '@/composables/useTablePagination'
import MobileFilterSheet from '@/components/ui/MobileFilterSheet.vue'
import MsIcon from '@/components/ui/MsIcon.vue'

defineOptions({ name: 'ActivityLogsPage' })

const { t, te } = useI18n({ useScope: 'global' })
const { detailLabel } = useActivityLog()
const { get, handleError } = useApiFetch()
const { formatDateTime } = useFormatDate()

// ── Types ──
interface LogItem {
  id: number
  timestamp: string | null
  actor: string
  category: string
  status: 'success' | 'failed'
  detailKey: string | null
  detailParams: Record<string, unknown>
}

interface LogResponse {
  logs: LogItem[]
  total: number
  page: number
  perPage: number
  totalPages: number
  filters: {
    actors: string[]
    categories: string[]
  }
}

const logs = ref<LogItem[]>([])
const filterActor = ref('')
const filterCategory = ref('')
const filterStatus = ref('')
const categoryOptions = ref<string[]>([])
const { sortBy, sortOrder, toggleSort } = useTableSort({
  defaultBy: 'timestamp',
  defaultOrder: 'desc',
  descColumns: ['timestamp'],
})

const {
  page,
  perPage,
  total: totalCount,
  totalPages,
  loading,
  reload: loadLogs,
  setPerPage,
} = useServerPagination(
  async ({ page: reqPage, perPage: reqPerPage, isCurrent }) => {
    const params = new URLSearchParams()
    params.set('page', String(reqPage))
    params.set('per_page', String(reqPerPage))
    if (filterActor.value.trim()) params.set('actor', filterActor.value.trim())
    if (filterCategory.value) params.set('category', filterCategory.value)
    if (filterStatus.value) params.set('status', filterStatus.value)
    if (sortBy.value) {
      params.set('sort_by', sortBy.value)
      params.set('sort_order', sortOrder.value)
    }
    const data = await get<LogResponse>(`/api/admin/activity-logs?${params}`)
    if (!data || !isCurrent()) return null
    logs.value = data.logs
    categoryOptions.value = data.filters.categories
    return { total: data.total }
  },
  {
    initialPerPage: 20,
    filters: [filterCategory, filterStatus, sortBy, sortOrder],
    search: filterActor,
    onError: handleError,
  },
)

onMounted(() => {
  void loadLogs()
})

// ── Helpers ──
function formatTime(ts: string | null): string {
  if (!ts) return formatDateTime(null)
  // Backend now always sends Z; the endsWith check is a defensive fallback
  // for any stale cache / older response.
  return formatDateTime(ts.endsWith('Z') ? ts : ts + 'Z')
}


function statusColor(status: string): string {
  return status === 'success' ? 'var(--green)' : 'var(--red)'
}
function actorLabel(actor: string): string {
  if (actor === 'system') return t('logs.actor.system')
  if (actor === 'unknown') return t('logs.actor.unknown')
  return actor
}

function categoryLabel(category: string): string {
  const key = `logs.category.${category}`
  return te(key) ? t(key) : category
}

const statusOptions = ['success', 'failed']

// ── Mobile filter sheet ──
const mobileFilterOpen = ref(false)
const sortColumns = computed(() => [
  { key: 'timestamp', label: t('logs.table.time') },
  { key: 'actor', label: t('logs.table.actor') },
  { key: 'category', label: t('logs.table.category') },
  { key: 'status', label: t('logs.table.status') },
])
const filterGroups = computed(() => [
  {
    key: 'category',
    label: t('logs.filter.category'),
    modelValue: filterCategory.value,
    options: [{ value: '', label: t('logs.filter.all') }, ...categoryOptions.value.map(c => ({ value: c, label: categoryLabel(c) }))],
  },
  {
    key: 'status',
    label: t('logs.filter.status'),
    modelValue: filterStatus.value,
    options: [{ value: '', label: t('logs.filter.all') }, ...statusOptions.map(s => ({ value: s, label: t(`logs.status_label.${s}`) }))],
  },
])
function onMobileFilter(groupKey: string, value: string | number | boolean) {
  if (groupKey === 'category') filterCategory.value = String(value)
  else if (groupKey === 'status') filterStatus.value = String(value)
}
</script>

<template>
  <PageHeader icon="history" :title="t('logs.title')" />

  <div class="page-body">
    <!-- Filters -->
    <SectionToolbar>
      <template #start>
        <div class="tb-search-row">
          <FilterInput
            v-model="filterActor"
            :placeholder="t('logs.filter.actorPlaceholder')"
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
        <span class="toolbar-status tb-status">{{ t('logs.total', { n: totalCount }) }}</span>
      </template>
      <template #end>
        <div class="tb-select-group tb-desktop-only">
          <BaseSelect
            v-model="filterCategory"
            :options="[{ value: '', label: t('logs.filter.all') }, ...categoryOptions.map(c => ({ value: c, label: categoryLabel(c) }))]"
            :prefix="t('logs.filter.category') + ': '"
            size="sm"
            fit
          />
          <BaseSelect
            v-model="filterStatus"
            :options="[{ value: '', label: t('logs.filter.all') }, ...statusOptions.map(s => ({ value: s, label: t(`logs.status_label.${s}`) }))]"
            :prefix="t('logs.filter.status') + ': '"
            size="sm"
            fit
          />
        </div>
      </template>
    </SectionToolbar>

    <!-- Mobile filter sheet -->
    <MobileFilterSheet
      v-model:open="mobileFilterOpen"
      :sort-columns="sortColumns"
      :sort-by="sortBy"
      :sort-order="sortOrder"
      :filters="filterGroups"
      @sort="toggleSort"
      @update:filter="onMobileFilter"
    />

    <!-- Table -->
    <DataTable
      :items="logs"
      :page="page"
      :total-pages="totalPages"
      :per-page="perPage"
      :per-page-label="t('logs.pagination.per_page')"
      :loading="loading"
      empty-icon="history"
      :empty-text="t('logs.empty')"
      @update:page="page = $event"
      @update:per-page="setPerPage"
    >
      <template #header>
        <SortTh class="col-time" col="timestamp" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('logs.table.time') }}</SortTh>
        <SortTh class="col-actor" col="actor" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('logs.table.actor') }}</SortTh>
        <SortTh class="col-action" col="category" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('logs.table.category') }}</SortTh>
        <SortTh class="col-status" col="status" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('logs.table.status') }}</SortTh>
        <th class="col-details">{{ t('logs.table.details') }}</th>
      </template>
      <template #row="{ item: log }">
        <td class="col-time">{{ formatTime(log.timestamp) }}</td>
        <td class="col-actor">{{ actorLabel(log.actor) }}</td>
        <td class="col-action"><Badge size="sm">{{ categoryLabel(log.category) }}</Badge></td>
        <td class="col-status">
          <Badge :color="statusColor(log.status)">
            {{ t(`logs.status_label.${log.status}`, log.status) }}
          </Badge>
        </td>
        <td class="col-details">
          <span class="details-text" :title="detailLabel(log)">{{ detailLabel(log) }}</span>
        </td>
      </template>

      <!-- Mobile card -->
      <template #card="{ item: log }">
        <div class="log-card-time">{{ formatTime(log.timestamp) }}</div>
        <div class="log-card-row">
          <span>{{ actorLabel(log.actor) }}</span>
          <Badge :color="statusColor(log.status)" size="sm">
            {{ t(`logs.status_label.${log.status}`, log.status) }}
          </Badge>
        </div>
        <Badge size="sm">{{ categoryLabel(log.category) }}</Badge>
        <div class="log-card-details">{{ detailLabel(log) }}</div>
      </template>
    </DataTable>
  </div>
</template>

<style scoped>
:deep(.col-time)    { white-space: nowrap; font-variant-numeric: tabular-nums; }
:deep(.col-actor)   { white-space: nowrap; }
:deep(.col-action)  { white-space: nowrap; }
:deep(.col-status)  { white-space: nowrap; }
:deep(.dt-table td.col-details) { white-space: normal; }

.details-text {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  white-space: normal;
  word-break: break-word;
  color: var(--t2);
  font-size: .82rem;
}
/* Mobile card styles */
.log-card-time {
  font-size: .78rem;
  color: var(--t3);
  font-variant-numeric: tabular-nums;
}
.log-card-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: var(--sp-1);
  font-size: .85rem;
}
.log-card-details {
  margin-top: var(--sp-2);
  font-size: .82rem;
  color: var(--t2);
  word-break: break-all;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>

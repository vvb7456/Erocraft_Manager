<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useFormatDate } from '@/composables/useFormatDate'
import PageHeader from '@/components/layout/PageHeader.vue'
import SectionToolbar from '@/components/ui/SectionToolbar.vue'
import FilterInput from '@/components/ui/FilterInput.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import Badge from '@/components/ui/Badge.vue'
import DataTable from '@/components/ui/DataTable.vue'
import MobileFilterSheet from '@/components/ui/MobileFilterSheet.vue'
import MsIcon from '@/components/ui/MsIcon.vue'

defineOptions({ name: 'ActivityLogsPage' })

const { t, te, tm, rt } = useI18n({ useScope: 'global' })
const { get, loading } = useApiFetch()
const { formatDateTime } = useFormatDate()

// ── Types ──
interface LogItem {
  id: number
  timestamp: string | null
  actor: string
  category: string
  status: string
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

// ── State ──
const logs = ref<LogItem[]>([])
const page = ref(1)
const perPage = ref(20)
const totalPages = ref(1)
const totalCount = ref(0)
const filterActor = ref('')
const filterCategory = ref('')
const filterStatus = ref('')
const categoryOptions = ref<string[]>([])

// ── Fetch ──
async function loadLogs() {
  const params = new URLSearchParams()
  params.set('page', String(page.value))
  params.set('per_page', String(perPage.value))
  if (filterActor.value) params.set('actor', filterActor.value)
  if (filterCategory.value) params.set('category', filterCategory.value)
  if (filterStatus.value) params.set('status', filterStatus.value)
  const data = await get<LogResponse>(`/api/admin/activity-logs?${params}`)
  if (data) {
    logs.value = data.logs
    totalPages.value = data.totalPages
    totalCount.value = data.total
    categoryOptions.value = data.filters.categories
  }
}

onMounted(loadLogs)
watch([filterActor, filterCategory, filterStatus], () => {
  page.value = 1
  loadLogs()
})

// ── Helpers ──
function formatTime(ts: string | null): string {
  if (!ts) return formatDateTime(null)
  // Backend now always sends Z; the endsWith check is a defensive fallback
  // for any stale cache / older response.
  return formatDateTime(ts.endsWith('Z') ? ts : ts + 'Z')
}


function statusColor(status: string): string {
  if (status === 'success') return 'var(--green)'
  if (status === 'failed') return 'var(--red)'
  if (status === 'partial') return 'var(--amber)'
  return 'var(--blue)'
}
function actorLabel(actor: string): string {
  if (actor === 'system') return t('logs.actor.system')
  if (actor === 'unknown') return t('logs.actor.unknown')
  return actor
}

function formatDurationSeconds(sec: number): string {
  if (!Number.isFinite(sec) || sec < 0) sec = 0
  sec = Math.round(sec)
  if (sec < 60) return t('logs.duration.seconds', { n: sec })
  if (sec < 3600) {
    const m = Math.floor(sec / 60)
    const s = sec % 60
    return s > 0
      ? t('logs.duration.minutesSeconds', { m, s })
      : t('logs.duration.minutes', { n: m })
  }
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  return m > 0
    ? t('logs.duration.hoursMinutes', { h, m })
    : t('logs.duration.hours', { n: h })
}

function categoryLabel(category: string): string {
  const key = `logs.category.${category}`
  return te(key) ? t(key) : category
}

function detailLabel(log: LogItem): string {
  if (!log.detailKey) return '—'
  const params = { ...(log.detailParams ?? {}) }
  if (typeof params.template === 'string') {
    params.template = t(`emailTemplates.${params.template}.title`, params.template)
  }
  if (typeof params.type === 'string') {
    params.type = t(`logs.reminderType.${params.type}`, params.type)
  }
  if (typeof params.kind === 'string') {
    const kindKey = `hosts.kind.${params.kind}`
    if (te(kindKey)) params.kind = t(kindKey)
  }
  if (typeof params.language === 'string') {
    params.language = t(`logs.language.${params.language}`, params.language)
  }
  if (typeof params.alert_type === 'string') {
    const k = `hosts.alerting.types.${params.alert_type}`
    if (te(k)) params.alert_type = t(k)
  }
  if (typeof params.severity === 'string') {
    const k = `logs.severity.${params.severity}`
    if (te(k)) params.severity = t(k)
  }
  if (typeof params.duration_seconds === 'number') {
    params.duration_human = formatDurationSeconds(params.duration_seconds)
  }

  // detail_key usually contains dots (e.g. "node.wings_config.update").
  // Treat it as a flat key under logs.detail first to avoid path-splitting misses.
  const detailMap = tm('logs.detail') as Record<string, unknown>
  const flatMessage = detailMap?.[log.detailKey]
  if (typeof flatMessage === 'string') {
    return rt(flatMessage, params)
  }

  const escapedPath = `logs.detail.${log.detailKey.replace(/\./g, '\\.')}`
  if (te(escapedPath)) {
    return t(escapedPath, params)
  }
  return t('logs.detail.unknown', { key: log.detailKey })
}

const statusOptions = ['success', 'failed', 'partial', 'info']

// ── Mobile filter sheet ──
const mobileFilterOpen = ref(false)
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
      :sort-columns="[]"
      :sort-by="''"
      :sort-order="'asc'"
      :filters="filterGroups"
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
      @update:page="v => { page = v; loadLogs() }"
      @update:per-page="v => { perPage = v; page = 1; loadLogs() }"
    >
      <template #header>
        <th class="col-time">{{ t('logs.table.time') }}</th>
        <th class="col-actor">{{ t('logs.table.actor') }}</th>
        <th class="col-action">{{ t('logs.table.category') }}</th>
        <th class="col-status">{{ t('logs.table.status') }}</th>
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
          <span class="details-text">{{ detailLabel(log) }}</span>
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
.col-time { width: 14%; white-space: nowrap; font-variant-numeric: tabular-nums; }
.col-actor { width: 10%; white-space: nowrap; }
.col-action { width: 13%; white-space: nowrap; }
.col-status { width: 7%; white-space: nowrap; }
.col-details { width: 56%; }

.details-text {
  word-break: break-all;
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

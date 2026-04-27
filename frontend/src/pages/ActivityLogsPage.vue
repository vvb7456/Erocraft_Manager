<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useAppStore } from '@/stores/app'
import PageHeader from '@/components/layout/PageHeader.vue'
import SectionToolbar from '@/components/ui/SectionToolbar.vue'
import FilterInput from '@/components/ui/FilterInput.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import Badge from '@/components/ui/Badge.vue'
import DataTable from '@/components/ui/DataTable.vue'

defineOptions({ name: 'ActivityLogsPage' })

const { t, te, tm, rt } = useI18n({ useScope: 'global' })
const { get, loading } = useApiFetch()
const appStore = useAppStore()

// ── Types ──
interface LogItem {
  id: number
  timestamp: string | null
  actor: string
  category: string
  action: string
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
    actions: string[]
  }
}

// ── State ──
const logs = ref<LogItem[]>([])
const page = ref(1)
const perPage = ref(20)
const totalPages = ref(1)
const totalCount = ref(0)
const filterActor = ref('')
const filterAction = ref('')
const filterStatus = ref('')
const actionOptions = ref<string[]>([])

// ── Fetch ──
async function loadLogs() {
  const params = new URLSearchParams()
  params.set('page', String(page.value))
  params.set('per_page', String(perPage.value))
  if (filterActor.value) params.set('actor', filterActor.value)
  if (filterAction.value) params.set('action', filterAction.value)
  if (filterStatus.value) params.set('status', filterStatus.value)
  const data = await get<LogResponse>(`/api/admin/activity-logs?${params}`)
  if (data) {
    logs.value = data.logs
    totalPages.value = data.totalPages
    totalCount.value = data.total
    actionOptions.value = data.filters.actions
  }
}

onMounted(loadLogs)
watch([filterActor, filterAction, filterStatus], () => {
  page.value = 1
  loadLogs()
})

// ── Helpers ──
function formatTime(ts: string | null): string {
  if (!ts) return '—'
  const d = new Date(ts + 'Z') // UTC
  return d.toLocaleString('zh-CN', { timeZone: appStore.timezone, hour12: false })
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

function actionLabel(action: string): string {
  const key = `logs.action.${action}`
  return te(key) ? t(key) : action
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
    params.kind = t(`hosts.kind.${params.kind}`, params.kind)
  }
  if (typeof params.language === 'string') {
    params.language = t(`logs.language.${params.language}`, params.language)
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
</script>

<template>
  <PageHeader icon="history" :title="t('logs.title')" />

  <div class="page-body">
    <!-- Filters -->
    <SectionToolbar>
      <template #start>
        <div class="toolbar-start-row">
          <FilterInput
            v-model="filterActor"
            :placeholder="t('logs.filter.actorPlaceholder')"
            class="logs-filter-input"
          />
          <span class="toolbar-status">{{ t('logs.total', { n: totalCount }) }}</span>
        </div>
      </template>
      <template #end>
        <BaseSelect
          v-model="filterAction"
          :options="[{ value: '', label: t('logs.filter.all') }, ...actionOptions.map(a => ({ value: a, label: actionLabel(a) }))]"
          :prefix="t('logs.filter.action') + ': '"
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
      </template>
    </SectionToolbar>

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
        <th class="col-action">{{ t('logs.table.action') }}</th>
        <th class="col-status">{{ t('logs.table.status') }}</th>
        <th class="col-details">{{ t('logs.table.details') }}</th>
      </template>
      <template #row="{ item: log }">
        <td class="col-time">{{ formatTime(log.timestamp) }}</td>
        <td class="col-actor">{{ actorLabel(log.actor) }}</td>
        <td class="col-action"><code class="action-code">{{ actionLabel(log.action) }}</code></td>
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
        <code class="action-code">{{ actionLabel(log.action) }}</code>
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

.toolbar-start-row {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  min-width: 0;
}

.logs-filter-input {
  width: min(320px, 72vw);
}

.toolbar-status {
  color: var(--t3);
  font-size: var(--text-sm);
  white-space: nowrap;
}

.action-code {
  font-family: var(--font-mono);
  font-size: .78rem;
  padding: 1px 6px;
  border-radius: 3px;
  background: var(--bg2);
  color: var(--t2);
}

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

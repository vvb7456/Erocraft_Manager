<script setup lang="ts">
import { ref, computed, watch, inject, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useAppStore } from '@/stores/app'
import { getEggMeta } from '@/config/eggRegistry'
import SectionToolbar from '@/components/ui/SectionToolbar.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import DataTable from '@/components/ui/DataTable.vue'

defineOptions({ name: 'ServerActivityPage' })

const { t, te, locale } = useI18n({ useScope: 'global' })
const { get, loading } = useApiFetch()
const appStore = useAppStore()

// ── Types ──
interface ActivityActor {
  id: number
  uuid: string
  username: string
  email: string
}

interface ActivityLogItem {
  id: number
  batch: string | null
  event: string
  ip: string
  description: string | null
  actorType: string | null
  actorId: number | null
  apiKeyId: number | null
  properties: Record<string, any>
  timestamp: string
  actor: ActivityActor | null
}

interface ActivityLogsResponse {
  logs: ActivityLogItem[]
  total: number
  page: number
  perPage: number
}

// ── Injections ──
const server = inject<Ref<{ id: number; eggName: string } | null>>('server')!

// ── State ──
const logs = ref<ActivityLogItem[]>([])
const page = ref(1)
const perPage = ref(20)
const total = ref(0)
const eventFilter = ref('')

// ── Filter options ──
const filterOptions = computed(() => [
  { value: '', label: t('activity.filter.all') },
  { value: 'server:power', label: t('activity.filter.power') },
  { value: 'server:file', label: t('activity.filter.file') },
  { value: 'server:startup,server:settings', label: t('activity.filter.settings') },
  { value: 'server:console', label: t('activity.filter.console') },
  { value: 'server:reinstall', label: t('activity.filter.system') },
])

// ── Fetch ──
async function loadLogs() {
  if (!server.value) return
  const params = new URLSearchParams()
  params.set('page', String(page.value))
  params.set('per_page', String(perPage.value))
  if (eventFilter.value) params.set('event', eventFilter.value)

  const data = await get<ActivityLogsResponse>(
    `/api/user/servers/${server.value.id}/activity?${params}`,
  )
  if (data) {
    logs.value = data.logs
    total.value = data.total
  }
}

watch([() => server.value?.id], () => { page.value = 1; loadLogs() }, { immediate: true })
watch(eventFilter, () => { page.value = 1; loadLogs() })

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / perPage.value)))

// ── Event display helpers ──
const EVENT_COLORS: Record<string, string> = {
  'server:power': 'var(--green)',
  'server:file': 'var(--blue)',
  'server:startup': 'var(--amber)',
  'server:settings': 'var(--amber)',
  'server:console': 'var(--t3)',
  'server:reinstall': 'var(--red)',
}

function getEventColor(event: string): string {
  for (const prefix of Object.keys(EVENT_COLORS)) {
    if (event.startsWith(prefix)) return EVENT_COLORS[prefix]
  }
  return 'var(--t3)'
}

function translateEvent(event: string): string {
  const key = 'activity.' + event.replace(':', '.')
  return te(key) ? t(key) : event
}

// ── Time formatting ──
function formatDateTime(ts: string): string {
  const d = new Date(ts.endsWith('Z') ? ts : ts + 'Z')
  return d.toLocaleString(locale.value, {
    timeZone: appStore.timezone,
    hour12: false,
    year: undefined,
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// ── Properties rendering ──
function getPropsText(log: ActivityLogItem): string {
  const p = log.properties
  if (!p || typeof p !== 'object' || Array.isArray(p)) return ''

  const parts: string[] = []

  if (log.event === 'server:console.command' && p.command) {
    const cmd = String(p.command)
    return cmd.length > 80 ? cmd.slice(0, 80) + '…' : cmd
  }

  if (p.file && typeof p.file === 'string') {
    parts.push(p.file)
  }

  if (Array.isArray(p.files) && p.files.length > 0) {
    const maxShow = 2
    for (let i = 0; i < Math.min(maxShow, p.files.length); i++) {
      const f = p.files[i]
      if (typeof f === 'object' && f.from && f.to) {
        parts.push(`${f.from} → ${f.to}`)
      } else {
        parts.push(String(f))
      }
    }
    if (p.files.length > maxShow) {
      parts.push(t('activity.props.filesCount', { n: p.files.length - maxShow }))
    }
  }

  if (p.name && typeof p.name === 'string' && !p.file) {
    parts.push(p.name)
  }

  if (p.directory && typeof p.directory === 'string' && p.directory !== '/') {
    parts.push(t('activity.props.inDir', { dir: p.directory }))
  }

  if (p.url && typeof p.url === 'string') {
    parts.push(p.url)
  }

  if (p.variable && typeof p.variable === 'string') {
    if (p.old !== undefined && p.new !== undefined) {
      const secrets = getEggMeta(server.value?.eggName ?? '').secretVars ?? []
      const isSecret = secrets.includes(p.variable)
      const oldDisplay = isSecret ? '***' : String(p.old)
      const newDisplay = isSecret ? '***' : String(p.new)
      parts.push(`${p.variable}: ${oldDisplay} → ${newDisplay}`)
    } else {
      parts.push(p.variable)
    }
  }

  return parts.join(' · ')
}
</script>

<template>
  <div class="activity-page">
    <SectionToolbar>
      <template #start>
        <span class="toolbar-count">{{ t('activity.total', { n: total }) }}</span>
      </template>
      <template #end>
        <BaseSelect
          v-model="eventFilter"
          :options="filterOptions"
          :prefix="t('activity.filter.label') + ': '"
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
      :per-page-label="t('activity.pagination.perPage')"
      :loading="loading"
      empty-icon="history"
      :empty-text="eventFilter ? t('activity.emptyFiltered') : t('activity.empty')"
      @update:page="v => { page = v; loadLogs() }"
      @update:per-page="v => { perPage = v; page = 1; loadLogs() }"
    >
      <template #header>
        <th class="col-time">{{ t('activity.col.time') }}</th>
        <th class="col-event">{{ t('activity.col.event') }}</th>
        <th class="col-user">{{ t('activity.col.user') }}</th>
        <th class="col-ip">IP</th>
        <th class="col-detail">{{ t('activity.col.detail') }}</th>
      </template>

      <template #row="{ item: log }">
        <td class="col-time">{{ formatDateTime(log.timestamp) }}</td>
        <td class="col-event">
          <span class="event-cell">
            <span class="event-dot" :style="{ background: getEventColor(log.event) }" />
            <span class="event-label">{{ translateEvent(log.event) }}</span>
          </span>
        </td>
        <td class="col-user">{{ log.actor?.username ?? '—' }}</td>
        <td class="col-ip">
          <code class="ip-text">{{ log.ip }}</code>
        </td>
        <td class="col-detail">
          <span class="detail-text">{{ getPropsText(log) }}</span>
        </td>
      </template>

      <!-- Mobile card -->
      <template #card="{ item: log }">
        <div class="card-top">
          <span class="event-cell">
            <span class="event-dot" :style="{ background: getEventColor(log.event) }" />
            <span class="event-label">{{ translateEvent(log.event) }}</span>
          </span>
          <span class="card-time">{{ formatDateTime(log.timestamp) }}</span>
        </div>
        <div v-if="getPropsText(log)" class="card-detail">{{ getPropsText(log) }}</div>
        <div class="card-meta">
          <span v-if="log.actor" class="card-actor">{{ log.actor.username }}</span>
          <code class="ip-text">{{ log.ip }}</code>
        </div>
      </template>
    </DataTable>
  </div>
</template>

<style scoped>
.activity-page {
  display: flex;
  flex-direction: column;
}

.toolbar-count {
  font-size: var(--text-sm);
  color: var(--t3);
}

/* ── Event cell ── */
.event-cell {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
}

.event-dot {
  flex-shrink: 0;
  width: 7px;
  height: 7px;
  border-radius: 50%;
}

.event-label {
  font-weight: 500;
}

/* ── Table columns ── */
.col-time {
  width: 13%;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  color: var(--t3);
}

.col-event {
  width: 14%;
  white-space: nowrap;
}

.col-user {
  width: 10%;
  white-space: nowrap;
  color: var(--t2);
}

.col-ip {
  width: 12%;
  white-space: nowrap;
}

.col-detail {
  width: 51%;
}

.detail-text {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  color: var(--t2);
  word-break: break-all;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.ip-text {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  color: var(--t3);
}

/* ── Mobile card ── */
.card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-2);
}

.card-time {
  font-size: var(--text-xs);
  font-variant-numeric: tabular-nums;
  font-family: var(--font-mono);
  color: var(--t3);
  white-space: nowrap;
}

.card-detail {
  margin-top: var(--sp-2);
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  color: var(--t2);
  word-break: break-all;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-meta {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin-top: var(--sp-2);
  font-size: var(--text-xs);
  color: var(--t3);
}

.card-actor::after {
  content: '·';
  margin-left: var(--sp-2);
}
</style>

<script setup lang="ts">
// Admin server detail container.
// Owns the runtime polling so the header badge can mirror the user-side
// console badge (uses utils/status.ts), and provides runtime + buffers to
// the Overview pane via inject so the pane stays a presentational layer.
import { computed, onBeforeUnmount, provide, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useApiFetch } from '@/composables/useApiFetch'
import PageHeader from '@/components/layout/PageHeader.vue'
import Badge from '@/components/ui/Badge.vue'
import StatusDot from '@/components/ui/StatusDot.vue'
import TabSwitcher from '@/components/ui/TabSwitcher.vue'
import LoadingCenter from '@/components/ui/LoadingCenter.vue'
import { getStatusDotKey, getStatusColor } from '@/utils/status'
import { hasLlmKey } from '@/config/eggRegistry'
import type {
  AdminServerDetailResponse,
  ServerRuntimeResponse,
} from '@/types/adminServer'

defineOptions({ name: 'AdminServerDetailPage' })

const { t } = useI18n({ useScope: 'global' })
const route = useRoute()
const router = useRouter()
const { get } = useApiFetch()

const serverId = computed(() => Number(route.params.id))
const detail = ref<AdminServerDetailResponse | null>(null)
const loading = ref(false)
// Whether this server has a provisioned LLM key (gates the LLM tab).
const llmProvisioned = ref(false)

provide('adminServerDetail', detail)
provide('adminServerId', serverId)

async function loadDetail(silent = false) {
  if (!Number.isFinite(serverId.value)) return
  if (!silent) loading.value = true
  try {
    const data = await get<AdminServerDetailResponse>(`/api/admin/servers/${serverId.value}`)
    if (data) detail.value = data
  } finally {
    if (!silent) loading.value = false
  }
}
provide('reloadAdminServer', () => loadDetail(true))

async function refreshLlmProvisioned() {
  if (!Number.isFinite(serverId.value)) return
  const data = await get<{ provisioned: boolean }>(
    `/api/admin/servers/${serverId.value}/llm/provisioned`,
    { silent: true },
  )
  llmProvisioned.value = !!data?.provisioned
}
provide('refreshAdminServerLlm', refreshLlmProvisioned)

// ── runtime polling shared with Overview pane ──────────────────────────
const SAMPLE_INTERVAL_MS = 5_000
const SAMPLE_LIMIT = 60   // 5min @ 5s

const runtime = ref<ServerRuntimeResponse | null>(null)
const runtimeStale = ref(false)
const cpuBuffer = ref<number[]>([])
const memBuffer = ref<number[]>([])

provide('adminServerRuntime', runtime)
provide('adminServerRuntimeStale', runtimeStale)
provide('adminServerCpuBuffer', cpuBuffer)
provide('adminServerMemBuffer', memBuffer)

function pushBuffer(buf: typeof cpuBuffer, value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return
  const next = [...buf.value, value]
  if (next.length > SAMPLE_LIMIT) next.shift()
  buf.value = next
}

async function fetchRuntime(withMetrics = false) {
  if (!Number.isFinite(serverId.value)) return
  const data = await get<ServerRuntimeResponse>(
    `/api/admin/servers/${serverId.value}/runtime`,
    { silent: true },
  )
  if (data) {
    runtime.value = data
    runtimeStale.value = false
    if (withMetrics) {
      const r = data.resources ?? {}
      pushBuffer(cpuBuffer, (r as { cpu_absolute?: number }).cpu_absolute)
      const memBytes = (r as { memory_bytes?: number }).memory_bytes
      pushBuffer(memBuffer, memBytes != null ? memBytes / (1024 * 1024) : null)
    }
  } else {
    runtimeStale.value = true
  }
}

let runtimeTimer: number | null = null

function stopRuntimePolling() {
  if (runtimeTimer !== null) {
    clearInterval(runtimeTimer)
    runtimeTimer = null
  }
}

function startRuntimePolling() {
  stopRuntimePolling()
  runtimeTimer = window.setInterval(() => {
    void fetchRuntime(activeTab.value === 'admin-server-overview')
  }, SAMPLE_INTERVAL_MS)
}

onBeforeUnmount(() => {
  stopRuntimePolling()
})

// ── header status badge — mirrors user-side ServerDetailPage.statusBadge() ─
const liveState = computed(() => runtime.value?.state ?? detail.value?.server.status ?? 'offline')
const isSuspended = computed(() => detail.value?.server.isSuspended ?? false)
const isInstalling = computed(() => detail.value?.server.isInstalling ?? false)

const statusDot = computed(() =>
  getStatusDotKey(liveState.value, isSuspended.value, isInstalling.value, runtimeStale.value),
)

const statusColor = computed(() => {
  // user-side maps differently: stale->t3, suspended->red, installing->amber.
  // We mirror that exactly via getStatusColor.
  return getStatusColor(liveState.value, isSuspended.value, isInstalling.value, runtimeStale.value)
})

const statusLabel = computed(() => {
  if (!detail.value) return t('adminServer.status.unknown')
  if (runtimeStale.value) return t('adminServer.status.disconnected')
  if (isSuspended.value) return t('adminServer.status.suspended')
  if (isInstalling.value) return t('adminServer.status.installing')
  if (detail.value.server.status === 'install_failed') return t('adminServer.status.install_failed')
  const s = liveState.value
  switch (s) {
    case 'running': return t('adminServer.status.running')
    case 'starting': return t('adminServer.status.starting')
    case 'stopping': return t('adminServer.status.stopping')
    case 'installing': return t('adminServer.status.installing')
    default: return t('adminServer.status.offline')
  }
})

const headerTitle = computed(() => {
  if (detail.value) return `${detail.value.server.name}  #${detail.value.server.id}`
  return Number.isFinite(serverId.value)
    ? `${t('adminServer.title')}  #${serverId.value}`
    : t('adminServer.title')
})

const tabs = computed(() => {
  const list: { key: string; label: string; icon: string; disabled?: boolean }[] = [
    { key: 'admin-server-overview',  label: t('adminServer.tabs.overview'),  icon: 'dashboard' },
    { key: 'admin-server-settings',  label: t('adminServer.tabs.settings'),  icon: 'settings' },
  ]
  // LLM tab only for LLM-capable eggs.
  if (detail.value && hasLlmKey(detail.value.egg.name)) {
    list.push({
      key: 'admin-server-llm',
      label: t('adminServer.tabs.llm'),
      icon: 'smart_toy',
    })
  }
  list.push({ key: 'admin-server-lifecycle', label: t('adminServer.tabs.lifecycle'), icon: 'warning' })
  return list
})

const activeTab = computed(() => {
  const name = route.name as string | undefined
  return name && tabs.value.some(tab => tab.key === name) ? name : 'admin-server-overview'
})

const headerBreadcrumbs = computed(() => [
  { label: t('servers.title'), to: { name: 'servers' } },
  { label: headerTitle.value },
])

watch(
  [serverId, activeTab],
  async ([id], prev) => {
    if (!Number.isFinite(id)) return

    const prevId = prev?.[0]
    const changedServer = id !== prevId
    if (changedServer) {
      detail.value = null
      runtime.value = null
      runtimeStale.value = false
      cpuBuffer.value = []
      memBuffer.value = []
    } else if (activeTab.value !== 'admin-server-overview') {
      // Keep badge status live on non-overview tabs, but drop chart buffers
      // so only overview participates in metrics history updates.
      cpuBuffer.value = []
      memBuffer.value = []
    }

    // Single detail fetch when opening / switching tabs. No background
    // detail polling while staying on a tab.
    await loadDetail(changedServer)
    if (changedServer) refreshLlmProvisioned()

    // Header badge keeps a minimal live status on every tab.
    // Only overview tab appends metrics history buffers.
    await fetchRuntime(activeTab.value === 'admin-server-overview')
    startRuntimePolling()
  },
  { immediate: true },
)

function onTabChange(key: string) {
  router.push({ name: key, params: { id: serverId.value } })
}
</script>

<template>
  <LoadingCenter v-if="loading && !detail" />

  <template v-else>
    <PageHeader icon="dns" :title="headerTitle" :breadcrumbs="headerBreadcrumbs">
      <template v-if="detail" #badge>
        <Badge :color="statusColor">
          <StatusDot :status="statusDot" />
          {{ statusLabel }}
        </Badge>
      </template>
    </PageHeader>

    <div class="page-body">
      <TabSwitcher :tabs="tabs" :modelValue="activeTab" @update:modelValue="onTabChange" />
      <RouterView :key="serverId" />
    </div>
  </template>
</template>

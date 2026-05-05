<script setup lang="ts">
import { ref, provide, computed, watch, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useApiFetch } from '@/composables/useApiFetch'
import { useServerResourceStore } from '@/stores/serverResources'
import PageHeader from '@/components/layout/PageHeader.vue'
import TabSwitcher from '@/components/ui/TabSwitcher.vue'
import LoadingCenter from '@/components/ui/LoadingCenter.vue'
import StatusDot from '@/components/ui/StatusDot.vue'
import Badge from '@/components/ui/Badge.vue'
import { getStatusDotKey, getStatusColor } from '@/utils/status'
import { getEggMeta, hasTunnel } from '@/config/eggRegistry'

defineOptions({ name: 'ServerDetailPage' })

const { t } = useI18n({ useScope: 'global' })
const route = useRoute()
const router = useRouter()
const { get, loading } = useApiFetch()
const resourceStore = useServerResourceStore()
const RESOURCE_SUB_KEY = 'serverDetail'

interface ServerDetail {
  id: number
  uuid: string
  uuidShort: string
  name: string
  description: string | null
  status: string | null
  isSuspended: boolean
  isInstalling: boolean
  isInstalled: boolean
  nodeId: number
  eggId: number
  eggName: string
  limits: { memory: number; disk: number; cpu: number }
  allocation: { ip: string | null; port: number | null }
  node: { fqdn: string | null }
  expirationDate: string | null
  daysLeft: number | null
  address: string | null
  planId: number | null
  tunnel: {
    status: string
    hostname: string
    customSubdomain: string | null
    lastError: string | null
  } | null
  hostTunnelReady: boolean
}

const server = ref<ServerDetail | null>(null)
const serverId = computed(() => Number(route.params.id))

async function loadServer() {
  const data = await get<ServerDetail>(`/api/user/servers/${serverId.value}`)
  if (data) server.value = data
}

// Provide server data to child pages
provide('server', server)
provide('reloadServer', loadServer)

const isInstalling = computed(() => server.value?.isInstalling ?? false)
provide('isInstalling', isInstalling)

const isSuspended = computed(() => server.value?.isSuspended ?? false)

const tabs = computed(() => {
  const list: { key: string; label: string; icon: string; disabled?: boolean }[] = [
    { key: 'server-console', label: t('userServers.console'), icon: 'terminal' },
    { key: 'server-files', label: t('userServers.files'), icon: 'folder', disabled: isInstalling.value || stale.value || isSuspended.value },
    { key: 'server-settings', label: (() => { const lbl = getEggMeta(server.value?.eggName ?? '').label; return lbl ? t('userServers.settings', { name: lbl }) : t('userServers.settingsGeneric') })(), icon: 'settings', disabled: isInstalling.value || stale.value || isSuspended.value },
  ]
  if (server.value && hasTunnel(server.value.eggName)) {
    list.push({ key: 'server-network', label: t('userServers.network.tab'), icon: 'lan', disabled: isInstalling.value || stale.value || isSuspended.value })
  }
  list.push(
    { key: 'server-activity', label: t('activity.title'), icon: 'history', disabled: isInstalling.value || stale.value || isSuspended.value },
    { key: 'server-more', label: t('userServers.more'), icon: 'more_horiz', disabled: isInstalling.value || stale.value || isSuspended.value },
  )
  return list
})

const activeTab = computed(() => route.name as string)

watch([serverId, activeTab], ([id, tab]) => {
  if (!Number.isFinite(id)) {
    resourceStore.unsubscribe(RESOURCE_SUB_KEY)
    return
  }
  // Console tab already receives realtime stats/state from WebSocket.
  // Other tabs only need minimal polling for header/status consistency.
  if (tab === 'server-console') {
    resourceStore.unsubscribe(RESOURCE_SUB_KEY)
  } else {
    resourceStore.subscribe(RESOURCE_SUB_KEY, [id], 5000)
  }
}, { immediate: true })

onBeforeUnmount(() => {
  resourceStore.unsubscribe(RESOURCE_SUB_KEY)
})

// Non-monitor tabs follow "enter-refresh" semantics: fetch server detail
// when opening/switching tabs (or changing server id), no background
// polling in the container.
watch(
  [serverId, activeTab],
  async ([id], prev) => {
    if (!Number.isFinite(id)) return
    const prevId = prev?.[0]
    const changedServer = id !== prevId
    if (changedServer) {
      // Clear stale server data immediately so child components (especially
      // console WS) don't mount with the previous server identity.
      server.value = null
    }
    await loadServer()
  },
  { immediate: true },
)

function onTabChange(key: string) {
  router.push({ name: key, params: { id: serverId.value } })
}

const headerBreadcrumbs = computed(() => [
  { label: t('userServers.title'), to: { name: 'user-servers' } },
  { label: server.value?.name || '' },
])

// Read live state from the centralized store (sidebar already polling)
const liveState = computed(() => {
  if (!server.value) return 'offline'
  return resourceStore.getState(server.value.id) || server.value.status || 'offline'
})

const stale = computed(() => server.value ? resourceStore.isStale(server.value.id) : false)

const dotKey = computed(() => {
  if (!server.value) return 'stopped' as const
  return getStatusDotKey(
    liveState.value,
    server.value.isSuspended,
    server.value.isInstalling,
    stale.value,
  )
})

function statusBadge(): { color: string; label: string } {
  if (!server.value) return { color: 'var(--t3)', label: t('userServers.status.offline') }
  if (stale.value) return { color: 'var(--t3)', label: t('userServers.status.disconnected') }
  if (server.value.isSuspended) return { color: 'var(--red)', label: t('userServers.status.suspended') }
  if (server.value.isInstalling) return { color: 'var(--amber)', label: t('userServers.status.installing') }
  const st = liveState.value
  switch (st) {
    case 'running': return { color: 'var(--green)', label: t('userServers.status.running') }
    case 'starting': return { color: 'var(--amber)', label: t('userServers.status.starting') }
    case 'stopping': return { color: 'var(--amber)', label: t('userServers.status.stopping') }
    case 'installing': return { color: 'var(--blue)', label: t('userServers.status.installing') }
    default: return { color: 'var(--t3)', label: t('userServers.status.offline') }
  }
}

// Auto-reload when install completes (Wings status changes from installing → other)
watch(liveState, (newState, oldState) => {
  if (oldState === 'installing' && newState !== 'installing') {
    loadServer()
  }
})

// While the server is installing, Wings does not push stats over the
// console WebSocket, so the resourceStore-derived `liveState` watcher
// above never fires on console-tab. Poll the server detail endpoint
// directly until panel.servers.status flips back to NULL (= isInstalling
// becomes false). Mirrors the UserServersPage list-page pattern.
let installPollTimer: ReturnType<typeof setInterval> | null = null
watch(isInstalling, (val) => {
  if (val && !installPollTimer) {
    installPollTimer = setInterval(loadServer, 5000)
  } else if (!val && installPollTimer) {
    clearInterval(installPollTimer)
    installPollTimer = null
  }
}, { immediate: true })

onBeforeUnmount(() => {
  if (installPollTimer) { clearInterval(installPollTimer); installPollTimer = null }
})

// Kick to console tab when server enters a state where the active tab is
// no longer usable (suspended / installing / stale connection).
watch([stale, isSuspended, isInstalling], ([isStale, isSusp, isInst]) => {
  if ((isStale || isSusp || isInst) && activeTab.value !== 'server-console') {
    router.replace({ name: 'server-console', params: { id: serverId.value } })
  }
})

</script>

<template>
  <LoadingCenter v-if="loading && !server" />

  <template v-else-if="server">
    <PageHeader icon="dns" :title="server.name" :breadcrumbs="headerBreadcrumbs">
      <template #badge>
        <Badge :color="statusBadge().color">
          <StatusDot :status="dotKey" size="sm" />
          {{ statusBadge().label }}
        </Badge>
      </template>
    </PageHeader>

    <div class="page-body">
      <TabSwitcher :tabs="tabs" :modelValue="activeTab" @update:modelValue="onTabChange" />
      <RouterView :key="serverId" />
    </div>
  </template>
</template>

<style scoped>
</style>

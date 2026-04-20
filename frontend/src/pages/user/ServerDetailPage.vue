<script setup lang="ts">
import { ref, onMounted, onUnmounted, provide, computed, watch } from 'vue'
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
import { getEggMeta } from '@/config/eggRegistry'

defineOptions({ name: 'ServerDetailPage' })

const { t } = useI18n({ useScope: 'global' })
const route = useRoute()
const router = useRouter()
const { get, loading } = useApiFetch()
const resourceStore = useServerResourceStore()

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
}

interface ServerResourcesPayload {
  state: string
  isSuspended: boolean
  resources: {
    cpu_absolute?: number
    memory_bytes?: number
    disk_bytes?: number
    network?: {
      rx_bytes?: number
      tx_bytes?: number
    }
    network_rx_bytes?: number
    network_tx_bytes?: number
    uptime?: number
  }
}

const server = ref<ServerDetail | null>(null)
const serverId = computed(() => Number(route.params.id))

async function loadServer() {
  const data = await get<ServerDetail>(`/api/user/servers/${serverId.value}`)
  if (data) server.value = data
}

onMounted(loadServer)
watch(serverId, () => {
  // Clear stale server data immediately so child components (especially console WS)
  // don't mount with the previous server's identity
  server.value = null
  loadServer()
})

// Provide server data to child pages
provide('server', server)
provide('reloadServer', loadServer)

const isInstalling = computed(() => server.value?.isInstalling ?? false)
provide('isInstalling', isInstalling)

const isSuspended = computed(() => server.value?.isSuspended ?? false)

const tabs = computed(() => [
  { key: 'server-console', label: t('userServers.console'), icon: 'terminal' },
  { key: 'server-files', label: t('userServers.files'), icon: 'folder', disabled: isInstalling.value || stale.value || isSuspended.value },
  { key: 'server-settings', label: (() => { const lbl = getEggMeta(server.value?.eggName ?? '').label; return lbl ? t('userServers.settings', { name: lbl }) : t('userServers.settingsGeneric') })(), icon: 'settings', disabled: isInstalling.value || stale.value || isSuspended.value },
  { key: 'server-activity', label: t('activity.title'), icon: 'history', disabled: isInstalling.value || stale.value || isSuspended.value },
])

const activeTab = computed(() => route.name as string)

function onTabChange(key: string) {
  router.push({ name: key, params: { id: serverId.value } })
}

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

// Kick to console tab when connection becomes stale or server gets suspended on non-console tabs
watch([stale, isSuspended], ([isStale, isSusp]) => {
  if ((isStale || isSusp) && activeTab.value !== 'server-console') {
    router.replace({ name: 'server-console', params: { id: serverId.value } })
  }
})

// Poll server data while installing (in case Wings never reports 'installing' state)
let installPollTimer: ReturnType<typeof setInterval> | null = null
watch(isInstalling, (val) => {
  if (val && !installPollTimer) {
    installPollTimer = setInterval(loadServer, 10000)
  } else if (!val && installPollTimer) {
    clearInterval(installPollTimer)
    installPollTimer = null
  }
}, { immediate: true })

// Independent resource polling for non-console tabs (console has WS push)
let resourcePollTimer: ReturnType<typeof setInterval> | null = null

function startResourcePoll() {
  if (resourcePollTimer) return
  resourcePollTimer = setInterval(async () => {
    if (activeTab.value === 'server-console') return
    if (!server.value) return
    try {
      const data = await get<ServerResourcesPayload>(
        `/api/user/servers/${server.value.id}/resources`,
      )
      if (data) {
        const r = data.resources || {}
        resourceStore.updateOne(server.value.id, {
          state: data.state,
          isSuspended: data.isSuspended,
          cpu: r.cpu_absolute ?? 0,
          memoryBytes: r.memory_bytes ?? 0,
          diskBytes: r.disk_bytes ?? 0,
          networkRx: r.network?.rx_bytes ?? r.network_rx_bytes ?? 0,
          networkTx: r.network?.tx_bytes ?? r.network_tx_bytes ?? 0,
          uptime: r.uptime ?? 0,
        })
      } else {
        // Request failed — mark stale
        const existing = resourceStore.resources[server.value.id]
        if (existing) existing.stale = true
      }
    } catch {
      const existing = resourceStore.resources[server.value!.id]
      if (existing) existing.stale = true
    }
  }, 10_000)
}

onMounted(startResourcePoll)

onUnmounted(() => {
  if (installPollTimer) clearInterval(installPollTimer)
  if (resourcePollTimer) { clearInterval(resourcePollTimer); resourcePollTimer = null }
})
</script>

<template>
  <LoadingCenter v-if="loading && !server" />

  <template v-else-if="server">
    <PageHeader icon="dns" :title="server.name">
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

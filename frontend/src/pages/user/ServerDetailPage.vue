<script setup lang="ts">
import { ref, onMounted, provide, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useApiFetch } from '@/composables/useApiFetch'
import { useServerResourceStore } from '@/stores/serverResources'
import PageHeader from '@/components/layout/PageHeader.vue'
import TabSwitcher from '@/components/ui/TabSwitcher.vue'
import LoadingCenter from '@/components/ui/LoadingCenter.vue'
import StatusDot from '@/components/ui/StatusDot.vue'
import Badge from '@/components/ui/Badge.vue'

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
  limits: { memory: number; disk: number; cpu: number }
  allocation: { ip: string | null; port: number | null }
  node: { fqdn: string | null }
  expirationDate: string | null
  daysLeft: number | null
  address: string | null
}

const server = ref<ServerDetail | null>(null)
const serverId = computed(() => Number(route.params.id))

async function loadServer() {
  const data = await get<ServerDetail>(`/api/user/servers/${serverId.value}`)
  if (data) server.value = data
}

onMounted(loadServer)
watch(serverId, loadServer)

// Provide server data to child pages
provide('server', server)
provide('reloadServer', loadServer)

const isInstalling = computed(() => server.value?.isInstalling ?? false)
provide('isInstalling', isInstalling)

const tabs = computed(() => [
  { key: 'server-console', label: t('userServers.console'), icon: 'terminal' },
  { key: 'server-files', label: t('userServers.files'), icon: 'folder', disabled: isInstalling.value },
  { key: 'server-settings', label: t('userServers.settings'), icon: 'settings', disabled: isInstalling.value },
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

function statusDotKey(): 'running' | 'loading' | 'error' | 'stopped' {
  if (!server.value) return 'stopped'
  if (server.value.isSuspended) return 'error'
  if (server.value.isInstalling) return 'loading'
  const st = liveState.value
  if (st === 'running') return 'running'
  if (st === 'starting' || st === 'stopping' || st === 'installing') return 'loading'
  return 'stopped'
}

function statusBadge(): { color: string; label: string } {
  if (!server.value) return { color: 'var(--t3)', label: t('userServers.status.offline') }
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
</script>

<template>
  <LoadingCenter v-if="loading && !server" />

  <template v-else-if="server">
    <PageHeader icon="dns" :title="server.name">
      <template #badge>
        <Badge :color="statusBadge().color">
          <StatusDot :status="statusDotKey()" size="sm" />
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

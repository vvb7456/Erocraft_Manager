<script setup lang="ts">
// C6 — host detail container.
// Loads the host once and provides it to child panes via inject.
// TabSwitcher mirrors the active route name (host-overview / host-setting /
// host-activity); navigating away clicks router.push so deep-links work.
import { computed, onBeforeUnmount, provide, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useApiFetch } from '@/composables/useApiFetch'
import PageHeader from '@/components/layout/PageHeader.vue'
import Badge from '@/components/ui/Badge.vue'
import StatusDot from '@/components/ui/StatusDot.vue'
import TabSwitcher from '@/components/ui/TabSwitcher.vue'
import LoadingCenter from '@/components/ui/LoadingCenter.vue'
import type { HostDetail, HostStatusKey } from '@/types/host'

defineOptions({ name: 'HostDetailPage' })

const { t } = useI18n({ useScope: 'global' })
const route = useRoute()
const router = useRouter()
const { get } = useApiFetch()

const hostId = computed(() => Number(route.params.id))
const host = ref<HostDetail | null>(null)
const loading = ref(false)
const statusLive = ref<Pick<HostDetail, 'enabled' | 'inbound_reachable' | 'last_seen_at'> | null>(null)

provide('hostDetail', host)
provide('hostId', hostId)

function classifyStatus(h: Pick<HostDetail, 'enabled' | 'inbound_reachable' | 'last_seen_at'> | null): HostStatusKey {
  if (!h) return 'offline'
  if (!h.enabled) return 'disabled'
  if (!h.inbound_reachable && !h.last_seen_at) return 'unconfigured'
  if (!h.inbound_reachable) return 'offline'
  return 'online'
}

function statusDotKey(s: HostStatusKey): 'running' | 'error' | 'stopped' {
  if (s === 'online') return 'running'
  if (s === 'offline') return 'error'
  return 'stopped'
}

const statusKey = computed(() => classifyStatus(statusLive.value ?? host.value))
const statusBadgeColor = computed(() => {
  if (statusKey.value === 'online') return 'var(--green)'
  if (statusKey.value === 'offline') return 'var(--red)'
  return 'var(--t3)'
})

async function loadHost(silent = false) {
  if (!Number.isFinite(hostId.value)) return
  if (!silent) loading.value = true
  try {
    const data = await get<HostDetail>(`/api/admin/hosts/${hostId.value}`)
    if (data) {
      host.value = data
      statusLive.value = {
        enabled: data.enabled,
        inbound_reachable: data.inbound_reachable,
        last_seen_at: data.last_seen_at,
      }
    }
  } finally {
    if (!silent) loading.value = false
  }
}

async function refreshHostStatus() {
  if (!Number.isFinite(hostId.value)) return
  const data = await get<HostDetail>(`/api/admin/hosts/${hostId.value}`, { silent: true })
  if (!data) return
  statusLive.value = {
    enabled: data.enabled,
    inbound_reachable: data.inbound_reachable,
    last_seen_at: data.last_seen_at,
  }
}

let statusTimer: number | null = null
function stopStatusPolling() {
  if (statusTimer !== null) {
    clearInterval(statusTimer)
    statusTimer = null
  }
}

function startStatusPolling() {
  stopStatusPolling()
  statusTimer = window.setInterval(() => {
    void refreshHostStatus()
  }, 5000)
}

provide('reloadHost', () => loadHost(true))

const tabs = computed(() => {
  const items: Array<{ key: string; label: string; icon: string }> = [
    { key: 'host-overview', label: t('hosts.detail.tabs.overview'), icon: 'dashboard' },
    { key: 'host-setting',  label: t('hosts.detail.tabs.setting'),  icon: 'settings' },
  ]
  if (host.value?.kind === 'wings_node') {
    items.push({ key: 'host-wings', label: t('hosts.detail.tabs.wings'), icon: 'settings_applications' })
    items.push({ key: 'host-allocations', label: t('hosts.detail.tabs.allocations'), icon: 'lan' })
    items.push({ key: 'host-tunnel', label: t('hosts.detail.tabs.tunnel'), icon: 'cloud' })
  }
  items.push({ key: 'host-activity', label: t('hosts.detail.tabs.activity'), icon: 'history' })
  return items
})

const activeTab = computed(() => {
  const name = route.name as string | undefined
  return name && tabs.value.some(tab => tab.key === name) ? name : 'host-overview'
})

const activeTabLabel = computed(() =>
  tabs.value.find(tab => tab.key === activeTab.value)?.label ?? t('hosts.detail.tabs.overview'),
)

const headerBreadcrumbs = computed(() => [
  { label: t('hosts.title'), to: { name: 'hosts' } },
  {
    label: host.value?.name || t('hosts.detail.title'),
    to: { name: 'host-overview', params: { id: hostId.value } },
  },
  { label: activeTabLabel.value },
])

// Non-monitor host tabs follow "enter-refresh" semantics: load once when
// entering a tab (or switching host id), then stay idle unless an explicit
// action triggers reloadHost().
watch(
  [hostId, activeTab],
  async ([id], prev) => {
    if (!Number.isFinite(id)) return
    const prevId = prev?.[0]
    const changedHost = id !== prevId
    if (changedHost) {
      host.value = null
      statusLive.value = null
    }
    await loadHost(changedHost)
    await refreshHostStatus()
    startStatusPolling()
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  stopStatusPolling()
})

function onTabChange(key: string) {
  router.push({ name: key, params: { id: hostId.value } })
}
</script>

<template>
  <LoadingCenter v-if="loading && !host" />

  <template v-else>
    <PageHeader
      icon="dvr"
      :title="host?.name || t('hosts.detail.title')"
      :breadcrumbs="headerBreadcrumbs"
    >
      <template v-if="host" #badge>
        <Badge :color="statusBadgeColor" size="sm">
          <StatusDot :status="statusDotKey(statusKey)" size="sm" />
          {{ t(`hosts.status.${statusKey}`) }}
        </Badge>
      </template>
    </PageHeader>

    <div class="page-body">
      <TabSwitcher :tabs="tabs" :modelValue="activeTab" @update:modelValue="onTabChange" />
      <RouterView :key="hostId" />
    </div>
  </template>
</template>

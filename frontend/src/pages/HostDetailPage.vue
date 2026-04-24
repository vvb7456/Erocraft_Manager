<script setup lang="ts">
// C6 — host detail container.
// Loads the host once and provides it to child panes via inject.
// TabSwitcher mirrors the active route name (host-overview / host-setting /
// host-activity); navigating away clicks router.push so deep-links work.
import { computed, onBeforeUnmount, onMounted, provide, ref, watch } from 'vue'
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

provide('hostDetail', host)
provide('hostId', hostId)

function classifyStatus(h: HostDetail | null): HostStatusKey {
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

const statusKey = computed(() => classifyStatus(host.value))
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
    if (data) host.value = data
  } finally {
    if (!silent) loading.value = false
  }
}

provide('reloadHost', () => loadHost(true))

let pollTimer: number | null = null
onMounted(() => {
  loadHost()
  // 30s passive refresh while operator is on this page; child panes own
  // their own faster polling for live charts.
  pollTimer = window.setInterval(() => loadHost(true), 30_000)
})
onBeforeUnmount(() => {
  if (pollTimer !== null) clearInterval(pollTimer)
})

// Reload when navigating between hosts (e.g. from list directly to another
// host id without unmounting this page).
watch(hostId, () => {
  host.value = null
  loadHost()
})

const tabs = computed(() => {
  const items: Array<{ key: string; label: string; icon: string }> = [
    { key: 'host-overview', label: t('hosts.detail.tabs.overview'), icon: 'dashboard' },
    { key: 'host-setting',  label: t('hosts.detail.tabs.setting'),  icon: 'settings' },
  ]
  if (host.value?.kind === 'wings_node') {
    items.push({ key: 'host-wings', label: t('hosts.detail.tabs.wings'), icon: 'settings_applications' })
    items.push({ key: 'host-allocations', label: t('hosts.detail.tabs.allocations'), icon: 'lan' })
  }
  items.push({ key: 'host-activity', label: t('hosts.detail.tabs.activity'), icon: 'history' })
  return items
})

const activeTab = computed(() => {
  const name = route.name as string | undefined
  return name && tabs.value.some(tab => tab.key === name) ? name : 'host-overview'
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

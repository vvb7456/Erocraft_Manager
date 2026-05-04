<script setup lang="ts">
import { ref, inject, computed, watch, onMounted, onBeforeUnmount, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useServerResourceStore } from '@/stores/serverResources'
import { hasWebUi } from '@/config/eggRegistry'
import { getStatusDotKey, getStatusColor } from '@/utils/status'
import { useConsoleWs } from '@/composables/useConsoleWs'
import BaseCard from '@/components/ui/BaseCard.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import StatusDot from '@/components/ui/StatusDot.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import Spinner from '@/components/ui/Spinner.vue'
import PowerControls from '@/components/server/PowerControls.vue'
import ResourceStats from '@/components/server/ResourceStats.vue'
import ServerAddress from '@/components/server/ServerAddress.vue'
import { useRenewFlow } from '@/composables/useRenewFlow'
import CreateOrderModal from '@/components/CreateOrderModal.vue'
import 'xterm/css/xterm.css'

defineOptions({ name: 'ServerConsolePage' })

const { t } = useI18n({ useScope: 'global' })
const resourceStore = useServerResourceStore()

interface ServerDetail {
  id: number; uuid: string; nodeId: number; isSuspended: boolean
  name: string
  eggId: number; eggName: string; status: string | null; address: string | null
  limits: { memory: number; disk: number; cpu: number }
  expirationDate: string | null; daysLeft: number | null
  planId: number | null
  hasUpgradeOptions: boolean
  tunnel: { status: string; hostname: string; customSubdomain: string | null; lastError: string | null } | null
  hostTunnelReady: boolean
}

const server = inject<Ref<ServerDetail | null>>('server')!
const isInstalling = inject<Ref<boolean>>('isInstalling', ref(false))

// ── Renewal flow ──
const { openRenew, loading: renewLoading } = useRenewFlow()
const canRenew = computed(() => !!server.value?.planId)
async function onRenew() {
  if (!server.value || !server.value.planId) return
  await openRenew({
    serverId: server.value.id,
    serverName: server.value.name,
    planId: server.value.planId,
  })
}

// ── Upgrade flow ──
const upgradeModalOpen = ref(false)
function onUpgrade() {
  upgradeModalOpen.value = true
}

// ── Resource state ──
const res = computed(() => server.value ? resourceStore.resources[server.value.id] : null)
const state = computed(() => res.value?.state ?? 'offline')
const cpuPercent = computed(() => res.value?.cpu ?? 0)
const memoryBytes = computed(() => res.value?.memoryBytes ?? 0)
const diskBytes = computed(() => res.value?.diskBytes ?? 0)
const networkRx = computed(() => res.value?.networkRx ?? 0)
const networkTx = computed(() => res.value?.networkTx ?? 0)
const uptimeMs = computed(() => res.value?.uptime ?? 0)

// ── Status display ──
const statusColor = computed(() =>
  getStatusColor(state.value, !!server.value?.isSuspended, isInstalling.value, server.value ? resourceStore.isStale(server.value.id) : false),
)

const statusText = computed(() => {
  if (server.value && resourceStore.isStale(server.value.id)) return t('userServers.status.disconnected')
  if (server.value?.isSuspended) return t('userServers.status.suspended')
  if (isInstalling.value) return t('userServers.status.installing')
  const s = state.value
  return t(`userServers.status.${s === 'stopped' ? 'offline' : s}`)
})

const dotKey = computed(() =>
  getStatusDotKey(state.value, !!server.value?.isSuspended, isInstalling.value, server.value ? resourceStore.isStale(server.value.id) : false),
)

// ── Lifecycle display ──
const expirationText = computed(() => {
  const s = server.value
  if (!s) return ''
  if (s.expirationDate === null) return t('userServers.permanent')
  if (s.daysLeft === null) return ''
  if (s.daysLeft < 0) return t('userServers.expired')
  if (s.daysLeft === 0) return t('userServers.expired')
  return t('userServers.daysLeft', { n: s.daysLeft })
})

const expirationColor = computed(() => {
  const s = server.value
  if (!s || s.expirationDate === null) return 'var(--t2)' // permanent
  if (s.daysLeft === null) return 'var(--t2)'
  if (s.daysLeft <= 0) return 'var(--red)'
  if (s.daysLeft <= 7) return 'var(--amber)'
  return 'var(--green)'
})

// ── Server address ──
const isWebEgg = computed(() => server.value ? hasWebUi(server.value.eggName) : false)
const tunnelHostname = computed(() =>
  server.value?.tunnel?.status === 'active' ? server.value.tunnel.hostname : undefined,
)
const serverUrl = computed(() => {
  if (tunnelHostname.value) return `https://${tunnelHostname.value}`
  return server.value?.address ? `http://${server.value.address}` : null
})

// ── Console ──
const termEl = ref<HTMLElement | null>(null)
const serverId = computed(() => server.value?.id)

const {
  wsConnected, connecting, disconnected, reconnecting, reconnectAttempt, reconnectCountdown,
  suspended,
  commandInput,
  connect: connectConsole, sendCommand, handleCommandKey,
  loadHistory, fit, dispose, clearTerminal, manualReconnect,
} = useConsoleWs({ serverId, termEl })

// ── Resize ──
let resizeObserver: ResizeObserver | null = null

// Auto-reconnect when resource polling recovers (stale → non-stale)
const isStale = computed(() => server.value ? resourceStore.isStale(server.value.id) : false)
watch(isStale, (newVal, oldVal) => {
  if (oldVal && !newVal && disconnected.value) {
    manualReconnect()
  }
})

// Reload server data when suspended state changes (so DetailPage badge updates)
const reloadServer = inject<() => Promise<void>>('reloadServer')
watch(suspended, () => {
  if (reloadServer) reloadServer()
})

// ── Offline: clear terminal + show EmptyState ──
const isServerOff = computed(() => state.value === 'offline' || state.value === 'stopped')

// Clear terminal on any transition: entering offline (hide stale output) and
// leaving offline (remove old session logs before fresh output arrives).
watch(isServerOff, () => {
  clearTerminal()
})

onMounted(() => {
  loadHistory()
  connectConsole()
  resizeObserver = new ResizeObserver(() => fit())
  if (termEl.value) resizeObserver.observe(termEl.value)
})

onBeforeUnmount(() => {
  dispose()
  if (resizeObserver) { resizeObserver.disconnect(); resizeObserver = null }
})
</script>

<template>
  <div class="console-page">
    <!-- ═══ Mobile top: Address + Power (above terminal on mobile) ═══ -->
    <div class="mobile-top">
      <!-- Address -->
      <BaseCard v-if="server?.address" variant="bg3" class="mobile-card">
        <ServerAddress
          :addresses="[server.address]"
          :tunnel-hostname="tunnelHostname"
          :open-url="isWebEgg ? serverUrl! : undefined"
          :open-disabled="state !== 'running'"
          :egg-name="server.eggName"
          compact
        />
      </BaseCard>

      <!-- Lifecycle (expiration + renew) -->
      <BaseCard variant="bg3" class="mobile-card">
        <div class="mobile-lifecycle-card">
          <div class="mobile-lifecycle-card__head">
            <MsIcon name="schedule" class="section-icon" />
            <span class="mobile-lifecycle-label">{{ t('userServers.expiration') }}：</span>
            <span v-if="server?.expirationDate" class="lifecycle-value">
              {{ server.expirationDate }}
              <span class="lifecycle-remaining" :style="{ color: expirationColor }">（{{ expirationText }}）</span>
            </span>
            <span v-else class="lifecycle-value">{{ expirationText }}</span>
          </div>
          <BaseButton
            size="sm"
            :disabled="!canRenew"
            :loading="renewLoading"
            :title="canRenew ? '' : t('userServers.renewFlow.noPlan')"
            @click="onRenew"
          >
            <MsIcon name="autorenew" size="xs" /> {{ t('userServers.renew') }}
          </BaseButton>
          <BaseButton
            size="sm"
            :disabled="!server?.hasUpgradeOptions"
            @click="onUpgrade"
          >
            <MsIcon name="arrow_upward" size="xs" /> {{ t('userServers.upgrade.button') }}
          </BaseButton>
        </div>
      </BaseCard>

      <!-- Power controls -->
      <BaseCard variant="bg3" class="mobile-card">
        <PowerControls
          v-if="server"
          :server-id="server.id"
          :state="state"
          :is-suspended="server.isSuspended"
          :is-installing="isInstalling"
          :disabled="!wsConnected || reconnecting"
          :disabled-reason="t('userServers.consoleDisconnected')"
          :egg-name="server.eggName"
          layout="row"
        />
      </BaseCard>
    </div>

    <!-- ═══ Main: Terminal ═══ -->
    <div class="console-main">
      <BaseCard class="terminal-card">
        <!-- Connecting overlay -->
        <div v-if="connecting && !wsConnected" class="terminal-overlay">
          <Spinner />
        </div>
        <!-- Suspended overlay -->
        <div v-else-if="suspended" class="terminal-overlay terminal-overlay--reconnect">
          <MsIcon name="block" class="reconnect-icon" />
          <span class="reconnect-text">{{ t('userServers.status.suspended') }}</span>
          <span class="reconnect-hint">{{ t('userServers.suspendedHint') }}</span>
          <BaseButton
            size="sm"
            variant="primary"
            class="overlay-renew-btn"
            :disabled="!canRenew"
            :loading="renewLoading"
            :title="canRenew ? '' : t('userServers.renewFlow.noPlan')"
            @click="onRenew"
          >
            <MsIcon name="autorenew" size="xs" /> {{ t('userServers.renew') }}
          </BaseButton>
        </div>
        <!-- Reconnecting overlay -->
        <div v-else-if="reconnecting" class="terminal-overlay terminal-overlay--reconnect">
          <MsIcon name="cloud_off" class="reconnect-icon" />
          <span class="reconnect-text">{{ t('userServers.reconnectFailed') }}</span>
          <span class="reconnect-hint">{{ t('userServers.reconnecting', { seconds: reconnectCountdown, current: reconnectAttempt, max: 5 }) }}</span>
          <Spinner size="sm" />
        </div>
        <!-- Disconnected (all retries exhausted or initial connect failed) -->
        <div v-else-if="disconnected && !wsConnected" class="terminal-overlay terminal-overlay--reconnect">
          <MsIcon name="cloud_off" class="reconnect-icon" />
          <span class="reconnect-text">{{ t('userServers.reconnectFailed') }}</span>
          <span class="reconnect-hint">{{ t('userServers.reconnectHint') }}</span>
          <BaseButton size="sm" variant="primary" @click="manualReconnect">
            <MsIcon name="refresh" /> {{ t('userServers.consoleReconnect') }}
          </BaseButton>
        </div>
        <!-- Server offline -->
        <div v-else-if="isServerOff && wsConnected" class="terminal-overlay terminal-overlay--reconnect">
          <EmptyState icon="power_settings_new" :title="t('userServers.status.offline')" :message="t('userServers.serverOfflineHint')" density="compact" />
        </div>
        <!-- Terminal -->
        <div ref="termEl" class="terminal-container" />
        <!-- Command input -->
        <div class="command-row">
          <span class="prompt">&gt;</span>
          <input
            v-model="commandInput"
            class="command-input"
            :placeholder="t('userServers.commandPlaceholder')"
            :disabled="!wsConnected || isInstalling || reconnecting || isServerOff"
            @keydown.enter="sendCommand"
            @keydown="handleCommandKey"
          />
        </div>
      </BaseCard>
    </div>

    <!-- ═══ Sidebar (desktop only) ═══ -->
    <aside class="console-sidebar">
      <!-- Status indicator -->
      <div class="status-card" :style="{ '--status-color': statusColor }">
        <StatusDot :status="dotKey" />
        <span class="status-label">{{ statusText }}</span>
      </div>

      <!-- Lifecycle card -->
      <BaseCard variant="bg3" class="sidebar-card">
        <div class="sidebar-section-title">
          <MsIcon name="schedule" class="section-icon" />
          {{ t('userServers.expiration') }}
        </div>
        <!-- Expiration info -->
        <div class="lifecycle-row">
          <span v-if="server?.expirationDate" class="lifecycle-value">
            {{ server.expirationDate }}
            <span class="lifecycle-remaining" :style="{ color: expirationColor }">（{{ expirationText }}）</span>
          </span>
          <span v-else class="lifecycle-value">{{ expirationText }}</span>
          <BaseButton
            size="sm"
            class="lifecycle-renew-btn"
            :disabled="!canRenew"
            :loading="renewLoading"
            :title="canRenew ? '' : t('userServers.renewFlow.noPlan')"
            @click="onRenew"
          >
            <MsIcon name="autorenew" size="xs" /> {{ t('userServers.renew') }}
          </BaseButton>
        </div>
      </BaseCard>

      <!-- Address card -->
      <BaseCard v-if="server?.address" variant="bg3" class="sidebar-card">
        <div class="sidebar-section-title">
          <MsIcon name="language" class="section-icon" />
          {{ t('userServers.address.label') }}
        </div>
        <ServerAddress
          :addresses="[server.address]"
          :tunnel-hostname="tunnelHostname"
          :open-url="isWebEgg ? serverUrl! : undefined"
          :open-disabled="state !== 'running'"
          :egg-name="server.eggName"
        />
      </BaseCard>

      <!-- Power controls -->
      <BaseCard variant="bg3" class="sidebar-card">
        <div class="sidebar-section-title">
          <MsIcon name="power_settings_new" class="section-icon" />
          {{ t('userServers.power.title') }}
        </div>
        <PowerControls
          v-if="server"
          :server-id="server.id"
          :state="state"
          :is-suspended="server.isSuspended"
          :is-installing="isInstalling"
          :disabled="!wsConnected || reconnecting"
          :disabled-reason="t('userServers.consoleDisconnected')"
          :egg-name="server.eggName"
        />
      </BaseCard>

      <!-- Server info -->
      <BaseCard variant="bg3" class="sidebar-card">
        <div class="sidebar-section-title">
          <MsIcon name="info" class="section-icon" />
          {{ t('userServers.serverInfo') }}
        </div>
        <div class="info-preset">
          <MsIcon name="widgets" class="info-preset-icon" />
          <span class="info-preset-label">{{ t('userServers.table.preset') }}</span>
          <span class="info-preset-value">{{ server?.eggName ?? '—' }}</span>
        </div>
        <ResourceStats
          v-if="server"
          :cpu-percent="cpuPercent"
          :memory-bytes="memoryBytes"
          :disk-bytes="diskBytes"
          :network-rx="networkRx"
          :network-tx="networkTx"
          :uptime-ms="uptimeMs"
          :limits="server.limits"
        />
      </BaseCard>
    </aside>

    <!-- ═══ Mobile bottom: Resource stats ═══ -->
    <div class="mobile-bottom">
      <BaseCard variant="bg3" class="mobile-card">
        <!-- Preset -->
        <div class="mobile-preset">
          <MsIcon name="widgets" class="section-icon" />
          <span class="mobile-preset-label">{{ t('userServers.table.preset') }}：</span>
          <span class="mobile-preset-value">{{ server?.eggName ?? '—' }}</span>
        </div>
        <!-- Stats -->
        <ResourceStats
          v-if="server"
          :cpu-percent="cpuPercent"
          :memory-bytes="memoryBytes"
          :disk-bytes="diskBytes"
          :network-rx="networkRx"
          :network-tx="networkTx"
          :uptime-ms="uptimeMs"
          :limits="server.limits"
          layout="mobile"
        />
      </BaseCard>
    </div>
  </div>

  <!-- Upgrade Plan Modal -->
  <CreateOrderModal
    v-if="server"
    v-model="upgradeModalOpen"
    :plan="null"
    mode="upgrade"
    :target-server-id="server.id"
    :server-name="server.name"
  />
</template>

<style scoped>
/* ═══ Page layout ═══ */
.console-page {
  display: grid;
  grid-template-columns: 1fr 4fr;
  gap: var(--sp-4);
  align-items: start;
}

.console-main {
  min-width: 0;
  grid-column: 2;
  grid-row: 1;
}

.console-sidebar {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  grid-column: 1;
  grid-row: 1;
}

.mobile-top,
.mobile-bottom {
  display: none;
}

/* ── Mobile lifecycle card ── */
.mobile-lifecycle-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  flex-wrap: wrap;
}

.mobile-lifecycle-card__head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex: 1;
  min-width: 0;
  flex-wrap: wrap;
}

.mobile-lifecycle-label {
  font-size: var(--text-sm);
  color: var(--t2);
  white-space: nowrap;
}

/* ═══ Status card ═══ */
.status-card {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-3);
  background: color-mix(in srgb, var(--status-color, var(--t3)) 8%, var(--bg3));
  border: 1px solid color-mix(in srgb, var(--status-color, var(--t3)) 20%, var(--bd));
  border-radius: var(--r-md);
}

.status-label {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--status-color, var(--t3));
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

/* ═══ Terminal card ═══ */
.terminal-card {
  position: relative;
  padding: 0 !important;
  overflow: hidden;
  border-radius: var(--r-lg);
}

.terminal-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--sp-3);
  background: rgba(11, 15, 15, 0.85);
  z-index: 2;
}

.terminal-overlay--reconnect {
  background: rgba(11, 15, 15, 0.92);
}

.reconnect-icon {
  font-size: 2rem;
  color: var(--t3);
}

.reconnect-text {
  font-size: var(--text-sm);
  color: var(--t2);
}

.reconnect-hint {
  font-size: var(--text-xs);
  color: var(--t3);
}

.overlay-renew-btn {
  margin-top: var(--sp-3);
}

.terminal-container {
  height: clamp(300px, 55vh, 700px);
  overflow: hidden;
}

.terminal-container :deep(.xterm) {
  height: 100%;
  padding: var(--sp-2) var(--sp-3);
}

.terminal-container :deep(.xterm-viewport) {
  overflow-y: auto !important;
}

.command-row {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-2) var(--sp-3);
  border-top: 1px solid var(--bd);
  background: var(--bg-in);
}

.prompt {
  color: var(--ac);
  font-family: 'IBM Plex Mono', monospace;
  font-weight: 600;
  font-size: var(--text-sm);
}

.command-input {
  flex: 1;
  background: none;
  border: none;
  outline: none;
  color: var(--t1);
  font-family: 'IBM Plex Mono', monospace;
  font-size: var(--text-sm);
}

.command-input::placeholder {
  color: var(--t3);
}

.command-input:disabled {
  opacity: 0.5;
}

/* ═══ Sidebar cards ═══ */
.sidebar-card {
  padding: var(--sp-3) !important;
}

.sidebar-section-title {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--t3);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: var(--sp-3);
}

.section-icon {
  font-size: 1rem;
  color: var(--t3);
}

/* ── Server info: preset row ── */
.info-preset {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding-bottom: var(--sp-3);
  margin-bottom: var(--sp-3);
  border-bottom: 1px solid var(--bd);
}

.info-preset-icon {
  font-size: 1rem;
  color: var(--t3);
}

.info-preset-label {
  font-size: var(--text-sm);
  color: var(--t2);
}

.info-preset-value {
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--t1);
  margin-left: auto;
}

/* ── Mobile preset ── */
.mobile-preset {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding-bottom: var(--sp-2);
  margin-bottom: var(--sp-2);
  border-bottom: 1px solid var(--bd);
}

.mobile-preset-label {
  font-size: var(--text-sm);
  color: var(--t2);
  white-space: nowrap;
}

.mobile-preset-value {
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--t1);
}

/* ── Lifecycle ── */
.lifecycle-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  flex-wrap: wrap;
}

.lifecycle-value {
  font-family: 'IBM Plex Mono', monospace;
  font-size: var(--text-sm);
  color: var(--t1);
}

.lifecycle-remaining {
  font-family: 'IBM Plex Sans', sans-serif;
  font-size: var(--text-xs);
  font-weight: 600;
}

.lifecycle-renew-btn {
  flex-shrink: 0;
}

/* ═══ Mobile layout ═══ */
@media (max-width: 1023px) {
  .console-page {
    display: flex;
    flex-direction: column;
    gap: var(--sp-3);
    align-items: stretch;
  }

  .console-sidebar {
    display: none;
  }

  .mobile-top {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
    order: -1;
  }

  .mobile-bottom {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
  }

  .mobile-card {
    padding: var(--sp-3) !important;
  }

  .terminal-container {
    height: clamp(250px, 45vh, 500px);
  }
}
</style>

<script setup lang="ts">
import { ref, inject, computed, onMounted, onBeforeUnmount, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'
import { useServerResourceStore } from '@/stores/serverResources'
import { WEB_ACCESSIBLE_EGGS } from '@/utils/constants'
import { fmtBytes } from '@/utils/format'
import BaseCard from '@/components/ui/BaseCard.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import UsageBar from '@/components/ui/UsageBar.vue'
import StatusDot from '@/components/ui/StatusDot.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import Spinner from '@/components/ui/Spinner.vue'
import 'xterm/css/xterm.css'

defineOptions({ name: 'ServerConsolePage' })

const { t } = useI18n({ useScope: 'global' })
const { get, post } = useApiFetch()
const { toast } = useToast()
const { confirm } = useConfirm()
const resourceStore = useServerResourceStore()

interface ServerDetail {
  id: number; uuid: string; nodeId: number; isSuspended: boolean
  eggId: number; status: string | null; address: string | null
  limits: { memory: number; disk: number; cpu: number }
  expirationDate: string | null; daysLeft: number | null
}

const server = inject<Ref<ServerDetail | null>>('server')!
const isInstalling = inject<Ref<boolean>>('isInstalling', ref(false))

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
const statusColor = computed(() => {
  if (server.value?.isSuspended) return 'var(--red)'
  const s = state.value
  if (s === 'running') return 'var(--green)'
  if (s === 'starting' || s === 'stopping') return 'var(--amber)'
  return 'var(--t3)'
})

const statusText = computed(() => {
  if (server.value?.isSuspended) return t('userServers.status.suspended')
  const s = state.value
  return t(`userServers.status.${s === 'stopped' ? 'offline' : s}`)
})

function statusDotKey(): 'running' | 'loading' | 'error' | 'stopped' {
  if (server.value?.isSuspended) return 'error'
  const s = state.value
  if (s === 'running') return 'running'
  if (s === 'starting' || s === 'stopping' || s === 'installing') return 'loading'
  return 'stopped'
}

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
const isWebEgg = computed(() => server.value ? WEB_ACCESSIBLE_EGGS.includes(server.value.eggId) : false)
const serverUrl = computed(() => server.value?.address ? `http://${server.value.address}` : null)
const copied = ref(false)

async function copyAddress() {
  if (!server.value?.address) return
  try {
    await navigator.clipboard.writeText(server.value.address)
    copied.value = true
    setTimeout(() => { copied.value = false }, 2000)
  } catch { /* clipboard API not available */ }
}

function openSillyTavern() {
  if (serverUrl.value) window.open(serverUrl.value, '_blank')
}

// ── Console state ──
const termEl = ref<HTMLElement | null>(null)
const commandInput = ref('')
const wsConnected = ref(false)
const connecting = ref(false)
const disconnected = ref(false)

let ws: WebSocket | null = null
let term: any = null
let fitAddon: any = null

// ── Command history ──
const HISTORY_MAX = 32
let commandHistory: string[] = []
let historyIndex = -1

function loadHistory() {
  try {
    const raw = sessionStorage.getItem(`console_history_${server.value?.id}`)
    commandHistory = raw ? JSON.parse(raw) : []
  } catch { commandHistory = [] }
}

function saveHistory() {
  try {
    sessionStorage.setItem(`console_history_${server.value?.id}`, JSON.stringify(commandHistory))
  } catch { /* quota exceeded */ }
}

// ── WebSocket console ──
async function connectConsole() {
  if (!server.value || connecting.value) return
  connecting.value = true
  disconnected.value = false

  const data = await get<{ token: string; socket: string }>(
    `/api/user/servers/${server.value.id}/console`,
    { silent: true },
  )
  if (!data) {
    connecting.value = false
    disconnected.value = true
    toast(t('userServers.consoleFailed'), 'error')
    return
  }

  const [{ Terminal }, { FitAddon }, { WebLinksAddon }] = await Promise.all([
    import('xterm'),
    import('xterm-addon-fit'),
    import('xterm-addon-web-links'),
  ])

  if (term) term.dispose()

  term = new Terminal({
    disableStdin: true,
    cursorBlink: false,
    cursorStyle: 'underline',
    cursorInactiveStyle: 'none',
    fontSize: 13,
    fontFamily: '"IBM Plex Mono", monospace',
    theme: {
      background: '#0b0f0f',
      foreground: '#e4ece8',
      cursor: '#14b8a6',
      selectionBackground: '#263434',
      black: '#0b0f0f',
      red: '#ef6060',
      green: '#34d399',
      yellow: '#f59e0b',
      blue: '#60a5fa',
      magenta: '#c084fc',
      cyan: '#2dd4bf',
      white: '#e4ece8',
      brightBlack: '#5a706a',
      brightRed: '#ef6060',
      brightGreen: '#34d399',
      brightYellow: '#f59e0b',
      brightBlue: '#60a5fa',
      brightMagenta: '#c084fc',
      brightCyan: '#2dd4bf',
      brightWhite: '#ffffff',
    },
    scrollback: 5000,
    convertEol: true,
    allowProposedApi: true,
  })

  fitAddon = new FitAddon()
  const webLinksAddon = new WebLinksAddon()
  term.loadAddon(fitAddon)
  term.loadAddon(webLinksAddon)

  // Ctrl+C: copy selected text
  term.attachCustomKeyEventHandler((e: KeyboardEvent) => {
    if (e.type !== 'keydown') return true
    if ((e.ctrlKey || e.metaKey) && e.key === 'c') {
      const selection = term!.getSelection()
      if (selection) {
        navigator.clipboard.writeText(selection)
        term!.clearSelection()
      }
      return false
    }
    return true
  })

  term.open(termEl.value!)
  fitAddon.fit()

  ws = new WebSocket(data.socket)

  ws.onopen = () => {
    ws!.send(JSON.stringify({ event: 'auth', args: [data.token] }))
  }

  ws.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data)
      switch (msg.event) {
        case 'auth success':
          wsConnected.value = true
          connecting.value = false
          ws!.send(JSON.stringify({ event: 'send logs', args: [null] }))
          break
        case 'console output':
        case 'install output':
          term.writeln(msg.args[0])
          break
        case 'daemon message':
          term.writeln('\x1b[1m\x1b[33m' + msg.args[0] + '\x1b[0m')
          break
        case 'daemon error':
          term.writeln('\x1b[1m\x1b[41m' + msg.args[0] + '\x1b[0m')
          break
        case 'status':
          if (server.value) {
            resourceStore.updateOne(server.value.id, { state: msg.args[0] })
            // Write status change to terminal
            term.writeln('\x1b[1m\x1b[33m* ' + t('userServers.status.' + msg.args[0]) + '\x1b[0m')
          }
          break
        case 'stats':
          try {
            const stats = JSON.parse(msg.args[0])
            if (server.value) {
              resourceStore.updateOne(server.value.id, {
                cpu: stats.cpu_absolute ?? 0,
                memoryBytes: stats.memory_bytes ?? 0,
                diskBytes: stats.disk_bytes ?? 0,
                networkRx: stats.network?.rx_bytes ?? 0,
                networkTx: stats.network?.tx_bytes ?? 0,
                uptime: stats.uptime ?? 0,
                state: stats.state ?? resourceStore.getState(server.value.id),
              })
            }
          } catch { /* ignore malformed stats */ }
          break
        case 'token expiring':
          renewToken()
          break
        case 'token expired':
          disconnectConsole()
          connectConsole()
          break
      }
    } catch { /* non-JSON message */ }
  }

  ws.onclose = () => {
    wsConnected.value = false
    connecting.value = false
    disconnected.value = true
  }

  ws.onerror = () => {
    wsConnected.value = false
    connecting.value = false
    disconnected.value = true
    toast(t('userServers.consoleFailed'), 'error')
  }
}

async function renewToken() {
  if (!server.value || !ws || ws.readyState !== WebSocket.OPEN) return
  const data = await get<{ token: string }>(
    `/api/user/servers/${server.value.id}/console`,
    { silent: true },
  )
  if (data) {
    ws.send(JSON.stringify({ event: 'auth', args: [data.token] }))
  }
}

function disconnectConsole() {
  if (ws) { ws.close(); ws = null }
  wsConnected.value = false
}

function sendCommand() {
  const cmd = commandInput.value.trim()
  if (!cmd || !ws || ws.readyState !== WebSocket.OPEN) return
  ws.send(JSON.stringify({ event: 'send command', args: [cmd] }))
  // Add to history
  commandHistory = [cmd, ...commandHistory.filter(c => c !== cmd)].slice(0, HISTORY_MAX)
  historyIndex = -1
  saveHistory()
  commandInput.value = ''
}

function handleCommandKey(e: KeyboardEvent) {
  if (e.key === 'ArrowUp') {
    e.preventDefault()
    if (historyIndex < commandHistory.length - 1) {
      historyIndex++
      commandInput.value = commandHistory[historyIndex] || ''
    }
  } else if (e.key === 'ArrowDown') {
    e.preventDefault()
    if (historyIndex > 0) {
      historyIndex--
      commandInput.value = commandHistory[historyIndex] || ''
    } else {
      historyIndex = -1
      commandInput.value = ''
    }
  }
}

// ── Power actions ──
async function sendPower(action: string) {
  if (!server.value) return

  if (action === 'stop') {
    const ok = await confirm({
      title: t('common.confirm.title'),
      message: t('userServers.power.confirmStop'),
      confirmText: t('userServers.power.stop'),
    })
    if (!ok) return
  } else if (action === 'kill') {
    const ok = await confirm({
      title: t('common.confirm.dangerTitle'),
      message: t('userServers.power.confirmKill'),
      confirmText: t('userServers.power.kill'),
      variant: 'danger',
    })
    if (!ok) return
  }

  await post(`/api/user/servers/${server.value.id}/power`, { action })
}

// ── Formatting helpers ──
function formatUptime(ms: number): string {
  if (ms <= 0) return '—'
  const s = Math.floor(ms / 1000)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  if (h > 0) return `${h}h ${m}m`
  return `${m}m ${s % 60}s`
}

function memPercent(): number {
  if (!server.value?.limits.memory) return 0
  return Math.min(100, (memoryBytes.value / (server.value.limits.memory * 1024 * 1024)) * 100)
}

function diskPercent(): number {
  if (!server.value?.limits.disk) return 0
  return Math.min(100, (diskBytes.value / (server.value.limits.disk * 1024 * 1024)) * 100)
}

function memLimit(): string {
  if (!server.value?.limits.memory) return '∞'
  const mb = server.value.limits.memory
  return mb >= 1024 ? (mb / 1024).toFixed(1) + ' GB' : mb + ' MB'
}

function diskLimit(): string {
  if (!server.value?.limits.disk) return '∞'
  const mb = server.value.limits.disk
  return mb >= 1024 ? (mb / 1024).toFixed(1) + ' GB' : mb + ' MB'
}

function cpuLimit(): string {
  if (!server.value?.limits.cpu) return '∞'
  return server.value.limits.cpu + '%'
}

// ── Resize ──
function handleResize() { fitAddon?.fit() }

let resizeObserver: ResizeObserver | null = null

onMounted(() => {
  loadHistory()
  connectConsole()
  resizeObserver = new ResizeObserver(handleResize)
  if (termEl.value) resizeObserver.observe(termEl.value)
})

onBeforeUnmount(() => {
  disconnectConsole()
  if (term) { term.dispose(); term = null }
  if (resizeObserver) { resizeObserver.disconnect(); resizeObserver = null }
})
</script>

<template>
  <div class="console-page">
    <!-- ═══ Mobile top: Address + Power (above terminal on mobile) ═══ -->
    <div class="mobile-top">
      <!-- Address -->
      <BaseCard v-if="server?.address" variant="bg3" class="mobile-card">
        <template v-if="isWebEgg">
          <BaseButton
            variant="primary"
            size="sm"
            class="mobile-open-btn"
            :disabled="state !== 'running'"
            @click="openSillyTavern"
          >
            <MsIcon name="open_in_new" />
            {{ t('userServers.openApp') }}
          </BaseButton>
        </template>
        <div class="address-line" :style="isWebEgg ? { marginTop: 'var(--sp-2)' } : undefined">
          <span class="address-text">{{ server.address }}</span>
          <button class="copy-btn" :title="t('userServers.address.copy')" @click="copyAddress">
            <MsIcon :name="copied ? 'check' : 'content_copy'" />
          </button>
        </div>
      </BaseCard>

      <!-- Power controls -->
      <BaseCard variant="bg3" class="mobile-card">
        <div class="mobile-power-row">
          <!-- Installing: disabled -->
          <BaseButton
            v-if="isInstalling"
            variant="primary"
            size="sm"
            disabled
          >
            <Spinner size="xs" /> {{ t('userServers.status.installing') }}
          </BaseButton>
          <!-- Suspended: disabled start -->
          <BaseButton
            v-else-if="server?.isSuspended"
            variant="primary"
            size="sm"
            disabled
          >
            <MsIcon name="play_arrow" /> {{ t('userServers.power.start') }}
          </BaseButton>
          <BaseButton
            v-else-if="state === 'offline' || state === 'stopped'"
            variant="primary"
            size="sm"
            @click="sendPower('start')"
          >
            <MsIcon name="play_arrow" /> {{ t('userServers.power.start') }}
          </BaseButton>
          <template v-else-if="state === 'starting'">
            <BaseButton size="sm" disabled><Spinner size="xs" /> {{ t('userServers.status.starting') }}</BaseButton>
            <BaseButton size="sm" variant="danger" @click="sendPower('kill')">
              <MsIcon name="power_off" /> {{ t('userServers.power.kill') }}
            </BaseButton>
          </template>
          <template v-else-if="state === 'running'">
            <BaseButton size="sm" @click="sendPower('restart')">
              <MsIcon name="refresh" /> {{ t('userServers.power.restart') }}
            </BaseButton>
            <BaseButton size="sm" variant="warning" @click="sendPower('stop')">
              <MsIcon name="power_settings_new" /> {{ t('userServers.power.stop') }}
            </BaseButton>
            <BaseButton size="sm" variant="danger" @click="sendPower('kill')">
              <MsIcon name="power_off" /> {{ t('userServers.power.kill') }}
            </BaseButton>
          </template>
          <template v-else-if="state === 'stopping'">
            <BaseButton size="sm" disabled><Spinner size="xs" /></BaseButton>
            <BaseButton size="sm" variant="danger" @click="sendPower('kill')">
              <MsIcon name="power_off" /> {{ t('userServers.power.kill') }}
            </BaseButton>
          </template>
        </div>
      </BaseCard>
    </div>

    <!-- ═══ Main: Terminal ═══ -->
    <div class="console-main">
      <BaseCard class="terminal-card">
        <!-- Connecting overlay -->
        <div v-if="connecting && !wsConnected" class="terminal-overlay">
          <Spinner />
        </div>
        <!-- Disconnected overlay -->
        <div v-else-if="disconnected && !wsConnected" class="terminal-overlay terminal-overlay--reconnect">
          <MsIcon name="cloud_off" class="reconnect-icon" />
          <span class="reconnect-text">{{ t('userServers.consoleDisconnected') }}</span>
          <BaseButton size="sm" variant="primary" @click="connectConsole">
            <MsIcon name="refresh" /> {{ t('userServers.consoleReconnect') }}
          </BaseButton>
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
            :disabled="!wsConnected || isInstalling"
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
        <StatusDot :status="statusDotKey()" />
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
        </div>
      </BaseCard>

      <!-- Address card -->
      <BaseCard v-if="server?.address" variant="bg3" class="sidebar-card">
        <div class="sidebar-section-title">
          <MsIcon name="language" class="section-icon" />
          {{ t('userServers.address.label') }}
        </div>
        <template v-if="isWebEgg">
          <BaseButton
            variant="primary"
            size="sm"
            class="address-open-btn"
            :disabled="state !== 'running'"
            @click="openSillyTavern"
          >
            <MsIcon name="open_in_new" />
            {{ t('userServers.openApp') }}
          </BaseButton>
          <div class="address-lines">
            <div class="address-line">
              <span class="address-text">{{ server.address }}</span>
              <button class="copy-btn" :title="t('userServers.address.copy')" @click="copyAddress">
                <MsIcon :name="copied ? 'check' : 'content_copy'" />
              </button>
            </div>
          </div>
        </template>
        <template v-else>
          <div class="address-lines">
            <div class="address-line address-line--large">
              <span class="address-text">{{ server.address }}</span>
              <button class="copy-btn" :title="t('userServers.address.copy')" @click="copyAddress">
                <MsIcon :name="copied ? 'check' : 'content_copy'" />
              </button>
            </div>
          </div>
        </template>
      </BaseCard>

      <!-- Power controls -->
      <BaseCard variant="bg3" class="sidebar-card">
        <div class="sidebar-section-title">
          <MsIcon name="power_settings_new" class="section-icon" />
          {{ t('userServers.power.title') }}
        </div>
        <div class="power-buttons">
          <!-- Installing: disabled -->
          <BaseButton
            v-if="isInstalling"
            variant="primary"
            class="power-btn"
            disabled
          >
            <Spinner size="xs" /> {{ t('userServers.status.installing') }}
          </BaseButton>
          <!-- Suspended: disabled start -->
          <BaseButton
            v-else-if="server?.isSuspended"
            variant="primary"
            class="power-btn"
            disabled
          >
            <MsIcon name="play_arrow" />
            {{ t('userServers.power.start') }}
          </BaseButton>
          <BaseButton
            v-else-if="state === 'offline' || state === 'stopped'"
            variant="primary"
            class="power-btn"
            @click="sendPower('start')"
          >
            <MsIcon name="play_arrow" />
            {{ t('userServers.power.start') }}
          </BaseButton>
          <template v-else-if="state === 'starting'">
            <BaseButton class="power-btn" disabled>
              <Spinner size="xs" /> {{ t('userServers.status.starting') }}
            </BaseButton>
            <BaseButton class="power-btn" variant="danger" @click="sendPower('kill')">
              <MsIcon name="power_off" />
              {{ t('userServers.power.kill') }}
            </BaseButton>
          </template>
          <template v-else-if="state === 'running'">
            <BaseButton class="power-btn" @click="sendPower('restart')">
              <MsIcon name="refresh" />
              {{ t('userServers.power.restart') }}
            </BaseButton>
            <BaseButton class="power-btn" variant="warning" @click="sendPower('stop')">
              <MsIcon name="power_settings_new" />
              {{ t('userServers.power.stop') }}
            </BaseButton>
            <BaseButton class="power-btn" variant="danger" @click="sendPower('kill')">
              <MsIcon name="power_off" />
              {{ t('userServers.power.kill') }}
            </BaseButton>
          </template>
          <template v-else-if="state === 'stopping'">
            <BaseButton class="power-btn" disabled>
              <Spinner size="xs" /> {{ t('userServers.status.stopping') }}
            </BaseButton>
            <BaseButton class="power-btn" variant="danger" @click="sendPower('kill')">
              <MsIcon name="power_off" />
              {{ t('userServers.power.kill') }}
            </BaseButton>
          </template>
        </div>
      </BaseCard>

      <!-- Resource stats -->
      <BaseCard variant="bg3" class="sidebar-card">
        <div class="sidebar-section-title">
          <MsIcon name="monitoring" class="section-icon" />
          {{ t('userServers.resources.title') }}
        </div>
        <div class="stats-grid">
          <div class="stat-row">
            <div class="stat-header">
              <span class="stat-label">{{ t('userServers.resources.cpu') }}</span>
              <span class="stat-value">{{ cpuPercent.toFixed(1) }}% <span class="stat-limit">/ {{ cpuLimit() }}</span></span>
            </div>
            <UsageBar :percent="cpuPercent" />
          </div>
          <div class="stat-row">
            <div class="stat-header">
              <span class="stat-label">{{ t('userServers.resources.memory') }}</span>
              <span class="stat-value">{{ fmtBytes(memoryBytes) }} <span class="stat-limit">/ {{ memLimit() }}</span></span>
            </div>
            <UsageBar :percent="memPercent()" />
          </div>
          <div class="stat-row">
            <div class="stat-header">
              <span class="stat-label">{{ t('userServers.resources.disk') }}</span>
              <span class="stat-value">{{ fmtBytes(diskBytes) }} <span class="stat-limit">/ {{ diskLimit() }}</span></span>
            </div>
            <UsageBar :percent="diskPercent()" />
          </div>
          <div class="stat-row stat-row--inline">
            <span class="stat-label">{{ t('userServers.resources.network') }}</span>
            <span class="stat-value">
              <span class="net-up">↑ {{ fmtBytes(networkTx) }}</span>
              <span class="net-down">↓ {{ fmtBytes(networkRx) }}</span>
            </span>
          </div>
          <div class="stat-row stat-row--inline">
            <span class="stat-label">{{ t('userServers.resources.uptime') }}</span>
            <span class="stat-value">{{ formatUptime(uptimeMs) }}</span>
          </div>
        </div>
      </BaseCard>
    </aside>

    <!-- ═══ Mobile bottom: Resource stats ═══ -->
    <div class="mobile-bottom">
      <BaseCard variant="bg3" class="mobile-card">
        <!-- Lifecycle (single line) -->
        <div class="mobile-lifecycle">
          <div class="mobile-lifecycle-left">
            <MsIcon name="schedule" class="section-icon" />
            <span class="mobile-lifecycle-label">{{ t('userServers.expiration') }}：</span>
            <span v-if="server?.expirationDate" class="lifecycle-value">
              {{ server.expirationDate }}
              <span class="lifecycle-remaining" :style="{ color: expirationColor }">（{{ expirationText }}）</span>
            </span>
            <span v-else class="lifecycle-value">{{ expirationText }}</span>
          </div>
          <span v-if="server?.isSuspended" class="mobile-suspended-badge">{{ t('userServers.status.suspended') }}</span>
        </div>
        <!-- Stats -->
        <div class="mobile-stats">
          <div class="mobile-stat">
            <div class="stat-header" style="margin-top: auto">
              <span class="mobile-stat-label">CPU</span>
              <span class="mobile-stat-value">{{ cpuPercent.toFixed(1) }}% / {{ cpuLimit() }}</span>
            </div>
            <UsageBar :percent="cpuPercent" class="mobile-stat-bar" />
          </div>
          <div class="mobile-stat">
            <div class="stat-header" style="margin-top: auto">
              <span class="mobile-stat-label">{{ t('userServers.resources.memory') }}</span>
              <span class="mobile-stat-value">{{ fmtBytes(memoryBytes) }} / {{ memLimit() }}</span>
            </div>
            <UsageBar :percent="memPercent()" class="mobile-stat-bar" />
          </div>
          <div class="mobile-stat">
            <div class="stat-header" style="margin-top: auto">
              <span class="mobile-stat-label">{{ t('userServers.resources.disk') }}</span>
              <span class="mobile-stat-value">{{ fmtBytes(diskBytes) }} / {{ diskLimit() }}</span>
            </div>
            <UsageBar :percent="diskPercent()" class="mobile-stat-bar" />
          </div>
          <div class="mobile-stat">
            <span class="mobile-stat-label">{{ t('userServers.resources.network') }}</span>
            <span class="mobile-stat-value" style="margin-top: auto">↑{{ fmtBytes(networkTx) }} ↓{{ fmtBytes(networkRx) }}</span>
          </div>
        </div>
      </BaseCard>
    </div>
  </div>
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

/* ── Mobile lifecycle ── */
.mobile-lifecycle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: var(--sp-2);
  margin-bottom: var(--sp-2);
  border-bottom: 1px solid var(--bd);
}

.mobile-lifecycle-left {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}

.mobile-lifecycle-label {
  font-size: var(--text-sm);
  color: var(--t2);
  white-space: nowrap;
}

.mobile-suspended-badge {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--red);
  padding: 2px var(--sp-2);
  background: color-mix(in srgb, var(--red) 10%, var(--bg-in));
  border: 1px solid color-mix(in srgb, var(--red) 25%, var(--bd));
  border-radius: var(--r-pill);
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

/* ── Address ── */
.address-open-btn {
  width: 100%;
  margin-bottom: var(--sp-2);
}

/* ── Lifecycle ── */
.lifecycle-row {
  display: flex;
  align-items: baseline;
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

.address-lines {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}

.address-line {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-1) var(--sp-2);
  background: var(--bg-in);
  border-radius: var(--r-sm);
  border: 1px solid var(--bd);
}

.address-line--large {
  padding: var(--sp-2);
}

.address-text {
  flex: 1;
  font-family: 'IBM Plex Mono', monospace;
  font-size: var(--text-xs);
  color: var(--t2);
  word-break: break-all;
}

.copy-btn {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: var(--r-xs);
  background: none;
  color: var(--t3);
  cursor: pointer;
  transition: color 0.15s, background 0.15s;
}

.copy-btn:hover {
  color: var(--ac);
  background: var(--bg4);
}

/* ── Power ── */
.power-buttons {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.power-btn {
  width: 100%;
}

/* ── Stats ── */
.stats-grid {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

.stat-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.stat-row--inline {
  flex-direction: row;
  justify-content: space-between;
  align-items: center;
  gap: var(--sp-2);
}

.stat-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}

.stat-label {
  font-size: var(--text-xs);
  color: var(--t3);
  font-weight: 500;
}

.stat-value {
  font-family: 'IBM Plex Mono', monospace;
  font-size: var(--text-xs);
  color: var(--t1);
}

.stat-limit {
  color: var(--t3);
}

.net-up, .net-down {
  margin-left: var(--sp-1);
}

.net-up { color: var(--ac2); }
.net-down { color: var(--blue); }

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

  .mobile-open-btn {
    width: 100%;
  }

  .mobile-power-row {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
  }

  .mobile-power-row > * {
    flex: 1;
    min-width: 0;
  }

  .mobile-stats {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: var(--sp-3);
  }

  .mobile-stat {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .mobile-stat-label {
    font-size: var(--text-xs);
    color: var(--t3);
    font-weight: 500;
  }

  .mobile-stat-value {
    font-family: 'IBM Plex Mono', monospace;
    font-size: var(--text-xs);
    color: var(--t1);
  }

  .mobile-stat-bar {
    margin-top: 2px;
  }

  .terminal-container {
    height: clamp(250px, 45vh, 500px);
  }
}

@media (max-width: 480px) {
  .mobile-stats {
    grid-template-columns: 1fr 1fr;
  }
}
</style>

import { ref, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import { useServerResourceStore } from '@/stores/serverResources'
import router from '@/router'

export interface UseConsoleWsOptions {
  serverId: Ref<number | undefined>
  termEl: Ref<HTMLElement | null>
}

export function useConsoleWs({ serverId, termEl }: UseConsoleWsOptions) {
  const { t } = useI18n({ useScope: 'global' })
  const { get } = useApiFetch()
  const { toast } = useToast()
  const resourceStore = useServerResourceStore()

  const wsConnected = ref(false)
  const connecting = ref(false)
  const disconnected = ref(false)
  const reconnecting = ref(false)
  const reconnectAttempt = ref(0)
  const commandInput = ref('')

  let ws: WebSocket | null = null
  let term: any = null
  let fitAddon: any = null
  let intentionalClose = false
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null

  // Reconnect constants
  const RECONNECT_MAX = 5
  const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 16000]
  const reconnectCountdown = ref(0)
  let countdownTimer: ReturnType<typeof setInterval> | null = null

  // Wings token state (shared for upload / reconnect)
  let cachedWsUrl = ''
  let cachedBaseUrl = ''
  let cachedServerUuid = ''
  let cachedExpiresAt = 0

  // ── Command history ──
  const HISTORY_MAX = 32
  let commandHistory: string[] = []
  let historyIndex = -1

  function loadHistory() {
    try {
      const raw = sessionStorage.getItem(`console_history_${serverId.value}`)
      commandHistory = raw ? JSON.parse(raw) : []
    } catch { commandHistory = [] }
  }

  function saveHistory() {
    try {
      sessionStorage.setItem(`console_history_${serverId.value}`, JSON.stringify(commandHistory))
    } catch { /* quota exceeded */ }
  }

  // ── Message handler factory ──
  function createMessageHandler(): (e: MessageEvent) => void {
    return (e: MessageEvent) => {
      try {
        const msg = JSON.parse(e.data)
        switch (msg.event) {
          case 'auth success':
            wsConnected.value = true
            connecting.value = false
            if (reconnecting.value) {
              resetReconnect()
              term?.writeln('\x1b[1m\x1b[33m* ' + t('userServers.reconnected') + '\x1b[0m')
            }
            ws!.send(JSON.stringify({ event: 'send logs', args: [null] }))
            break
          case 'console output':
          case 'install output':
            term?.writeln(msg.args[0])
            break
          case 'daemon message':
            term?.writeln('\x1b[1m\x1b[33m' + msg.args[0] + '\x1b[0m')
            break
          case 'daemon error':
            term?.writeln('\x1b[1m\x1b[41m' + msg.args[0] + '\x1b[0m')
            break
          case 'status':
            if (serverId.value) {
              resourceStore.updateOne(serverId.value, { state: msg.args[0] })
              term?.writeln('\x1b[1m\x1b[33m* ' + t('userServers.status.' + msg.args[0]) + '\x1b[0m')
            }
            break
          case 'stats':
            try {
              const stats = JSON.parse(msg.args[0])
              if (serverId.value) {
                resourceStore.updateOne(serverId.value, {
                  cpu: stats.cpu_absolute ?? 0,
                  memoryBytes: stats.memory_bytes ?? 0,
                  diskBytes: stats.disk_bytes ?? 0,
                  networkRx: stats.network?.rx_bytes ?? 0,
                  networkTx: stats.network?.tx_bytes ?? 0,
                  uptime: stats.uptime ?? 0,
                  state: stats.state ?? resourceStore.getState(serverId.value),
                })
              }
            } catch { /* ignore malformed stats */ }
            break
          case 'token expiring':
            renewToken()
            break
          case 'token expired':
            reconnectWs()
            break
        }
      } catch { /* non-JSON message */ }
    }
  }

  interface WingsTokenResponse {
    token: string
    wsUrl: string
    baseUrl: string
    serverUuid: string
    expiresAt: number
  }

  const suspended = ref(false)

  async function fetchWingsToken(): Promise<WingsTokenResponse | null> {
    if (!serverId.value) return null
    try {
      const res = await fetch(`/api/user/servers/${serverId.value}/wings-token`)
      if (res.status === 401) {
        router.push({ name: 'login' })
        return null
      }
      if (res.status === 403) {
        const body = await res.json().catch(() => ({}))
        if (body.error === 'server_suspended') {
          suspended.value = true
          return null
        }
      }
      if (!res.ok) return null
      suspended.value = false
      return await res.json()
    } catch {
      return null
    }
  }

  /** Create WS connection from token data, wire up event handlers */
  function _setupWs(data: WingsTokenResponse): void {
    cachedWsUrl = data.wsUrl
    cachedBaseUrl = data.baseUrl
    cachedServerUuid = data.serverUuid
    cachedExpiresAt = data.expiresAt
    intentionalClose = false

    const socket = new WebSocket(data.wsUrl)
    ws = socket

    socket.onopen = () => {
      socket.send(JSON.stringify({ event: 'auth', args: [data.token] }))
    }

    socket.onmessage = createMessageHandler()

    socket.onclose = () => {
      // Ignore close events from stale sockets (e.g. replaced by reconnectWs)
      if (ws !== socket) return
      wsConnected.value = false
      connecting.value = false
      if (!intentionalClose) {
        scheduleReconnect()
      } else {
        disconnected.value = true
      }
    }

    socket.onerror = () => {
      if (!disconnected.value && !reconnecting.value) {
        toast(t('userServers.consoleFailed'), 'error')
      }
    }
  }

  /** Schedule auto-reconnect with exponential backoff */
  function scheduleReconnect() {
    if (reconnectAttempt.value >= RECONNECT_MAX) {
      reconnecting.value = false
      disconnected.value = true
      return
    }
    reconnecting.value = true
    disconnected.value = false
    const delay = RECONNECT_DELAYS[reconnectAttempt.value] ?? 16000
    reconnectAttempt.value++

    // Start countdown
    reconnectCountdown.value = Math.ceil(delay / 1000)
    if (countdownTimer) clearInterval(countdownTimer)
    countdownTimer = setInterval(() => {
      reconnectCountdown.value--
      if (reconnectCountdown.value <= 0 && countdownTimer) {
        clearInterval(countdownTimer)
        countdownTimer = null
      }
    }, 1000)

    reconnectTimer = setTimeout(async () => {
      reconnectTimer = null
      if (countdownTimer) { clearInterval(countdownTimer); countdownTimer = null }
      reconnectCountdown.value = 0
      const data = await fetchWingsToken()
      if (!data) {
        if (suspended.value) {
          reconnecting.value = false
          disconnected.value = true
          return
        }
        scheduleReconnect()
        return
      }
      _setupWs(data)
    }, delay)
  }

  /** Reset reconnect state (called on successful auth) */
  function resetReconnect() {
    reconnectAttempt.value = 0
    reconnecting.value = false
  }

  // ── WebSocket console ──
  async function connect() {
    if (!serverId.value || connecting.value) return
    connecting.value = true
    disconnected.value = false

    const data = await fetchWingsToken()
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

    _setupWs(data)
  }

  async function renewToken() {
    if (!serverId.value || !ws || ws.readyState !== WebSocket.OPEN) return
    const data = await fetchWingsToken()
    if (data) {
      cachedExpiresAt = data.expiresAt
      ws.send(JSON.stringify({ event: 'auth', args: [data.token] }))
    }
  }

  /** Reconnect WebSocket only (token expired), keep terminal intact */
  async function reconnectWs() {
    if (!serverId.value) return
    if (ws) { ws.close(); ws = null } // old socket's onclose will see ws !== socket, skip
    wsConnected.value = false

    const data = await fetchWingsToken()
    if (!data) {
      disconnected.value = true
      toast(t('userServers.consoleFailed'), 'error')
      return
    }

    _setupWs(data)
  }

  function disconnect() {
    intentionalClose = true
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null }
    if (countdownTimer) { clearInterval(countdownTimer); countdownTimer = null }
    reconnecting.value = false
    reconnectAttempt.value = 0
    reconnectCountdown.value = 0
    if (ws) { ws.close(); ws = null }
    wsConnected.value = false
  }

  function sendCommand() {
    const cmd = commandInput.value.trim()
    if (!cmd || !ws || ws.readyState !== WebSocket.OPEN) return
    ws.send(JSON.stringify({ event: 'send command', args: [cmd] }))
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

  function fit() {
    fitAddon?.fit()
  }

  function dispose() {
    disconnect()
    if (term) { term.dispose(); term = null }
  }

  /** Manual reconnect from user button — reset counters and try again */
  async function manualReconnect() {
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null }
    if (countdownTimer) { clearInterval(countdownTimer); countdownTimer = null }
    reconnectAttempt.value = 0
    reconnectCountdown.value = 0
    disconnected.value = false
    suspended.value = false
    // If terminal was never created (first connect failed), do full connect
    if (!term) {
      await connect()
    } else {
      connecting.value = true
      await reconnectWs()
      if (!wsConnected.value && !reconnecting.value) {
        connecting.value = false
      }
    }
  }

  return {
    wsConnected,
    connecting,
    disconnected,
    reconnecting,
    reconnectAttempt,
    reconnectCountdown,
    suspended,
    commandInput,
    connect,
    disconnect,
    sendCommand,
    handleCommandKey,
    loadHistory,
    fit,
    dispose,
    manualReconnect,
    /** Fetch a fresh wings token (for upload, etc.) */
    fetchWingsToken,
    /** Cached Wings base URL (e.g. http://10.0.0.22:8443) */
    get wingsBaseUrl() { return cachedBaseUrl },
    /** Cached server UUID */
    get wingsServerUuid() { return cachedServerUuid },
  }
}

import { computed, onBeforeUnmount, onMounted, watch } from 'vue'
import { useAppStore } from '@/stores/app'
import { useSupportStore } from '@/stores/support'
import { createSupportSound } from '@/utils/supportSound'
import { useApiFetch } from './useApiFetch'
import { useSupportConnection, useSupportEvents } from './useSupportEvents'

export function useSupportNotifications() {
  const app = useAppStore()
  const support = useSupportStore()
  const { get } = useApiFetch()
  const sound = createSupportSound()
  const identity = computed(() => support.identity)
  const enabled = computed(() => !!identity.value)
  let latestId: number | null = null
  let generation = 0
  let alive = true
  let busy = false
  let again = false
  let retry: ReturnType<typeof setTimeout> | undefined
  let retryDelay = 2000
  let lastSessionCheck = 0
  let checkingSession = false

  async function checkSession() {
    const now = Date.now()
    if (checkingSession || now - lastSessionCheck < 30_000) return
    checkingSession = true
    lastSessionCheck = now
    try {
      await app.fetchSessionUser({ force: true })
    } catch {
      // Transient 5xx or network errors during backend restarts should not surface as unhandled rejections.
    } finally {
      checkingSession = false
    }
  }

  async function refresh() {
    if (!alive || !enabled.value) return
    if (busy) { again = true; return }
    clearTimeout(retry)
    busy = true
    const version = generation
    try {
      const data = await get<{ unread: number; latest_incoming_id: number }>('/api/support/unread', { silent: true })
      if (!alive || version !== generation) return
      retryDelay = 2000
      support.unread = data.unread
      const incoming = data.latest_incoming_id || 0
      if (latestId !== null && incoming > latestId && support.soundEnabled) sound.play(identity.value, incoming)
      latestId = Math.max(latestId ?? 0, incoming)
    } catch {
      if (alive && version === generation) {
        retry = setTimeout(() => void refresh(), retryDelay)
        retryDelay = Math.min(retryDelay * 2, 30_000)
      }
    } finally {
      busy = false
      if (again) { again = false; void refresh() }
    }
  }

  watch(identity, () => {
    generation++
    clearTimeout(retry)
    retryDelay = 2000
    lastSessionCheck = 0
    latestId = null
    support.unread = 0
    sound.reset()
    void refresh()
  }, { flush: 'sync' })
  watch(() => support.soundEnabled, enabled => { if (!enabled) sound.reset() })
  useSupportConnection(identity, () => { void checkSession() })
  useSupportEvents(() => {
    lastSessionCheck = 0
    void refresh()
  }, enabled)
  onMounted(() => { void refresh() })
  onBeforeUnmount(() => { alive = false; generation++; clearTimeout(retry); sound.dispose() })
}

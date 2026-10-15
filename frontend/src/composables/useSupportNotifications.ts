import { computed, onBeforeUnmount, onMounted, watch } from 'vue'
import { useAppStore } from '@/stores/app'
import { useSupportStore } from '@/stores/support'
import { createSupportSound, playSupportSoundOnce } from '@/utils/supportSound'
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
      if (latestId !== null && incoming > latestId) {
        void playSupportSoundOnce(identity.value, incoming, sound.play, () => alive && version === generation, () => support.soundEnabled)
      }
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
    latestId = null
    support.unread = 0
    sound.reset()
    void refresh()
  }, { flush: 'sync' })
  watch(() => support.soundEnabled, enabled => { if (!enabled) sound.reset() })
  useSupportConnection(identity, () => { void app.fetchSessionUser({ force: true }) })
  useSupportEvents(() => void refresh(), enabled)
  onMounted(() => { sound.start(); void refresh() })
  onBeforeUnmount(() => { alive = false; generation++; clearTimeout(retry); sound.dispose() })
}

import { defineStore } from 'pinia'
import { computed, onScopeDispose, reactive, ref, watch } from 'vue'
import { useAppStore } from './app'
import { supportSoundEnabled, supportSoundKey } from '@/utils/supportSound'

interface Draft { text: string; file: File | null; clientId: string; sending: boolean }

export const useSupportStore = defineStore('support', () => {
  const app = useAppStore()
  const open = ref(false)
  const unread = ref(0)
  const identity = computed(() => app.sessionUser ? `${app.sessionUser.username}:${app.isAdmin}` : '')
  const soundEnabled = ref(true)
  const drafts = reactive<Record<number, Draft>>({})

  function draftFor(id: number): Draft {
    if (!drafts[id]) drafts[id] = { text: '', file: null, clientId: '', sending: false }
    return drafts[id]!
  }

  function syncSoundPreference() { soundEnabled.value = supportSoundEnabled(identity.value) }
  function setSoundEnabled(value: boolean) {
    soundEnabled.value = value
    try { localStorage.setItem(supportSoundKey(identity.value), soundEnabled.value ? '1' : '0') } catch { /* Keep the preference for this tab when storage is unavailable. */ }
  }
  function onStorage(event: StorageEvent) {
    if (event.key === null || event.key === supportSoundKey(identity.value)) syncSoundPreference()
  }
  window.addEventListener('storage', onStorage)
  onScopeDispose(() => window.removeEventListener('storage', onStorage))

  watch(identity, () => {
    open.value = false
    unread.value = 0
    syncSoundPreference()
    for (const key of Object.keys(drafts)) delete drafts[Number(key)]
  }, { immediate: true, flush: 'sync' })

  return { open, unread, identity, soundEnabled, setSoundEnabled, draftFor }
})

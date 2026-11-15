export const supportSoundKey = (identity: string) => `support-sound:${identity}`
const lastPlayedKey = (identity: string) => `support-sound-last:${identity}`

export function supportSoundEnabled(identity: string) {
  return localStorage.getItem(supportSoundKey(identity)) !== '0'
}

export function createSupportSound() {
  const audio = new Audio('/sounds/support-message.wav')
  let lastPlayed = -Infinity

  function play(identity?: string, messageId?: number) {
    // Tabs without user activation cannot autoplay; skip claiming the message ID so an active tab can chime.
    if (navigator.userActivation && !navigator.userActivation.hasBeenActive) return
    if (identity && messageId) {
      try {
        if (Number(localStorage.getItem(lastPlayedKey(identity)) || 0) >= messageId) return
        localStorage.setItem(lastPlayedKey(identity), String(messageId))
      } catch { /* Storage may be unavailable in restricted contexts. */ }
    }
    const now = performance.now()
    if (now - lastPlayed < 2000) return
    lastPlayed = now
    audio.currentTime = 0
    void audio.play().catch(() => {})
  }

  function reset() {
    audio.pause()
    audio.currentTime = 0
    lastPlayed = -Infinity
  }

  return { play, reset, dispose: reset }
}

export const supportSoundKey = (identity: string) => `support-sound:${identity}`

export function supportSoundEnabled(identity: string) {
  try { return localStorage.getItem(supportSoundKey(identity)) !== '0' } catch { return true }
}

export async function playSupportSoundOnce(identity: string, id: number, play: () => boolean, current: () => boolean, enabled: () => boolean) {
  const key = `support-notified:${identity}`
  function claim() {
    if (!current()) return
    let previous = { id: 0, playedAt: 0 }
    try {
      const saved = JSON.parse(localStorage.getItem(key) || 'null')
      if (saved && Number.isSafeInteger(saved.id) && Number.isFinite(saved.playedAt)) previous = saved
    } catch { /* Storage is optional; per-tab cursors still prevent replay. */ }
    if (id <= previous.id) return
    const muted = !enabled() || !supportSoundEnabled(identity)
    const now = Date.now()
    const limited = now - previous.playedAt < 1500
    // Only a tab with usable audio claims the sound, so a suspended tab cannot silence a live one.
    if (!muted && !limited && !play()) return
    try { localStorage.setItem(key, JSON.stringify({ id, playedAt: muted || limited ? previous.playedAt : now })) } catch { /* Storage may be unavailable. */ }
  }
  if (navigator.locks) {
    try { await navigator.locks.request(key, claim) } catch { if (current()) claim() }
  } else claim()
}

export function createSupportSound() {
  let context: AudioContext | null = null
  let buffer: AudioBuffer | null = null
  let loading = false
  let disposed = false
  let source: AudioBufferSourceNode | null = null
  let lastPlayed = -Infinity
  const controller = new AbortController()

  function unlock(event: Event) {
    if (!event.isTrusted || disposed) return
    const AudioContextClass = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
    if (!AudioContextClass) return
    try {
      context ||= new AudioContextClass()
      if (context.state !== 'running') void context.resume().catch(() => {})
      if (buffer || loading) return
      loading = true
      const audioContext = context
      // Resume inside the gesture; waiting for the audio download first loses activation on iOS.
      void fetch('/sounds/support-message.wav', { signal: controller.signal })
        .then(response => { if (!response.ok) throw new Error('Sound unavailable'); return response.arrayBuffer() })
        .then(data => audioContext.decodeAudioData(data))
        .then(decoded => { if (!disposed) buffer = decoded })
        .catch(() => {})
        .finally(() => { loading = false })
    } catch { /* Browsers without usable audio continue with the unread badge. */ }
  }

  function play() {
    const now = performance.now()
    if (disposed || !context || context.state !== 'running' || !buffer || now - lastPlayed < 1500) return false
    try { source?.stop() } catch { /* The previous sound may already have ended. */ }
    try {
      const next = context.createBufferSource()
      source = next
      next.buffer = buffer
      next.connect(context.destination)
      next.onended = () => { next.disconnect(); if (source === next) source = null }
      next.start()
      lastPlayed = now
      return true
    } catch { return false }
  }

  function reset() {
    try { source?.stop() } catch { /* The previous sound may already have ended. */ }
    source = null
    lastPlayed = -Infinity
  }

  function start() {
    document.addEventListener('pointerdown', unlock, { passive: true })
    document.addEventListener('keydown', unlock)
  }

  function dispose() {
    disposed = true
    document.removeEventListener('pointerdown', unlock)
    document.removeEventListener('keydown', unlock)
    controller.abort()
    reset()
    void context?.close().catch(() => {})
  }

  return { start, play, reset, dispose }
}

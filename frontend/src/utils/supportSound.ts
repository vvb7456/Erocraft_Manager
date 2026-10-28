export const supportSoundKey = (identity: string) => `support-sound:${identity}`

export function supportSoundEnabled(identity: string) {
  return localStorage.getItem(supportSoundKey(identity)) !== '0'
}

export function createSupportSound() {
  const audio = new Audio('/sounds/support-message.wav')
  let lastPlayed = -Infinity

  function play() {
    const now = performance.now()
    if (now - lastPlayed < 2000) return
    lastPlayed = now
    audio.currentTime = 0
    // 浏览器可能在用户首次交互前禁止播放，未读提示仍正常显示。
    void audio.play().catch(() => {})
  }

  function reset() {
    audio.pause()
    audio.currentTime = 0
    lastPlayed = -Infinity
  }

  return { play, reset, dispose: reset }
}

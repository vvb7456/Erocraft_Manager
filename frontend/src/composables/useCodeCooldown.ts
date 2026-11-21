import { onUnmounted, ref } from 'vue'

export function useCodeCooldown(defaultSeconds = 60) {
  const remaining = ref(0)
  let timer: ReturnType<typeof setInterval> | null = null

  function stop() {
    if (timer !== null) {
      clearInterval(timer)
      timer = null
    }
  }

  function start(seconds = defaultSeconds) {
    stop()
    remaining.value = Math.max(0, Math.ceil(seconds))
    if (remaining.value <= 0) return
    timer = setInterval(() => {
      if (remaining.value <= 1) {
        remaining.value = 0
        stop()
      } else {
        remaining.value -= 1
      }
    }, 1000)
  }

  function reset() {
    stop()
    remaining.value = 0
  }

  onUnmounted(stop)

  return { remaining, start, reset }
}

// Shared reactive `Date.now()` tick. All consumers share a single interval;
// the interval starts on first subscription and stops when last consumer
// unsubscribes. Granularity defaults to 1s — fine for relative-time labels
// like "1s / 5m / 2h".

import { onBeforeUnmount, ref, type Ref } from 'vue'

const nowRef = ref<number>(Date.now())
let timerId: ReturnType<typeof setInterval> | null = null
let refCount = 0
const TICK_MS = 1000

function start() {
  if (timerId !== null) return
  timerId = setInterval(() => { nowRef.value = Date.now() }, TICK_MS)
}
function stop() {
  if (timerId !== null) { clearInterval(timerId); timerId = null }
}

export function useNow(): Ref<number> {
  refCount += 1
  start()
  onBeforeUnmount(() => {
    refCount -= 1
    if (refCount <= 0) { refCount = 0; stop() }
  })
  return nowRef
}

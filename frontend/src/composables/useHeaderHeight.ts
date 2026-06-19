import { onMounted, watch, nextTick } from 'vue'
import { useRoute } from 'vue-router'

let ro: ResizeObserver | null = null
let currentEl: HTMLElement | null = null
let initialized = false

function setVar(px: number) {
  document.documentElement.style.setProperty('--app-header-h', px + 'px')
}

function observe() {
  const el = document.querySelector<HTMLElement>('.page-header')
  if (el === currentEl) return
  ro?.disconnect()
  currentEl = el
  if (el) {
    setVar(el.offsetHeight)
    ro = new ResizeObserver(() => setVar(el.offsetHeight))
    ro.observe(el)
  } else {
    setVar(0)
  }
}

/**
 * Tracks `.page-header` height and exposes it as `--app-header-h` on :root.
 * Allows fixed-position overlays (BaseModal, BottomSheet) to reserve space
 * for the page header on mobile, keeping it visible while a modal is open.
 *
 * Re-observes on route changes because PageHeader is re-mounted per route.
 * Call once in App.vue setup.
 */
export function useHeaderHeight() {
  if (initialized) return
  initialized = true
  const route = useRoute()
  watch(() => route.path, () => nextTick(observe))
  onMounted(observe)
}

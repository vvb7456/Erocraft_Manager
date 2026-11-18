import { watch, type Ref } from 'vue'

const obstructions = new Map<symbol, number>()

function syncCssVar() {
  let maxPx = 0
  for (const h of obstructions.values()) {
    if (h > maxPx) maxPx = h
  }
  if (maxPx > 0) {
    document.documentElement.style.setProperty('--bottom-obstruction-h', `${Math.ceil(maxPx)}px`)
  } else {
    document.documentElement.style.removeProperty('--bottom-obstruction-h')
  }
}

export function useBottomObstruction(element: Ref<HTMLElement | null>) {
  const id = Symbol('bottom-obstruction')
  watch(element, (el, _, onCleanup) => {
    if (!el) return
    const update = () => {
      const bottomOffset = parseFloat(window.getComputedStyle(el).bottom) || 0
      obstructions.set(id, Math.max(0, bottomOffset) + el.offsetHeight)
      syncCssVar()
    }
    const observer = new ResizeObserver(update)
    update()
    observer.observe(el)
    window.addEventListener('resize', update)
    onCleanup(() => {
      observer.disconnect()
      window.removeEventListener('resize', update)
      obstructions.delete(id)
      syncCssVar()
    })
  }, { flush: 'post' })
}

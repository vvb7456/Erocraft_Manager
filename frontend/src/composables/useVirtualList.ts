import { computed, onBeforeUnmount, onMounted, ref, watch, type Ref } from 'vue'

/**
 * Fixed-row-height virtual list.
 *
 * Designed for large file listings (~thousands of rows) where every row
 * has the same height. Avoids the cost of a full virtualisation library
 * for what is fundamentally a 50-line problem.
 *
 * Key design points:
 * - Row height is provided by the caller (or auto-measured from the first
 *   rendered row on mount via ``measureRowHeight``).
 * - We render ``[overscan]`` extra rows above and below the visible band
 *   so fast scroll doesn't reveal blank space before the next frame.
 * - The container is unchanged; the caller provides:
 *     - top spacer height: ``offsetTop`` px
 *     - bottom spacer height: ``offsetBottom`` px
 *     - the slice of items to actually render: ``visibleItems``
 *
 * The container element MUST be the scroll-owner (``overflow-y: auto``).
 * Pass it via ``scrollerRef``.
 */
export interface UseVirtualListOptions<T> {
  items: Ref<readonly T[]>
  /** Scroll container ref — must own ``overflow-y: auto`` */
  scrollerRef: Ref<HTMLElement | null>
  /** Fixed row height in px. */
  rowHeight: Ref<number> | number
  /** Extra rows to render above & below the visible window. Default 6. */
  overscan?: number
  /**
   * Optional fixed offset (px) at the top of the scroll container that
   * isn't part of the virtual list (e.g. a sticky table header inside
   * the same scroll container). Default 0.
   */
  headerOffset?: Ref<number> | number
}

export function useVirtualList<T>(opts: UseVirtualListOptions<T>) {
  const overscan = opts.overscan ?? 6
  const rh = () => (typeof opts.rowHeight === 'number' ? opts.rowHeight : opts.rowHeight.value)
  const ho = () => (typeof opts.headerOffset === 'number' ? opts.headerOffset ?? 0 : opts.headerOffset?.value ?? 0)

  const scrollTop = ref(0)
  const viewportH = ref(0)

  function refreshViewport() {
    const el = opts.scrollerRef.value
    if (!el) return
    scrollTop.value = el.scrollTop
    viewportH.value = el.clientHeight
  }

  function onScroll() {
    refreshViewport()
  }

  let resizeObs: ResizeObserver | null = null
  onMounted(() => {
    refreshViewport()
    const el = opts.scrollerRef.value
    if (!el) return
    el.addEventListener('scroll', onScroll, { passive: true })
    if (typeof ResizeObserver !== 'undefined') {
      resizeObs = new ResizeObserver(refreshViewport)
      resizeObs.observe(el)
    } else {
      window.addEventListener('resize', refreshViewport)
    }
  })

  onBeforeUnmount(() => {
    const el = opts.scrollerRef.value
    if (el) el.removeEventListener('scroll', onScroll)
    if (resizeObs) resizeObs.disconnect()
    else window.removeEventListener('resize', refreshViewport)
  })

  // When items collection changes, the previous scrollTop may no longer
  // be valid (e.g. switched directories). Reset the scroll-derived state.
  watch(
    () => opts.items.value,
    () => {
      const el = opts.scrollerRef.value
      if (el && el.scrollTop !== 0) el.scrollTop = 0
      refreshViewport()
    },
  )

  const total = computed(() => opts.items.value.length)
  const totalH = computed(() => total.value * rh())

  const startIndex = computed(() => {
    const top = Math.max(0, scrollTop.value - ho())
    const start = Math.floor(top / rh()) - overscan
    return Math.max(0, start)
  })

  const endIndex = computed(() => {
    const top = Math.max(0, scrollTop.value - ho())
    const visibleCount = Math.ceil(viewportH.value / rh()) + overscan * 2
    return Math.min(total.value, startIndex.value + visibleCount)
  })

  const visibleItems = computed(() => opts.items.value.slice(startIndex.value, endIndex.value))
  const offsetTop = computed(() => startIndex.value * rh())
  const offsetBottom = computed(() => Math.max(0, totalH.value - endIndex.value * rh()))

  return {
    visibleItems,
    startIndex,
    endIndex,
    offsetTop,
    offsetBottom,
    totalH,
    refresh: refreshViewport,
  }
}

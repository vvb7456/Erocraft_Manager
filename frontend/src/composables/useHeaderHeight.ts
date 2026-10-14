import { watch, type Ref } from 'vue'

export function useHeaderHeight(element: Ref<HTMLElement | null>) {
  watch(element, (header, _, onCleanup) => {
    if (!header) return
    const update = () => document.documentElement.style.setProperty('--app-header-h', `${header.offsetHeight}px`)
    const observer = new ResizeObserver(update)
    update()
    observer.observe(header)
    onCleanup(() => {
      observer.disconnect()
      document.documentElement.style.removeProperty('--app-header-h')
    })
  }, { flush: 'post' })
}

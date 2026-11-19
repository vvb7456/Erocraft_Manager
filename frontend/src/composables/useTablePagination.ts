import {
  computed,
  nextTick,
  onScopeDispose,
  ref,
  toValue,
  watch,
  type ComputedRef,
  type MaybeRefOrGetter,
  type Ref,
  type WatchSource,
} from 'vue'

export interface UseClientPaginationOptions {
  initialPerPage?: number
  resetDeps?: WatchSource<unknown>[]
}

export interface UseClientPaginationReturn<T> {
  page: Ref<number>
  perPage: Ref<number>
  totalPages: ComputedRef<number>
  paginated: ComputedRef<T[]>
  resetPage: () => void
  setPerPage: (next: number) => void
}

export function useClientPagination<T>(
  items: MaybeRefOrGetter<readonly T[]>,
  options: UseClientPaginationOptions = {},
): UseClientPaginationReturn<T> {
  const page = ref(1)
  const perPage = ref(options.initialPerPage ?? 20)

  const totalPages = computed(() =>
    Math.max(1, Math.ceil(toValue(items).length / perPage.value)),
  )

  const paginated = computed(() => {
    const list = toValue(items)
    const start = (page.value - 1) * perPage.value
    return list.slice(start, start + perPage.value)
  })

  if (options.resetDeps && options.resetDeps.length > 0) {
    watch(options.resetDeps, () => {
      page.value = 1
    })
  }

  watch(totalPages, (tp) => {
    if (page.value > tp) page.value = tp
  })

  function resetPage() {
    page.value = 1
  }

  function setPerPage(next: number) {
    perPage.value = next
    page.value = 1
  }

  return {
    page,
    perPage,
    totalPages,
    paginated,
    resetPage,
    setPerPage,
  }
}

export interface ServerPaginationFetchContext {
  page: number
  perPage: number
  offset: number
  silent: boolean
  isCurrent: () => boolean
}

export interface ServerPaginationFetchResult {
  total: number
}

export interface UseServerPaginationOptions {
  initialPerPage?: number
  filters?: WatchSource<unknown>[]
  search?: WatchSource<unknown> | WatchSource<unknown>[]
  searchDebounceMs?: number
  enabled?: () => boolean
  onError?: (err: unknown) => void
  immediate?: boolean
}

export interface UseServerPaginationReturn {
  page: Ref<number>
  perPage: Ref<number>
  offset: ComputedRef<number>
  total: Ref<number>
  totalPages: ComputedRef<number>
  loading: Ref<boolean>
  reload: (opts?: { silent?: boolean }) => Promise<void>
  setPerPage: (next: number) => void
  resetStateWithoutFetch: (mutate?: () => void) => void
}

export function useServerPagination(
  fetcher: (ctx: ServerPaginationFetchContext) => Promise<ServerPaginationFetchResult | null | void>,
  options: UseServerPaginationOptions = {},
): UseServerPaginationReturn {
  const page = ref(1)
  const perPage = ref(options.initialPerPage ?? 20)
  const total = ref(0)
  const loading = ref(false)

  const offset = computed(() => (page.value - 1) * perPage.value)
  const totalPages = computed(() => Math.max(1, Math.ceil(total.value / perPage.value)))

  const debounceMs = options.searchDebounceMs ?? 250
  let activeRequestId = 0
  let searchTimer: ReturnType<typeof setTimeout> | null = null
  let suppressCount = 0

  function clearSearchTimer() {
    if (searchTimer !== null) {
      clearTimeout(searchTimer)
      searchTimer = null
    }
  }

  function isEnabled(): boolean {
    return options.enabled ? options.enabled() : true
  }

  async function runFetch(opts: { silent?: boolean } = {}): Promise<void> {
    if (!isEnabled()) return
    const reqId = ++activeRequestId
    const silent = !!opts.silent
    if (!silent) loading.value = true
    try {
      const res = await fetcher({
        page: page.value,
        perPage: perPage.value,
        offset: offset.value,
        silent,
        isCurrent: () => reqId === activeRequestId,
      })
      if (reqId !== activeRequestId) return
      if (res != null) {
        total.value = res.total
        if (page.value > totalPages.value) {
          page.value = totalPages.value
        }
      }
    } catch (err) {
      if (reqId !== activeRequestId) return
      if (options.onError) {
        options.onError(err)
      } else {
        throw err
      }
    } finally {
      // Only the latest request may clear loading so a superseded response
      // never hides the spinner while a newer request is still in flight.
      if (reqId === activeRequestId) {
        loading.value = false
      }
    }
  }

  function triggerResetAndFetch() {
    if (!isEnabled()) return
    if (page.value !== 1) {
      page.value = 1
    } else {
      void runFetch()
    }
  }

  watch([page, perPage], () => {
    if (suppressCount > 0 || !isEnabled()) return
    clearSearchTimer()
    void runFetch()
  })

  if (options.filters && options.filters.length > 0) {
    watch(options.filters, () => {
      if (suppressCount > 0 || !isEnabled()) return
      clearSearchTimer()
      triggerResetAndFetch()
    })
  }

  if (options.search !== undefined) {
    const searchSources = Array.isArray(options.search) ? options.search : [options.search]
    if (searchSources.length > 0) {
      watch(searchSources, () => {
        if (suppressCount > 0 || !isEnabled()) return
        clearSearchTimer()
        searchTimer = setTimeout(() => {
          searchTimer = null
          if (suppressCount > 0 || !isEnabled()) return
          triggerResetAndFetch()
        }, debounceMs)
      })
    }
  }

  function reload(opts?: { silent?: boolean }): Promise<void> {
    clearSearchTimer()
    return runFetch(opts)
  }

  function setPerPage(next: number) {
    perPage.value = next
    page.value = 1
  }

  function resetStateWithoutFetch(mutate?: () => void) {
    clearSearchTimer()
    activeRequestId++
    loading.value = false
    // Keep watchers suppressed until after Vue flushes pre-flush jobs queued
    // by the synchronous mutations below.
    suppressCount++
    page.value = 1
    mutate?.()
    void nextTick(() => {
      suppressCount = Math.max(0, suppressCount - 1)
    })
  }

  onScopeDispose(() => {
    clearSearchTimer()
    activeRequestId++
  })

  if (options.immediate) {
    void runFetch()
  }

  return {
    page,
    perPage,
    offset,
    total,
    totalPages,
    loading,
    reload,
    setPerPage,
    resetStateWithoutFetch,
  }
}

import { ref, type Ref } from 'vue'

export type SortOrder = 'asc' | 'desc'
export type SortValue = string | number | boolean | Date | null | undefined

export interface UseTableSortOptions {
  /** Initial sort column key (default: '') */
  defaultBy?: string
  /** Initial sort direction (default: 'asc') */
  defaultOrder?: SortOrder
  /** Per-column default direction on first click when switching from another column */
  columnDefaultOrders?: Record<string, SortOrder>
  /** Shorthand list of columns whose first click defaults to 'desc' (e.g. timestamps, IDs, counts) */
  descColumns?: string[]
  /** Fallback initial direction for columns not listed above (default: 'asc') */
  fallbackOrder?: SortOrder
  /** Optional callback invoked after sortBy/sortOrder changes (e.g. reset page = 1) */
  onSortChange?: (sortBy: string, sortOrder: SortOrder) => void
}

export interface SortItemsOptions<T> {
  tieBreaker?: (a: T, b: T) => number
}

export interface UseTableSortReturn {
  sortBy: Ref<string>
  sortOrder: Ref<SortOrder>
  toggleSort: (col: string, initialOrder?: SortOrder) => void
  sortItems: <T>(
    items: readonly T[],
    getters: Record<string, (item: T) => SortValue>,
    options?: SortItemsOptions<T>,
  ) => T[]
}

const ISO_DATE_RE =
  /^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?$/

const collator = new Intl.Collator(['zh-CN', 'en'], {
  numeric: true,
  sensitivity: 'base',
})

function isEmptySortValue(v: SortValue): boolean {
  return v === null || v === undefined || v === '' || (typeof v === 'number' && Number.isNaN(v))
}

function tryParseIsoTimestamp(v: string): number | null {
  if (!ISO_DATE_RE.test(v)) return null
  const normalized = v.includes(' ') ? v.replace(' ', 'T') : v
  const ms = Date.parse(normalized)
  return Number.isNaN(ms) ? null : ms
}

/**
 * Compare two cell values. Empty values (null / undefined / '' / NaN) are always
 * placed at the end regardless of sort direction.
 */
export function compareSortValues(a: SortValue, b: SortValue, order: SortOrder): number {
  const aEmpty = isEmptySortValue(a)
  const bEmpty = isEmptySortValue(b)
  if (aEmpty && bEmpty) return 0
  if (aEmpty) return 1
  if (bEmpty) return -1

  const dir = order === 'asc' ? 1 : -1

  if (a instanceof Date && b instanceof Date) {
    const diff = a.getTime() - b.getTime()
    return diff === 0 ? 0 : diff < 0 ? -dir : dir
  }

  if (typeof a === 'number' && typeof b === 'number') {
    if (a === b) return 0
    return a < b ? -dir : dir
  }

  if (typeof a === 'boolean' && typeof b === 'boolean') {
    if (a === b) return 0
    return (Number(a) - Number(b)) * dir
  }

  if (typeof a === 'string' && typeof b === 'string') {
    const ta = tryParseIsoTimestamp(a)
    const tb = tryParseIsoTimestamp(b)
    if (ta !== null && tb !== null) {
      if (ta === tb) return 0
      return ta < tb ? -dir : dir
    }
    return collator.compare(a, b) * dir
  }

  return collator.compare(String(a), String(b)) * dir
}

export function sortItemsBy<T>(
  items: readonly T[],
  sortBy: string,
  sortOrder: SortOrder,
  getters: Record<string, (item: T) => SortValue>,
  options?: SortItemsOptions<T>,
): T[] {
  const getter = sortBy ? getters[sortBy] : undefined
  if (!getter) return [...items]

  const list = [...items]
  list.sort((a, b) => {
    const cmp = compareSortValues(getter(a), getter(b), sortOrder)
    if (cmp !== 0) return cmp
    return options?.tieBreaker ? options.tieBreaker(a, b) : 0
  })
  return list
}

export function useTableSort(options: UseTableSortOptions = {}): UseTableSortReturn {
  const sortBy = ref<string>(options.defaultBy ?? '')
  const sortOrder = ref<SortOrder>(options.defaultOrder ?? 'asc')
  const descSet = new Set(options.descColumns ?? [])
  const colDefaults = options.columnDefaultOrders ?? {}
  const fallbackOrder: SortOrder = options.fallbackOrder ?? 'asc'

  function getInitialOrder(col: string, explicit?: SortOrder): SortOrder {
    if (explicit) return explicit
    if (col in colDefaults) return colDefaults[col]!
    if (descSet.has(col)) return 'desc'
    return fallbackOrder
  }

  function toggleSort(col: string, initialOrder?: SortOrder) {
    if (sortBy.value === col) {
      sortOrder.value = sortOrder.value === 'asc' ? 'desc' : 'asc'
    } else {
      sortBy.value = col
      sortOrder.value = getInitialOrder(col, initialOrder)
    }
    options.onSortChange?.(sortBy.value, sortOrder.value)
  }

  function sortItems<T>(
    items: readonly T[],
    getters: Record<string, (item: T) => SortValue>,
    sortOptions?: SortItemsOptions<T>,
  ): T[] {
    return sortItemsBy(items, sortBy.value, sortOrder.value, getters, sortOptions)
  }

  return {
    sortBy,
    sortOrder,
    toggleSort,
    sortItems,
  }
}

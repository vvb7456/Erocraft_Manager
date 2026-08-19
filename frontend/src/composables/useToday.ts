// Reactive "today" date string (YYYY-MM-DD) in the system-configured timezone
// (appStore.timezone, sourced from /api/version). Mirrors the backend
// `local_today(TIMEZONE)` so frontend "today" / daysLeft / renew-default-date
// computations stay aligned with the backend regardless of the browser's
// own timezone.
//
// Re-evaluates on the shared useNow tick (1s); Vue's computed memoization
// ensures downstream dependents only re-compute when the returned string
// actually changes (i.e. at most once per day at local midnight).

import { computed, type Ref } from 'vue'
import { useAppStore } from '@/stores/app'
import { useNow } from '@/composables/useNow'

function todayIn(tz: string, ref: number): string {
  // `ref` is read so the computed re-evaluates on each tick; the value is
  // discarded — only the formatted date matters.
  void ref
  try {
    return new Intl.DateTimeFormat('en-CA', {
      timeZone: tz,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    }).format(new Date())
  } catch {
    return new Intl.DateTimeFormat('en-CA', {
      timeZone: 'UTC',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    }).format(new Date())
  }
}

export function useToday(): Ref<string> {
  const appStore = useAppStore()
  const now = useNow()
  return computed(() => todayIn(appStore.timezone, now.value))
}
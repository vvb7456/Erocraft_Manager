import { useI18n } from 'vue-i18n'
import { useAppStore } from '@/stores/app'

export function useFormatDate() {
  const { locale } = useI18n({ useScope: 'global' })
  const appStore = useAppStore()

  function formatDateTime(iso: string | null): string {
    if (!iso) return '—'
    try {
      return new Date(iso).toLocaleString(locale.value, {
        timeZone: appStore.timezone,
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      })
    } catch {
      return iso
    }
  }

  function formatDate(iso: string | null): string {
    if (!iso) return '—'
    try {
      return new Date(iso).toLocaleDateString(locale.value, {
        timeZone: appStore.timezone,
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
      })
    } catch {
      return iso
    }
  }

  return { formatDateTime, formatDate }
}

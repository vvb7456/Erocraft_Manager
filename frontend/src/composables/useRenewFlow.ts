/**
 * useRenewFlow — singleton composable managing the user-side renewal modal.
 *
 * One ``CreateOrderModal`` instance lives in the app shell (mounted by
 * ``RenewFlowProvider``); any page or component can call ``openRenew(target)``
 * to fetch the bound plan and pop the modal.
 *
 * Module-scope refs keep state shared across all consumers — no provide/inject
 * needed. The provider component just binds these refs into the modal props.
 *
 * See: docs/BILLING_FRONTEND_DESIGN_RenewFlow.md
 */

import { ref, type Ref } from 'vue'
import { useApiFetch } from './useApiFetch'
import { useToast } from './useToast'
import { useI18n } from 'vue-i18n'

export interface RenewPeriodOption {
  count: number
  discount_pct: number
}

export interface RenewPlan {
  id: number
  code: string
  display_name: string
  description_md: string | null
  category_label: string | null
  price_fen: number
  days: number
  currency_code: string
  period_options: RenewPeriodOption[]
  cpu: number
  memory_mb: number
  disk_mb: number
}

export interface RenewTarget {
  serverId: number
  serverName: string
  planId: number
}

// ── Global singleton state (HMR-safe across module reloads) ──
type RenewFlowState = {
  open: Ref<boolean>
  plan: Ref<RenewPlan | null>
  targetServerId: Ref<number | null>
  serverName: Ref<string>
  loading: Ref<boolean>
}

const g = globalThis as typeof globalThis & {
  __erocraftRenewFlowState?: RenewFlowState
}

const state: RenewFlowState = g.__erocraftRenewFlowState ?? {
  open: ref(false),
  plan: ref<RenewPlan | null>(null),
  targetServerId: ref<number | null>(null),
  serverName: ref<string>(''),
  loading: ref(false),
}

g.__erocraftRenewFlowState = state

export function useRenewFlow() {
  const { get } = useApiFetch()
  const { toast } = useToast()
  const { t } = useI18n({ useScope: 'global' })

  async function openRenew(target: RenewTarget): Promise<void> {
    if (state.loading.value) return
    state.loading.value = true
    try {
      const data = await get<RenewPlan>(
        `/api/user/plans/${target.planId}`,
        { silent: true },
      )
      if (!data) {
        toast(t('userServers.renewFlow.planLoadFailed'), 'error')
        return
      }
      state.plan.value = data
      state.targetServerId.value = target.serverId
      state.serverName.value = target.serverName
      state.open.value = true
    } catch {
      // Keep a visible user feedback path even if fetch/composable internals throw unexpectedly.
      toast(t('userServers.renewFlow.planLoadFailed'), 'error')
    } finally {
      state.loading.value = false
    }
  }

  return {
    open: state.open,
    plan: state.plan,
    targetServerId: state.targetServerId,
    serverName: state.serverName,
    loading: state.loading,
    openRenew,
  }
}

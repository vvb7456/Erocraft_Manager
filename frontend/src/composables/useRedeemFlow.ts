import { ref, type Ref } from 'vue'

type RedeemFlowState = {
  open: Ref<boolean>
  redeemedTick: Ref<number>
}

const g = globalThis as typeof globalThis & {
  __erocraftRedeemFlowState?: RedeemFlowState
}

const state: RedeemFlowState = g.__erocraftRedeemFlowState ?? {
  open: ref(false),
  redeemedTick: ref(0),
}

g.__erocraftRedeemFlowState = state

export function useRedeemFlow() {
  function openRedeem() {
    state.open.value = true
  }

  function notifyRedeemed() {
    state.redeemedTick.value += 1
  }

  return {
    open: state.open,
    redeemedTick: state.redeemedTick,
    openRedeem,
    notifyRedeemed,
  }
}

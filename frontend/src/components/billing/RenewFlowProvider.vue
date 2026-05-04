<script setup lang="ts">
/**
 * RenewFlowProvider — global mount point for the user-side renewal modal.
 *
 * Place once near the app root. Any page or component can call
 * ``useRenewFlow().openRenew(target)`` to fetch the bound plan and pop
 * the cashier modal in renew mode.
 *
 * See: docs/BILLING_FRONTEND_DESIGN_RenewFlow.md
 */
import { useRenewFlow } from '@/composables/useRenewFlow'
import CreateOrderModal from '@/components/CreateOrderModal.vue'

defineOptions({ name: 'RenewFlowProvider' })

const { open, plan, targetServerId, serverName } = useRenewFlow()
</script>

<template>
  <CreateOrderModal
    v-model="open"
    mode="renew"
    :plan="plan"
    :target-server-id="targetServerId"
    :server-name="serverName"
  />
</template>

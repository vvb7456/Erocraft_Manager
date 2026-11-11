<script setup lang="ts">
/**
 * UserOrdersPage — `/orders`
 */
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import PageHeader from '@/components/layout/PageHeader.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import UserOrdersListTab from '@/components/billing/UserOrdersListTab.vue'
import { useRedeemFlow } from '@/composables/useRedeemFlow'

defineOptions({ name: 'UserOrdersPage' })

const { t } = useI18n({ useScope: 'global' })
const { openRedeem, redeemedTick } = useRedeemFlow()

const ordersTabRef = ref<InstanceType<typeof UserOrdersListTab> | null>(null)

watch(redeemedTick, () => {
  ordersTabRef.value?.reload()
})
</script>

<template>
  <PageHeader icon="receipt_long" :title="t('billing.orders.pageTitle')">
    <template #controls>
      <BaseButton size="sm" variant="primary" @click="openRedeem()">
        <MsIcon name="redeem" size="xs" />{{ t('billing.redeem.openBtn') }}
      </BaseButton>
    </template>
  </PageHeader>

  <div class="page-body">
    <UserOrdersListTab ref="ordersTabRef" />
  </div>
</template>

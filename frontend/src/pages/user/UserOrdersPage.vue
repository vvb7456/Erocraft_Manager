<script setup lang="ts">
/**
 * UserOrdersPage — `/orders`
 *
 * Plain orders list. Coupons + invite have been moved out to
 * `/promotions` (sidebar entry "Rewards & Referrals").
 */
import { useI18n } from 'vue-i18n'
import PageHeader from '@/components/layout/PageHeader.vue'
import UserOrdersListTab from '@/components/billing/UserOrdersListTab.vue'

defineOptions({ name: 'UserOrdersPage' })

const { t } = useI18n({ useScope: 'global' })
</script>

<template>
  <PageHeader icon="receipt_long" :title="t('billing.orders.pageTitle')" />

  <div class="page-body">
    <UserOrdersListTab />
  </div>
</template>

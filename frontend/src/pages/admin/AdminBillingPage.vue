<script setup lang="ts">
/**
 * AdminBillingPage — `/admin/billing`
 *
 * Unified billing entry point with TabSwitcher:
 *   - 订单管理 → OrdersTab + OrderDetailModal
 *   - 套餐设置 → AdminPlansPage embedded
 */
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import PageHeader from '@/components/layout/PageHeader.vue'
import TabSwitcher from '@/components/ui/TabSwitcher.vue'
import AdminPlansPage from '@/pages/admin/AdminPlansPage.vue'
import OrdersTab from '@/pages/admin/billing/OrdersTab.vue'
import OrderDetailModal from '@/pages/admin/billing/OrderDetailModal.vue'

defineOptions({ name: 'AdminBillingPage' })

const { t } = useI18n({ useScope: 'global' })

const activeTab = ref('orders')
const detailOrderId = ref<number | null>(null)
const detailOpen = ref(false)

function onSelectOrder(orderId: number) {
  detailOrderId.value = orderId
  detailOpen.value = true
}

function onDetailSaved() {
  // refresh orders list after an action
}

const tabs = [
  { key: 'orders', icon: 'receipt_long', label: t('billing.admin.tabOrders') },
  { key: 'plans',  icon: 'local_offer',  label: t('billing.admin.tabPlans') },
]
</script>

<template>
  <PageHeader icon="receipt_long" :title="t('billing.admin.title')" />

  <div class="page-body">
    <TabSwitcher v-model="activeTab" :tabs="tabs" />

    <div class="tab-content">
      <OrdersTab v-if="activeTab === 'orders'" @select-order="onSelectOrder" />
      <AdminPlansPage v-else-if="activeTab === 'plans'" :standalone="false" />
    </div>
  </div>

  <OrderDetailModal
    v-model="detailOpen"
    :order-id="detailOrderId"
    @saved="onDetailSaved"
  />
</template>

<style scoped>
.tab-content {
  margin-top: var(--sp-4);
}
</style>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '@/components/layout/PageHeader.vue'
import OrdersTab from '@/pages/admin/billing/OrdersTab.vue'
import OrderDetailModal from '@/pages/admin/billing/OrderDetailModal.vue'

defineOptions({ name: 'AdminOrdersPage' })

const { t } = useI18n({ useScope: 'global' })
const route = useRoute()
const router = useRouter()

const detailOrderId = computed(() => {
  const value = route.query.order
  const id = typeof value === 'string' && /^\d+$/.test(value) ? Number(value) : 0
  return Number.isSafeInteger(id) && id > 0 ? id : null
})

const detailOpen = computed({
  get: () => detailOrderId.value !== null,
  set: (open) => {
    if (!open) void router.replace({ query: { ...route.query, order: undefined } })
  },
})

function onSelectOrder(orderId: number) {
  void router.push({ query: { ...route.query, order: orderId } })
}
</script>

<template>
  <PageHeader icon="receipt_long" :title="t('nav.adminOrders')" />

  <div class="page-body">
    <OrdersTab @select-order="onSelectOrder" />
  </div>

  <OrderDetailModal
    v-model="detailOpen"
    :order-id="detailOrderId"
  />
</template>

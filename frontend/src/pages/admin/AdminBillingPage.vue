<script setup lang="ts">
/**
 * AdminBillingPage — `/admin/billing`
 *
 * Unified billing entry point with TabSwitcher:
 *   - 订单管理 → OrdersTab + OrderDetailModal
 *   - 套餐设置 → AdminPlansPage embedded
 *   - 优惠券模板 → AdminCouponTemplatesTab
 *   - 已发券 → AdminCouponsTab (supports ?action=grant)
 *
 * Selects active tab from ``?tab=…`` query and keeps the URL in sync.
 */
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '@/components/layout/PageHeader.vue'
import TabSwitcher from '@/components/ui/TabSwitcher.vue'
import AdminPlansPage from '@/pages/admin/AdminPlansPage.vue'
import OrdersTab from '@/pages/admin/billing/OrdersTab.vue'
import OrderDetailModal from '@/pages/admin/billing/OrderDetailModal.vue'
import AdminCouponTemplatesTab from '@/pages/admin/billing/AdminCouponTemplatesTab.vue'
import AdminCouponsTab from '@/pages/admin/billing/AdminCouponsTab.vue'

defineOptions({ name: 'AdminBillingPage' })

const { t } = useI18n({ useScope: 'global' })
const route = useRoute()
const router = useRouter()

type TabKey = 'orders' | 'plans' | 'coupon-templates' | 'coupons'
const VALID_TABS: TabKey[] = ['orders', 'plans', 'coupon-templates', 'coupons']

function pickInitial(): TabKey {
  const q = route.query.tab
  const raw = Array.isArray(q) ? q[0] : q
  if (raw && (VALID_TABS as string[]).includes(raw)) return raw as TabKey
  return 'orders'
}

const activeTab = ref<TabKey>(pickInitial())
const detailOrderId = ref<number | null>(null)
const detailOpen = ref(false)

// Whether the coupons tab should auto-open the grant modal on mount.
const couponsInitialAction = computed<'grant' | null>(() =>
  activeTab.value === 'coupons' && route.query.action === 'grant' ? 'grant' : null,
)

function onSelectOrder(orderId: number) {
  detailOrderId.value = orderId
  detailOpen.value = true
}

function onDetailSaved() {
  // refresh orders list after an action
}

const tabs = computed(() => [
  { key: 'orders',           icon: 'receipt_long',        label: t('billing.admin.tabOrders') },
  { key: 'plans',            icon: 'local_offer',         label: t('billing.admin.tabPlans') },
  { key: 'coupon-templates', icon: 'confirmation_number', label: t('billing.admin.tabCouponTemplates') },
  { key: 'coupons',          icon: 'card_giftcard',       label: t('billing.admin.tabCoupons') },
])

watch(activeTab, (next) => {
  const current = route.query.tab
  if (current !== next) {
    void router.replace({
      query: { ...route.query, tab: next, action: undefined },
    })
  }
})

onMounted(() => {
  if (route.query.tab !== activeTab.value) {
    void router.replace({ query: { ...route.query, tab: activeTab.value } })
  }
})
</script>

<template>
  <PageHeader icon="receipt_long" :title="t('billing.admin.title')" />

  <div class="page-body">
    <TabSwitcher v-model="activeTab" :tabs="tabs" />

    <div class="tab-content">
      <OrdersTab v-if="activeTab === 'orders'" @select-order="onSelectOrder" />
      <AdminPlansPage v-else-if="activeTab === 'plans'" :standalone="false" />
      <AdminCouponTemplatesTab v-else-if="activeTab === 'coupon-templates'" />
      <AdminCouponsTab v-else-if="activeTab === 'coupons'" :initial-action="couponsInitialAction" />
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

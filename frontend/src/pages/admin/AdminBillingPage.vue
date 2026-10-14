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
import { computed } from 'vue'
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
  if (detailOrderId.value !== null) return 'orders'
  const q = route.query.tab
  const raw = Array.isArray(q) ? q[0] : q
  if (raw && (VALID_TABS as string[]).includes(raw)) return raw as TabKey
  return 'orders'
}

const activeTab = computed<TabKey>({
  get: pickInitial,
  set: tab => { void router.push({ query: { ...route.query, tab, action: undefined, order: undefined } }) },
})
const detailOrderId = computed(() => {
  const value = route.query.order
  const id = typeof value === 'string' && /^\d+$/.test(value) ? Number(value) : 0
  return Number.isSafeInteger(id) && id > 0 ? id : null
})
const detailOpen = computed({
  get: () => detailOrderId.value !== null,
  set: open => { if (!open) void router.replace({ query: { ...route.query, order: undefined } }) },
})

// Whether the coupons tab should auto-open the grant modal on mount.
const couponsInitialAction = computed<'grant' | null>(() =>
  activeTab.value === 'coupons' && route.query.action === 'grant' ? 'grant' : null,
)

function onSelectOrder(orderId: number) {
  void router.push({ query: { ...route.query, tab: 'orders', order: orderId, action: undefined } })
}

const tabs = computed(() => [
  { key: 'orders',           icon: 'receipt_long',        label: t('billing.admin.tabOrders') },
  { key: 'plans',            icon: 'local_offer',         label: t('billing.admin.tabPlans') },
  { key: 'coupon-templates', icon: 'confirmation_number', label: t('billing.admin.tabCouponTemplates') },
  { key: 'coupons',          icon: 'card_giftcard',       label: t('billing.admin.tabCoupons') },
])

</script>

<template>
  <PageHeader icon="receipt_long" :title="t('billing.admin.title')">
    <TabSwitcher v-model="activeTab" :tabs="tabs" />
  </PageHeader>

  <div class="page-body">
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
  />
</template>

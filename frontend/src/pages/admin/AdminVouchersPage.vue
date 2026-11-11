<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '@/components/layout/PageHeader.vue'
import TabSwitcher from '@/components/ui/TabSwitcher.vue'
import AdminCouponTemplatesTab from '@/pages/admin/billing/AdminCouponTemplatesTab.vue'
import AdminCouponsTab from '@/pages/admin/billing/AdminCouponsTab.vue'
import AdminRedemptionBatchesTab from '@/pages/admin/billing/AdminRedemptionBatchesTab.vue'

defineOptions({ name: 'AdminVouchersPage' })

const { t } = useI18n({ useScope: 'global' })
const route = useRoute()
const router = useRouter()

type TabKey = 'redemption-batches' | 'coupon-templates' | 'coupons'
const VALID_TABS: TabKey[] = ['redemption-batches', 'coupon-templates', 'coupons']

function pickInitial(): TabKey {
  const q = route.query.tab
  const raw = Array.isArray(q) ? q[0] : q
  if (raw && (VALID_TABS as string[]).includes(raw)) return raw as TabKey
  return 'redemption-batches'
}

const activeTab = computed<TabKey>({
  get: pickInitial,
  set: (tab) => {
    void router.push({ query: { ...route.query, tab, action: undefined } })
  },
})

const couponsInitialAction = computed<'grant' | null>(() =>
  activeTab.value === 'coupons' && route.query.action === 'grant' ? 'grant' : null,
)

const tabs = computed(() => [
  { key: 'redemption-batches', icon: 'redeem',              label: t('billing.admin.tabRedemptionBatches') },
  { key: 'coupon-templates',   icon: 'confirmation_number', label: t('billing.admin.tabCouponTemplates') },
  { key: 'coupons',            icon: 'card_giftcard',       label: t('billing.admin.tabCoupons') },
])
</script>

<template>
  <PageHeader icon="confirmation_number" :title="t('nav.adminVouchers')">
    <TabSwitcher v-model="activeTab" :tabs="tabs" />
  </PageHeader>

  <div class="page-body">
    <div class="tab-content">
      <AdminRedemptionBatchesTab v-if="activeTab === 'redemption-batches'" />
      <AdminCouponTemplatesTab v-else-if="activeTab === 'coupon-templates'" />
      <AdminCouponsTab v-else-if="activeTab === 'coupons'" :initial-action="couponsInitialAction" />
    </div>
  </div>
</template>

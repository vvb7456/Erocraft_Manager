<script setup lang="ts">
/**
 * UserOrdersPage — `/orders` (also reachable via `/coupons` and `/invite`
 * aliases that mount this same page and select the corresponding tab).
 *
 * Per design doc §8.1 the sidebar stays slim: coupons + invite-a-friend
 * are tabs inside the billing page rather than top-level menu entries.
 * The `?tab=` query param syncs both directions so bookmark + email links
 * (e.g. `/orders?tab=invite`) land on the right tab.
 */
import { computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '@/components/layout/PageHeader.vue'
import TabSwitcher from '@/components/ui/TabSwitcher.vue'
import UserOrdersListTab from '@/components/billing/UserOrdersListTab.vue'
import UserCouponsTab from '@/components/billing/UserCouponsTab.vue'
import UserInviteTab from '@/components/billing/UserInviteTab.vue'

defineOptions({ name: 'UserOrdersPage' })

type TabKey = 'orders' | 'coupons' | 'invite'

const { t } = useI18n({ useScope: 'global' })
const route = useRoute()
const router = useRouter()

function pickInitialTab(): TabKey {
  if (route.path === '/coupons') return 'coupons'
  if (route.path === '/invite') return 'invite'
  const q = String(route.query.tab || '')
  if (q === 'coupons' || q === 'invite') return q
  return 'orders'
}

const activeTab = computed<TabKey>({
  get() { return pickInitialTab() },
  set(v) {
    router.replace({ path: '/orders', query: v === 'orders' ? {} : { tab: v } })
  },
})

const tabs = computed(() => [
  { key: 'orders',  icon: 'receipt_long',         label: t('billing.orders.tab') },
  { key: 'coupons', icon: 'confirmation_number',  label: t('billing.coupons.tab') },
  { key: 'invite',  icon: 'group_add',            label: t('billing.invite.tab') },
])

onMounted(() => {
  if (route.path === '/coupons') router.replace({ path: '/orders', query: { tab: 'coupons' } })
  else if (route.path === '/invite') router.replace({ path: '/orders', query: { tab: 'invite' } })
})
</script>

<template>
  <PageHeader icon="receipt_long" :title="t('billing.pageTitle')" />

  <div class="page-body">
    <TabSwitcher v-model="activeTab" :tabs="tabs" />

    <div class="tab-content">
      <UserOrdersListTab v-if="activeTab === 'orders'" />
      <UserCouponsTab    v-else-if="activeTab === 'coupons'" />
      <UserInviteTab     v-else-if="activeTab === 'invite'" />
    </div>
  </div>
</template>

<style scoped>
.tab-content {
  margin-top: var(--sp-4);
}
</style>

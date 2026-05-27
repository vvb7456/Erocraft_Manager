<script setup lang="ts">
/**
 * UserPlansPage — `/plans`
 *
 * Browses active billing plans, grouped by ``category_label`` (admin-set
 * UI label, decoupled from egg). Plans without a label fall into a final
 * "其他" / "Others" section. Clicking "Buy now" posts to
 * ``POST /api/user/orders`` and redirects to ``/orders/:id``.
 */
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useApiFetch } from '@/composables/useApiFetch'
import PageHeader from '@/components/layout/PageHeader.vue'
import SectionHeader from '@/components/ui/SectionHeader.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import LoadingCenter from '@/components/ui/LoadingCenter.vue'
import AlertBanner from '@/components/ui/AlertBanner.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import SupportModal from '@/components/billing/SupportModal.vue'
import PlanCard from '@/components/PlanCard.vue'
import CreateOrderModal from '@/components/CreateOrderModal.vue'

defineOptions({ name: 'UserPlansPage' })

interface PeriodOption {
  count: number
  discount_pct: number
}

interface Plan {
  id: number
  code: string
  display_name: string
  price_fen: number
  days: number
  currency_code: string
  period_options: PeriodOption[]
  cpu: number
  memory_mb: number
  disk_mb: number
  description_md: string | null
  category_label: string | null
  display_order: number
  created_at: string
  updated_at: string
}

interface PlanGroup {
  label: string | null
  plans: Plan[]
}

const { t } = useI18n({ useScope: 'global' })
const { get } = useApiFetch()
const router = useRouter()

const plans = ref<Plan[]>([])
const initialLoading = ref(true)
const loadFailed = ref(false)

// Cashier modal state
const cashierOpen = ref(false)
const cashierPlan = ref<Plan | null>(null)
const cashierPeriodCount = ref<number | undefined>(undefined)

// Support modal state
const supportOpen = ref(false)

/** Group plans by category_label, preserving display_order within each group. */
const groups = computed<PlanGroup[]>(() => {
  const map = new Map<string, PlanGroup>()
  const order: string[] = []

  for (const p of plans.value) {
    const key = p.category_label ?? '__uncategorised__'
    if (!map.has(key)) {
      map.set(key, { label: p.category_label, plans: [] })
      order.push(key)
    }
    map.get(key)!.plans.push(p)
  }

  // Push uncategorised group to the bottom
  const idx = order.indexOf('__uncategorised__')
  if (idx !== -1 && idx !== order.length - 1) {
    order.splice(idx, 1)
    order.push('__uncategorised__')
  }

  return order.map((k) => map.get(k)!)
})

async function loadPlans() {
  loadFailed.value = false
  const data = await get<Plan[]>('/api/user/plans', { silent: true })
  if (data === null) {
    loadFailed.value = true
  } else {
    plans.value = data
  }
  initialLoading.value = false
}

async function handleBuy(plan: Plan, period: PeriodOption) {
  cashierPlan.value = plan
  cashierPeriodCount.value = period.count
  cashierOpen.value = true
}

onMounted(loadPlans)
</script>

<template>
  <PageHeader icon="storefront" :title="t('billing.plans.pageTitle')" />

  <div class="plans-page">
    <LoadingCenter v-if="initialLoading" />

    <AlertBanner v-else-if="loadFailed" tone="danger">
      <div class="plans-page__error">
        <span>{{ t('billing.plans.loadFailed') }}</span>
        <BaseButton size="sm" variant="primary" @click="loadPlans">
          {{ t('billing.plans.retry') }}
        </BaseButton>
      </div>
    </AlertBanner>

    <EmptyState
      v-else-if="plans.length === 0"
      icon="inventory_2"
      :title="t('billing.plans.emptyTitle')"
      :message="t('billing.plans.emptyHint')"
    >
      <BaseButton variant="default" @click="router.push({ name: 'user-servers' })">
        <MsIcon name="dns" />
        {{ t('nav.myServers') }}
      </BaseButton>
      <BaseButton variant="primary" @click="supportOpen = true">
        <MsIcon name="support_agent" />
        {{ t('nav.contactSupport') }}
      </BaseButton>
    </EmptyState>

    <template v-else>
      <section
        v-for="(group, idx) in groups"
        :key="group.label ?? '__uncategorised__'"
        class="plans-page__group"
      >
        <SectionHeader align="center" with-lines :flush="idx === 0">
          {{ group.label ?? t('billing.plans.uncategorised') }}
        </SectionHeader>
        <div class="plans-grid">
          <PlanCard
            v-for="plan in group.plans"
            :key="plan.id"
            :plan="plan"
            @buy="handleBuy"
          />
        </div>
      </section>
      <div class="plans-page__support">
        <span class="support-hint">
          {{ t('billing.plans.supportHint') }}
          <a href="#" class="support-link" @click.prevent="supportOpen = true">
            {{ t('billing.plans.supportLink') }}
          </a>
        </span>
      </div>
    </template>

    <CreateOrderModal
      v-model="cashierOpen"
      :plan="cashierPlan"
      :default-period-count="cashierPeriodCount"
    />

    <SupportModal v-model="supportOpen" />
  </div>
</template>

<style scoped>
.plans-page {
  padding: var(--sp-5) var(--sp-6);
  max-width: 1320px;
  margin: 0 auto;
  min-height: calc(100vh - 64px);
  min-height: calc(100dvh - 64px);
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.plans-page__error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  width: 100%;
}

.plans-page__group + .plans-page__group {
  margin-top: var(--sp-8);
}

.plans-page__support {
  display: flex;
  justify-content: center;
  margin-top: var(--sp-5);
}

.support-hint {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1);
  font-size: var(--text-sm);
  color: var(--t2);
}

.support-link {
  color: var(--ac);
  text-decoration: none;
  cursor: pointer;
}

.support-link:hover {
  text-decoration: underline;
}

.plans-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 360px));
  gap: var(--sp-6);
  align-items: stretch;
  justify-content: center;
}

@media (max-width: 768px) {
  .plans-page {
    padding: var(--sp-4) var(--sp-3);
  }

  .plans-grid {
    grid-template-columns: minmax(0, 1fr);
    gap: var(--sp-4);
  }
}
</style>

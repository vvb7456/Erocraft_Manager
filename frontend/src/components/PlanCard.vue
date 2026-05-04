<script setup lang="ts" generic="P extends {
  id: number
  display_name: string
  price_fen: number
  days: number
  currency_code: string
  period_options: { count: number; discount_pct: number }[]
  cpu: number
  memory_mb: number
  disk_mb: number
  description_md: string | null
}">
/**
 * PlanCard — single billing plan tile used by UserPlansPage.
 *
 * Shows a plan's name, base price, resources and a "Buy now" CTA. Period
 * selection happens in the cashier modal (CreateOrderModal), not here.
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import BaseCard from '@/components/ui/BaseCard.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import MsIcon from '@/components/ui/MsIcon.vue'

defineOptions({ name: 'PlanCard' })

interface PeriodOption {
  count: number
  discount_pct: number
}

interface Plan {
  id: number
  display_name: string
  price_fen: number
  days: number
  currency_code: string
  period_options: PeriodOption[]
  cpu: number
  memory_mb: number
  disk_mb: number
  description_md: string | null
}

const props = defineProps<{
  plan: P
  loading?: boolean
  disabled?: boolean
}>()

const emit = defineEmits<{
  buy: [plan: P, period: PeriodOption]
}>()

const { t } = useI18n({ useScope: 'global' })

// Card always advertises the base (1×) price; multi-period discounts surface in the cashier.
const basePeriod = computed<PeriodOption>(() => ({ count: 1, discount_pct: 0 }))

function fenToYuan(fen: number): string {
  return (fen / 100).toFixed(2)
}

const cpuLabel = computed(() => formatResource(props.plan.cpu / 100))
const memLabel = computed(() => formatResource(props.plan.memory_mb / 1024))
const diskLabel = computed(() => formatResource(props.plan.disk_mb / 1024))

function formatResource(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}

function onBuy() {
  emit('buy', props.plan, basePeriod.value)
}
</script>

<template>
  <BaseCard variant="bg2" radius="lg" class="plan-card">
    <div class="plan-card__inner">
      <div class="plan-card__head">
        <h3 class="plan-card__name">{{ plan.display_name }}</h3>
      </div>

      <div class="plan-card__price-block">
        <div class="plan-card__price-main">
          <span class="plan-card__currency">¥</span>
          <span class="plan-card__amount">{{ fenToYuan(plan.price_fen) }}</span>
          <span class="plan-card__unit">
            {{ t('billing.plans.perBaseDays', { days: plan.days }) }}
          </span>
        </div>
      </div>

      <div class="plan-card__divider" />

      <ul class="plan-card__resources">
        <li class="plan-card__res-row">
          <MsIcon name="developer_board" size="sm" />
          <span>{{ t('billing.plans.resCpu', { n: cpuLabel }) }}</span>
        </li>
        <li class="plan-card__res-row">
          <MsIcon name="memory" size="sm" />
          <span>{{ t('billing.plans.resMemory', { n: memLabel }) }}</span>
        </li>
        <li class="plan-card__res-row">
          <MsIcon name="storage" size="sm" />
          <span>{{ t('billing.plans.resDisk', { n: diskLabel }) }}</span>
        </li>
      </ul>

      <p v-if="plan.description_md" class="plan-card__desc">
        {{ plan.description_md }}
      </p>

      <div class="plan-card__cta">
        <BaseButton
          variant="primary"
          size="lg"
          :loading="loading"
          :disabled="disabled"
          @click="onBuy"
        >
          {{ t('billing.plans.buyNow') }}
          <MsIcon name="arrow_forward" size="sm" />
        </BaseButton>
      </div>
    </div>
  </BaseCard>
</template>

<style scoped>
.plan-card {
  height: 100%;
  display: flex;
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}

.plan-card:hover {
  transform: translateY(-2px);
  border-color: var(--bd-f);
  box-shadow: 0 6px 18px rgba(20, 184, 166, 0.12);
}

.plan-card__inner {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  width: 100%;
}

.plan-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-2);
}

.plan-card__name {
  margin: 0;
  font-size: var(--text-xl);
  font-weight: 600;
  color: var(--t1);
  line-height: 1.3;
}

.plan-card__price-block {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}

.plan-card__price-main {
  display: flex;
  align-items: baseline;
  gap: var(--sp-1);
  color: var(--ac);
}

.plan-card__currency {
  font-size: 1rem;
  font-weight: 600;
}

.plan-card__amount {
  font-size: 1.85rem;
  font-weight: 700;
  font-family: 'IBM Plex Mono', monospace;
  letter-spacing: -0.02em;
}

.plan-card__unit {
  font-size: var(--text-sm);
  color: var(--t2);
  font-weight: 500;
}

.plan-card__divider {
  height: 1px;
  background: var(--bd);
  margin: var(--sp-2) 0;
}

.plan-card__resources {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.plan-card__res-row {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: var(--text-base);
  color: var(--t1);
}

.plan-card__res-row :deep(.ms) {
  color: var(--ac2);
}

.plan-card__desc {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--t2);
  line-height: 1.55;
  white-space: pre-line;
  display: -webkit-box;
  -webkit-line-clamp: 4;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.plan-card__cta {
  margin-top: auto;
  padding-top: var(--sp-2);
}

.plan-card__cta :deep(.base-btn) {
  width: 100%;
  justify-content: center;
}
</style>

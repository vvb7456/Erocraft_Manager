<script setup lang="ts">
/**
 * CreateOrderModal — universal cashier modal.
 *
 * Two modes share this component:
 *   - ``mode='new_purchase'`` (default): launched from PlanCard. Submits
 *     ``{ kind: 'new_purchase', plan_code, period_count, gateway_code }``.
 *   - ``mode='renew'``: launched from any "renew" button on user-server
 *     surfaces. Submits ``{ kind: 'renew', target_server_id, period_count,
 *     gateway_code }``. The plan is pre-resolved by the caller (via
 *     ``useRenewFlow`` → ``GET /api/user/plans/{id}``) and passed in as
 *     a prop.
 *
 *   - ``mode='upgrade'``: launched from server surfaces. Fetches upgrade
 *     options from ``GET /api/user/servers/{id}/upgrade-options`` and lets
 *     the user pick a target plan. Submits ``{ kind: 'upgrade',
 *     target_server_id, plan_code, period_count: 1, gateway_code }``.
 *     The diff price (``diffFen``) is shown instead of the full plan price.
 *
 * Both modes display the same hero, resource strip, period selector,
 * gateway picker and cost breakdown. On confirm both POST to
 * ``/api/user/orders`` and route to ``/pay/:id`` for actual payment.
 *
 * Gateway list comes from ``GET /api/user/payment-gateways`` — backend
 * returns clean user-facing labels; this component never displays the
 * underlying vendor brand.
 *
 * See: docs/BILLING_FRONTEND_DESIGN_CreateOrderModal.md
 *      docs/BILLING_FRONTEND_DESIGN_RenewFlow.md
 */
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import BaseModal from '@/components/ui/BaseModal.vue'
import BaseCard from '@/components/ui/BaseCard.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import Badge from '@/components/ui/Badge.vue'
import ChipSelect, { type ChipOption } from '@/components/ui/ChipSelect.vue'
import Spinner from '@/components/ui/Spinner.vue'
import AlertBanner from '@/components/ui/AlertBanner.vue'
import MsIcon from '@/components/ui/MsIcon.vue'

defineOptions({ name: 'CreateOrderModal' })

interface PeriodOption { count: number; discount_pct: number }
interface Plan {
  id: number
  code: string
  display_name: string
  description_md: string | null
  category_label: string | null
  price_fen: number
  days: number
  currency_code: string
  period_options: PeriodOption[]
  cpu: number
  memory_mb: number
  disk_mb: number
}
interface PaymentGateway {
  code: string
  display_name: string
  icon_name: string
}
interface UpgradeOption {
  planCode: string
  planName: string
  displayOrder: number
  categoryLabel: string | null
  descriptionMd: string | null
  cpu: number
  memoryMb: number
  diskMb: number
  diffFen: number
  priceFen: number
}
interface UpgradeOptionsResponse {
  serverId: number
  serverName: string
  currentPlanName: string | null
  remainingDays: number
  options: UpgradeOption[]
}
interface OrderCreated {
  order: { id: number }
}
interface UsableCoupon {
  id: number
  code: string
  template_name: string | null
  discount_fen: number
  min_order_fen: number
  expires_at: string
}
interface CouponListPayload {
  items: UsableCoupon[]
  total: number
}

type CashierMode = 'new_purchase' | 'renew' | 'upgrade'

const props = withDefaults(
  defineProps<{
    modelValue: boolean
    plan: Plan | null
    defaultPeriodCount?: number
    mode?: CashierMode
    targetServerId?: number | null
    serverName?: string
  }>(),
  {
    mode: 'new_purchase',
    targetServerId: null,
    serverName: '',
  },
)

// ── Upgrade mode state ──
const upgradeData = ref<UpgradeOptionsResponse | null>(null)
const upgradeLoading = ref(false)
const selectedUpgradePlan = ref<string>('')

async function loadUpgradeOptions() {
  if (!props.targetServerId) return
  upgradeLoading.value = true
  upgradeData.value = null
  const data = await get<UpgradeOptionsResponse>(
    `/api/user/servers/${props.targetServerId}/upgrade-options`,
    { silent: true },
  )
  upgradeLoading.value = false
  if (data) {
    upgradeData.value = data
    selectedUpgradePlan.value = data.options[0]?.planCode ?? ''
  }
}

const selectedUpgradeOption = computed<UpgradeOption | null>(() => {
  if (!upgradeData.value || !selectedUpgradePlan.value) return null
  return upgradeData.value.options.find((o) => o.planCode === selectedUpgradePlan.value) ?? null
})

const emit = defineEmits<{
  'update:modelValue': [open: boolean]
}>()

const { t } = useI18n({ useScope: 'global' })
const router = useRouter()
const { get, post } = useApiFetch()
const { toast } = useToast()

const open = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

// ── Periods ──
const sortedPeriods = computed<PeriodOption[]>(() => {
  if (!props.plan) return []
  return [...props.plan.period_options].sort((a, b) => a.count - b.count)
})

const selectedCount = ref<number>(1)

watch(
  () => [props.plan?.id, props.modelValue],
  () => {
    if (!props.plan || !props.modelValue) return
    const fallback = sortedPeriods.value[0]?.count ?? 1
    const want = props.defaultPeriodCount ?? fallback
    selectedCount.value = sortedPeriods.value.some((p) => p.count === want)
      ? want
      : fallback
  },
  { immediate: true },
)

const selectedPeriod = computed<PeriodOption>(() => {
  return (
    sortedPeriods.value.find((p) => p.count === selectedCount.value) ??
    sortedPeriods.value[0] ?? { count: 1, discount_pct: 0 }
  )
})

// Pricing math
function fenToYuan(fen: number): string {
  return (fen / 100).toFixed(2)
}
function formatPct(pct: number): string {
  return Number.isInteger(pct) ? String(pct) : pct.toFixed(1)
}

const basePriceFen = computed(() => {
  if (!props.plan) return 0
  return props.plan.price_fen * selectedPeriod.value.count
})
const finalPriceFen = computed(() =>
  Math.round(basePriceFen.value * (1 - selectedPeriod.value.discount_pct / 100)),
)
const savedFen = computed(() => basePriceFen.value - finalPriceFen.value)
const totalDays = computed(() => {
  if (!props.plan) return 0
  return props.plan.days * selectedPeriod.value.count
})
const hasDiscount = computed(() => savedFen.value > 0)

function periodUnitYuan(p: PeriodOption): string {
  if (!props.plan) return '0.00'
  const unitFen = Math.round(
    (props.plan.price_fen * (1 - p.discount_pct / 100)),
  )
  return fenToYuan(unitFen)
}
function periodSavedYuan(p: PeriodOption): string {
  if (!props.plan) return '0.00'
  const base = props.plan.price_fen * p.count
  const fin = Math.round(base * (1 - p.discount_pct / 100))
  return fenToYuan(base - fin)
}

// ── Resources ──
function formatResource(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}
const cpuLabel = computed(() =>
  props.plan ? formatResource(props.plan.cpu / 100) : '',
)
const memLabel = computed(() =>
  props.plan ? formatResource(props.plan.memory_mb / 1024) : '',
)
const diskLabel = computed(() =>
  props.plan ? formatResource(props.plan.disk_mb / 1024) : '',
)

// ── Payment gateways ──
const gateways = ref<PaymentGateway[]>([])
const gatewayLoading = ref(false)
const gatewayFailed = ref(false)
const selectedGateway = ref<string>('')

async function loadGateways() {
  gatewayLoading.value = true
  gatewayFailed.value = false
  const data = await get<PaymentGateway[]>('/api/user/payment-gateways', { silent: true })
  gatewayLoading.value = false
  if (data && data.length > 0) {
    gateways.value = data
    selectedGateway.value = data[0].code
  } else {
    gatewayFailed.value = true
  }
}

// ── Mode flags (must be declared before the immediate watch below) ──
const isRenew = computed(() => props.mode === 'renew')
const isUpgrade = computed(() => props.mode === 'upgrade')

watch(
  () => props.modelValue,
  (v) => {
    if (v && gateways.value.length === 0 && !gatewayFailed.value) loadGateways()
    if (v && isUpgrade.value) loadUpgradeOptions()
  },
  { immediate: true },
)

const gatewayOptions = computed<ChipOption[]>(() =>
  gateways.value.map((g) => ({ value: g.code, label: g.display_name })),
)
const selectedGatewayMeta = computed<PaymentGateway | null>(() =>
  gateways.value.find((g) => g.code === selectedGateway.value) ?? null,
)

// ── Coupons ──
//
// The picker is populated from the user coupon list filtered by the
// current order context (kind/plan/subtotal). The backend already
// strips out non-applicable coupons via ``_is_applicable``, so we just
// render whatever comes back. We re-fetch whenever the modal opens or
// the underlying subtotal changes (period switch, upgrade target
// switch), because the ``min_order_fen`` rule can toggle a coupon in
// and out of "usable" status.
const usableCoupons = ref<UsableCoupon[]>([])
const couponsLoading = ref(false)
const selectedCouponCode = ref<string>('')

const couponOrderKind = computed<'new_purchase' | 'renew' | 'upgrade'>(() => {
  if (isUpgrade.value) return 'upgrade'
  if (isRenew.value) return 'renew'
  return 'new_purchase'
})

const couponSubtotalFen = computed(() => {
  // Mirror the C4 floor: ``min_order_fen`` is evaluated against the
  // post-period-discount subtotal in services/billing/coupons.py.
  if (isUpgrade.value) return selectedUpgradeOption.value?.diffFen ?? 0
  return finalPriceFen.value
})

const couponPlanId = computed<number | null>(() => {
  // Upgrade options expose ``planCode`` only; without an id we leave
  // this null and rely on the strict per-coupon ``_is_applicable``
  // check on the server side.
  if (isUpgrade.value) return null
  return props.plan?.id ?? null
})

async function loadUsableCoupons() {
  if (couponSubtotalFen.value <= 0) {
    usableCoupons.value = []
    selectedCouponCode.value = ''
    return
  }
  couponsLoading.value = true
  const params = new URLSearchParams({
    order_kind: couponOrderKind.value,
    subtotal_fen: String(couponSubtotalFen.value),
  })
  if (couponPlanId.value != null) params.set('plan_id', String(couponPlanId.value))
  const data = await get<CouponListPayload>(
    `/api/user/coupons?${params.toString()}`,
    { silent: true },
  )
  couponsLoading.value = false
  usableCoupons.value = data?.items ?? []
  // If the previously selected coupon is no longer applicable (e.g.
  // user shrank the period and the new subtotal falls below
  // ``min_order_fen``), drop the selection silently.
  if (selectedCouponCode.value
    && !usableCoupons.value.some((c) => c.code === selectedCouponCode.value)) {
    selectedCouponCode.value = ''
  }
}

const selectedCoupon = computed<UsableCoupon | null>(() =>
  usableCoupons.value.find((c) => c.code === selectedCouponCode.value) ?? null,
)

const couponDiscountFen = computed<number>(() => {
  if (!selectedCoupon.value) return 0
  return Math.min(selectedCoupon.value.discount_fen, couponSubtotalFen.value)
})

const finalPriceAfterCouponFen = computed<number>(() =>
  Math.max(0, couponSubtotalFen.value - couponDiscountFen.value),
)

const couponSelectOptions = computed(() => ([
  { value: '', label: t('billing.coupons.applyNone') },
  ...usableCoupons.value.map((c) => ({
    value: c.code,
    label: `${c.template_name || c.code} (-¥${(c.discount_fen / 100).toFixed(2)})`,
  })),
]))

// Refresh the usable-coupon list whenever the order context changes.
// Triggers: opening the modal, switching the period, picking a
// different upgrade target. We don't watch ``couponPlanId`` directly
// because it only changes alongside ``props.plan?.id``.
watch(
  () => [props.modelValue, couponSubtotalFen.value, couponOrderKind.value, couponPlanId.value],
  ([open]) => {
    if (open) loadUsableCoupons()
  },
  { immediate: true },
)

// ── Submit ──
const submitting = ref(false)

const modalTitle = computed(() => {
  if (isRenew.value) return t('billing.cashier.renewTitle')
  if (isUpgrade.value) return t('userServers.upgrade.modalTitle')
  return t('billing.cashier.title')
})

const canSubmit = computed(() => {
  if (!selectedGateway.value || submitting.value) return false
  if (isUpgrade.value) return !!(selectedUpgradePlan.value && props.targetServerId)
  if (!props.plan) return false
  if (isRenew.value && !props.targetServerId) return false
  return true
})

async function onConfirm() {
  if (!canSubmit.value) return
  submitting.value = true
  try {
    let body: Record<string, unknown>
    if (isUpgrade.value) {
      body = {
        kind: 'upgrade' as const,
        target_server_id: props.targetServerId!,
        plan_code: selectedUpgradePlan.value,
        period_count: 1,
        gateway_code: selectedGateway.value,
      }
    } else if (isRenew.value) {
      body = {
        kind: 'renew' as const,
        target_server_id: props.targetServerId!,
        period_count: selectedPeriod.value.count,
        gateway_code: selectedGateway.value,
      }
    } else {
      body = {
        kind: 'new_purchase' as const,
        plan_code: props.plan!.code,
        period_count: selectedPeriod.value.count,
        gateway_code: selectedGateway.value,
      }
    }
    if (selectedCouponCode.value) {
      // The backend accepts ``coupon_code`` (uppercased EC-XXXX form).
      // It runs a fresh applicability check inside the order
      // transaction, so if the coupon flipped to non-usable between
      // load and submit the order will fail cleanly with a 4xx.
      body.coupon_code = selectedCouponCode.value
    }
    const res = await post<OrderCreated>('/api/user/orders', body)
    if (res?.order?.id) {
      open.value = false
      router.push({ path: `/pay/${res.order.id}` })
    } else {
      toast(t('billing.cashier.createFailed'), 'error')
    }
  } catch {
    toast(t('billing.cashier.createFailed'), 'error')
  } finally {
    submitting.value = false
  }
}

function onCancel() {
  open.value = false
}
</script>

<template>
  <BaseModal
    v-model="open"
    :title="modalTitle"
    icon="receipt_long"
    size="md"
    :persistent="submitting"
  >
    <!-- ── Upgrade mode ── -->
    <template v-if="isUpgrade">
      <div v-if="upgradeLoading" class="gateway-loading"><Spinner /></div>
      <template v-else-if="upgradeData && upgradeData.options.length">
        <div v-if="upgradeData.currentPlanName" class="renew-hint">
          <MsIcon name="arrow_upward" size="sm" class="renew-hint__icon" />
          <div class="renew-hint__body">
            <div class="renew-hint__row">
              <span class="renew-hint__label">{{ t('userServers.upgrade.currentPlan', { name: upgradeData.currentPlanName, days: upgradeData.remainingDays }) }}</span>
            </div>
            <div class="renew-hint__sub">{{ serverName }}</div>
          </div>
        </div>

        <AlertBanner tone="info" icon="restart_alt" :closable="false" class="upgrade-restart-banner">
          {{ t('userServers.upgrade.restartRequired') }}
        </AlertBanner>

        <section class="section">
          <div class="section__title">{{ t('userServers.upgrade.selectTarget') }}</div>
          <div class="period-list">
            <label
              v-for="opt in upgradeData.options"
              :key="opt.planCode"
              class="period-row upgrade-row"
              :class="{ selected: selectedUpgradePlan === opt.planCode }"
            >
              <input type="radio" :value="opt.planCode" v-model="selectedUpgradePlan" class="period-radio" />
              <span class="period-radio-dot" />
              <div class="upgrade-row__info">
                <span class="period-label">{{ opt.planName }}</span>
                <span class="upgrade-row__res">
                  <span class="res-item"><MsIcon name="developer_board" size="sm" />{{ t('billing.plans.resCpu', { n: formatResource(opt.cpu / 100) }) }}</span>
                  <span class="res-divider">·</span>
                  <span class="res-item"><MsIcon name="memory" size="sm" />{{ t('billing.plans.resMemory', { n: formatResource(opt.memoryMb / 1024) }) }}</span>
                  <span class="res-divider">·</span>
                  <span class="res-item"><MsIcon name="storage" size="sm" />{{ t('billing.plans.resDisk', { n: formatResource(opt.diskMb / 1024) }) }}</span>
                </span>
              </div>
              <span class="upgrade-row__diff mono">¥{{ fenToYuan(opt.priceFen) }}</span>
            </label>
          </div>
        </section>

        <section class="section">
          <div class="section__title">{{ t('billing.cashier.gatewaySection') }}</div>
          <div v-if="gatewayLoading" class="gateway-loading"><Spinner /></div>
          <AlertBanner v-else-if="gatewayFailed" tone="danger" :closable="false">
            {{ t('billing.cashier.gatewayLoadFailed') }}
          </AlertBanner>
          <div v-else class="gateway-row">
            <ChipSelect v-model="selectedGateway" :options="gatewayOptions" />
            <span v-if="selectedGatewayMeta" class="gateway-icon">
              <MsIcon :name="selectedGatewayMeta.icon_name" size="md" />
            </span>
          </div>
        </section>

        <BaseCard v-if="selectedUpgradeOption" variant="bg3" radius="md" class="summary-card">
          <div class="summary-row">
            <span class="summary-label">{{ t('userServers.upgrade.diffLabel') }}</span>
            <span class="summary-value mono">¥{{ fenToYuan(selectedUpgradeOption.diffFen) }}</span>
          </div>
          <div class="summary-divider" />
          <div class="summary-row summary-row--total">
            <span class="summary-label">{{ t('billing.cashier.summaryTotal') }}</span>
            <span class="summary-value mono summary-value--total">¥{{ fenToYuan(selectedUpgradeOption.diffFen) }}</span>
          </div>
        </BaseCard>
      </template>
      <div v-else-if="!upgradeLoading" class="gateway-loading">
        <span style="color: var(--t2); font-size: var(--text-sm)">{{ t('userServers.upgrade.noOptions') }}</span>
      </div>
    </template>

    <!-- ── Normal / renew mode ── -->
    <template v-else-if="plan">
      <!-- Plan hero -->
      <div class="hero">
        <div class="hero__main">
          <h3 class="hero__name">{{ plan.display_name }}</h3>        </div>
        <Badge v-if="plan.category_label" color="var(--ac)">
          {{ plan.category_label }}
        </Badge>
      </div>

      <!-- Renew target hint -->
      <div v-if="isRenew" class="renew-hint">
        <MsIcon name="autorenew" size="sm" class="renew-hint__icon" />
        <div class="renew-hint__body">
          <div class="renew-hint__row">
            <span class="renew-hint__label">{{ t('billing.cashier.renewTarget') }}：</span>
            <span class="renew-hint__server">{{ serverName }}</span>
          </div>
          <div class="renew-hint__sub">{{ t('billing.cashier.renewHint') }}</div>
        </div>
      </div>

      <!-- Resources strip -->
      <div class="res-strip">
        <span class="res-item">
          <MsIcon name="developer_board" size="sm" />
          {{ t('billing.plans.resCpu', { n: cpuLabel }) }}
        </span>
        <span class="res-divider">·</span>
        <span class="res-item">
          <MsIcon name="memory" size="sm" />
          {{ t('billing.plans.resMemory', { n: memLabel }) }}
        </span>
        <span class="res-divider">·</span>
        <span class="res-item">
          <MsIcon name="storage" size="sm" />
          {{ t('billing.plans.resDisk', { n: diskLabel }) }}
        </span>
      </div>

      <!-- Period selector -->
      <section v-if="sortedPeriods.length > 1" class="section">
        <div class="section__title">{{ t('billing.cashier.periodSection') }}</div>
        <div class="period-list">
          <label
            v-for="p in sortedPeriods"
            :key="p.count"
            class="period-row"
            :class="{ selected: selectedCount === p.count }"
          >
            <input
              type="radio"
              :value="p.count"
              v-model="selectedCount"
              class="period-radio"
            />
            <span class="period-radio-dot" />
            <span class="period-label">{{ t('billing.cashier.periodMonth', { count: p.count }) }}</span>
            <span class="period-unit">{{ t('billing.cashier.periodPerMonth', { amount: periodUnitYuan(p) }) }}</span>
            <Badge v-if="p.discount_pct > 0" color="var(--ac)">
              {{ t('billing.cashier.periodDiscountTag', { pct: formatPct(p.discount_pct) }) }}
            </Badge>
            <span v-if="p.discount_pct > 0" class="period-saved">
              {{ t('billing.cashier.periodSaved', { amount: periodSavedYuan(p) }) }}
            </span>
            <span v-else class="period-saved" />
          </label>
        </div>
      </section>

      <!-- Payment gateway -->
      <section class="section">
        <div class="section__title">{{ t('billing.cashier.gatewaySection') }}</div>
        <div v-if="gatewayLoading" class="gateway-loading"><Spinner /></div>
        <AlertBanner v-else-if="gatewayFailed" tone="danger" :closable="false">
          {{ t('billing.cashier.gatewayLoadFailed') }}
        </AlertBanner>
        <div v-else class="gateway-row">
          <ChipSelect
            v-model="selectedGateway"
            :options="gatewayOptions"
          />
          <span v-if="selectedGatewayMeta" class="gateway-icon">
            <MsIcon :name="selectedGatewayMeta.icon_name" size="md" />
          </span>
        </div>
      </section>

      <!-- Coupon picker -->
      <section class="section">
        <div class="section__title">{{ t('billing.coupons.applyHint') }}</div>
        <div v-if="couponsLoading" class="gateway-loading"><Spinner /></div>
        <template v-else>
          <BaseSelect
            v-if="usableCoupons.length > 0"
            v-model="selectedCouponCode"
            :options="couponSelectOptions"
            :placeholder="t('billing.coupons.applyPlaceholder')"
          />
          <p v-else class="coupon-empty">
            {{ t('billing.coupons.applyEmpty') }}
            <RouterLink class="coupon-invite-link" :to="{ name: 'user-promotions' }">
              {{ t('billing.coupons.inviteEntry') }} — {{ t('billing.coupons.inviteEntryLink') }}
            </RouterLink>
          </p>
        </template>
      </section>

      <!-- Cost breakdown -->
      <BaseCard variant="bg3" radius="md" class="summary-card">
        <div class="summary-row">
          <span class="summary-label">{{ t('billing.cashier.summaryUnit') }}</span>
          <span class="summary-value mono">
            {{ t('billing.cashier.summaryUnitExpr', { unit: fenToYuan(plan.price_fen), count: selectedPeriod.count }) }}
            = ¥{{ fenToYuan(basePriceFen) }}
          </span>
        </div>
        <div v-if="hasDiscount" class="summary-row">
          <span class="summary-label">
            {{ t('billing.cashier.summaryDiscount', { pct: formatPct(selectedPeriod.discount_pct) }) }}
          </span>
          <span class="summary-value mono summary-value--minus">
            -¥{{ fenToYuan(savedFen) }}
          </span>
        </div>
        <div v-if="selectedCoupon" class="summary-row">
          <span class="summary-label">
            {{ t('billing.coupons.applyHint') }} ({{ selectedCoupon.code }})
          </span>
          <span class="summary-value mono summary-value--minus">
            -¥{{ fenToYuan(couponDiscountFen) }}
          </span>
        </div>
        <div class="summary-divider" />
        <div class="summary-row summary-row--total">
          <span class="summary-label">{{ t('billing.cashier.summaryTotal') }}</span>
          <span class="summary-value mono summary-value--total">
            ¥{{ fenToYuan(selectedCoupon ? finalPriceAfterCouponFen : finalPriceFen) }}
          </span>
        </div>
        <div class="summary-duration">
          {{ t('billing.cashier.summaryDuration', { days: totalDays }) }}
        </div>
      </BaseCard>
    </template>

    <template #footer>
      <div class="footer">
        <div class="footer-actions">
          <BaseButton :disabled="submitting" @click="onCancel">
            {{ t('billing.cashier.btnCancel') }}
          </BaseButton>
          <BaseButton
            variant="primary"
            :loading="submitting"
            :disabled="!canSubmit"
            @click="onConfirm"
          >
            {{ t('billing.cashier.btnPay') }}
          </BaseButton>
        </div>
      </div>
    </template>
  </BaseModal>
</template>

<style scoped>
/* ── Upgrade rows ── */
.upgrade-row {
  grid-template-columns: auto auto 1fr auto !important;
}
.upgrade-row__info {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
  min-width: 0;
}
.upgrade-row__res {
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--sp-2);
  padding: var(--sp-1) var(--sp-2);
  background: var(--bg-in);
  border: 1px solid var(--bd);
  border-radius: var(--r-sm);
  font-size: var(--text-sm);
  color: var(--t2);
  align-self: flex-start;
}
.upgrade-row__diff {
  color: var(--ac2);
  font-weight: 600;
  font-size: var(--text-md);
  flex-shrink: 0;
  justify-self: end;
  text-align: right;
}

/* ── Hero ── */
.hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--sp-3);
  margin-bottom: var(--sp-4);
}
.hero__main {
  min-width: 0;
}
.hero__name {
  margin: 0 0 var(--sp-1);
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--t1);
}
.hero__desc {
  margin: 0;
  color: var(--t2);
  font-size: var(--text-sm);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* ── Resources strip ── */
.res-strip {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-2) var(--sp-3);
  background: var(--bg-in);
  border: 1px solid var(--bd);
  border-radius: var(--r-md);
  font-size: var(--text-sm);
  color: var(--t2);
  flex-wrap: wrap;
  margin-bottom: var(--sp-4);
}
.res-item {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1);
}
.res-divider {
  color: var(--t3);
}

/* ── Renew hint (mode='renew' only) ── */
.renew-hint {
  display: flex;
  align-items: flex-start;
  gap: var(--sp-2);
  padding: var(--sp-3);
  margin-bottom: var(--sp-3);
  background: color-mix(in srgb, var(--ac) 8%, var(--bg-in));
  border: 1px solid color-mix(in srgb, var(--ac) 25%, var(--bd));
  border-radius: var(--r-md);
}
.renew-hint__icon {
  color: var(--ac);
  margin-top: 2px;
  flex-shrink: 0;
}
.upgrade-restart-banner { margin-bottom: var(--sp-3); }
.renew-hint__body {
  flex: 1;
  min-width: 0;
}
.renew-hint__row {
  display: flex;
  align-items: baseline;
  gap: var(--sp-1);
  flex-wrap: wrap;
}
.renew-hint__label {
  font-size: var(--text-sm);
  color: var(--t2);
}
.renew-hint__server {
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--t1);
  font-family: 'IBM Plex Mono', monospace;
}
.renew-hint__sub {
  margin-top: 2px;
  font-size: var(--text-xs);
  color: var(--t3);
}

/* ── Section ── */
.section {
  margin-bottom: var(--sp-4);
}
.section__title {
  font-size: var(--text-sm);
  color: var(--t2);
  font-weight: 500;
  margin-bottom: var(--sp-2);
}

/* ── Period radio list ── */
.period-list {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.period-row {
  display: grid;
  grid-template-columns: auto auto 1fr auto auto;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-3);
  border: 1px solid var(--bd);
  border-radius: var(--r-md);
  cursor: pointer;
  transition: border-color .15s, background .15s;
}
.period-row:hover {
  border-color: var(--bd-f);
}
.period-row.selected {
  border-color: var(--bd-f);
  background: color-mix(in srgb, var(--ac) 8%, transparent);
}
.period-radio {
  position: absolute;
  opacity: 0;
  pointer-events: none;
}
.period-radio-dot {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  border: 1.5px solid var(--bd);
  position: relative;
  flex-shrink: 0;
}
.period-row.selected .period-radio-dot {
  border-color: var(--ac);
}
.period-row.selected .period-radio-dot::after {
  content: '';
  position: absolute;
  inset: 3px;
  border-radius: 50%;
  background: var(--ac);
}
.period-label {
  color: var(--t1);
  font-weight: 500;
  font-size: var(--text-base);
}
.period-unit {
  color: var(--t2);
  font-family: 'IBM Plex Mono', monospace;
  font-size: var(--text-sm);
}
.period-saved {
  color: var(--green);
  font-size: var(--text-sm);
  white-space: nowrap;
  min-width: 5em;
  text-align: right;
}

/* ── Gateway row ── */
.gateway-loading {
  padding: var(--sp-3) 0;
  display: flex;
  justify-content: center;
}
.gateway-row {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
}
.gateway-icon {
  color: var(--ac);
  display: inline-flex;
  align-items: center;
}

/* ── Coupon picker ── */
.coupon-empty {
  margin: 0;
  padding: var(--sp-2) var(--sp-3);
  background: var(--bg-in);
  border: 1px dashed var(--bd);
  border-radius: var(--r-md);
  color: var(--t3);
  font-size: .82rem;
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
  align-items: center;
}
.coupon-invite-link {
  color: var(--ac);
  text-decoration: none;
}
.coupon-invite-link:hover {
  color: var(--ac2);
  text-decoration: underline;
}

/* ── Summary card ── */
.summary-card {
  margin-top: var(--sp-2);
}
.summary-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--sp-1) 0;
}
.summary-label {
  color: var(--t2);
  font-size: var(--text-sm);
}
.summary-value {
  color: var(--t1);
  font-size: var(--text-sm);
}
.summary-value--minus {
  color: var(--amber);
}
.mono {
  font-family: 'IBM Plex Mono', monospace;
}
.summary-divider {
  height: 1px;
  background: var(--bd);
  margin: var(--sp-2) 0;
}
.summary-row--total .summary-label {
  color: var(--t1);
  font-weight: 500;
  font-size: var(--text-base);
}
.summary-value--total {
  color: var(--ac);
  font-size: var(--text-lg);
  font-weight: 700;
}
.summary-duration {
  margin-top: var(--sp-1);
  text-align: right;
  color: var(--t3);
  font-size: var(--text-xs);
}

/* ── Footer ── */
.footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  width: 100%;
  gap: var(--sp-3);
  flex-wrap: wrap;
}
.footer-actions {
  display: flex;
  gap: var(--sp-2);
}

@media (max-width: 520px) {
  .period-row {
    grid-template-columns: auto 1fr auto;
    grid-template-areas:
      'dot label badge'
      '.   unit  saved';
    row-gap: var(--sp-1);
  }
  .period-radio-dot { grid-area: dot; }
  .period-label { grid-area: label; }
  .period-unit { grid-area: unit; }
  .period-saved { grid-area: saved; min-width: 0; }
  .footer { flex-direction: column; align-items: stretch; }
  .footer-actions { justify-content: space-between; }
  .footer-actions :deep(.base-button) { flex: 1; }
}
</style>

<script setup lang="ts">
/**
 * UserPromotionsPage — `/promotions` (aliases: `/coupons`, `/invite`).
 *
 * Four-card layout (mirrors AccountPage pattern):
 *   1. Reward banner — explains the referral mechanics.
 *   2. My invite code — code + share link + 3 stat tiles.
 *   3. My coupons (compact) — up to 5 unused coupons, each as a row;
 *      "view all" link when total exceeds.
 *   4. Referral history — table of people who registered via your link.
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useClipboard } from '@/composables/useClipboard'
import PageHeader from '@/components/layout/PageHeader.vue'
import BaseCard from '@/components/ui/BaseCard.vue'
import SectionHeader from '@/components/ui/SectionHeader.vue'
import Badge from '@/components/ui/Badge.vue'
import LoadingCenter from '@/components/ui/LoadingCenter.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import MsIcon from '@/components/ui/MsIcon.vue'

defineOptions({ name: 'UserPromotionsPage' })

interface Referral {
  id: number
  invitee_user_id: number
  invitee_username: string | null
  status: string
  rewarded_at: string | null
  created_at: string
}

interface InviteSummary {
  invite: { code: string; invite_url: string | null; disabled: boolean }
  stats: { registered: number; rewarded: number; revoked: number; total: number }
  recent: Referral[]
  reward?: {
    enabled: boolean
    qualifying_min_fen: number
    inviter_discount_fen: number | null
    invitee_discount_fen: number | null
    inviter_valid_days: number | null
    invitee_valid_days: number | null
  } | null
}

interface Coupon {
  id: number
  code: string
  template_id: number
  template_name: string | null
  status: string
  discount_fen: number
  min_order_fen: number
  expires_at: string
}

interface CouponListResponse { items: Coupon[]; total: number }

const { t } = useI18n({ useScope: 'global' })
const { get } = useApiFetch()
const { copy } = useClipboard()

const loading = ref(true)
const invite = ref<InviteSummary | null>(null)
const coupons = ref<Coupon[]>([])

async function load() {
  loading.value = true
  const [iv, cp] = await Promise.all([
    get<InviteSummary>('/api/user/invite', { silent: true }),
    get<CouponListResponse>('/api/user/coupons', { silent: true }),
  ])
  if (iv) invite.value = iv
  if (cp?.items) coupons.value = cp.items
  loading.value = false
}

onMounted(load)

// ── Coupons (unused, sorted by soonest expiry) ──
const unusedCoupons = computed(() => {
  const now = Date.now()
  return coupons.value
    .filter((c) => (c.status === 'unused' || c.status === 'reserved') && new Date(c.expires_at).getTime() > now)
    .sort((a, b) => new Date(a.expires_at).getTime() - new Date(b.expires_at).getTime())
})
const couponExpanded = ref(false)
const COUPON_COLLAPSED_COUNT = 4
const couponPreview = computed(() =>
  couponExpanded.value ? unusedCoupons.value : unusedCoupons.value.slice(0, COUPON_COLLAPSED_COUNT)
)
const couponMore = computed(() => Math.max(0, unusedCoupons.value.length - COUPON_COLLAPSED_COUNT))

// ── Invite link (fallback synthesised from origin) ──
const inviteLink = computed(() => {
  if (!invite.value) return ''
  const fromApi = invite.value.invite.invite_url
  if (fromApi) return fromApi
  return `${window.location.origin}/#/register?invite=${invite.value.invite.code}`
})

// ── Reward banner copy ──
function fmtYuan(fen: number | null | undefined): string {
  if (fen == null) return '—'
  const y = fen / 100
  return `¥${y % 1 === 0 ? y.toFixed(0) : y.toFixed(2)}`
}

const rewardCopy = computed<{ headline: string; detail: string }>(() => {
  const r = invite.value?.reward
  if (!r) {
    return {
      headline: t('billing.invite.banner.enabledHeadline'),
      detail: t('billing.invite.rulesBody'),
    }
  }
  if (!r.enabled) {
    return {
      headline: t('billing.invite.banner.disabledHeadline'),
      detail: t('billing.invite.banner.disabledDetail'),
    }
  }
  return {
    headline: t('billing.invite.banner.enabledHeadline'),
    detail: t('billing.invite.banner.enabledDetail', {
      minOrder: fmtYuan(r.qualifying_min_fen),
      inviterAmount: fmtYuan(r.inviter_discount_fen),
      inviteeAmount: fmtYuan(r.invitee_discount_fen),
      inviterDays: r.inviter_valid_days ?? '—',
      inviteeDays: r.invitee_valid_days ?? '—',
    }),
  }
})

// ── Helpers ──
function formatDate(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '—'
  return d.toLocaleDateString(undefined, { year: 'numeric', month: '2-digit', day: '2-digit' })
}

function formatDateTime(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '—'
  return d.toLocaleString(undefined, {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  })
}

function daysLeft(iso: string): number {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return 0
  return Math.max(0, Math.ceil((d.getTime() - Date.now()) / 86_400_000))
}

function statusColor(s: string): string {
  if (s === 'rewarded') return 'var(--green)'
  if (s === 'registered') return 'var(--amber)'
  if (s === 'revoked') return 'var(--red)'
  return 'var(--t3)'
}
function statusLabel(s: string): string {
  return t(`billing.invite.referralStatus.${s}`)
}

function couponConstraint(c: Coupon): string {
  if (c.min_order_fen > 0) {
    return t('billing.coupons.minOrder', { amount: (c.min_order_fen / 100).toFixed(2) })
  }
  return t('billing.coupons.noThreshold')
}
</script>

<template>
  <PageHeader icon="redeem" :title="t('nav.promotions')" />

  <div class="page-body">
    <LoadingCenter v-if="loading">{{ t('common.loading') }}</LoadingCenter>

    <div v-else-if="invite" class="promotions-panel">
      <!-- Card 1: Reward banner -->
      <BaseCard variant="bg2" class="promo-section">
        <SectionHeader icon="campaign" flush>
          {{ rewardCopy.headline }}
        </SectionHeader>
        <p class="promo-section__desc">{{ rewardCopy.detail }}</p>
      </BaseCard>

      <!-- Card 2: My invite code -->
      <BaseCard variant="bg2" class="promo-section">
        <SectionHeader icon="qr_code_2" flush>
          {{ t('billing.invite.yourCode') }}
        </SectionHeader>

        <div class="field-block">
          <div class="field-label">{{ t('billing.invite.yourCode') }}</div>
          <div class="value-row">
            <span class="value-box mono value-box--code">{{ invite.invite.code }}</span>
            <button class="copy-btn" :title="t('common.btn.copy')" @click="copy(invite.invite.code)">
              <MsIcon name="content_copy" size="sm" />
            </button>
          </div>
        </div>

        <div class="field-block">
          <div class="field-label">{{ t('billing.invite.shareLink') }}</div>
          <div class="value-row">
            <span class="value-box mono trunc" :title="inviteLink">{{ inviteLink }}</span>
            <button class="copy-btn" :title="t('common.btn.copy')" @click="copy(inviteLink)">
              <MsIcon name="content_copy" size="sm" />
            </button>
          </div>
        </div>

        <div class="stat-row">
          <div class="stat-tile">
            <div class="stat-num">{{ invite.stats.total }}</div>
            <div class="stat-label">{{ t('billing.invite.stats.total') }}</div>
          </div>
          <div class="stat-tile stat-tile--accent">
            <div class="stat-num">{{ invite.stats.rewarded }}</div>
            <div class="stat-label">{{ t('billing.invite.stats.rewarded') }}</div>
          </div>
          <div class="stat-tile">
            <div class="stat-num">{{ invite.stats.registered }}</div>
            <div class="stat-label">{{ t('billing.invite.stats.pending') }}</div>
          </div>
        </div>
      </BaseCard>

      <!-- Card 3: My coupons (compact) -->
      <BaseCard variant="bg2" class="promo-section">
        <SectionHeader icon="confirmation_number" flush>
          {{ t('billing.coupons.tab') }}
        </SectionHeader>

        <EmptyState
          v-if="couponPreview.length === 0"
          icon="confirmation_number"
          :message="t('billing.coupons.empty.unused')"
          density="compact"
        />
        <div v-else class="ticket-grid">
          <div v-for="c in couponPreview" :key="c.id" class="ticket">
            <div class="ticket-amount">
              <span>
                <span class="ticket-currency">¥</span>
                <span class="ticket-value">{{ (c.discount_fen / 100) % 1 === 0 ? (c.discount_fen / 100).toFixed(0) : (c.discount_fen / 100).toFixed(2) }}</span>
              </span>
            </div>
            <div class="ticket-divider" aria-hidden="true"></div>
            <div class="ticket-body">
              <div class="ticket-top">
                <span class="ticket-sub">{{ couponConstraint(c) }}</span>
                <span class="ticket-meta" :class="{ 'expiry-warning': daysLeft(c.expires_at) <= 7 }">
                  <MsIcon name="schedule" size="xs" />
                  {{ t('billing.coupons.daysLeft', { days: daysLeft(c.expires_at) }) }}
                </span>
              </div>
              <div class="ticket-code-row">
                <span class="ticket-code">{{ c.code }}</span>
                <button class="copy-btn copy-btn--inline" :title="t('common.btn.copy')" @click="copy(c.code)">
                  <MsIcon name="content_copy" size="xs" />
                </button>
              </div>
            </div>
          </div>
        </div>
        <div v-if="couponMore > 0" class="coupon-more">
          <button
            type="button"
            class="coupon-toggle"
            :title="couponExpanded ? t('common.btn.collapse') : t('billing.coupons.showAll', { n: unusedCoupons.length })"
            @click="couponExpanded = !couponExpanded"
          >
            <MsIcon :name="couponExpanded ? 'expand_less' : 'expand_more'" size="sm" />
          </button>
        </div>
      </BaseCard>

      <!-- Card 4: Referral history -->
      <BaseCard variant="bg2" class="promo-section">
        <SectionHeader icon="group_add" flush>
          {{ t('billing.invite.history') }}
        </SectionHeader>

        <EmptyState
          v-if="invite.recent.length === 0"
          icon="group_add"
          :message="t('billing.invite.empty')"
          density="compact"
        />
        <template v-else>
          <!-- desktop table -->
          <table class="ref-table">
            <thead>
              <tr>
                <th>{{ t('billing.invite.table.invitee') }}</th>
                <th>{{ t('billing.invite.table.registeredAt') }}</th>
                <th>{{ t('billing.invite.table.status') }}</th>
                <th>{{ t('billing.invite.table.rewardedAt') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in invite.recent" :key="r.id">
                <td>{{ r.invitee_username || `#${r.invitee_user_id}` }}</td>
                <td class="mono">{{ formatDateTime(r.created_at) }}</td>
                <td><Badge :color="statusColor(r.status)">{{ statusLabel(r.status) }}</Badge></td>
                <td class="mono">{{ formatDateTime(r.rewarded_at) }}</td>
              </tr>
            </tbody>
          </table>

          <!-- mobile cards -->
          <ul class="ref-list">
            <li v-for="r in invite.recent" :key="r.id" class="ref-row">
              <div class="ref-row__top">
                <span class="ref-row__name">{{ r.invitee_username || `#${r.invitee_user_id}` }}</span>
                <Badge :color="statusColor(r.status)">{{ statusLabel(r.status) }}</Badge>
              </div>
              <div class="ref-row__meta">
                <span class="ref-row__metaItem">
                  <MsIcon name="person_add" size="xs" />
                  {{ formatDate(r.created_at) }}
                </span>
                <span v-if="r.rewarded_at" class="ref-row__metaItem">
                  <MsIcon name="redeem" size="xs" />
                  {{ formatDate(r.rewarded_at) }}
                </span>
              </div>
            </li>
          </ul>
        </template>
      </BaseCard>
    </div>
  </div>
</template>

<style scoped>
.promotions-panel {
  max-width: 760px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
  width: 100%;
}

.promo-section {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  padding: var(--sp-2);
}

.promo-section__desc {
  margin: 0;
  color: var(--t2);
  font-size: .84rem;
  line-height: 1.55;
}

/* ── invite code / share link ── */
.field-block { display: flex; flex-direction: column; gap: 6px; }
.field-label { color: var(--t3); font-size: var(--text-sm); }
.value-row   { display: flex; align-items: stretch; gap: var(--sp-2); min-width: 0; }
.value-box {
  flex: 1; min-width: 0;
  padding: var(--sp-2) var(--sp-3);
  background: var(--bg-in);
  border: 1px solid var(--bd);
  border-radius: var(--r-sm);
  color: var(--t1);
  font-size: var(--text-sm);
  display: inline-flex; align-items: center;
}
.value-box--code {
  font-size: 1.05rem; font-weight: 600;
  letter-spacing: .14em; color: var(--ac);
}
.trunc { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.copy-btn {
  display: inline-flex; align-items: center; justify-content: center;
  background: var(--bg-in); border: 1px solid var(--bd);
  border-radius: var(--r-sm); color: var(--t2);
  cursor: pointer; padding: 0 10px;
  transition: color .15s, background .15s, border-color .15s;
}
.copy-btn:hover {
  color: var(--ac); background: var(--bg3);
  border-color: color-mix(in srgb, var(--ac) 35%, var(--bd));
}
.copy-btn--inline { padding: 4px 6px; }

/* ── stats tiles ── */
.stat-row {
  display: grid; grid-template-columns: repeat(3, 1fr);
  gap: var(--sp-2); margin-top: var(--sp-1);
}
.stat-tile {
  display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  padding: var(--sp-3); border-radius: var(--r-md);
  background: var(--bg-in); border: 1px solid var(--bd);
}
.stat-tile--accent {
  border-color: color-mix(in srgb, var(--ac) 35%, var(--bd));
  background: color-mix(in srgb, var(--ac) 6%, var(--bg-in));
}
.stat-num {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 1.4rem; font-weight: 700; color: var(--t1);
}
.stat-tile--accent .stat-num { color: var(--ac); }
.stat-label { font-size: var(--text-xs); color: var(--t3); margin-top: 2px; }

/* ── coupon tickets ── */
.ticket-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: var(--sp-3);
}
.ticket {
  position: relative;
  display: flex;
  align-items: stretch;
  background: linear-gradient(135deg,
    color-mix(in srgb, var(--ac) 8%, var(--bg-in)) 0%,
    var(--bg-in) 60%);
  border: 1px solid color-mix(in srgb, var(--ac) 28%, var(--bd));
  border-radius: var(--r-md);
  overflow: hidden;
  min-height: 92px;
}
.ticket-amount {
  flex: 0 0 96px;
  display: flex; align-items: center; justify-content: center;
  padding: var(--sp-3) var(--sp-2);
  color: var(--ac);
  background: color-mix(in srgb, var(--ac) 12%, transparent);
}
.ticket-amount > span {
  display: inline-flex;
  align-items: baseline;
  gap: 2px;
  line-height: 1;
}
.ticket-currency { font-size: .95rem; font-weight: 600; opacity: .85; }
.ticket-value {
  font-size: 1.85rem; font-weight: 700; line-height: 1;
  letter-spacing: -.01em;
}
.ticket-divider {
  flex: 0 0 1px;
  background-image: linear-gradient(
    to bottom,
    color-mix(in srgb, var(--ac) 35%, var(--bd)) 50%,
    transparent 50%);
  background-size: 1px 6px;
  background-repeat: repeat-y;
  position: relative;
}
.ticket-divider::before,
.ticket-divider::after {
  content: '';
  position: absolute; left: 50%;
  width: 10px; height: 10px; border-radius: 50%;
  background: var(--bg2);
  border: 1px solid color-mix(in srgb, var(--ac) 28%, var(--bd));
  transform: translateX(-50%);
}
.ticket-divider::before { top: -6px; }
.ticket-divider::after  { bottom: -6px; }
.ticket-body {
  flex: 1; min-width: 0;
  display: flex; flex-direction: column;
  justify-content: center;
  gap: var(--sp-2);
  padding: var(--sp-3);
}
.ticket-top {
  display: flex; align-items: center; gap: var(--sp-2);
  justify-content: space-between;
}
.ticket-sub { color: var(--t2); font-size: var(--text-xs); }
.ticket-code-row {
  display: flex; align-items: center; gap: var(--sp-1);
  min-width: 0;
}
.ticket-code {
  flex: 1 1 auto; min-width: 0;
  color: var(--t1);
  font-size: var(--text-sm);
  letter-spacing: .04em;
  background: var(--bg-in);
  border: 1px solid var(--bd);
  border-radius: var(--r-xs);
  padding: 4px 8px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.copy-btn--inline { flex: 0 0 auto; }
.ticket-meta {
  flex: 0 0 auto;
  display: inline-flex; align-items: center; gap: 4px;
  font-size: var(--text-xs); color: var(--t3);
  white-space: nowrap;
}
.expiry-warning { color: var(--amber); }
.coupon-more {
  margin-top: var(--sp-1);
  text-align: center;
}
.coupon-toggle {
  display: inline-flex; align-items: center; justify-content: center;
  background: transparent; border: none; cursor: pointer;
  color: var(--t2);
  padding: 2px var(--sp-2);
  border-radius: var(--r-xs);
  line-height: 1;
}
.coupon-toggle:hover { background: var(--bg3); color: var(--ac); }

/* ── referral list (desktop = table, mobile = card list) ── */
.ref-table { width: 100%; border-collapse: collapse; font-size: var(--text-sm); }
.ref-table thead th {
  text-align: left; padding: var(--sp-2) var(--sp-3);
  color: var(--t3); font-weight: 500;
  border-bottom: 1px solid var(--bd);
  background: var(--bg-in);
}
.ref-table tbody td {
  padding: var(--sp-2) var(--sp-3);
  border-bottom: 1px solid var(--bd);
  color: var(--t1);
}
.ref-table tbody tr:last-child td { border-bottom: none; }
.mono { font-family: 'IBM Plex Mono', monospace; }

.ref-list { display: none; list-style: none; padding: 0; margin: 0; }
.ref-row {
  display: flex; flex-direction: column; gap: 6px;
  padding: var(--sp-3); border-radius: var(--r-sm);
  background: var(--bg-in); border: 1px solid var(--bd);
}
.ref-row + .ref-row { margin-top: var(--sp-2); }
.ref-row__top {
  display: flex; align-items: center; justify-content: space-between;
  gap: var(--sp-2);
}
.ref-row__name { color: var(--t1); font-weight: 600; font-size: var(--text-sm); }
.ref-row__meta {
  display: flex; flex-wrap: wrap; gap: var(--sp-3);
  color: var(--t3); font-size: var(--text-xs);
}
.ref-row__metaItem { display: inline-flex; align-items: center; gap: 4px; }

/* ── mobile ── */
@media (max-width: 768px) {
  .promo-section { padding: var(--sp-1); }
  .ticket-grid { grid-template-columns: 1fr; }
  .ticket-amount { flex: 0 0 84px; }
  .ticket-value { font-size: 1.6rem; }
  .ref-table { display: none; }
  .ref-list  { display: block; }
}
</style>


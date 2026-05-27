<script setup lang="ts">
/**
 * UserInviteTab — referral hub shown inside the orders page.
 *
 * Layout:
 *   - Top: AlertBanner explaining the referral reward
 *   - Hero card: invite code + share link (display + copy button, pattern
 *     borrowed from AdminServerOverviewPane) + stats
 *   - History card: recent referrals table
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useClipboard } from '@/composables/useClipboard'
import AlertBanner from '@/components/ui/AlertBanner.vue'
import BaseCard from '@/components/ui/BaseCard.vue'
import Badge from '@/components/ui/Badge.vue'
import LoadingCenter from '@/components/ui/LoadingCenter.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import SectionHeader from '@/components/ui/SectionHeader.vue'
import MsIcon from '@/components/ui/MsIcon.vue'

defineOptions({ name: 'UserInviteTab' })

interface InviteCode {
  code: string
  invite_url: string | null
  disabled: boolean
  created_at: string | null
}

interface Referral {
  id: number
  inviter_user_id: number
  invitee_user_id: number
  invitee_username: string | null
  invitee_email: string | null
  invite_code: string
  status: string
  qualifying_order_id: number | null
  rewarded_at: string | null
  inviter_coupon_id: number | null
  invitee_coupon_id: number | null
  created_at: string
}

interface InviteSummary {
  invite: InviteCode
  stats: { registered: number; rewarded: number; revoked: number; total: number }
  recent: Referral[]
  reward?: {
    enabled: boolean
    qualifying_min_fen: number
    inviter_discount_fen: number | null
    invitee_discount_fen: number | null
    inviter_valid_days: number | null
    invitee_valid_days: number | null
    inviter_min_order_fen: number | null
    invitee_min_order_fen: number | null
  } | null
}

const { t } = useI18n({ useScope: 'global' })
const { get } = useApiFetch()
const { copy } = useClipboard()

const loading = ref(true)
const summary = ref<InviteSummary | null>(null)

async function load() {
  loading.value = true
  const data = await get<InviteSummary>('/api/user/invite', { silent: true })
  if (data) summary.value = data
  loading.value = false
}

onMounted(load)

const inviteLink = computed(() => {
  const fromApi = summary.value?.invite.invite_url
  if (fromApi) return fromApi
  // Fallback: SITE_URL not configured — synthesize from window.location so
  // the user still has a working link to share, just on the current origin.
  if (!summary.value) return ''
  const origin = window.location.origin
  return `${origin}/#/register?invite=${summary.value.invite.code}`
})

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '—'
  return d.toLocaleString(undefined, {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  })
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

/** Format ``fen`` (cents) as ¥X.XX, trimming trailing zeros. */
function fmtYuan(fen: number | null | undefined): string {
  if (fen == null) return '—'
  const y = fen / 100
  // Show two decimals only when needed.
  return `¥${(y % 1 === 0 ? y.toFixed(0) : y.toFixed(2))}`
}

const rewardCopy = computed<{ headline: string; detail: string }>(() => {
  const r = summary.value?.reward
  if (!r) {
    // Backend hasn't been restarted (or older deployment) — show a safe
    // generic fallback rather than an empty page.
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
</script>

<template>
  <LoadingCenter v-if="loading" />

  <div v-else-if="summary" class="invite-tab">
    <!-- Top banner explaining the reward -->
    <AlertBanner tone="info" icon="local_offer">
      <div class="reward-banner">
        <div class="reward-headline">{{ rewardCopy.headline }}</div>
        <div class="reward-detail">{{ rewardCopy.detail }}</div>
      </div>
    </AlertBanner>

    <!-- Hero: invite code + share link + stats -->
    <BaseCard variant="bg2" class="invite-section">
      <div class="field-block">
        <div class="field-label">{{ t('billing.invite.yourCode') }}</div>
        <div class="value-row">
          <span class="value-box mono value-box--code">{{ summary.invite.code }}</span>
          <button class="copy-btn" :title="t('common.btn.copy')" @click="copy(summary.invite.code)">
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
          <div class="stat-num">{{ summary.stats.total }}</div>
          <div class="stat-label">{{ t('billing.invite.stats.total') }}</div>
        </div>
        <div class="stat-tile stat-tile--accent">
          <div class="stat-num">{{ summary.stats.rewarded }}</div>
          <div class="stat-label">{{ t('billing.invite.stats.rewarded') }}</div>
        </div>
        <div class="stat-tile">
          <div class="stat-num">{{ summary.stats.registered }}</div>
          <div class="stat-label">{{ t('billing.invite.stats.pending') }}</div>
        </div>
      </div>
    </BaseCard>

    <!-- Recent referrals -->
    <BaseCard variant="bg2" class="invite-section">
      <SectionHeader :title="t('billing.invite.history')" />
      <EmptyState
        v-if="summary.recent.length === 0"
        icon="group_add"
        :message="t('billing.invite.empty')"
        density="compact"
      />
      <table v-else class="ref-table">
        <thead>
          <tr>
            <th>{{ t('billing.invite.table.invitee') }}</th>
            <th>{{ t('billing.invite.table.registeredAt') }}</th>
            <th>{{ t('billing.invite.table.status') }}</th>
            <th>{{ t('billing.invite.table.rewardedAt') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in summary.recent" :key="r.id">
            <td>{{ r.invitee_username || `#${r.invitee_user_id}` }}</td>
            <td class="mono">{{ formatDate(r.created_at) }}</td>
            <td><Badge :color="statusColor(r.status)">{{ statusLabel(r.status) }}</Badge></td>
            <td class="mono">{{ formatDate(r.rewarded_at) }}</td>
          </tr>
        </tbody>
      </table>
    </BaseCard>
  </div>
</template>

<style scoped>
.invite-tab {
  max-width: 760px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
  width: 100%;
}

.invite-section {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

.reward-banner {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.reward-headline {
  font-weight: 600;
  color: var(--t1);
}
.reward-detail {
  color: var(--t2);
  font-size: var(--text-sm);
  line-height: 1.55;
}

.field-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field-label {
  color: var(--t3);
  font-size: var(--text-sm);
}

.value-row {
  display: flex;
  align-items: stretch;
  gap: var(--sp-2);
  min-width: 0;
}

.value-box {
  flex: 1;
  min-width: 0;
  padding: var(--sp-2) var(--sp-3);
  background: var(--bg-in);
  border: 1px solid var(--bd);
  border-radius: var(--r-sm);
  color: var(--t1);
  font-size: var(--text-sm);
  display: inline-flex;
  align-items: center;
}

.value-box--code {
  font-size: 1.05rem;
  font-weight: 600;
  letter-spacing: 0.14em;
  color: var(--ac);
}

.trunc {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.copy-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-in);
  border: 1px solid var(--bd);
  border-radius: var(--r-sm);
  color: var(--t2);
  cursor: pointer;
  padding: 0 10px;
  transition: color .15s, background .15s, border-color .15s;
}
.copy-btn:hover {
  color: var(--ac);
  background: var(--bg3);
  border-color: color-mix(in srgb, var(--ac) 35%, var(--bd));
}

.stat-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--sp-2);
  margin-top: var(--sp-1);
}

.stat-tile {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--sp-3);
  border-radius: var(--r-md);
  background: var(--bg-in);
  border: 1px solid var(--bd);
}

.stat-tile--accent {
  border-color: color-mix(in srgb, var(--ac) 35%, var(--bd));
  background: color-mix(in srgb, var(--ac) 6%, var(--bg-in));
}

.stat-num {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 1.4rem;
  font-weight: 700;
  color: var(--t1);
}

.stat-tile--accent .stat-num {
  color: var(--ac);
}

.stat-label {
  font-size: var(--text-xs);
  color: var(--t3);
  margin-top: 2px;
}

.mono {
  font-family: 'IBM Plex Mono', monospace;
}

.ref-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--text-sm);
}

.ref-table thead th {
  text-align: left;
  padding: var(--sp-2) var(--sp-3);
  color: var(--t3);
  font-weight: 500;
  border-bottom: 1px solid var(--bd);
  background: var(--bg-in);
}

.ref-table tbody td {
  padding: var(--sp-2) var(--sp-3);
  border-bottom: 1px solid var(--bd);
  color: var(--t1);
}

.ref-table tbody tr:last-child td {
  border-bottom: none;
}
</style>

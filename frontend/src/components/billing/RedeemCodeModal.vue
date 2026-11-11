<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useApiFetch } from '@/composables/useApiFetch'
import { apiErrorMessage } from '@/composables/apiClient'
import { useToast } from '@/composables/useToast'
import { useFormatDate } from '@/composables/useFormatDate'
import BaseModal from '@/components/ui/BaseModal.vue'
import BaseCard from '@/components/ui/BaseCard.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import Badge from '@/components/ui/Badge.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import FormField from '@/components/form/FormField.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import AlertBanner from '@/components/ui/AlertBanner.vue'

defineOptions({ name: 'RedeemCodeModal' })

interface RedeemCompatibleServer {
  id: number
  name: string
  kind: 'renew' | 'convert'
  is_trial: boolean
  is_suspended: boolean
  current_expiration_date: string | null
  projected_expiration_date: string
}

interface RedeemPlanSummary {
  id: number
  code: string
  display_name: string
  cpu: number
  memory_mb: number
  disk_mb: number
  llm_enabled: boolean
  llm_quota_grant: number
}

interface RedeemPreview {
  code: string
  days: number
  expires_at: string | null
  plan: RedeemPlanSummary
  new_server_expiration_date: string
  compatible_servers: RedeemCompatibleServer[]
  already_redeemed_by_me: boolean
  order_id: number | null
  order_no: string | null
  target_server_id: number | null
}

interface RedeemResult {
  code: string
  kind: 'new_purchase' | 'renew' | 'convert'
  order_id: number
  order_no: string
  server_id: number
  server_name: string
  days: number
  new_expiration_date: string
}

const props = defineProps<{
  modelValue: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  redeemed: [result: RedeemResult]
}>()

const { t } = useI18n({ useScope: 'global' })
const router = useRouter()
const { raw } = useApiFetch()
const { toast } = useToast()
const { formatDateTime: fmtDate } = useFormatDate()

const codeInput = ref('')
const preview = ref<RedeemPreview | null>(null)
const result = ref<RedeemResult | null>(null)
const selectedTarget = ref<'new' | number | ''>('')
const loadingPreview = ref(false)
const submitting = ref(false)
const errorMsg = ref<string | null>(null)

function resetState() {
  codeInput.value = ''
  preview.value = null
  result.value = null
  selectedTarget.value = ''
  loadingPreview.value = false
  submitting.value = false
  errorMsg.value = null
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) resetState()
  },
)

function formatResource(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}

const cpuLabel = computed(() =>
  preview.value ? formatResource(preview.value.plan.cpu / 100) : '',
)
const memLabel = computed(() =>
  preview.value ? formatResource(preview.value.plan.memory_mb / 1024) : '',
)
const diskLabel = computed(() =>
  preview.value ? formatResource(preview.value.plan.disk_mb / 1024) : '',
)

const canPreview = computed(() => !loadingPreview.value && codeInput.value.trim().length >= 4)
const canConfirm = computed(() => {
  if (!preview.value || preview.value.already_redeemed_by_me || submitting.value) return false
  return selectedTarget.value === 'new' || typeof selectedTarget.value === 'number'
})

async function doPreview() {
  if (!canPreview.value) return
  loadingPreview.value = true
  errorMsg.value = null
  try {
    const res = await raw('/api/user/redemptions/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code: codeInput.value.trim() }),
      silent: true,
    })
    const data = (await res.json()) as RedeemPreview
    preview.value = data
    selectedTarget.value = data.compatible_servers.length === 0 ? 'new' : ''
  } catch (err) {
    errorMsg.value = apiErrorMessage(err)
  } finally {
    loadingPreview.value = false
  }
}

function resetPreview() {
  preview.value = null
  selectedTarget.value = ''
  errorMsg.value = null
}

async function doRedeem() {
  if (!canConfirm.value || !preview.value) return
  submitting.value = true
  errorMsg.value = null
  try {
    const targetServerId = typeof selectedTarget.value === 'number' ? selectedTarget.value : null
    const res = await raw('/api/user/redemptions/redeem', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        code: preview.value.code,
        target_server_id: targetServerId,
      }),
      silent: true,
    })
    const data = (await res.json()) as RedeemResult
    result.value = data
    toast(t('billing.redeem.successToast'), 'success')
    emit('redeemed', data)
  } catch (err) {
    errorMsg.value = apiErrorMessage(err)
  } finally {
    submitting.value = false
  }
}

function close() {
  emit('update:modelValue', false)
}

function goServers() {
  emit('update:modelValue', false)
  void router.push({ name: 'user-servers' })
}
</script>

<template>
  <BaseModal
    :model-value="modelValue"
    :title="t('billing.redeem.modalTitle')"
    icon="redeem"
    size="md"
    :persistent="submitting"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="redeem-body">
      <AlertBanner v-if="errorMsg" tone="danger">{{ errorMsg }}</AlertBanner>

      <!-- Stage 3: Success summary -->
      <template v-if="result">
        <BaseCard variant="bg3" class="success-card">
          <div class="success-head">
            <MsIcon name="check_circle" size="md" class="success-icon" />
            <div>
              <div class="success-title">{{ t('billing.redeem.successTitle') }}</div>
              <div class="success-desc">
                <template v-if="result.kind === 'new_purchase'">
                  {{ t('billing.redeem.successDescNew', { serverName: result.server_name, date: result.new_expiration_date }) }}
                </template>
                <template v-else-if="result.kind === 'convert'">
                  {{ t('billing.redeem.successDescConvert', { serverName: result.server_name, days: result.days, date: result.new_expiration_date }) }}
                </template>
                <template v-else>
                  {{ t('billing.redeem.successDescRenew', { serverName: result.server_name, days: result.days, date: result.new_expiration_date }) }}
                </template>
              </div>
            </div>
          </div>
          <div class="success-meta mono">
            {{ t('billing.orderDetail.orderNo') }}：{{ result.order_no }}
          </div>
        </BaseCard>
      </template>

      <!-- Stage 1: Code input -->
      <template v-else-if="!preview">
        <FormField :label="t('billing.redeem.codeLabel')" required>
          <BaseInput
            v-model="codeInput"
            mono
            :placeholder="t('billing.redeem.codePlaceholder')"
            @keydown.enter.prevent="doPreview"
          />
        </FormField>
      </template>

      <!-- Stage 2: Preview & Target choice -->
      <template v-else>
        <div class="code-pill-bar">
          <code>{{ preview.code }}</code>
          <button type="button" class="link-btn" :disabled="submitting" @click="resetPreview">
            {{ t('billing.redeem.changeCode') }}
          </button>
        </div>

        <AlertBanner v-if="preview.already_redeemed_by_me" tone="info">
          {{ t('billing.redeem.alreadyRedeemedBanner', { orderNo: preview.order_no || `#${preview.order_id}` }) }}
        </AlertBanner>

        <template v-else>
          <div class="hero">
            <div class="hero__main">
              <h3 class="hero__name">{{ preview.plan.display_name }}</h3>
              <div v-if="preview.expires_at" class="hero__sub">
                {{ t('billing.redeem.codeExpiry', { date: fmtDate(preview.expires_at) }) }}
              </div>
            </div>
            <Badge color="var(--ac)">
              {{ t('billing.redeem.daysBadge', { days: preview.days }) }}
            </Badge>
          </div>

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

          <section class="section">
            <div class="section__title">{{ t('billing.redeem.targetSection') }}</div>

            <div class="target-list">
              <label
                v-for="srv in preview.compatible_servers"
                :key="srv.id"
                class="target-row"
                :class="{ selected: selectedTarget === srv.id }"
              >
                <input
                  v-model="selectedTarget"
                  type="radio"
                  :value="srv.id"
                  class="target-radio"
                />
                <span class="target-radio-dot" />
                <div class="target-info">
                  <div class="target-title-row">
                    <span class="target-label">
                      {{ srv.kind === 'convert'
                        ? t('billing.redeem.convertServerTitle', { name: srv.name })
                        : t('billing.redeem.renewServerTitle', { name: srv.name }) }}
                    </span>
                    <Badge v-if="srv.is_suspended" color="var(--amber)" size="sm">
                      {{ t('billing.redeem.suspendedBadge') }}
                    </Badge>
                  </div>
                  <div class="target-sub mono">
                    {{ t('billing.redeem.serverExpiryChange', {
                      before: srv.current_expiration_date || '—',
                      after: srv.projected_expiration_date,
                    }) }}
                  </div>
                </div>
              </label>

              <label
                class="target-row"
                :class="{ selected: selectedTarget === 'new' }"
              >
                <input
                  v-model="selectedTarget"
                  type="radio"
                  value="new"
                  class="target-radio"
                />
                <span class="target-radio-dot" />
                <div class="target-info">
                  <div class="target-title-row">
                    <span class="target-label">{{ t('billing.redeem.newServerTitle') }}</span>
                  </div>
                  <div class="target-sub mono">
                    {{ t('billing.redeem.newServerExpiry', { date: preview.new_server_expiration_date }) }}
                  </div>
                </div>
              </label>
            </div>
          </section>
        </template>
      </template>
    </div>

    <template #footer>
      <div class="footer-actions">
        <template v-if="result">
          <BaseButton @click="close">{{ t('billing.redeem.doneBtn') }}</BaseButton>
          <BaseButton variant="primary" @click="goServers">{{ t('billing.redeem.goServers') }}</BaseButton>
        </template>
        <template v-else-if="!preview">
          <BaseButton @click="close">{{ t('common.btn.cancel') }}</BaseButton>
          <BaseButton variant="primary" :loading="loadingPreview" :disabled="!canPreview" @click="doPreview">
            {{ t('billing.redeem.previewBtn') }}
          </BaseButton>
        </template>
        <template v-else-if="preview.already_redeemed_by_me">
          <BaseButton @click="close">{{ t('billing.redeem.doneBtn') }}</BaseButton>
          <BaseButton variant="primary" @click="goServers">{{ t('billing.redeem.goServers') }}</BaseButton>
        </template>
        <template v-else>
          <BaseButton :disabled="submitting" @click="close">{{ t('common.btn.cancel') }}</BaseButton>
          <BaseButton variant="primary" :loading="submitting" :disabled="!canConfirm" @click="doRedeem">
            {{ t('billing.redeem.confirmBtn') }}
          </BaseButton>
        </template>
      </div>
    </template>
  </BaseModal>
</template>

<style scoped>
.redeem-body { display: flex; flex-direction: column; gap: var(--sp-3); }

.code-pill-bar {
  display: flex; align-items: center; justify-content: space-between; gap: var(--sp-2);
  padding: var(--sp-2) var(--sp-3); background: var(--bg3); border: 1px solid var(--bd); border-radius: var(--r-sm);
}
code {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  color: var(--t1);
}
.link-btn {
  border: 0; background: none; color: var(--ac); font: inherit; font-size: var(--text-xs); cursor: pointer;
}
.link-btn:hover { text-decoration: underline; }

.hero {
  display: flex; align-items: flex-start; justify-content: space-between; gap: var(--sp-3);
}
.hero__main { min-width: 0; }
.hero__name { margin: 0; font-size: var(--text-lg); font-weight: 600; color: var(--t1); }
.hero__sub { margin-top: 2px; font-size: var(--text-xs); color: var(--t3); }

.res-strip {
  display: flex; align-items: center; gap: var(--sp-2);
  padding: var(--sp-2) var(--sp-3);
  background: var(--bg-in); border: 1px solid var(--bd); border-radius: var(--r-md);
  font-size: var(--text-sm); color: var(--t2); flex-wrap: wrap;
}
.res-item { display: inline-flex; align-items: center; gap: var(--sp-1); }
.res-divider { color: var(--t3); }

.section__title { font-size: var(--text-sm); color: var(--t2); font-weight: 500; margin-bottom: var(--sp-2); }

.target-list { display: flex; flex-direction: column; gap: var(--sp-2); }
.target-row {
  display: flex; align-items: center; gap: var(--sp-3);
  padding: var(--sp-3); border: 1px solid var(--bd); border-radius: var(--r-md);
  cursor: pointer; transition: border-color .15s, background .15s;
}
.target-row:hover { border-color: var(--bd-f); }
.target-row.selected {
  border-color: var(--bd-f);
  background: color-mix(in srgb, var(--ac) 8%, transparent);
}
.target-radio { position: absolute; opacity: 0; pointer-events: none; }
.target-radio-dot {
  width: 16px; height: 16px; border-radius: 50%; border: 1.5px solid var(--bd);
  position: relative; flex-shrink: 0;
}
.target-row.selected .target-radio-dot { border-color: var(--ac); }
.target-row.selected .target-radio-dot::after {
  content: ''; position: absolute; inset: 3px; border-radius: 50%; background: var(--ac);
}
.target-info { flex: 1; min-width: 0; }
.target-title-row { display: flex; align-items: center; gap: var(--sp-2); flex-wrap: wrap; }
.target-label { color: var(--t1); font-weight: 500; font-size: var(--text-base); }
.target-sub { color: var(--t2); font-size: var(--text-xs); margin-top: 2px; }
.mono { font-family: var(--font-mono); }

.success-card { display: flex; flex-direction: column; gap: var(--sp-2); }
.success-head { display: flex; align-items: flex-start; gap: var(--sp-2); }
.success-icon { color: var(--green); flex-shrink: 0; margin-top: 2px; }
.success-title { font-size: var(--text-base); font-weight: 600; color: var(--t1); }
.success-desc { font-size: var(--text-sm); color: var(--t2); margin-top: 4px; line-height: 1.5; }
.success-meta { font-size: var(--text-xs); color: var(--t3); padding-top: var(--sp-2); border-top: 1px solid var(--bd); }

.footer-actions { display: flex; align-items: center; justify-content: flex-end; gap: var(--sp-2); width: 100%; }
</style>

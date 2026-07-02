<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'
import { provideDirtyForm, useDirtyFormSection } from '@/composables/useDirtyForm'
import { useAppStore } from '@/stores/app'
import PageHeader from '@/components/layout/PageHeader.vue'
import TabSwitcher, { type TabItem } from '@/components/ui/TabSwitcher.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import NumberInput from '@/components/form/NumberInput.vue'
import SecretInput from '@/components/ui/SecretInput.vue'
import ToggleSwitch from '@/components/ui/ToggleSwitch.vue'
import Spinner from '@/components/ui/Spinner.vue'
import HelpTip from '@/components/ui/HelpTip.vue'
import FormField from '@/components/form/FormField.vue'
import Badge from '@/components/ui/Badge.vue'
import DirtyBar from '@/components/ui/DirtyBar.vue'
import BaseCard from '@/components/ui/BaseCard.vue'
import SectionHeader from '@/components/ui/SectionHeader.vue'
import AccountSettingsPanel from '@/components/account/AccountSettingsPanel.vue'
import { TIMEZONE_OPTIONS } from '@/config/timezones'

defineOptions({ name: 'SettingsPage' })

const { t } = useI18n({ useScope: 'global' })
const { get, post, put } = useApiFetch()
const { toast } = useToast()
const { confirm } = useConfirm()
const app = useAppStore()

// ── Tabs ──
const activeTab = ref('account')
const tabs = computed<TabItem[]>(() => [
  { key: 'account',    label: t('settings.account.title'),  icon: 'lock' },
  { key: 'smtp',       label: t('settings.smtp.title'),     icon: 'mail' },
  { key: 'payment',    label: t('settings.payment.title'),  icon: 'payments' },
  { key: 'branding',   label: t('settings.branding.title'), icon: 'palette' },
  { key: 'defaults',   label: t('settings.defaults.title'), icon: 'tune' },
  { key: 'automation', label: t('settings.automation.title'), icon: 'schedule' },
  { key: 'marketing',  label: t('settings.marketing.title'), icon: 'campaign' },
  { key: 'llm',        label: t('settings.llm.title'),        icon: 'smart_toy' },
])

// ── State ──
const initialLoading = ref(true)
const settings = ref<Record<string, any>>({})
const billingSettings = ref<Record<string, any>>({})
const llmSettings = ref<Record<string, any>>({})
const automation = ref({
  AUTOMATION_RUN_HOUR: 2,
  AUTOMATION_RUN_MINUTE: 0,
  AUTOMATION_SUSPEND_ENABLED: false,
  AUTOMATION_DELETE_ENABLED: false,
  AUTOMATION_DELETE_DAYS: 14,
  AUTOMATION_EMAIL_ENABLED: false,
  AUTOMATION_EMAIL_RUN_HOUR: 10,
  AUTOMATION_EMAIL_RUN_MINUTE: 0,
  TIMEZONE: 'Asia/Shanghai',
})
const saveLoading = ref(false)

// ── Payment tab helpers ──
const GATEWAY_CODES = ['hupijiao', 'alipay_direct'] as const
const gatewayTabs = computed<TabItem[]>(() =>
  GATEWAY_CODES.map(code => {
    const enabled = getBillingBool(`${code.toUpperCase()}_ENABLED`)
    const labelKey = code === 'hupijiao' ? 'settings.payment.gateways.hupijiao' : 'settings.payment.gateways.alipay_direct'
    return {
      key: code,
      label: t(labelKey),
      disabled: !enabled,
    }
  })
)
const activeGateway = ref<string>('hupijiao')
watch(gatewayTabs, (tabs) => {
  const active = tabs.find(t => t.key === activeGateway.value)
  if (!active || active.disabled) {
    const firstEnabled = tabs.find(t => !t.disabled)
    if (firstEnabled) activeGateway.value = firstEnabled.key
  }
}, { immediate: true })
function getBillingStr(key: string, def = ''): string { return billingSettings.value[key] ?? def }
function setBillingStr(key: string, val: string) { billingSettings.value[key] = val }
function getBillingNum(key: string, def = 0): number { return Number(billingSettings.value[key]) || def }
function setBillingNum(key: string, val: string | number | boolean | (string | number | boolean)[]) {
  const v = Array.isArray(val) ? val[0] : val
  billingSettings.value[key] = Number(v)
}
function getBillingBool(key: string): boolean {
  const v = billingSettings.value[key]
  return v === true || v === 'true' || v === '1'
}
function setBillingBool(key: string, val: boolean) { billingSettings.value[key] = val }

// ── LLM settings helpers ──
function getLlmStr(key: string, def = ''): string { return llmSettings.value[key] ?? def }
function setLlmStr(key: string, val: string) { llmSettings.value[key] = val }
function getLlmNum(key: string, def = 0): number { return Number(llmSettings.value[key]) || def }
function setLlmNum(key: string, val: string | number | boolean | (string | number | boolean)[]) {
  const v = Array.isArray(val) ? val[0] : val
  llmSettings.value[key] = Number(v)
}
function getLlmBool(key: string): boolean {
  const v = llmSettings.value[key]
  return v === true || v === 'true' || v === '1'
}
function setLlmBool(key: string, val: boolean) { llmSettings.value[key] = val }
function getLlmSecret(key: string): string {
  const v = llmSettings.value[key]
  if (!v || v === '********') return ''
  return String(v)
}
function setLlmSecret(key: string, val: string) { llmSettings.value[key] = val }

// ── SMTP test email ──
const testEmailRecipient = ref('')
const testEmailSending = ref(false)
async function sendTestEmail() {
  const to = testEmailRecipient.value.trim()
  if (!to || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(to)) {
    toast(t('settings.smtp.testInvalid'), 'error')
    return
  }
  testEmailSending.value = true
  try {
    const override: Record<string, any> = {}
    if (settings.value.SMTP_HOST) override.SMTP_HOST = settings.value.SMTP_HOST
    if (settings.value.SMTP_PORT) override.SMTP_PORT = settings.value.SMTP_PORT
    override.SMTP_USE_SSL = !!getBool('SMTP_USE_SSL')
    if (settings.value.SMTP_PASSWORD) override.SMTP_PASSWORD = settings.value.SMTP_PASSWORD
    if (settings.value.SENDER_EMAIL) override.SENDER_EMAIL = settings.value.SENDER_EMAIL
    const r = await post<{ ok: boolean; error: string | null }>('/api/admin/test-email', {
      recipient: to,
      smtpOverride: override,
    })
    if (r?.ok) toast(t('settings.smtp.testOk'), 'success')
    else toast(t('settings.smtp.testFail', { err: r?.error || 'unknown' }), 'error')
  } catch (e: any) {
    toast(t('settings.smtp.testFail', { err: String(e?.message || e) }), 'error')
  } finally {
    testEmailSending.value = false
  }
}

// ── Helpers ──
function getStr(key: string, def = ''): string { return settings.value[key] ?? def }
function setStr(key: string, val: string) { settings.value[key] = val }
function getNum(key: string, def = 0): number { return Number(settings.value[key]) || def }
function setNum(key: string, val: string | number | boolean | (string | number | boolean)[]) {
  const v = Array.isArray(val) ? val[0] : val
  settings.value[key] = Number(v)
}
function getBool(key: string): boolean {
  const v = settings.value[key]
  return v === true || v === 'true' || v === '1'
}
function setBool(key: string, val: boolean) { settings.value[key] = val }

// ── Resources for selects ──
const nestList = ref<any[]>([])
const eggList = ref<any[]>([])
const nodeList = ref<any[]>([])
const nestOptions = computed(() => nestList.value.map((n: any) => ({ value: n.id, label: `${n.name} (#${n.id})` })))
const eggOptions = computed(() => eggList.value.map((e: any) => ({ value: e.id, label: `${e.name} (#${e.id})` })))
const nodeOptions = computed(() => nodeList.value.map((n: any) => ({ value: n.id, label: `${n.name} (#${n.id})` })))

// Coupon templates — populated for the marketing tab so referral template
// pickers don't ask the operator to type raw codes.
interface CouponTemplateLite {
  id: number
  code: string
  name: string
  discount_fen: number
  valid_days: number
  is_active: boolean
}
const couponTemplates = ref<CouponTemplateLite[]>([])
const couponTemplateOptions = computed(() =>
  couponTemplates.value
    .filter(tpl => tpl.is_active)
    .map(tpl => ({
      value: tpl.code,
      label: `${tpl.name} · ¥${(tpl.discount_fen / 100).toFixed(2)} · ${tpl.valid_days}d`,
    }))
)

// Order-kind multi-select options (matches BillingOrder.kind enum subset that
// can qualify a referral reward).
const QUALIFYING_KIND_KEYS = ['new_purchase', 'renew', 'upgrade'] as const
const qualifyingKindOptions = computed(() =>
  QUALIFYING_KIND_KEYS.map(k => ({
    value: k,
    label: t(`settings.marketing.referral.kindOption.${k}`),
  }))
)

/** Read REFERRAL_QUALIFYING_KINDS as a string[] (backend returns a JSON list). */
function getBillingKinds(): string[] {
  const raw = billingSettings.value['REFERRAL_QUALIFYING_KINDS']
  if (Array.isArray(raw)) return raw.map(String).filter(Boolean)
  return ['new_purchase', 'renew', 'upgrade']
}

watch(() => getNum('DEFAULT_NEST_ID'), async (nestId) => {
  if (!nestId) { eggList.value = []; return }
  const data = await get<{ eggs: any[] }>(`/api/admin/resources/nests/${nestId}/eggs`)
  eggList.value = data?.eggs || []
})

// ── Fetch ──
onMounted(async () => {
  const [settingsData, autoData, billingData, llmData, nestsRes, nodesRes, tplRes] = await Promise.all([
    get<Record<string, any>>('/api/admin/settings'),
    get<Record<string, any>>('/api/admin/automation'),
    get<Record<string, any>>('/api/admin/billing/settings'),
    get<Record<string, any>>('/api/admin/llm/settings'),
    get<{ nests: any[] }>('/api/admin/resources/nests'),
    get<{ nodes: any[] }>('/api/admin/resources/nodes'),
    get<CouponTemplateLite[]>('/api/admin/billing/coupon-templates'),
  ])
  if (settingsData) settings.value = settingsData
  if (autoData) Object.assign(automation.value, autoData)
  if (billingData) billingSettings.value = billingData
  if (llmData) llmSettings.value = llmData
  if (nestsRes) nestList.value = nestsRes.nests
  if (nodesRes) nodeList.value = nodesRes.nodes
  if (tplRes) couponTemplates.value = tplRes
  const nestId = getNum('DEFAULT_NEST_ID')
  if (nestId) {
    const data = await get<{ eggs: any[] }>(`/api/admin/resources/nests/${nestId}/eggs`)
    eggList.value = data?.eggs || []
  }
  initialLoading.value = false
  snapshot()
})

// ── Dirty tracking + leave guard ──
//
// account tab is handled by AccountSettingsPanel which manages its own
// state — it does not contribute to dirty here. All other tabs share
// the two reactive blobs (settings / automation / billingSettings).
const orig = ref({
  settings: '{}',
  automation: '{}',
  billing: '{}',
  llm: '{}',
})
function snapshot() {
  orig.value.settings   = JSON.stringify(settings.value)
  orig.value.automation = JSON.stringify(automation.value)
  orig.value.billing    = JSON.stringify(billingSettings.value)
  orig.value.llm        = JSON.stringify(llmSettings.value)
}
const isDirty = computed(() => {
  if (activeTab.value === 'account') return false
  if (JSON.stringify(settings.value)        !== orig.value.settings) return true
  if (JSON.stringify(automation.value)      !== orig.value.automation) return true
  if (JSON.stringify(billingSettings.value) !== orig.value.billing) return true
  if (JSON.stringify(llmSettings.value)     !== orig.value.llm) return true
  return false
})

function discardChanges() {
  settings.value        = JSON.parse(orig.value.settings)
  automation.value      = JSON.parse(orig.value.automation)
  billingSettings.value = JSON.parse(orig.value.billing)
  llmSettings.value     = JSON.parse(orig.value.llm)
}

// ── Save ──
// Validation: runs across every tab. Each entry describes a concrete
// user-fixable problem and which tab owns it, so the floating dirty
// bar can render a jump-to-tab error list. Rules intentionally allow
// empty values where a runtime default exists (BRAND_NAME, UI_*, etc).
interface ValidationError { tab: string; label: string; message: string }
const URL_RE = /^https?:\/\/[^\s]+$/i
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

function validateAll(): ValidationError[] {
  const errs: ValidationError[] = []

  // SMTP: SENDER_EMAIL, if provided, must be a valid address
  const sender = String(settings.value.SENDER_EMAIL || '').trim()
  if (sender && !EMAIL_RE.test(sender)) {
    errs.push({ tab: 'smtp', label: t('settings.smtp.sender'), message: t('settings.validate.invalidEmail') })
  }

  // Branding: URL fields, if provided, must start with http(s)://
  const urlFields: [string, string][] = [
    ['SITE_URL', 'settings.branding.siteUrl'],
    ['UI_BANNER_URL', 'settings.branding.bannerUrl'],
    ['UI_TUTORIAL_URL', 'settings.branding.tutorialUrl'],
  ]
  for (const [key, labelKey] of urlFields) {
    const v = String(settings.value[key] || '').trim()
    if (v && !URL_RE.test(v)) {
      errs.push({ tab: 'branding', label: t(labelKey), message: t('settings.validate.invalidUrl') })
    }
  }

  // Payment: REFERER, if non-empty, must be http(s)://
  const payUrlFields: [string, string][] = [
    ['HUPIJIAO_REFERER', 'settings.payment.referer'],
  ]
  for (const [key, labelKey] of payUrlFields) {
    const v = String(billingSettings.value[key] || '').trim()
    if (v && !URL_RE.test(v)) {
      errs.push({ tab: 'payment', label: t(labelKey), message: t('settings.validate.invalidUrl') })
    }
  }

  // LLM: URL fields must be http(s)://
  const llmUrlFields: [string, string][] = [
    ['NEWAPI_BASE_URL', 'settings.llm.connection.baseUrl'],
    ['LLM_ST_ENDPOINT_URL', 'settings.llm.injection.stEndpoint'],
  ]
  for (const [key, labelKey] of llmUrlFields) {
    const v = String(llmSettings.value[key] || '').trim()
    if (v && !URL_RE.test(v)) {
      errs.push({ tab: 'llm', label: t(labelKey), message: t('settings.validate.invalidUrl') })
    }
  }

  return errs
}

const errors = computed<ValidationError[]>(() => (isDirty.value ? validateAll() : []))
const hasErrors = computed(() => errors.value.length > 0)

function tabLabel(key: string): string {
  return tabs.value.find(tt => tt.key === key)?.label || key
}

async function saveAll(): Promise<boolean> {
  if (!isDirty.value || saveLoading.value) return true
  if (hasErrors.value) return false
  saveLoading.value = true
  try {
    // Only PUT the section(s) that actually changed. This avoids
    // round-tripping a stale automation payload when the user only
    // touched a settings field (and vice versa), which historically
    // caused unrelated runtime values to be re-applied on every save.
    // (Audit FH2.)
    const settingsDirty = JSON.stringify(settings.value) !== orig.value.settings
    const autoDirty = JSON.stringify(automation.value) !== orig.value.automation
    const billingDirty = JSON.stringify(billingSettings.value) !== orig.value.billing
    const llmDirty = JSON.stringify(llmSettings.value) !== orig.value.llm
    if (settingsDirty) {
      const r = await post<{ message: string }>('/api/admin/settings', settings.value)
      if (!r) return false
    }
    if (autoDirty) {
      const r = await post<{ message: string }>('/api/admin/automation', automation.value)
      if (!r) return false
    }
    if (billingDirty) {
      const r = await post<{ message: string }>('/api/admin/billing/settings', { settings: billingSettings.value })
      if (!r) return false
    }
    if (llmDirty) {
      const r = await post<{ message: string }>('/api/admin/llm/settings', { settings: llmSettings.value })
      if (!r) return false
    }
    if (settingsDirty) await app.loadVersion()
    toast(t('settings.saved'), 'success')
    snapshot()
    return true
  } finally {
    saveLoading.value = false
  }
}

// Page-wide dirty-form orchestration. The custom prompt switches to a
// validation-error dialog when the form has errors (no "save" option in
// that state — user must fix or discard). Both the route leave-guard
// and the tab switcher reuse this same prompt for consistency.
const dirtyForm = provideDirtyForm({
  prompt: async () => {
    if (hasErrors.value) {
      const result = await confirm({
        title: t('settings.unsavedTitle'),
        message: t('settings.unsavedHasErrors'),
        confirmText: t('settings.unsavedDiscard'),
        cancelText: t('settings.unsavedStay'),
      })
      return result === true ? 'discard' : 'stay'
    }
    const result = await confirm({
      title: t('settings.unsavedTitle'),
      message: t('settings.unsavedMessage'),
      confirmText: t('settings.unsavedSave'),
      cancelText: t('settings.unsavedDiscard'),
      altText: t('settings.unsavedStay'),
    })
    if (result === 'alt') return 'stay'
    return result === true ? 'save' : 'discard'
  },
})
dirtyForm.attachLeaveGuard()
useDirtyFormSection({
  name: 'settings',
  isDirty,
  save: saveAll,
  discard: discardChanges,
}, dirtyForm)

/**
 * Intercept tab switches: if the current tab has unsaved changes,
 * prompt the user. Reuses the page-level dirty-form prompt so both
 * route-leave and tab-switch surface identical dialogs.
 */
async function onTabChange(next: string) {
  if (next === activeTab.value) return
  if (!isDirty.value) {
    activeTab.value = next
    return
  }
  const r = await dirtyForm.promptUnsaved()
  if (r === 'stay') return
  if (r === 'save') {
    const ok = await saveAll()
    if (!ok) return
  } else {
    discardChanges()
  }
  activeTab.value = next
}

</script>

<template>
  <PageHeader icon="settings" :title="t('settings.title')" />

  <div class="page-body">
    <div v-if="initialLoading" class="center-loading"><Spinner size="lg" /></div>

    <template v-else>
      <TabSwitcher :tabs="tabs" :modelValue="activeTab" @update:modelValue="onTabChange" />

      <AccountSettingsPanel v-if="activeTab === 'account'" />

      <template v-else>
        <div class="st-panel">
          <template v-if="activeTab === 'smtp'">
            <BaseCard variant="bg2" class="settings-card">
              <p class="section-note">{{ t('settings.smtp.desc') }}</p>
              <FormField :label="t('settings.smtp.host')" layout="horizontal">
                <BaseInput :modelValue="getStr('SMTP_HOST')" @update:modelValue="setStr('SMTP_HOST', $event)" />
              </FormField>
              <FormField :label="t('settings.smtp.port')" layout="horizontal">
                <NumberInput :modelValue="getNum('SMTP_PORT', 587)" @update:modelValue="setNum('SMTP_PORT', $event)" :min="1" :max="65535" />
              </FormField>
              <FormField :label="t('settings.smtp.sender')" layout="horizontal">
                <BaseInput :modelValue="getStr('SENDER_EMAIL')" type="email" @update:modelValue="setStr('SENDER_EMAIL', $event)" />
              </FormField>
              <FormField :label="t('settings.smtp.password')" layout="horizontal">
                <SecretInput :modelValue="getStr('SMTP_PASSWORD')" @update:modelValue="setStr('SMTP_PASSWORD', $event)" />
              </FormField>
              <FormField :label="t('settings.smtp.delay')" layout="horizontal">
                <NumberInput :modelValue="getNum('EMAIL_SEND_DELAY', 2)" @update:modelValue="setNum('EMAIL_SEND_DELAY', $event)" :min="0" :max="60" />
              </FormField>
              <FormField :label="t('settings.smtp.ssl')" layout="horizontal">
                <ToggleSwitch :modelValue="getBool('SMTP_USE_SSL')" @update:modelValue="setBool('SMTP_USE_SSL', $event)" />
              </FormField>
              <FormField :hint="undefined" layout="horizontal">
                <template #label>
                  {{ t('settings.smtp.testRecipient') }}
                  <HelpTip :text="t('settings.smtp.testHint')" />
                </template>
                <div class="st-test-row">
                  <BaseInput v-model="testEmailRecipient" type="email" :placeholder="t('settings.smtp.testPlaceholder')" />
                  <BaseButton size="sm" :loading="testEmailSending" @click="sendTestEmail">
                    {{ t('settings.smtp.sendTest') }}
                  </BaseButton>
                </div>
              </FormField>
            </BaseCard>
          </template>

          <template v-else-if="activeTab === 'branding'">
            <BaseCard variant="bg2" class="settings-card">
              <p class="section-note">{{ t('settings.branding.desc') }}</p>
              <FormField :label="t('settings.branding.brandName')" layout="horizontal">
                <BaseInput :modelValue="getStr('BRAND_NAME')" @update:modelValue="setStr('BRAND_NAME', $event)" />
              </FormField>
              <FormField :label="t('settings.branding.systemName')" layout="horizontal">
                <BaseInput :modelValue="getStr('UI_SYSTEM_NAME')" @update:modelValue="setStr('UI_SYSTEM_NAME', $event)" />
              </FormField>
              <FormField :label="t('settings.branding.siteUrl')" layout="horizontal">
                <BaseInput :modelValue="getStr('SITE_URL')" @update:modelValue="setStr('SITE_URL', $event)" />
              </FormField>
              <FormField :label="t('settings.branding.bannerUrl')" layout="horizontal">
                <BaseInput :modelValue="getStr('UI_BANNER_URL')" @update:modelValue="setStr('UI_BANNER_URL', $event)" />
              </FormField>
              <FormField :label="t('settings.branding.icpRecord')" layout="horizontal">
                <BaseInput :modelValue="getStr('UI_ICP_RECORD')" @update:modelValue="setStr('UI_ICP_RECORD', $event)" />
              </FormField>
              <FormField layout="horizontal">
                <template #label>
                  {{ t('settings.branding.tutorialUrl') }}
                  <HelpTip :text="t('settings.branding.tutorialUrl_tip')" />
                </template>
                <BaseInput :modelValue="getStr('UI_TUTORIAL_URL')" @update:modelValue="setStr('UI_TUTORIAL_URL', $event)" placeholder="https://" />
              </FormField>
              <FormField layout="horizontal">
                <template #label>
                  {{ t('settings.branding.allowRegistration') }}
                  <HelpTip :text="t('settings.branding.allowRegistration_tip')" />
                </template>
                <ToggleSwitch :modelValue="getBool('ALLOW_PUBLIC_REGISTRATION')" @update:modelValue="setBool('ALLOW_PUBLIC_REGISTRATION', $event)" size="sm" />
              </FormField>
            </BaseCard>

            <BaseCard variant="bg2" class="settings-card">
              <SectionHeader icon="support_agent" flush>{{ t('settings.branding.support.title') }}</SectionHeader>
              <p class="section-note">{{ t('settings.branding.support.desc') }}</p>
              <FormField :label="t('settings.branding.support.email')" layout="horizontal">
                <BaseInput :modelValue="getStr('SUPPORT_EMAIL')" type="email" @update:modelValue="setStr('SUPPORT_EMAIL', $event)" />
              </FormField>
              <FormField :label="t('settings.branding.support.qqGroup')" layout="horizontal">
                <BaseInput :modelValue="getStr('SUPPORT_QQ_GROUP')" @update:modelValue="setStr('SUPPORT_QQ_GROUP', $event)" />
              </FormField>
              <FormField :label="t('settings.branding.support.qq')" layout="horizontal">
                <BaseInput :modelValue="getStr('SUPPORT_QQ')" @update:modelValue="setStr('SUPPORT_QQ', $event)" />
              </FormField>
              <FormField :label="t('settings.branding.support.wechat')" layout="horizontal">
                <BaseInput :modelValue="getStr('SUPPORT_WECHAT')" @update:modelValue="setStr('SUPPORT_WECHAT', $event)" />
              </FormField>
              <FormField layout="horizontal">
                <template #label>
                  {{ t('settings.branding.support.footerNote') }}
                  <HelpTip :text="t('settings.branding.support.footerNote_tip')" />
                </template>
                <BaseInput :modelValue="getStr('SUPPORT_FOOTER_NOTE')" @update:modelValue="setStr('SUPPORT_FOOTER_NOTE', $event)" />
              </FormField>
            </BaseCard>
          </template>

          <template v-else-if="activeTab === 'payment'">
            <!-- Card 1: Enabled gateways -->
            <BaseCard variant="bg2" class="settings-card">
              <SectionHeader icon="hub" flush>{{ t('settings.payment.gateways.title') }}</SectionHeader>
              <p class="section-note">{{ t('settings.payment.gateways.desc') }}</p>
              <FormField :label="t('settings.payment.gateways.enabled')" layout="horizontal">
                <BaseSelect
                  :modelValue="[
                    ...(getBillingBool('HUPIJIAO_ENABLED') ? ['hupijiao'] : []),
                    ...(getBillingBool('ALIPAY_DIRECT_ENABLED') ? ['alipay_direct'] : []),
                  ]"
                  :options="[
                    { value: 'hupijiao', label: t('settings.payment.gateways.hupijiao') },
                    { value: 'alipay_direct', label: t('settings.payment.gateways.alipay_direct') },
                  ]"
                  multiple
                  @update:modelValue="setBillingBool('HUPIJIAO_ENABLED', (($event as string[]).includes('hupijiao'))), setBillingBool('ALIPAY_DIRECT_ENABLED', (($event as string[]).includes('alipay_direct')))"
                />
              </FormField>
            </BaseCard>

            <!-- Gateway config: TabSwitcher wrapping all gateway cards in one container -->
            <template v-if="getBillingBool('HUPIJIAO_ENABLED') || getBillingBool('ALIPAY_DIRECT_ENABLED')">
              <BaseCard variant="bg2" class="settings-card pay-gateway-config-card">
                <TabSwitcher :tabs="gatewayTabs" :modelValue="activeGateway" @update:modelValue="activeGateway = $event" />

                <!-- Hupijiao -->
                <div v-if="activeGateway === 'hupijiao'" class="pay-gateway-pane">
                  <SectionHeader icon="badge" flush>{{ t('settings.payment.credentials.title') }}</SectionHeader>
                  <p class="section-note">{{ t('settings.payment.credentials.desc') }}</p>
                  <FormField :label="t('settings.payment.credentials.displayName')" layout="horizontal">
                    <BaseInput :modelValue="getBillingStr('HUPIJIAO_DISPLAY_NAME')" @update:modelValue="setBillingStr('HUPIJIAO_DISPLAY_NAME', $event)" />
                  </FormField>
                  <FormField :label="t('settings.payment.credentials.appid')" layout="horizontal">
                    <BaseInput :modelValue="getBillingStr('HUPIJIAO_APPID')" @update:modelValue="setBillingStr('HUPIJIAO_APPID', $event)" />
                  </FormField>
                  <FormField :label="t('settings.payment.credentials.appsecret')" layout="horizontal">
                    <SecretInput :modelValue="getBillingStr('HUPIJIAO_APPSECRET')" @update:modelValue="setBillingStr('HUPIJIAO_APPSECRET', $event)" />
                  </FormField>

                  <SectionHeader icon="link" flush>{{ t('settings.payment.urls.title') }}</SectionHeader>
                  <p class="section-note">{{ t('settings.payment.urls.desc') }}</p>
                  <FormField layout="horizontal">
                    <template #label>
                      {{ t('settings.payment.referer') }}
                      <HelpTip :text="t('settings.payment.referer_tip')" />
                    </template>
                    <BaseInput :modelValue="getBillingStr('HUPIJIAO_REFERER')" @update:modelValue="setBillingStr('HUPIJIAO_REFERER', $event)" />
                  </FormField>
                  <FormField layout="horizontal">
                    <template #label>
                      {{ t('settings.payment.gatewayEndpoints') }}
                      <HelpTip :text="t('settings.payment.gatewayEndpoints_tip')" />
                    </template>
                    <BaseInput :modelValue="getBillingStr('HUPIJIAO_GATEWAY_ENDPOINTS')" @update:modelValue="setBillingStr('HUPIJIAO_GATEWAY_ENDPOINTS', $event)" />
                  </FormField>
                </div>

                <!-- Alipay direct -->
                <div v-if="activeGateway === 'alipay_direct'" class="pay-gateway-pane">
                  <SectionHeader icon="badge" flush>{{ t('settings.payment.credentials.title') }}</SectionHeader>
                  <p class="section-note">{{ t('settings.payment.credentials.desc') }}</p>
                  <FormField :label="t('settings.payment.credentials.displayName')" layout="horizontal">
                    <BaseInput :modelValue="getBillingStr('ALIPAY_DIRECT_DISPLAY_NAME')" @update:modelValue="setBillingStr('ALIPAY_DIRECT_DISPLAY_NAME', $event)" />
                  </FormField>
                  <FormField :label="t('settings.payment.credentials.appid')" layout="horizontal">
                    <BaseInput :modelValue="getBillingStr('ALIPAY_DIRECT_APPID')" @update:modelValue="setBillingStr('ALIPAY_DIRECT_APPID', $event)" />
                  </FormField>
                  <FormField :label="t('settings.payment.alipay.appPrivateKey')" layout="horizontal">
                    <SecretInput :modelValue="getBillingStr('ALIPAY_DIRECT_APP_PRIVATE_KEY')" @update:modelValue="setBillingStr('ALIPAY_DIRECT_APP_PRIVATE_KEY', $event)" />
                  </FormField>
                  <FormField :label="t('settings.payment.alipay.alipayPublicKey')" layout="horizontal">
                    <SecretInput :modelValue="getBillingStr('ALIPAY_DIRECT_ALIPAY_PUBLIC_KEY')" @update:modelValue="setBillingStr('ALIPAY_DIRECT_ALIPAY_PUBLIC_KEY', $event)" />
                  </FormField>

                  <SectionHeader icon="link" flush>{{ t('settings.payment.urls.title') }}</SectionHeader>
                  <p class="section-note">{{ t('settings.payment.alipay.gatewayDesc') }}</p>
                  <FormField layout="horizontal">
                    <template #label>
                      {{ t('settings.payment.alipay.gateway') }}
                      <HelpTip :text="t('settings.payment.alipay.gateway_tip')" />
                    </template>
                    <BaseInput :modelValue="getBillingStr('ALIPAY_DIRECT_GATEWAY')" @update:modelValue="setBillingStr('ALIPAY_DIRECT_GATEWAY', $event)" />
                  </FormField>
                  <FormField :label="t('settings.payment.alipay.sellerId')" layout="horizontal">
                    <BaseInput :modelValue="getBillingStr('ALIPAY_DIRECT_SELLER_ID')" @update:modelValue="setBillingStr('ALIPAY_DIRECT_SELLER_ID', $event)" />
                  </FormField>
                </div>
              </BaseCard>
            </template>
            <BaseCard variant="bg2" class="settings-card">
              <SectionHeader icon="tune" flush>{{ t('settings.payment.quotas.title') }}</SectionHeader>
              <p class="section-note">{{ t('settings.payment.quotas.desc') }}</p>
              <FormField layout="horizontal">
                <template #label>
                  {{ t('settings.payment.payTimeout') }}
                  <HelpTip :text="t('settings.payment.payTimeout_tip')" />
                </template>
                <NumberInput :modelValue="getBillingNum('BILLING_ORDER_PAY_TIMEOUT_MIN', 5)" @update:modelValue="setBillingNum('BILLING_ORDER_PAY_TIMEOUT_MIN', $event)" :min="3" :max="5" />
              </FormField>
              <FormField layout="horizontal">
                <template #label>
                  {{ t('settings.payment.refundStuckHours') }}
                  <HelpTip :text="t('settings.payment.refundStuckHours_tip')" />
                </template>
                <NumberInput :modelValue="getBillingNum('BILLING_REFUND_STUCK_HOURS', 24)" @update:modelValue="setBillingNum('BILLING_REFUND_STUCK_HOURS', $event)" :min="1" :max="168" />
              </FormField>
            </BaseCard>
          </template>

          <template v-else-if="activeTab === 'defaults'">
            <BaseCard variant="bg2" class="settings-card">
              <p class="section-note">{{ t('settings.defaults.desc') }}</p>
              <FormField :label="t('settings.defaults.nest')" layout="horizontal">
                <BaseSelect :modelValue="getNum('DEFAULT_NEST_ID')" :options="nestOptions" :placeholder="t('settings.defaults.nest')" @update:modelValue="setNum('DEFAULT_NEST_ID', $event)" />
              </FormField>
              <FormField :label="t('settings.defaults.egg')" layout="horizontal">
                <BaseSelect :modelValue="getNum('DEFAULT_EGG_ID')" :options="eggOptions" :placeholder="t('settings.defaults.egg')" :disabled="!getNum('DEFAULT_NEST_ID')" @update:modelValue="setNum('DEFAULT_EGG_ID', $event)" />
              </FormField>
              <FormField :label="t('settings.defaults.node')" layout="horizontal">
                <BaseSelect :modelValue="getNum('DEFAULT_NODE_ID')" :options="nodeOptions" :placeholder="t('settings.defaults.node')" @update:modelValue="setNum('DEFAULT_NODE_ID', $event)" />
              </FormField>
              <FormField :label="t('settings.defaults.serverNamePrefix')" layout="horizontal">
                <BaseInput :modelValue="getStr('SERVER_NAME_PREFIX')" :placeholder="t('settings.defaults.serverNamePrefix_placeholder')" @update:modelValue="setStr('SERVER_NAME_PREFIX', $event)" />
              </FormField>
              <FormField :label="t('settings.defaults.dockerImage')" layout="horizontal">
                <BaseInput :modelValue="getStr('DOCKER_IMAGE')" @update:modelValue="setStr('DOCKER_IMAGE', $event)" />
              </FormField>
              <FormField :label="t('settings.defaults.cpu')" layout="horizontal">
                <NumberInput :modelValue="getNum('DEFAULT_CPU', 100)" @update:modelValue="setNum('DEFAULT_CPU', $event)" :min="0" />
              </FormField>
              <FormField :label="t('settings.defaults.memory')" layout="horizontal">
                <NumberInput :modelValue="getNum('DEFAULT_MEMORY', 1024)" @update:modelValue="setNum('DEFAULT_MEMORY', $event)" :min="0" />
              </FormField>
              <FormField :label="t('settings.defaults.disk')" layout="horizontal">
                <NumberInput :modelValue="getNum('DEFAULT_DISK', 5120)" @update:modelValue="setNum('DEFAULT_DISK', $event)" :min="0" />
              </FormField>
              <FormField :label="t('settings.defaults.databases')" layout="horizontal">
                <NumberInput :modelValue="getNum('DEFAULT_DATABASES')" @update:modelValue="setNum('DEFAULT_DATABASES', $event)" :min="0" />
              </FormField>
              <FormField :label="t('settings.defaults.backups')" layout="horizontal">
                <NumberInput :modelValue="getNum('DEFAULT_BACKUPS')" @update:modelValue="setNum('DEFAULT_BACKUPS', $event)" :min="0" />
              </FormField>
              <FormField :label="t('settings.defaults.allocations')" layout="horizontal">
                <NumberInput :modelValue="getNum('DEFAULT_ALLOCATIONS', 1)" @update:modelValue="setNum('DEFAULT_ALLOCATIONS', $event)" :min="0" />
              </FormField>
            </BaseCard>
          </template>

          <template v-else-if="activeTab === 'automation'">
            <BaseCard variant="bg2" class="settings-card">
              <SectionHeader icon="schedule" flush>{{ t('settings.automation.time.title') }}</SectionHeader>
              <p class="section-note">{{ t('settings.automation.time.desc') }}</p>
              <FormField :label="t('settings.automation.timezone')" layout="horizontal">
                <BaseSelect :modelValue="automation.TIMEZONE" :options="TIMEZONE_OPTIONS as any" searchable @update:modelValue="automation.TIMEZONE = String($event)" />
              </FormField>
            </BaseCard>

            <BaseCard variant="bg2" class="settings-card">
              <SectionHeader icon="pause_circle" flush>{{ t('settings.automation.suspend.title') }}</SectionHeader>
              <p class="section-note">{{ t('settings.automation.suspend.desc') }}</p>
              <FormField :label="t('settings.automation.suspend.enabled')" layout="horizontal">
                <ToggleSwitch v-model="automation.AUTOMATION_SUSPEND_ENABLED" size="sm" />
              </FormField>
              <FormField :label="t('settings.automation.suspend.runHour')" layout="horizontal">
                <NumberInput v-model="automation.AUTOMATION_RUN_HOUR" :min="0" :max="23" />
              </FormField>
              <FormField :label="t('settings.automation.suspend.runMinute')" layout="horizontal">
                <NumberInput v-model="automation.AUTOMATION_RUN_MINUTE" :min="0" :max="59" />
              </FormField>
            </BaseCard>

            <BaseCard variant="bg2" class="settings-card">
              <SectionHeader icon="delete" flush>{{ t('settings.automation.delete.title') }}</SectionHeader>
              <p class="section-note">{{ t('settings.automation.delete.desc') }}</p>
              <FormField :label="t('settings.automation.delete.enabled')" layout="horizontal">
                <ToggleSwitch v-model="automation.AUTOMATION_DELETE_ENABLED" size="sm" />
              </FormField>
              <FormField :label="t('settings.automation.delete.days')" layout="horizontal">
                <NumberInput v-model="automation.AUTOMATION_DELETE_DAYS" :min="0" :max="365" />
              </FormField>
            </BaseCard>

            <BaseCard variant="bg2" class="settings-card">
              <SectionHeader icon="alternate_email" flush>{{ t('settings.automation.email.title') }}</SectionHeader>
              <p class="section-note">{{ t('settings.automation.email.desc') }}</p>
              <FormField :label="t('settings.automation.email.enabled')" layout="horizontal">
                <ToggleSwitch v-model="automation.AUTOMATION_EMAIL_ENABLED" size="sm" />
              </FormField>
              <FormField :label="t('settings.automation.email.runHour')" layout="horizontal">
                <NumberInput v-model="automation.AUTOMATION_EMAIL_RUN_HOUR" :min="0" :max="23" />
              </FormField>
              <FormField :label="t('settings.automation.email.runMinute')" layout="horizontal">
                <NumberInput v-model="automation.AUTOMATION_EMAIL_RUN_MINUTE" :min="0" :max="59" />
              </FormField>
            </BaseCard>
          </template>

          <template v-else-if="activeTab === 'marketing'">
            <BaseCard variant="bg2" class="settings-card">
              <SectionHeader icon="group_add" flush>{{ t('settings.marketing.referral.title') }}</SectionHeader>
              <FormField layout="horizontal">
                <template #label>
                  {{ t('settings.marketing.referral.enabled') }}
                  <HelpTip :text="t('settings.marketing.referral.enabledHint')" />
                </template>
                <ToggleSwitch
                  :modelValue="getBillingBool('REFERRAL_REWARD_ENABLED')"
                  size="sm"
                  @update:modelValue="setBillingBool('REFERRAL_REWARD_ENABLED', $event)"
                />
              </FormField>

              <FormField layout="horizontal">
                <template #label>
                  {{ t('settings.marketing.referral.inviterTemplate') }}
                  <HelpTip :text="t('settings.marketing.referral.inviterTemplateHint')" />
                </template>
                <BaseSelect
                  :modelValue="getBillingStr('REFERRAL_INVITER_TEMPLATE_CODE')"
                  :options="couponTemplateOptions"
                  :placeholder="t('settings.marketing.referral.templatePlaceholder')"
                  @update:modelValue="setBillingStr('REFERRAL_INVITER_TEMPLATE_CODE', String($event))"
                />
              </FormField>

              <FormField layout="horizontal">
                <template #label>
                  {{ t('settings.marketing.referral.inviteeTemplate') }}
                  <HelpTip :text="t('settings.marketing.referral.inviteeTemplateHint')" />
                </template>
                <BaseSelect
                  :modelValue="getBillingStr('REFERRAL_INVITEE_TEMPLATE_CODE')"
                  :options="couponTemplateOptions"
                  :placeholder="t('settings.marketing.referral.templatePlaceholder')"
                  @update:modelValue="setBillingStr('REFERRAL_INVITEE_TEMPLATE_CODE', String($event))"
                />
              </FormField>

              <FormField layout="horizontal">
                <template #label>
                  {{ t('settings.marketing.referral.minFen') }}
                  <HelpTip :text="t('settings.marketing.referral.minFenHint')" />
                </template>
                <NumberInput
                  :modelValue="getBillingNum('REFERRAL_QUALIFYING_MIN_FEN', 1) / 100"
                  :min="0.01"
                  :step="0.01"
                  @update:modelValue="setBillingNum('REFERRAL_QUALIFYING_MIN_FEN', Math.max(1, Math.round(Number($event) * 100)))"
                />
              </FormField>

              <FormField layout="horizontal">
                <template #label>
                  {{ t('settings.marketing.referral.qualifyingKinds') }}
                  <HelpTip :text="t('settings.marketing.referral.qualifyingKindsHint')" />
                </template>
                <BaseSelect
                  :modelValue="getBillingKinds()"
                  :options="qualifyingKindOptions"
                  multiple
                  :placeholder="t('settings.marketing.referral.qualifyingKindsPlaceholder')"
                  @update:modelValue="billingSettings[`REFERRAL_QUALIFYING_KINDS`] = Array.isArray($event) ? $event.map(String) : [String($event)]"
                />
              </FormField>
            </BaseCard>
          </template>
          <template v-else-if="activeTab === 'llm'">
            <BaseCard variant="bg2" class="settings-card">
              <SectionHeader icon="toggle_on" flush>{{ t('settings.llm.general.title') }}</SectionHeader>
              <FormField layout="horizontal">
                <template #label>
                  {{ t('settings.llm.general.enabled') }}
                  <HelpTip :text="t('settings.llm.general.enabledHint')" />
                </template>
                <ToggleSwitch :modelValue="getLlmBool('LLM_ENABLED')" size="sm" @update:modelValue="setLlmBool('LLM_ENABLED', $event)" />
              </FormField>
            </BaseCard>

            <BaseCard variant="bg2" class="settings-card">
              <SectionHeader icon="hub" flush>{{ t('settings.llm.connection.title') }}</SectionHeader>
              <FormField :label="t('settings.llm.connection.baseUrl')" layout="horizontal">
                <BaseInput :modelValue="getLlmStr('NEWAPI_BASE_URL')" @update:modelValue="setLlmStr('NEWAPI_BASE_URL', $event)" placeholder="https://llm.erocraft.com:8443" />
              </FormField>
              <FormField :label="t('settings.llm.connection.adminToken')" layout="horizontal">
                <SecretInput :modelValue="getLlmSecret('NEWAPI_ADMIN_TOKEN')" @update:modelValue="setLlmSecret('NEWAPI_ADMIN_TOKEN', $event)" />
              </FormField>
              <FormField :label="t('settings.llm.connection.poolUserId')" layout="horizontal">
                <NumberInput :modelValue="getLlmNum('NEWAPI_POOL_USER_ID', 0)" @update:modelValue="setLlmNum('NEWAPI_POOL_USER_ID', $event)" :min="0" />
              </FormField>
              <FormField :label="t('settings.llm.connection.poolUserToken')" layout="horizontal">
                <SecretInput :modelValue="getLlmSecret('NEWAPI_POOL_USER_ACCESS_TOKEN')" @update:modelValue="setLlmSecret('NEWAPI_POOL_USER_ACCESS_TOKEN', $event)" />
              </FormField>
            </BaseCard>

            <BaseCard variant="bg2" class="settings-card">
              <SectionHeader icon="extension" flush>{{ t('settings.llm.injection.title') }}</SectionHeader>
              <FormField :label="t('settings.llm.injection.stEndpoint')" layout="horizontal">
                <BaseInput :modelValue="getLlmStr('LLM_ST_ENDPOINT_URL')" @update:modelValue="setLlmStr('LLM_ST_ENDPOINT_URL', $event)" placeholder="https://llm.erocraft.com:8443/v1" />
              </FormField>
            </BaseCard>
          </template>
        </div>
      </template>
    </template>
  </div>

  <!-- Floating dirty bar: appears whenever there are unsaved changes on any
       non-account tab. DirtyBar itself renders the red hint and disables
       Save when `errors` is non-empty; we override #extra to make each chip
       clickable so the user can jump to the offending tab. -->
  <DirtyBar
    :dirty="dirtyForm.isDirty.value"
    :saving="saveLoading"
    :errors="errors.map(e => `${tabLabel(e.tab)}: ${e.label}`)"
    confirm-before-unload
    @save="saveAll"
    @discard="discardChanges"
  >
    <template v-if="hasErrors" #extra>
      <span
        v-for="(e, i) in errors" :key="i"
        class="db-err-chip"
        @click="activeTab = e.tab"
      ><Badge color="var(--amber)">{{ tabLabel(e.tab) }}</Badge> {{ e.label }}</span>
    </template>
  </DirtyBar>
</template>

<style scoped>
.center-loading { display: flex; justify-content: center; padding: var(--sp-8); }

.st-test-row {
  display: flex;
  gap: var(--sp-2);
  align-items: center;
  width: 100%;
}
.st-test-row :deep(.bi-wrap) { flex: 1; }

.st-panel {
  margin-top: var(--sp-4);
  max-width: 760px;
  margin-left: auto;
  margin-right: auto;
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}

.settings-card {
  padding: var(--sp-2);
}

.section-note {
  font-size: .84rem;
  font-weight: 400;
  line-height: 1.55;
  color: var(--t2);
  margin: 0 0 var(--sp-3);
  max-width: 56ch;
}

/* Save bar */
.st-save {
  display: flex;
  justify-content: flex-end;
  padding: var(--sp-4) 0;
  max-width: 640px;
  margin-left: auto;
  margin-right: auto;
}

/* Validation error chips in DirtyBar (clickable tab-switcher) */
.db-err-chip {
  display: inline-flex; align-items: center; gap: var(--sp-1);
  font-size: var(--text-xs); cursor: pointer; white-space: nowrap;
  color: var(--t2); border-radius: var(--r-xs); padding: 2px 4px;
  transition: background .12s;
}
.db-err-chip:hover { background: var(--bg-in); }

.pay-gateway-config-card { display: flex; flex-direction: column; gap: var(--sp-4); }
.pay-gateway-pane { display: flex; flex-direction: column; gap: var(--sp-3); }
.dirty-bar__err-item:hover {
  background: color-mix(in srgb, var(--amber) 10%, transparent);
}
.dirty-bar__err-label {
  color: var(--t1);
  font-weight: 500;
  white-space: nowrap;
}
.dirty-bar__err-msg {
  color: var(--t2);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

</style>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'
import { provideDirtyForm, useDirtyFormSection } from '@/composables/useDirtyForm'
import { useAppStore } from '@/stores/app'
import PageHeader from '@/components/layout/PageHeader.vue'
import WorkspacePage from '@/components/layout/WorkspacePage.vue'
import SettingsWorkspace from '@/components/layout/SettingsWorkspace.vue'
import type { SettingsNavItem } from '@/components/layout/SettingsNavigation.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import BaseTextarea from '@/components/form/BaseTextarea.vue'
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
import AgreementSettingsPanel from '@/components/settings/AgreementSettingsPanel.vue'
import NotificationSettingsPanel from '@/components/settings/NotificationSettingsPanel.vue'
import HostMonitoringSettingsPanel from '@/components/settings/HostMonitoringSettingsPanel.vue'
import { TIMEZONE_OPTIONS } from '@/config/timezones'
import { formSnapshot, restoreScalarValue, sameFormValue } from '@/utils/formState'

defineOptions({ name: 'SettingsPage' })

const { t } = useI18n({ useScope: 'global' })
const { get, post, put, handleError } = useApiFetch()
const { toast } = useToast()
const { confirm } = useConfirm()
const app = useAppStore()
const route = useRoute()
const router = useRouter()

// ── Tabs ──
const activeTab = computed(() => tabs.value.some(item => item.key === route.query.tab) ? String(route.query.tab) : 'branding')
const tabs = computed<SettingsNavItem[]>(() => [
  { key: 'branding',   label: t('settings.branding.title'), icon: 'palette' },
  { key: 'agreements', label: t('settings.agreements.title'), icon: 'gavel' },
  { key: 'defaults',   label: t('settings.defaults.title'), icon: 'tune' },
  { key: 'llm',        label: t('settings.llm.title'),        icon: 'smart_toy' },
  { key: 'payment',    label: t('settings.payment.title'),  icon: 'payments' },
  { key: 'marketing',  label: t('settings.marketing.title'), icon: 'campaign' },
  { key: 'automation', label: t('settings.automation.title'), icon: 'schedule' },
  { key: 'monitoring', label: t('settings.monitoring.title'), icon: 'monitoring' },
  { key: 'channels', label: t('notifications.center.channels'), icon: 'notifications' },
  { key: 'recipients', label: t('notifications.center.recipientGroups'), icon: 'group' },
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
  TIMEZONE: 'Asia/Shanghai',
})
const saveLoading = ref(false)

// ── Payment tab helpers ──
const gatewayTabs = computed<SettingsNavItem[]>(() => [
  { key: 'gateway', label: t('settings.payment.gateway.title') },
  { key: 'miniprogram', label: t('settings.payment.miniLogin') },
])
const activeGateway = computed(() => gatewayTabs.value.some(item => item.key === route.query.gateway) ? String(route.query.gateway) : 'gateway')
const channel = computed(() => route.query.channel === 'email' ? 'email' : 'wecom')
const navItems = computed(() => tabs.value.map(item => ({ ...item, children: item.key === 'payment'
  ? gatewayTabs.value.map(gateway => ({ ...gateway, key: `payment:${gateway.key}` }))
  : item.key === 'channels' ? ['wecom', 'email'].map(key => ({ key: `channels:${key}`, label: t(`notifications.center.${key}`) })) : undefined })))
const selectedNav = computed(() => activeTab.value === 'payment' ? `payment:${activeGateway.value}` : activeTab.value === 'channels' ? `channels:${channel.value}` : activeTab.value)
function setSetting(section: 'settings' | 'billing' | 'llm', key: string, value: string | number | boolean) {
  const previous = JSON.parse(orig.value[section])[key]
  const target = section === 'settings' ? settings.value : section === 'billing' ? billingSettings.value : llmSettings.value
  target[key] = restoreScalarValue(value, previous)
}
function getBillingStr(key: string, def = ''): string { return billingSettings.value[key] ?? def }
function setBillingStr(key: string, val: string) { setSetting('billing', key, val) }
function getBillingNum(key: string, def = 0): number { return Number(billingSettings.value[key] ?? def) }
function setBillingNum(key: string, val: string | number | boolean | (string | number | boolean)[]) {
  const v = Array.isArray(val) ? val[0] : val
  setSetting('billing', key, Number(v))
}
function getBillingBool(key: string): boolean {
  const v = billingSettings.value[key]
  return v === true || v === 'true' || v === '1'
}
function setBillingBool(key: string, val: boolean) { setSetting('billing', key, val) }

// ── LLM settings helpers ──
function getLlmStr(key: string, def = ''): string { return llmSettings.value[key] ?? def }
function setLlmStr(key: string, val: string) { setSetting('llm', key, val) }
function getLlmNum(key: string, def = 0): number { return Number(llmSettings.value[key] ?? def) }
function setLlmNum(key: string, val: string | number | boolean | (string | number | boolean)[]) {
  const v = Array.isArray(val) ? val[0] : val
  setSetting('llm', key, Number(v))
}
function getLlmBool(key: string): boolean {
  const v = llmSettings.value[key]
  return v === true || v === 'true' || v === '1'
}
function setLlmBool(key: string, val: boolean) { setSetting('llm', key, val) }
function getLlmSecret(key: string): string {
  return String(llmSettings.value[key] || '')
}
function setLlmSecret(key: string, val: string) { setSetting('llm', key, val) }

// ── Helpers ──
function getStr(key: string, def = ''): string { return settings.value[key] ?? def }
function setStr(key: string, val: string) { setSetting('settings', key, val) }
function getNum(key: string, def = 0): number { return Number(settings.value[key] ?? def) }
function setNum(key: string, val: string | number | boolean | (string | number | boolean)[]) {
  const v = Array.isArray(val) ? val[0] : val
  setSetting('settings', key, Number(v))
}
function getBool(key: string): boolean {
  const v = settings.value[key]
  return v === true || v === 'true' || v === '1'
}
function setBool(key: string, val: boolean) { setSetting('settings', key, val) }

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
function setBillingKinds(value: unknown) {
  const next = (Array.isArray(value) ? value : [value]).map(String)
  const original = JSON.parse(orig.value.billing).REFERRAL_QUALIFYING_KINDS
  billingSettings.value.REFERRAL_QUALIFYING_KINDS = sameFormValue([...next].sort(), [...(original ?? ['new_purchase', 'renew', 'upgrade'])].sort()) ? original : next
}

watch(() => getNum('DEFAULT_NEST_ID'), async (nestId) => {
  if (!nestId) { eggList.value = []; return }
  const data = await get<{ eggs: any[] }>(`/api/admin/resources/nests/${nestId}/eggs`)
  eggList.value = data?.eggs || []
})

// ── Fetch ──
onMounted(async () => {
  try {
    const results = await Promise.allSettled([
      get<Record<string, any>>('/api/admin/settings'),
      get<Record<string, any>>('/api/admin/automation'),
      get<Record<string, any>>('/api/admin/billing/settings'),
      get<Record<string, any>>('/api/admin/llm/settings'),
      get<{ nests: any[] }>('/api/admin/resources/nests'),
      get<{ nodes: any[] }>('/api/admin/resources/nodes'),
      get<CouponTemplateLite[]>('/api/admin/billing/coupon-templates'),
    ])
    const [settingsData, autoData, billingData, llmData, nestsRes, nodesRes, tplRes] = results
    if (settingsData.status === 'fulfilled') settings.value = Object.fromEntries(Object.entries(settingsData.value).filter(([key]) => !key.startsWith('SMTP_') && !['SENDER_EMAIL', 'EMAIL_SEND_DELAY'].includes(key)))
    if (autoData.status === 'fulfilled') Object.assign(automation.value, Object.fromEntries(Object.keys(automation.value).map(key => [key, autoData.value[key]])))
    if (billingData.status === 'fulfilled') billingSettings.value = billingData.value
    if (llmData.status === 'fulfilled') llmSettings.value = llmData.value
    if (nestsRes.status === 'fulfilled') nestList.value = nestsRes.value.nests
    if (nodesRes.status === 'fulfilled') nodeList.value = nodesRes.value.nodes
    if (tplRes.status === 'fulfilled') couponTemplates.value = tplRes.value
    for (const result of results) if (result.status === 'rejected') handleError(result.reason)
    const nestId = getNum('DEFAULT_NEST_ID')
    if (nestId) {
      const data = await get<{ eggs: any[] }>(`/api/admin/resources/nests/${nestId}/eggs`)
      eggList.value = data.eggs
    }
  } finally {
    snapshot()
    initialLoading.value = false
  }
})

// ── Dirty tracking + leave guard ──
//
const orig = ref({
  settings: '{}',
  automation: '{}',
  billing: '{}',
  llm: '{}',
})
function snapshot() {
  orig.value.settings   = formSnapshot(settings.value)
  orig.value.automation = formSnapshot(automation.value)
  orig.value.billing    = formSnapshot(billingSettings.value)
  orig.value.llm        = formSnapshot(llmSettings.value)
}
const isDirty = computed(() => {
  if (initialLoading.value) return false
  if (formSnapshot(settings.value)        !== orig.value.settings) return true
  if (formSnapshot(automation.value)      !== orig.value.automation) return true
  if (formSnapshot(billingSettings.value) !== orig.value.billing) return true
  if (formSnapshot(llmSettings.value)     !== orig.value.llm) return true
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

function validateAll(): ValidationError[] {
  const errs: ValidationError[] = []

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

  const payUrlFields: [string, string][] = [
    ['PAYMENT_GATEWAY_URL', 'settings.payment.gateway.url'],
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
  if (saveLoading.value) return false
  if (!isDirty.value) return true
  if (hasErrors.value) return false
  saveLoading.value = true
  try {
    const sections = [
      { key: 'settings', value: settings.value, url: '/api/admin/settings' },
      { key: 'automation', value: automation.value, url: '/api/admin/automation' },
      { key: 'billing', value: billingSettings.value, url: '/api/admin/billing/settings', wrapped: true },
      { key: 'llm', value: llmSettings.value, url: '/api/admin/llm/settings', wrapped: true },
    ] as const
    for (const section of sections) {
      const submitted = formSnapshot(section.value)
      if (submitted === orig.value[section.key]) continue
      const previous = JSON.parse(orig.value[section.key])
      const changes = Object.fromEntries(Object.entries(JSON.parse(submitted)).filter(([key, value]) => !sameFormValue(value, previous[key])))
      if (!await post(section.url, 'wrapped' in section ? { settings: changes } : changes)) return false
      orig.value[section.key] = submitted
      if (section.key === 'settings') await app.loadVersion()
    }
    toast(t('settings.saved'), 'success')
    return !isDirty.value
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
      cancelText: t('settings.unsavedStay'),
      altText: t('settings.unsavedDiscard'),
    })
    if (result === 'alt') return 'discard'
    return result === true ? 'save' : 'stay'
  },
})
dirtyForm.attachLeaveGuard({
  update: (to, from) => ['channels', 'recipients', 'monitoring'].includes(String(from.query.tab)) && to.query.tab !== from.query.tab,
})
useDirtyFormSection({
  name: 'settings',
  isDirty,
  save: saveAll,
  discard: discardChanges,
}, dirtyForm)

function onTabChange(next: string) {
  const [tab, value] = next.split(':')
  void router.push({ query: { ...route.query, tab,
    gateway: tab === 'payment' ? value || activeGateway.value : undefined,
    channel: tab === 'channels' ? value || channel.value : undefined,
  } })
}


</script>

<template>
  <WorkspacePage>
    <template #header><PageHeader icon="settings" :title="t('settings.title')" /></template>
    <div v-if="initialLoading" class="center-loading"><Spinner size="lg" /></div>

    <SettingsWorkspace v-else :items="navItems" :model-value="selectedNav" :label="t('settings.title')" storage-key="settings" :disabled="dirtyForm.saving.value" @update:model-value="onTabChange">
      <div :inert="dirtyForm.saving.value" class="settings-form">

      <NotificationSettingsPanel v-if="activeTab === 'channels' || activeTab === 'recipients'" :section="activeTab" :channel="channel" />
      <HostMonitoringSettingsPanel v-else-if="activeTab === 'monitoring'" />
      <AgreementSettingsPanel
        v-else-if="activeTab === 'agreements'"
        :settings="settings"
        @update:settings="settings = { ...settings, ...$event }"
      />

      <template v-else>
        <div class="st-panel">
          <template v-if="activeTab === 'branding'">
            <BaseCard variant="bg2" density="compact">
              <SectionHeader icon="palette" :subtitle="t('settings.branding.desc')" flush>{{ t('settings.branding.title') }}</SectionHeader>
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

            <BaseCard variant="bg2" density="compact">
              <SectionHeader icon="support_agent" :subtitle="t('settings.branding.support.desc')" flush>{{ t('settings.branding.support.title') }}</SectionHeader>
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
              <FormField :label="t('support.welcomeEnabled')" layout="horizontal">
                <ToggleSwitch :modelValue="getBool('SUPPORT_WELCOME_ENABLED')" size="sm" @update:modelValue="setBool('SUPPORT_WELCOME_ENABLED', $event)" />
              </FormField>
              <FormField v-if="getBool('SUPPORT_WELCOME_ENABLED')" :label="t('support.welcomeMessage')" layout="horizontal">
                <BaseTextarea :modelValue="getStr('SUPPORT_WELCOME_MESSAGE')" :rows="3" maxlength="2000" @update:modelValue="setStr('SUPPORT_WELCOME_MESSAGE', $event)" />
              </FormField>
            </BaseCard>
          </template>

          <template v-else-if="activeTab === 'payment'">
            <BaseCard variant="bg2" density="compact" class="pay-gateway-config-card">
              <div v-if="activeGateway === 'gateway'" class="pay-gateway-pane">
                <SectionHeader icon="payments" :subtitle="t('settings.payment.gateway.desc')" flush>{{ t('settings.payment.gateway.title') }}</SectionHeader>
                <FormField :label="t('settings.payment.gateway.url')" layout="horizontal"><BaseInput :modelValue="getBillingStr('PAYMENT_GATEWAY_URL')" @update:modelValue="setBillingStr('PAYMENT_GATEWAY_URL', $event)" /></FormField>
                <FormField :label="t('settings.payment.gateway.appId')" layout="horizontal"><BaseInput :modelValue="getBillingStr('PAYMENT_GATEWAY_APP_ID')" @update:modelValue="setBillingStr('PAYMENT_GATEWAY_APP_ID', $event)" /></FormField>
                <FormField :label="t('settings.payment.gateway.secret')" layout="horizontal"><SecretInput :modelValue="getBillingStr('PAYMENT_GATEWAY_SECRET')" @update:modelValue="setBillingStr('PAYMENT_GATEWAY_SECRET', $event)" /></FormField>
              </div>
              <div v-else class="pay-gateway-pane">
                <SectionHeader icon="badge" :subtitle="t('settings.payment.miniHint')" flush>{{ t('settings.payment.miniLogin') }}</SectionHeader>
                <FormField :label="t('wechat.MINIPROGRAM_APPID')" layout="horizontal"><BaseInput :modelValue="getBillingStr('MINIPROGRAM_APPID')" @update:modelValue="setBillingStr('MINIPROGRAM_APPID', $event)" /></FormField>
                <FormField :label="t('wechat.MINIPROGRAM_APP_SECRET')" layout="horizontal"><SecretInput :modelValue="getBillingStr('MINIPROGRAM_APP_SECRET')" @update:modelValue="setBillingStr('MINIPROGRAM_APP_SECRET', $event)" /></FormField>
              </div>
            </BaseCard>
            <BaseCard variant="bg2" density="compact">
              <SectionHeader icon="tune" :subtitle="t('settings.payment.quotas.desc')" flush>{{ t('settings.payment.quotas.title') }}</SectionHeader>
              <FormField layout="horizontal">
                <template #label>
                  {{ t('settings.payment.payTimeout') }}
                  <HelpTip :text="t('settings.payment.payTimeout_tip')" />
                </template>
                <NumberInput :modelValue="getBillingNum('BILLING_ORDER_PAY_TIMEOUT_MIN', 5)" @update:modelValue="setBillingNum('BILLING_ORDER_PAY_TIMEOUT_MIN', $event)" :min="3" :max="1440" />
              </FormField>
            </BaseCard>
          </template>

          <template v-else-if="activeTab === 'defaults'">
            <BaseCard variant="bg2" density="compact">
              <SectionHeader icon="tune" :subtitle="t('settings.defaults.desc')" flush>{{ t('settings.defaults.title') }}</SectionHeader>
              <FormField :label="t('settings.defaults.nest')" layout="horizontal">
                <BaseSelect teleport :modelValue="getNum('DEFAULT_NEST_ID')" :options="nestOptions" :placeholder="t('settings.defaults.nest')" @update:modelValue="setNum('DEFAULT_NEST_ID', $event)" />
              </FormField>
              <FormField :label="t('settings.defaults.egg')" layout="horizontal">
                <BaseSelect teleport :modelValue="getNum('DEFAULT_EGG_ID')" :options="eggOptions" :placeholder="t('settings.defaults.egg')" :disabled="!getNum('DEFAULT_NEST_ID')" @update:modelValue="setNum('DEFAULT_EGG_ID', $event)" />
              </FormField>
              <FormField :label="t('settings.defaults.node')" layout="horizontal">
                <BaseSelect teleport :modelValue="getNum('DEFAULT_NODE_ID')" :options="nodeOptions" :placeholder="t('settings.defaults.node')" @update:modelValue="setNum('DEFAULT_NODE_ID', $event)" />
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
            <BaseCard variant="bg2" density="compact">
              <SectionHeader icon="schedule" :subtitle="t('settings.automation.time.desc')" flush>{{ t('settings.automation.time.title') }}</SectionHeader>
              <FormField :label="t('settings.automation.timezone')" layout="horizontal">
                <BaseSelect teleport :modelValue="automation.TIMEZONE" :options="TIMEZONE_OPTIONS as any" searchable @update:modelValue="automation.TIMEZONE = String($event)" />
              </FormField>
            </BaseCard>

            <BaseCard variant="bg2" density="compact">
              <SectionHeader icon="pause_circle" :subtitle="t('settings.automation.suspend.desc')" flush>{{ t('settings.automation.suspend.title') }}</SectionHeader>
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

            <BaseCard variant="bg2" density="compact">
              <SectionHeader icon="delete" :subtitle="t('settings.automation.delete.desc')" flush>{{ t('settings.automation.delete.title') }}</SectionHeader>
              <FormField :label="t('settings.automation.delete.enabled')" layout="horizontal">
                <ToggleSwitch v-model="automation.AUTOMATION_DELETE_ENABLED" size="sm" />
              </FormField>
              <FormField :label="t('settings.automation.delete.days')" layout="horizontal">
                <NumberInput v-model="automation.AUTOMATION_DELETE_DAYS" :min="0" :max="365" />
              </FormField>
            </BaseCard>

          </template>

          <template v-else-if="activeTab === 'marketing'">
            <BaseCard variant="bg2" density="compact">
              <SectionHeader icon="group_add" :subtitle="t('settings.marketing.referral.desc')" flush>{{ t('settings.marketing.referral.title') }}</SectionHeader>
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
                  teleport
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
                  teleport
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
                  teleport
                  :modelValue="getBillingKinds()"
                  :options="qualifyingKindOptions"
                  multiple
                  :placeholder="t('settings.marketing.referral.qualifyingKindsPlaceholder')"
                  @update:modelValue="setBillingKinds"
                />
              </FormField>
            </BaseCard>
          </template>
          <template v-else-if="activeTab === 'llm'">
            <BaseCard variant="bg2" density="compact">
              <SectionHeader icon="toggle_on" :subtitle="t('settings.llm.general.desc')" flush>{{ t('settings.llm.general.title') }}</SectionHeader>
              <FormField layout="horizontal">
                <template #label>
                  {{ t('settings.llm.general.enabled') }}
                  <HelpTip :text="t('settings.llm.general.enabledHint')" />
                </template>
                <ToggleSwitch :modelValue="getLlmBool('LLM_ENABLED')" size="sm" @update:modelValue="setLlmBool('LLM_ENABLED', $event)" />
              </FormField>
            </BaseCard>

            <BaseCard variant="bg2" density="compact">
              <SectionHeader icon="hub" :subtitle="t('settings.llm.connection.desc')" flush>{{ t('settings.llm.connection.title') }}</SectionHeader>
              <FormField :label="t('settings.llm.connection.baseUrl')" layout="horizontal">
                <BaseInput :modelValue="getLlmStr('NEWAPI_BASE_URL')" @update:modelValue="setLlmStr('NEWAPI_BASE_URL', $event)" placeholder="https://llm.erocraft.com:8443" />
              </FormField>
              <FormField :label="t('settings.llm.connection.adminToken')" layout="horizontal">
                <SecretInput :modelValue="getLlmSecret('NEWAPI_ADMIN_TOKEN')" @update:modelValue="setLlmSecret('NEWAPI_ADMIN_TOKEN', $event)" />
              </FormField>
            </BaseCard>

            <BaseCard variant="bg2" density="compact">
              <SectionHeader icon="extension" :subtitle="t('settings.llm.injection.desc')" flush>{{ t('settings.llm.injection.title') }}</SectionHeader>
              <FormField :label="t('settings.llm.injection.stEndpoint')" layout="horizontal">
                <BaseInput :modelValue="getLlmStr('LLM_ST_ENDPOINT_URL')" @update:modelValue="setLlmStr('LLM_ST_ENDPOINT_URL', $event)" placeholder="https://llm.erocraft.com:8443/v1" />
              </FormField>
            </BaseCard>
          </template>
        </div>
      </template>
      </div>
    </SettingsWorkspace>
  </WorkspacePage>

  <DirtyBar
    :dirty="dirtyForm.isDirty.value"
    :saving="dirtyForm.saving.value"
    :errors="errors.map(e => `${tabLabel(e.tab)}: ${e.label}`)"
    @save="dirtyForm.save"
    @discard="dirtyForm.discard"
  >
    <template v-if="hasErrors" #extra>
      <span
        v-for="(e, i) in errors" :key="i"
        class="db-err-chip"
        @click="onTabChange(e.tab)"
      ><Badge color="var(--amber)">{{ tabLabel(e.tab) }}</Badge> {{ e.label }}</span>
    </template>
  </DirtyBar>
</template>

<style scoped>
.center-loading { display: flex; justify-content: center; padding: var(--sp-8); }

.st-panel {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
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
</style>

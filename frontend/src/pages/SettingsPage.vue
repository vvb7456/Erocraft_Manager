<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { onBeforeRouteLeave } from 'vue-router'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'
import { useAppStore } from '@/stores/app'
import PageHeader from '@/components/layout/PageHeader.vue'
import TabSwitcher, { type TabItem } from '@/components/ui/TabSwitcher.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import NumberInput from '@/components/form/NumberInput.vue'
import RangeField from '@/components/form/RangeField.vue'
import SecretInput from '@/components/ui/SecretInput.vue'
import ToggleSwitch from '@/components/ui/ToggleSwitch.vue'
import Spinner from '@/components/ui/Spinner.vue'
import HelpTip from '@/components/ui/HelpTip.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import FormField from '@/components/form/FormField.vue'
import CollapsibleGroup from '@/components/ui/CollapsibleGroup.vue'
import Badge from '@/components/ui/Badge.vue'
import StatusDot from '@/components/ui/StatusDot.vue'
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
  { key: 'branding',   label: t('settings.branding.title'), icon: 'palette' },
  { key: 'defaults',   label: t('settings.defaults.title'), icon: 'tune' },
  { key: 'automation', label: t('settings.automation.title'), icon: 'schedule' },
  { key: 'agent',      label: t('monitoring.settings.agentTabTitle'),    icon: 'memory' },
  { key: 'alerting',   label: t('monitoring.settings.alertingTabTitle'), icon: 'notifications_active' },
])

// ── State ──
const initialLoading = ref(true)
const settings = ref<Record<string, any>>({})
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
const monitorSettings = ref<Record<string, any>>({})
const saveLoading = ref(false)

// ── Per-node agent config ──
interface NodeAgentRow {
  nodeId: number
  name: string
  fqdn: string
  monitored: boolean        // 是否在 MONITOR_NODE_IDS 中
  agentEndpoint: string
  agentTokenInput: string   // 用户输入(留空表示不变)
  agentTokenSet: boolean    // 后端是否已存
  agentOnline: boolean      // 最近一次 pull 是否成功 (来自 overview)
  origEndpoint: string      // 基线 endpoint，用于 dirty diff
  pinging: boolean
}
const nodeAgentRows = ref<NodeAgentRow[]>([])
const nodesLoading = ref(false)

function badgeForRow(row: NodeAgentRow): { label: string; color?: string } {
  if (!row.agentEndpoint || !row.agentTokenSet) {
    return { label: t('monitoring.settings.agents.badgeUnconfigured') }
  }
  if (!row.monitored) {
    return { label: t('monitoring.settings.agents.badgeConfigured'), color: '#60a5fa' }
  }
  if (row.agentOnline) {
    return { label: t('monitoring.settings.agents.badgeOnline'), color: '#34d399' }
  }
  return { label: t('monitoring.settings.agents.badgeOffline'), color: '#ef6060' }
}

function dotStatus(row: NodeAgentRow): 'online' | 'offline' | 'pending' {
  if (!row.monitored) return 'offline'
  if (row.agentOnline) return 'online'
  return 'pending'
}

function endpointPlaceholder(row: NodeAgentRow): string {
  return t('monitoring.settings.agents.endpointPlaceholder', { host: row.fqdn || 'host' })
}

async function loadNodeAgentRows() {
  nodesLoading.value = true
  try {
    const monitoredIds = new Set(
      String(monitorSettings.value.MONITOR_NODE_IDS || '')
        .split(',').map(s => s.trim()).filter(Boolean).map(Number).filter(n => !isNaN(n))
    )
    const [allNodesRes, overviewRes, metasRes] = await Promise.all([
      get<{ nodes: { id: number; name: string; fqdn?: string }[] }>('/api/nodes'),
      get<{ nodes: { id: number; agentOnline: boolean }[] }>('/api/monitoring/overview'),
      get<{ nodeId: number; fqdn: string; agentEndpoint: string | null; agentTokenSet: boolean }[]>('/api/admin/nodes/agents'),
    ])
    const overviewMap = new Map<number, boolean>()
    for (const n of overviewRes?.nodes || []) overviewMap.set(n.id, !!n.agentOnline)
    const metaMap = new Map<number, { fqdn: string; agentEndpoint: string | null; agentTokenSet: boolean }>()
    for (const m of metasRes || []) metaMap.set(m.nodeId, m)

    const all = allNodesRes?.nodes || []
    const rows = all.map((n) => {
      const meta = metaMap.get(n.id)
      return {
        nodeId: n.id,
        name: n.name,
        fqdn: meta?.fqdn || n.fqdn || '',
        monitored: monitoredIds.has(n.id),
        agentEndpoint: meta?.agentEndpoint || '',
        agentTokenInput: '',
        agentTokenSet: !!meta?.agentTokenSet,
        agentOnline: overviewMap.get(n.id) ?? false,
        origEndpoint: meta?.agentEndpoint || '',
        pinging: false,
      } as NodeAgentRow
    })
    nodeAgentRows.value = rows
    // Push the initial monitored set into monitorSettings so future
    // toggles show up via JSON diff, then re-baseline the snapshot
    // so the round-trip is not reported as a dirty edit.
    syncMonitorIdsFromRows()
    orig.value.monitorSettings = JSON.stringify(monitorSettings.value)
  } finally {
    nodesLoading.value = false
  }
}

// Any row mutation (including the monitored toggle) eagerly pushes the
// derived MONITOR_NODE_IDS into monitorSettings so isDirty can see it.
// Endpoint / token edits are tracked separately in isDirty.
watch(nodeAgentRows, () => {
  if (nodeAgentRows.value.length) syncMonitorIdsFromRows()
}, { deep: true })

watch(activeTab, (tab) => {
  if (tab === 'agent' && !nodeAgentRows.value.length) loadNodeAgentRows()
  if (tab === 'alerting' && !adminList.value.length) loadAdmins()
})

function syncMonitorIdsFromRows() {
  const ids = nodeAgentRows.value.filter(r => r.monitored).map(r => r.nodeId)
  monitorSettings.value.MONITOR_NODE_IDS = ids.join(',')
}

async function saveAgentRows(): Promise<boolean> {
  for (const r of nodeAgentRows.value) {
    const endpointChanged = r.agentEndpoint !== r.origEndpoint
    const tokenChanged = !!r.agentTokenInput
    if (!endpointChanged && !tokenChanged) continue
    const body: Record<string, string> = { agentEndpoint: r.agentEndpoint }
    if (tokenChanged) body.agentToken = r.agentTokenInput
    const rr = await put<{ agentTokenSet?: boolean }>(`/api/admin/nodes/${r.nodeId}/agent`, body)
    if (!rr) return false
    r.origEndpoint = r.agentEndpoint
    r.agentTokenSet = !!rr.agentTokenSet
    r.agentTokenInput = ''
  }
  return true
}

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
    const r = await post<{ ok: boolean; error: string | null }>('/api/test-email', {
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

async function pingAgent(row: NodeAgentRow) {
  row.pinging = true
  try {
    const r = await post<any>(`/api/admin/nodes/${row.nodeId}/agent/ping`, {})
    if (r?.ok) {
      row.agentOnline = true
      toast(t('monitoring.settings.agents.pingOk'), 'success')
    } else {
      row.agentOnline = false
      toast(t('monitoring.settings.agents.pingFail', { err: r?.detail || 'unknown' }), 'error')
    }
  } finally {
    row.pinging = false
  }
}

// ── Alerting: admin recipient multi-select ──
interface AdminOption { id: number; username: string; email: string }
const adminList = ref<AdminOption[]>([])
const adminIdsSelected = ref<string[]>([])
const adminOptions = computed(() =>
  adminList.value.map(a => ({ value: String(a.id), label: `${a.username} (${a.email || '—'})` }))
)

async function loadAdmins() {
  const r = await get<{ users: any[] }>('/api/users?page=1&perPage=200')
  if (!r) return
  adminList.value = (r.users || [])
    .filter((u: any) => u.root_admin || u.rootAdmin)
    .map((u: any) => ({ id: u.id, username: u.username, email: u.email || '' }))
  syncAdminIdsFromSettings()
  // Re-baseline adminIds in the snapshot — they were derived from a
  // setting that was already in the snapshot, so this is not a dirty edit.
  orig.value.adminIds = JSON.stringify(adminIdsSelected.value)
}

function syncAdminIdsFromSettings() {
  const raw = String(monitorSettings.value.ALERT_EMAIL_ADMIN_IDS || '')
  adminIdsSelected.value = raw.split(',').map(s => s.trim()).filter(Boolean)
}

function syncAdminIdsToSettings() {
  monitorSettings.value.ALERT_EMAIL_ADMIN_IDS = adminIdsSelected.value.join(',')
}

// ── Helpers ──
// Route a setting key to its backing store by *key prefix*, not by the
// currently visible tab. Previously ``_store`` returned ``monitorSettings``
// iff ``activeTab === 'monitoring'`` — correct in the common case but
// prone to races when a watcher fired during a tab transition or when a
// key was read before ``activeTab`` settled (CR §5.5).
//
// Invariant: every key belongs to exactly one store, determined statically.
// ``MONITOR_*`` and ``ALERT_*`` live in ``monitorSettings``; everything
// else (SMTP_*, DEFAULT_*, AUTOMATION_*, UI_*, ...) lives in ``settings``.
const MONITOR_KEY_PREFIXES = ['MONITOR_', 'ALERT_'] as const
function _store(key: string) {
  return MONITOR_KEY_PREFIXES.some(p => key.startsWith(p)) ? monitorSettings : settings
}
function getStr(key: string, def = ''): string { return _store(key).value[key] ?? def }
function setStr(key: string, val: string) { _store(key).value[key] = val }
function getNum(key: string, def = 0): number { return Number(_store(key).value[key]) || def }
function setNum(key: string, val: string | number | boolean) { _store(key).value[key] = Number(val) }
function getBool(key: string): boolean {
  const v = _store(key).value[key]
  return v === true || v === 'true' || v === '1'
}
function setBool(key: string, val: boolean) { _store(key).value[key] = val }

// ── Resources for selects ──
const nestList = ref<any[]>([])
const eggList = ref<any[]>([])
const nodeList = ref<any[]>([])
const nestOptions = computed(() => nestList.value.map((n: any) => ({ value: n.id, label: `${n.name} (#${n.id})` })))
const eggOptions = computed(() => eggList.value.map((e: any) => ({ value: e.id, label: `${e.name} (#${e.id})` })))
const nodeOptions = computed(() => nodeList.value.map((n: any) => ({ value: n.id, label: `${n.name} (#${n.id})` })))

watch(() => getNum('DEFAULT_NEST_ID'), async (nestId) => {
  if (!nestId) { eggList.value = []; return }
  const data = await get<{ eggs: any[] }>(`/api/nests/${nestId}/eggs`)
  eggList.value = data?.eggs || []
})

// ── Fetch ──
onMounted(async () => {
  const [settingsData, autoData, monData, nestsRes, nodesRes] = await Promise.all([
    get<Record<string, any>>('/api/settings'),
    get<Record<string, any>>('/api/automation'),
    get<Record<string, any>>('/api/monitoring-settings'),
    get<{ nests: any[] }>('/api/nests'),
    get<{ nodes: any[] }>('/api/nodes'),
  ])
  if (settingsData) settings.value = settingsData
  if (autoData) Object.assign(automation.value, autoData)
  if (monData) monitorSettings.value = monData
  if (nestsRes) nestList.value = nestsRes.nests
  if (nodesRes) nodeList.value = nodesRes.nodes
  const nestId = getNum('DEFAULT_NEST_ID')
  if (nestId) {
    const data = await get<{ eggs: any[] }>(`/api/nests/${nestId}/eggs`)
    eggList.value = data?.eggs || []
  }
  initialLoading.value = false
  snapshot()
})

// ── Dirty tracking + leave guard ──
//
// account tab is handled by AccountSettingsPanel which manages its own
// state — it does not contribute to dirty here. All other tabs map to
// one of the three reactive blobs (settings / automation / monitorSettings)
// plus the multi-select admin IDs ref.
const orig = ref({
  settings: '{}',
  automation: '{}',
  monitorSettings: '{}',
  adminIds: '[]',
})
function snapshot() {
  orig.value.settings        = JSON.stringify(settings.value)
  orig.value.automation      = JSON.stringify(automation.value)
  orig.value.monitorSettings = JSON.stringify(monitorSettings.value)
  orig.value.adminIds        = JSON.stringify(adminIdsSelected.value)
}
const isDirty = computed(() => {
  if (activeTab.value === 'account') return false
  if (JSON.stringify(settings.value)        !== orig.value.settings) return true
  if (JSON.stringify(automation.value)      !== orig.value.automation) return true
  if (JSON.stringify(monitorSettings.value) !== orig.value.monitorSettings) return true
  if (JSON.stringify(adminIdsSelected.value) !== orig.value.adminIds) return true
  // Per-node agent rows: endpoint change or any pending token input.
  for (const r of nodeAgentRows.value) {
    if (r.agentEndpoint !== r.origEndpoint) return true
    if (r.agentTokenInput) return true
  }
  return false
})

function discardChanges() {
  settings.value         = JSON.parse(orig.value.settings)
  automation.value       = JSON.parse(orig.value.automation)
  monitorSettings.value  = JSON.parse(orig.value.monitorSettings)
  adminIdsSelected.value = JSON.parse(orig.value.adminIds)
  // re-derive per-row monitored flag from restored MONITOR_NODE_IDS
  if (nodeAgentRows.value.length) {
    const monitoredIds = new Set(
      String(monitorSettings.value.MONITOR_NODE_IDS || '')
        .split(',').map(s => s.trim()).filter(Boolean).map(Number)
    )
    for (const r of nodeAgentRows.value) {
      r.monitored = monitoredIds.has(r.nodeId)
      r.agentEndpoint = r.origEndpoint
      r.agentTokenInput = ''
    }
  }
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
  ]
  for (const [key, labelKey] of urlFields) {
    const v = String(settings.value[key] || '').trim()
    if (v && !URL_RE.test(v)) {
      errs.push({ tab: 'branding', label: t(labelKey), message: t('settings.validate.invalidUrl') })
    }
  }

  // Agent tab: endpoint URL format + required when monitored
  for (const r of nodeAgentRows.value) {
    const ep = r.agentEndpoint.trim()
    if (ep && !URL_RE.test(ep)) {
      errs.push({ tab: 'agent', label: r.name, message: t('settings.validate.invalidUrl') })
    }
    if (r.monitored) {
      if (!ep) {
        errs.push({ tab: 'agent', label: r.name, message: t('settings.validate.endpointRequired') })
      }
      if (!r.agentTokenSet && !r.agentTokenInput) {
        errs.push({ tab: 'agent', label: r.name, message: t('settings.validate.tokenRequired') })
      }
    }
  }

  // Alerting: if email alerts are on, at least one recipient
  if (getBool('ALERT_EMAIL_ENABLED') && adminIdsSelected.value.length === 0) {
    errs.push({
      tab: 'alerting',
      label: t('monitoring.settings.email.recipients'),
      message: t('settings.validate.recipientsRequired'),
    })
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
    if (activeTab.value === 'agent' || activeTab.value === 'alerting') {
      if (activeTab.value === 'agent') {
        syncMonitorIdsFromRows()
        const okRows = await saveAgentRows()
        if (!okRows) return false
      }
      if (activeTab.value === 'alerting') syncAdminIdsToSettings()
      const r = await post<{ message: string }>('/api/monitoring-settings', monitorSettings.value)
      if (!r) return false
      toast(t('settings.saved'), 'success')
    } else {
      const r1 = await post<{ message: string }>('/api/settings', settings.value)
      const r2 = await post<{ message: string }>('/api/automation', automation.value)
      if (!r1 || !r2) return false
      await app.loadVersion()
      toast(t('settings.saved'), 'success')
    }
    snapshot()
    return true
  } finally {
    saveLoading.value = false
  }
}

onBeforeRouteLeave(async () => {
  if (!isDirty.value) return true
  const r = await promptUnsaved()
  if (r === 'stay') return false
  if (r === 'save') {
    const ok = await saveAll()
    if (!ok) return false
  }
  return true
})

// Shared unsaved-changes prompt, used by both route-leave and tab-switch.
// Returns: 'save' | 'discard' | 'stay'
async function promptUnsaved(): Promise<'save' | 'discard' | 'stay'> {
  // When there are validation errors, "save" is not an option — the
  // user must either stay and fix, or discard the unsaved changes.
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
}

/**
 * Intercept tab switches: if the current tab has unsaved changes,
 * prompt the user. Mirrors the route-leave guard so the same
 * confirm dialog catches both cases.
 */
async function onTabChange(next: string) {
  if (next === activeTab.value) return
  if (!isDirty.value) {
    activeTab.value = next
    return
  }
  const r = await promptUnsaved()
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
          <!-- SMTP -->
          <template v-if="activeTab === 'smtp'">
            <FormField :label="t('settings.smtp.host')" layout="horizontal" bordered>
              <BaseInput :modelValue="getStr('SMTP_HOST')" @update:modelValue="setStr('SMTP_HOST', $event)" />
            </FormField>
            <FormField :label="t('settings.smtp.port')" layout="horizontal" bordered>
              <NumberInput :modelValue="getNum('SMTP_PORT', 587)" @update:modelValue="setNum('SMTP_PORT', $event)" :min="1" :max="65535" />
            </FormField>
            <FormField :label="t('settings.smtp.sender')" layout="horizontal" bordered>
              <BaseInput :modelValue="getStr('SENDER_EMAIL')" type="email" @update:modelValue="setStr('SENDER_EMAIL', $event)" />
            </FormField>
            <FormField :label="t('settings.smtp.password')" layout="horizontal" bordered>
              <SecretInput :modelValue="getStr('SMTP_PASSWORD')" @update:modelValue="setStr('SMTP_PASSWORD', $event)" />
            </FormField>
            <FormField :label="t('settings.smtp.delay')" layout="horizontal" bordered>
              <NumberInput :modelValue="getNum('EMAIL_SEND_DELAY', 2)" @update:modelValue="setNum('EMAIL_SEND_DELAY', $event)" :min="0" :max="60" />
            </FormField>
            <FormField :label="t('settings.smtp.ssl')" layout="horizontal" bordered>
              <ToggleSwitch :modelValue="getBool('SMTP_USE_SSL')" @update:modelValue="setBool('SMTP_USE_SSL', $event)" />
            </FormField>
            <FormField :hint="undefined" layout="horizontal" bordered>
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
          </template>

          <!-- Branding -->
          <template v-if="activeTab === 'branding'">
            <FormField :label="t('settings.branding.brandName')" layout="horizontal" bordered>
              <BaseInput :modelValue="getStr('BRAND_NAME')" @update:modelValue="setStr('BRAND_NAME', $event)" />
            </FormField>
            <FormField :label="t('settings.branding.systemName')" layout="horizontal" bordered>
              <BaseInput :modelValue="getStr('UI_SYSTEM_NAME')" @update:modelValue="setStr('UI_SYSTEM_NAME', $event)" />
            </FormField>
            <FormField :label="t('settings.branding.siteUrl')" layout="horizontal" bordered>
              <BaseInput :modelValue="getStr('SITE_URL')" @update:modelValue="setStr('SITE_URL', $event)" />
            </FormField>
            <FormField :label="t('settings.branding.bannerUrl')" layout="horizontal" bordered>
              <BaseInput :modelValue="getStr('UI_BANNER_URL')" @update:modelValue="setStr('UI_BANNER_URL', $event)" />
            </FormField>
            <FormField :label="t('settings.branding.icpRecord')" layout="horizontal" bordered>
              <BaseInput :modelValue="getStr('UI_ICP_RECORD')" @update:modelValue="setStr('UI_ICP_RECORD', $event)" />
            </FormField>
          </template>

          <!-- Server Defaults -->
          <template v-if="activeTab === 'defaults'">
            <FormField :label="t('settings.defaults.nest')" layout="horizontal" bordered>
              <BaseSelect :modelValue="getNum('DEFAULT_NEST_ID')" :options="nestOptions" :placeholder="t('settings.defaults.nest')" @update:modelValue="setNum('DEFAULT_NEST_ID', $event)" />
            </FormField>
            <FormField :label="t('settings.defaults.egg')" layout="horizontal" bordered>
              <BaseSelect :modelValue="getNum('DEFAULT_EGG_ID')" :options="eggOptions" :placeholder="t('settings.defaults.egg')" :disabled="!getNum('DEFAULT_NEST_ID')" @update:modelValue="setNum('DEFAULT_EGG_ID', $event)" />
            </FormField>
            <FormField :label="t('settings.defaults.node')" layout="horizontal" bordered>
              <BaseSelect :modelValue="getNum('DEFAULT_NODE_ID')" :options="nodeOptions" :placeholder="t('settings.defaults.node')" @update:modelValue="setNum('DEFAULT_NODE_ID', $event)" />
            </FormField>
            <FormField :label="t('settings.defaults.serverNamePrefix')" layout="horizontal" bordered>
              <BaseInput :modelValue="getStr('SERVER_NAME_PREFIX')" :placeholder="t('settings.defaults.serverNamePrefix_placeholder')" @update:modelValue="setStr('SERVER_NAME_PREFIX', $event)" />
            </FormField>
            <FormField :label="t('settings.defaults.dockerImage')" layout="horizontal" bordered>
              <BaseInput :modelValue="getStr('DOCKER_IMAGE')" @update:modelValue="setStr('DOCKER_IMAGE', $event)" />
            </FormField>
            <FormField :label="t('settings.defaults.cpu')" layout="horizontal" bordered>
              <NumberInput :modelValue="getNum('DEFAULT_CPU', 100)" @update:modelValue="setNum('DEFAULT_CPU', $event)" :min="0" />
            </FormField>
            <FormField :label="t('settings.defaults.memory')" layout="horizontal" bordered>
              <NumberInput :modelValue="getNum('DEFAULT_MEMORY', 1024)" @update:modelValue="setNum('DEFAULT_MEMORY', $event)" :min="0" />
            </FormField>
            <FormField :label="t('settings.defaults.disk')" layout="horizontal" bordered>
              <NumberInput :modelValue="getNum('DEFAULT_DISK', 5120)" @update:modelValue="setNum('DEFAULT_DISK', $event)" :min="0" />
            </FormField>
            <FormField :label="t('settings.defaults.databases')" layout="horizontal" bordered>
              <NumberInput :modelValue="getNum('DEFAULT_DATABASES')" @update:modelValue="setNum('DEFAULT_DATABASES', $event)" :min="0" />
            </FormField>
            <FormField :label="t('settings.defaults.backups')" layout="horizontal" bordered>
              <NumberInput :modelValue="getNum('DEFAULT_BACKUPS')" @update:modelValue="setNum('DEFAULT_BACKUPS', $event)" :min="0" />
            </FormField>
            <FormField :label="t('settings.defaults.allocations')" layout="horizontal" bordered>
              <NumberInput :modelValue="getNum('DEFAULT_ALLOCATIONS', 1)" @update:modelValue="setNum('DEFAULT_ALLOCATIONS', $event)" :min="0" />
            </FormField>
          </template>

          <!-- Automation -->
          <template v-if="activeTab === 'automation'">
            <FormField :label="t('settings.automation.timezone')" layout="horizontal" bordered>
              <BaseSelect :modelValue="automation.TIMEZONE" :options="TIMEZONE_OPTIONS as any" searchable @update:modelValue="automation.TIMEZONE = String($event)" />
            </FormField>

            <div class="st-sub">
              {{ t('settings.automation.suspend.title') }}
              <HelpTip :text="t('settings.automation.suspend.desc')" />
            </div>
            <FormField :label="t('settings.automation.suspend.enabled')" layout="horizontal" bordered>
              <ToggleSwitch v-model="automation.AUTOMATION_SUSPEND_ENABLED" size="sm" />
            </FormField>
            <FormField :label="t('settings.automation.suspend.runHour')" layout="horizontal" bordered>
              <NumberInput v-model="automation.AUTOMATION_RUN_HOUR" :min="0" :max="23" />
            </FormField>
            <FormField :label="t('settings.automation.suspend.runMinute')" layout="horizontal" bordered>
              <NumberInput v-model="automation.AUTOMATION_RUN_MINUTE" :min="0" :max="59" />
            </FormField>

            <div class="st-sub">
              {{ t('settings.automation.delete.title') }}
              <HelpTip :text="t('settings.automation.delete.desc')" />
            </div>
            <FormField :label="t('settings.automation.delete.enabled')" layout="horizontal" bordered>
              <ToggleSwitch v-model="automation.AUTOMATION_DELETE_ENABLED" size="sm" />
            </FormField>
            <FormField :label="t('settings.automation.delete.days')" layout="horizontal" bordered>
              <NumberInput v-model="automation.AUTOMATION_DELETE_DAYS" :min="0" :max="365" />
            </FormField>

            <div class="st-sub">
              {{ t('settings.automation.email.title') }}
              <HelpTip :text="t('settings.automation.email.desc')" />
            </div>
            <FormField :label="t('settings.automation.email.enabled')" layout="horizontal" bordered>
              <ToggleSwitch v-model="automation.AUTOMATION_EMAIL_ENABLED" size="sm" />
            </FormField>
            <FormField :label="t('settings.automation.email.runHour')" layout="horizontal" bordered>
              <NumberInput v-model="automation.AUTOMATION_EMAIL_RUN_HOUR" :min="0" :max="23" />
            </FormField>
            <FormField :label="t('settings.automation.email.runMinute')" layout="horizontal" bordered>
              <NumberInput v-model="automation.AUTOMATION_EMAIL_RUN_MINUTE" :min="0" :max="59" />
            </FormField>
          </template>

          <!-- Agent (monitoring global + per-node agents) -->
          <template v-if="activeTab === 'agent'">
            <div class="st-sub">
              {{ t('monitoring.settings.global.section') }}
              <HelpTip :text="t('monitoring.settings.global.sectionTip')" />
            </div>
            <FormField layout="horizontal" bordered>
              <template #label>
                {{ t('monitoring.settings.global.enabled') }}
                <HelpTip :text="t('monitoring.settings.global.enabledTip')" />
              </template>
              <ToggleSwitch :modelValue="getBool('MONITOR_ENABLED')" @update:modelValue="setBool('MONITOR_ENABLED', $event)" size="sm" />
            </FormField>
            <FormField layout="horizontal" bordered>
              <template #label>
                {{ t('monitoring.settings.global.interval') }}
                <HelpTip :text="t('monitoring.settings.global.intervalTip')" />
              </template>
              <NumberInput :modelValue="getNum('MONITOR_INTERVAL_SEC', 60)" @update:modelValue="setNum('MONITOR_INTERVAL_SEC', $event)" :min="30" :max="3600" />
            </FormField>
            <FormField layout="horizontal" bordered>
              <template #label>
                {{ t('monitoring.settings.global.retentionDays') }}
                <HelpTip :text="t('monitoring.settings.global.retentionDaysTip')" />
              </template>
              <NumberInput :modelValue="getNum('MONITOR_RETENTION_DAYS', 30)" @update:modelValue="setNum('MONITOR_RETENTION_DAYS', $event)" :min="1" :max="365" />
            </FormField>

            <div class="st-sub">
              {{ t('monitoring.settings.agents.section') }}
              <HelpTip :text="t('monitoring.settings.agents.sectionTip')" />
            </div>
            <div v-if="nodesLoading" class="agents-loading"><Spinner size="md" /></div>
            <div v-else-if="!nodeAgentRows.length" class="agents-empty">
              {{ t('monitoring.settings.agents.empty') }}
            </div>
            <ul v-else class="agents-list">
              <li v-for="row in nodeAgentRows" :key="row.nodeId" class="agent-item">
                <CollapsibleGroup :default-open="row.monitored && nodeAgentRows.indexOf(row) === 0">
                  <template #header>
                    <StatusDot :status="dotStatus(row)" size="sm" />
                    <span class="agent-name">{{ row.name }}</span>
                    <span class="agent-fqdn">{{ row.fqdn }}</span>
                  </template>
                  <template #title-right>
                    <Badge :color="badgeForRow(row).color">{{ badgeForRow(row).label }}</Badge>
                    <ToggleSwitch v-model="row.monitored" size="sm" @click.stop />
                  </template>

                  <div class="agent-body" @click.stop>
                    <FormField layout="horizontal" bordered>
                      <template #label>
                        {{ t('monitoring.settings.agents.endpoint') }}
                        <HelpTip :text="t('monitoring.settings.agents.endpointTip')" />
                      </template>
                      <BaseInput v-model="row.agentEndpoint" :placeholder="endpointPlaceholder(row)" />
                    </FormField>
                    <FormField layout="horizontal" bordered>
                      <template #label>
                        {{ t('monitoring.settings.agents.token') }}
                        <HelpTip :text="t('monitoring.settings.agents.tokenTip')" />
                      </template>
                      <SecretInput
                        v-model="row.agentTokenInput"
                        :placeholder="row.agentTokenSet ? t('monitoring.settings.agents.tokenPlaceholder') : ''"
                      />
                    </FormField>
                    <div class="agent-actions">
                      <BaseButton
                        size="sm"
                        variant="secondary"
                        :loading="row.pinging"
                        :disabled="!row.agentEndpoint || (!row.agentTokenSet && !row.agentTokenInput)"
                        @click="pingAgent(row)"
                      >
                        {{ t('monitoring.settings.agents.ping') }}
                      </BaseButton>
                    </div>
                  </div>
                </CollapsibleGroup>
              </li>
            </ul>
          </template>

          <!-- Alerting (email channel + combined type/threshold rows) -->
          <template v-if="activeTab === 'alerting'">
            <div class="st-sub">
              {{ t('monitoring.settings.email.section') }}
              <HelpTip :text="t('monitoring.settings.email.sectionTip')" />
            </div>
            <FormField layout="horizontal" bordered>
              <template #label>
                {{ t('monitoring.settings.email.enabled') }}
                <HelpTip :text="t('monitoring.settings.email.enabledTip')" />
              </template>
              <ToggleSwitch :modelValue="getBool('ALERT_EMAIL_ENABLED')" @update:modelValue="setBool('ALERT_EMAIL_ENABLED', $event)" size="sm" />
            </FormField>
            <FormField layout="horizontal" bordered>
              <template #label>
                {{ t('monitoring.settings.email.recipients') }}
                <HelpTip :text="t('monitoring.settings.email.recipientsTip')" />
              </template>
              <BaseSelect
                v-if="adminOptions.length"
                multiple
                :options="adminOptions"
                :modelValue="adminIdsSelected"
                :placeholder="t('monitoring.settings.email.recipientsEmpty')"
                @update:modelValue="(v: any) => adminIdsSelected = v as string[]"
              />
              <div v-else class="chip-empty">{{ t('monitoring.settings.email.recipientsEmpty') }}</div>
            </FormField>
            <FormField layout="horizontal" bordered>
              <template #label>
                {{ t('monitoring.settings.email.minSeverity') }}
                <HelpTip :text="t('monitoring.settings.email.minSeverityTip')" />
              </template>
              <BaseSelect
                :modelValue="getStr('ALERT_MIN_SEVERITY', 'warning')"
                :options="[
                  { value: 'warning',  label: t('monitoring.settings.email.severityWarning') },
                  { value: 'critical', label: t('monitoring.settings.email.severityCritical') },
                ]"
                @update:modelValue="(v: any) => setStr('ALERT_MIN_SEVERITY', String(v))"
              />
            </FormField>
            <FormField layout="horizontal" bordered>
              <template #label>
                {{ t('monitoring.settings.email.notifyResolve') }}
                <HelpTip :text="t('monitoring.settings.email.notifyResolveTip')" />
              </template>
              <ToggleSwitch :modelValue="getBool('ALERT_NOTIFY_RESOLVE')" @update:modelValue="setBool('ALERT_NOTIFY_RESOLVE', $event)" size="sm" />
            </FormField>
            <FormField layout="horizontal" bordered>
              <template #label>
                {{ t('monitoring.settings.thresholds.alertCooldown') }}
                <HelpTip :text="t('monitoring.settings.thresholds.alertCooldownTip')" />
              </template>
              <NumberInput
                :modelValue="getNum('ALERT_COOLDOWN_MIN', 30)"
                :min="1" :max="240"
                @update:modelValue="setNum('ALERT_COOLDOWN_MIN', $event)"
              />
            </FormField>

            <div class="st-sub">
              {{ t('monitoring.settings.types.section') }}
              <HelpTip :text="t('monitoring.settings.types.sectionTip')" />
            </div>

            <!-- Simple type toggles (no threshold) -->
            <FormField
              v-for="tkey in ['node_offline','agent_only_down','wings_only_down','network_down','clash_down']"
              :key="tkey"
              :label="t(`monitoring.settings.types.${tkey}`)"
              layout="horizontal"
              bordered
            >
              <ToggleSwitch
                :modelValue="getBool(`ALERT_TYPE_${tkey.toUpperCase()}`)"
                @update:modelValue="setBool(`ALERT_TYPE_${tkey.toUpperCase()}`, $event)"
                size="sm"
              />
            </FormField>

            <!-- CPU: toggle + threshold + sustain -->
            <FormField layout="horizontal" bordered>
              <template #label>
                {{ t('monitoring.settings.types.cpu_high') }}
                <HelpTip :text="t('monitoring.settings.thresholds.cpuThresholdTip')" />
              </template>
              <div class="alert-row">
                <ToggleSwitch :modelValue="getBool('ALERT_TYPE_CPU_HIGH')" @update:modelValue="setBool('ALERT_TYPE_CPU_HIGH', $event)" size="sm" />
                <div class="alert-sub">
                  <label class="alert-sub__label">{{ t('monitoring.settings.thresholds.cpuThreshold') }}</label>
                  <RangeField
                    :modelValue="getNum('ALERT_CPU_THRESHOLD', 90)"
                    :min="50" :max="100" :step="1"
                    show-value editable
                    :value-format="(v: number) => `${v}%`"
                    @update:modelValue="setNum('ALERT_CPU_THRESHOLD', $event)"
                  />
                </div>
                <div class="alert-sub">
                  <label class="alert-sub__label">{{ t('monitoring.settings.thresholds.cpuSustain') }}</label>
                  <RangeField
                    :modelValue="getNum('ALERT_CPU_SUSTAIN_MIN', 5)"
                    :min="1" :max="60" :step="1"
                    show-value editable
                    :value-format="(v: number) => `${v}m`"
                    @update:modelValue="setNum('ALERT_CPU_SUSTAIN_MIN', $event)"
                  />
                </div>
              </div>
            </FormField>

            <!-- Memory -->
            <FormField layout="horizontal" bordered>
              <template #label>
                {{ t('monitoring.settings.types.mem_high') }}
                <HelpTip :text="t('monitoring.settings.thresholds.memThresholdTip')" />
              </template>
              <div class="alert-row">
                <ToggleSwitch :modelValue="getBool('ALERT_TYPE_MEM_HIGH')" @update:modelValue="setBool('ALERT_TYPE_MEM_HIGH', $event)" size="sm" />
                <div class="alert-sub">
                  <label class="alert-sub__label">{{ t('monitoring.settings.thresholds.memThreshold') }}</label>
                  <RangeField
                    :modelValue="getNum('ALERT_MEM_THRESHOLD', 90)"
                    :min="50" :max="100" :step="1"
                    show-value editable
                    :value-format="(v: number) => `${v}%`"
                    @update:modelValue="setNum('ALERT_MEM_THRESHOLD', $event)"
                  />
                </div>
                <div class="alert-sub">
                  <label class="alert-sub__label">{{ t('monitoring.settings.thresholds.memSustain') }}</label>
                  <RangeField
                    :modelValue="getNum('ALERT_MEM_SUSTAIN_MIN', 5)"
                    :min="1" :max="60" :step="1"
                    show-value editable
                    :value-format="(v: number) => `${v}m`"
                    @update:modelValue="setNum('ALERT_MEM_SUSTAIN_MIN', $event)"
                  />
                </div>
              </div>
            </FormField>

            <!-- Swap -->
            <FormField layout="horizontal" bordered>
              <template #label>
                {{ t('monitoring.settings.types.swap_high') }}
                <HelpTip :text="t('monitoring.settings.thresholds.swapThresholdTip')" />
              </template>
              <div class="alert-row">
                <ToggleSwitch :modelValue="getBool('ALERT_TYPE_SWAP_HIGH')" @update:modelValue="setBool('ALERT_TYPE_SWAP_HIGH', $event)" size="sm" />
                <div class="alert-sub">
                  <label class="alert-sub__label">{{ t('monitoring.settings.thresholds.swapThreshold') }}</label>
                  <RangeField
                    :modelValue="getNum('ALERT_SWAP_THRESHOLD', 50)"
                    :min="10" :max="100" :step="1"
                    show-value editable
                    :value-format="(v: number) => `${v}%`"
                    @update:modelValue="setNum('ALERT_SWAP_THRESHOLD', $event)"
                  />
                </div>
              </div>
            </FormField>

            <!-- Disk warning -->
            <FormField layout="horizontal" bordered>
              <template #label>
                {{ t('monitoring.settings.types.disk_high') }}
                <HelpTip :text="t('monitoring.settings.thresholds.diskWarningTip')" />
              </template>
              <div class="alert-row">
                <ToggleSwitch :modelValue="getBool('ALERT_TYPE_DISK_HIGH')" @update:modelValue="setBool('ALERT_TYPE_DISK_HIGH', $event)" size="sm" />
                <div class="alert-sub">
                  <label class="alert-sub__label">{{ t('monitoring.settings.thresholds.diskWarning') }}</label>
                  <RangeField
                    :modelValue="getNum('ALERT_DISK_WARNING', 85)"
                    :min="50" :max="100" :step="1"
                    show-value editable
                    :value-format="(v: number) => `${v}%`"
                    @update:modelValue="setNum('ALERT_DISK_WARNING', $event)"
                  />
                </div>
              </div>
            </FormField>

            <!-- Disk critical -->
            <FormField layout="horizontal" bordered>
              <template #label>
                {{ t('monitoring.settings.types.disk_critical') }}
                <HelpTip :text="t('monitoring.settings.thresholds.diskCriticalTip')" />
              </template>
              <div class="alert-row">
                <ToggleSwitch :modelValue="getBool('ALERT_TYPE_DISK_CRITICAL')" @update:modelValue="setBool('ALERT_TYPE_DISK_CRITICAL', $event)" size="sm" />
                <div class="alert-sub">
                  <label class="alert-sub__label">{{ t('monitoring.settings.thresholds.diskCritical') }}</label>
                  <RangeField
                    :modelValue="getNum('ALERT_DISK_CRITICAL', 95)"
                    :min="50" :max="100" :step="1"
                    show-value editable
                    :value-format="(v: number) => `${v}%`"
                    @update:modelValue="setNum('ALERT_DISK_CRITICAL', $event)"
                  />
                </div>
              </div>
            </FormField>

            <!-- Load -->
            <FormField layout="horizontal" bordered>
              <template #label>
                {{ t('monitoring.settings.types.load_high') }}
                <HelpTip :text="t('monitoring.settings.thresholds.loadFactorTip')" />
              </template>
              <div class="alert-row">
                <ToggleSwitch :modelValue="getBool('ALERT_TYPE_LOAD_HIGH')" @update:modelValue="setBool('ALERT_TYPE_LOAD_HIGH', $event)" size="sm" />
                <div class="alert-sub">
                  <label class="alert-sub__label">{{ t('monitoring.settings.thresholds.loadFactor') }}</label>
                  <RangeField
                    :modelValue="getNum('ALERT_LOAD_FACTOR', 1.5)"
                    :min="0.5" :max="5" :step="0.1"
                    show-value editable
                    :value-format="(v: number) => `${v.toFixed(1)}×`"
                    @update:modelValue="setNum('ALERT_LOAD_FACTOR', $event)"
                  />
                </div>
                <div class="alert-sub">
                  <label class="alert-sub__label">{{ t('monitoring.settings.thresholds.loadSustain') }}</label>
                  <RangeField
                    :modelValue="getNum('ALERT_LOAD_SUSTAIN_MIN', 5)"
                    :min="1" :max="60" :step="1"
                    show-value editable
                    :value-format="(v: number) => `${v}m`"
                    @update:modelValue="setNum('ALERT_LOAD_SUSTAIN_MIN', $event)"
                  />
                </div>
              </div>
            </FormField>
          </template>
        </div>
      </template>
    </template>
  </div>

  <!-- Floating dirty bar: appears whenever there are unsaved changes
       on any non-account tab. When validation fails, the bar switches
       to error-list mode — the user must either fix the issues or
       discard. No ambiguous save button in that state. -->
  <Teleport to="body">
    <Transition name="slide-up">
      <div v-if="isDirty" class="dirty-bar" :class="{ 'dirty-bar--error': hasErrors }">
        <template v-if="hasErrors">
          <div class="dirty-bar__errors">
            <div class="dirty-bar__err-head">
              <MsIcon name="error" />
              {{ t('settings.validate.header', { n: errors.length }) }}
            </div>
            <ul class="dirty-bar__err-list">
              <li v-for="(e, i) in errors" :key="i" class="dirty-bar__err-item" @click="activeTab = e.tab">
                <Badge color="#f59e0b">{{ tabLabel(e.tab) }}</Badge>
                <span class="dirty-bar__err-label">{{ e.label }}</span>
                <span class="dirty-bar__err-msg">{{ e.message }}</span>
              </li>
            </ul>
          </div>
          <div class="dirty-bar__actions">
            <BaseButton size="sm" @click="discardChanges">
              {{ t('settings.discardBtn') }}
            </BaseButton>
          </div>
        </template>
        <template v-else>
          <span class="dirty-bar__text">
            <MsIcon name="edit" />
            {{ t('settings.unsavedHint') }}
          </span>
          <div class="dirty-bar__actions">
            <BaseButton size="sm" :disabled="saveLoading" @click="discardChanges">
              {{ t('settings.discardBtn') }}
            </BaseButton>
            <BaseButton
              variant="primary"
              size="sm"
              :loading="saveLoading"
              @click="saveAll"
            >
              {{ t('settings.save') }}
            </BaseButton>
          </div>
        </template>
      </div>
    </Transition>
  </Teleport>
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
  max-width: 640px;
  margin-left: auto;
  margin-right: auto;
}

/* Sub-heading / description */
.st-sub {
  display: flex;
  align-items: center;
  gap: var(--sp-1);
  font-size: .95rem;
  font-weight: 600;
  color: var(--t1);
  padding: var(--sp-5) 0 var(--sp-2);
  margin-top: var(--sp-2);
}
.st-sub:first-of-type {
  margin-top: 0;
  padding-top: var(--sp-2);
}

.st-desc {
  font-size: .84rem;
  font-weight: 400;
  line-height: 1.55;
  color: var(--t2);
  margin: 0 0 var(--sp-4);
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

/* Floating dirty bar (mirrors ServerSettingsPage.vue) */
.dirty-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  padding: var(--sp-3) var(--sp-5);
  background: var(--bg3);
  border-top: 1px solid var(--bd);
  box-shadow: 0 -4px 20px rgba(0, 0, 0, 0.35);
}
.dirty-bar__text {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--amber);
}
.dirty-bar__text :deep(.ms-icon) { font-size: 1.1rem; }
.dirty-bar__actions {
  display: flex;
  gap: var(--sp-2);
  flex-shrink: 0;
}

/* error-mode bar: slightly taller, error-tinted border, shows a
   scrollable list of concrete validation issues. */
.dirty-bar--error {
  align-items: flex-start;
  border-top-color: var(--amber);
  gap: var(--sp-4);
}
.dirty-bar__errors {
  flex: 1 1 auto;
  min-width: 0;
}
.dirty-bar__err-head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--amber);
  margin-bottom: var(--sp-1);
}
.dirty-bar__err-head :deep(.ms-icon) { font-size: 1.1rem; }
.dirty-bar__err-list {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 9rem;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}
.dirty-bar__err-item {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: var(--text-xs);
  line-height: 1.4;
  cursor: pointer;
  padding: 2px 4px;
  border-radius: var(--r-xs);
  transition: background .12s ease;
}
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

/* slide-up transition */
.slide-up-enter-active,
.slide-up-leave-active {
  transition: transform .24s ease, opacity .24s ease;
}
.slide-up-enter-from,
.slide-up-leave-to {
  transform: translateY(100%);
  opacity: 0;
}

/* Per-node agent list — flat, no card background */
.agents-loading {
  display: flex;
  justify-content: center;
  padding: var(--sp-4);
}
.agents-empty {
  padding: var(--sp-3) 0;
  font-size: var(--text-sm);
  color: var(--t3);
}
.agents-list {
  list-style: none;
  margin: 0;
  padding: 0;
}
.agent-item {
  border-bottom: 1px solid color-mix(in srgb, var(--bd) 50%, transparent);
}
.agent-item:last-child {
  border-bottom: none;
}
.agent-item :deep(.collapsible-group__header) {
  padding: var(--sp-2) 0;
  gap: var(--sp-2);
}
.agent-name {
  font-weight: 600;
  font-size: var(--text-base);
  color: var(--t1);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.agent-fqdn {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--t3);
  margin-left: var(--sp-1);
}
.agent-item :deep(.collapsible-group__body) {
  padding: var(--sp-2) 0 var(--sp-3) var(--sp-5);
  border-top: 1px dashed color-mix(in srgb, var(--bd) 40%, transparent);
}
.agent-body {
  display: flex;
  flex-direction: column;
}
.agent-actions {
  display: flex;
  gap: var(--sp-2);
  justify-content: flex-end;
  margin-top: var(--sp-3);
}
.chip-empty {
  color: var(--t3);
  font-size: var(--text-sm);
  padding: var(--sp-2) 0;
}

/* Combined alert type + threshold row */
.alert-row {
  display: flex;
  align-items: center;
  gap: var(--sp-4);
  flex-wrap: wrap;
  width: 100%;
}
.alert-sub {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
  flex: 1 1 160px;
  min-width: 140px;
}
.alert-sub__label {
  font-size: var(--text-xs);
  color: var(--t3);
  letter-spacing: .02em;
}

</style>

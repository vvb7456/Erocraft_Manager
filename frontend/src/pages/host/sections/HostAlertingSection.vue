<script setup lang="ts">
// HostAlertingSection — per-host 告警 channel + 规则覆盖
//
// GET /api/admin/hosts/{hostId}/alerts → { settings, rules, defaults }
// PUT /api/admin/hosts/{hostId}/alerts (full replacement: { settings, rules })
//
// settings 字段为 null 时表示"继承全局默认"。
// rules 为完整替换：未列出的 alert_type 即"使用默认"；列出但字段为 null
// 表示该字段使用默认。本组件采用 SettingsPage 的「alert-row + alert-sub」
// 视觉语言保持一致（toggle + RangeField 阈值 + RangeField sustain）。
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import { useDirtyFormSection } from '@/composables/useDirtyForm'
import CollapsibleGroup from '@/components/ui/CollapsibleGroup.vue'
import BaseCard from '@/components/ui/BaseCard.vue'
import FormField from '@/components/form/FormField.vue'
import NumberInput from '@/components/form/NumberInput.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import RangeField from '@/components/form/RangeField.vue'
import ToggleSwitch from '@/components/ui/ToggleSwitch.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import HelpTip from '@/components/ui/HelpTip.vue'
import Spinner from '@/components/ui/Spinner.vue'

defineOptions({ name: 'HostAlertingSection' })

const props = defineProps<{ hostId: number }>()
const { t } = useI18n({ useScope: 'global' })
const { get, raw } = useApiFetch()
const { toast } = useToast()

type Severity = 'info' | 'warning' | 'critical'

interface ChannelSettings {
  email_enabled: boolean | null
  email_recipients: number[] | null
  min_severity: Severity | null
  notify_resolve: boolean | null
  cooldown_min: number | null
}

interface AlertRule {
  alert_type: string
  enabled: boolean | null
  threshold: number | null
  warning_threshold: number | null
  critical_threshold: number | null
  sustain_min: number | null
}

interface AlertsResponse {
  settings: ChannelSettings
  rules: AlertRule[]
  defaults: {
    email_enabled: boolean
    email_recipients: number[]
    min_severity: Severity
    notify_resolve: boolean
    cooldown_min: number
    rules: Record<string, Partial<AlertRule>>
  }
}

interface AdminOpt { value: string; label: string }

const loading = ref(true)
const submitting = ref(false)
const syncing = ref(true)
const settings = ref<ChannelSettings>({
  email_enabled: null,
  email_recipients: null,
  min_severity: null,
  notify_resolve: null,
  cooldown_min: null,
})
const initialJson = ref<string>('')
const defaults = ref<AlertsResponse['defaults'] | null>(null)
const rulesByType = ref<Record<string, AlertRule>>({})
const adminOptions = ref<AdminOpt[]>([])

const TOGGLE_ONLY = ['node_offline', 'agent_only_down', 'wings_only_down', 'network_down', 'clash_down']
const SINGLE_THRESHOLD = ['cpu_high', 'mem_high', 'swap_high', 'load_high']
const DUAL_THRESHOLD = ['disk_high', 'disk_critical']
const ALL_TYPES = [...SINGLE_THRESHOLD, ...DUAL_THRESHOLD, ...TOGGLE_ONLY]

function emptyRule(alert_type: string): AlertRule {
  return { alert_type, enabled: null, threshold: null, warning_threshold: null, critical_threshold: null, sustain_min: null }
}

async function loadAdmins() {
  const r = await get<{ users: any[] }>('/api/admin/users?page=1&perPage=200')
  if (!r) return
  adminOptions.value = (r.users || [])
    .filter((u: any) => u.root_admin || u.rootAdmin)
    .map((u: any) => ({ value: String(u.id), label: `${u.username} (${u.email || '—'})` }))
}

async function load() {
  loading.value = true
  syncing.value = true
  // Keep a stable baseline even if request fails, so initial mount
  // and error paths never emit a transient dirty state.
  initialJson.value = serialize()
  try {
    const data = await get<AlertsResponse>(`/api/admin/hosts/${props.hostId}/alerts`)
    if (!data) return
    settings.value = { ...data.settings }
    defaults.value = data.defaults
    rulesByType.value = {}
    for (const r of data.rules) rulesByType.value[r.alert_type] = { ...r }
    for (const at of ALL_TYPES) {
      if (!rulesByType.value[at]) rulesByType.value[at] = emptyRule(at)
    }
    initialJson.value = serialize()
  } finally {
    syncing.value = false
    loading.value = false
  }
}

onMounted(async () => {
  await loadAdmins()
  await load()
})

function serialize(): string {
  return JSON.stringify({ settings: settings.value, rules: rulesByType.value })
}
const isDirty = computed(() => !syncing.value && serialize() !== initialJson.value)

const recipientIds = computed<string[]>({
  get: () => (settings.value.email_recipients ?? []).map(String),
  set: (v) => { settings.value.email_recipients = v.length ? v.map(Number) : null },
})

async function save(): Promise<boolean> {
  if (!isDirty.value) return true
  submitting.value = true
  try {
    const outRules: AlertRule[] = []
    for (const at of ALL_TYPES) {
      const r = rulesByType.value[at]
      if (r.enabled !== null || r.threshold !== null || r.warning_threshold !== null
          || r.critical_threshold !== null || r.sustain_min !== null) {
        outRules.push(r)
      }
    }
    const body = { settings: settings.value, rules: outRules }
    const res = await raw(`/api/admin/hosts/${props.hostId}/alerts`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!res) return false
    toast(t('hosts.setting.alerting.saved'), 'success')
    await load()
    return true
  } finally {
    submitting.value = false
  }
}

function discard() { load() }

// Register into the page-wide DirtyBar / leave-guard owned by the parent
// (HostSettingPane). The parent renders the bar and orchestrates the save.
useDirtyFormSection({ name: 'host-alerting', isDirty, save, discard })

// Mirrors SettingsPage / HostSettingPane leave-guard: ConfirmDialog with
// three outcomes (save / discard / stay) so leaving the page never silently
// drops in-progress edits to per-host alert overrides.

function resetToDefaults() {
  settings.value = {
    email_enabled: null, email_recipients: null, min_severity: null,
    notify_resolve: null, cooldown_min: null,
  }
  for (const at of ALL_TYPES) rulesByType.value[at] = emptyRule(at)
}

const severityOptions = [
  { value: 'info', label: 'info' },
  { value: 'warning', label: 'warning' },
  { value: 'critical', label: 'critical' },
]

function defaultRule(at: string): Partial<AlertRule> {
  return defaults.value?.rules[at] ?? {}
}

function ruleEnabled(at: string): boolean {
  return rulesByType.value[at].enabled ?? Boolean(defaultRule(at).enabled)
}
function setRuleEnabled(at: string, v: boolean) { rulesByType.value[at].enabled = v }

function ruleThreshold(at: string, fallback: number): number {
  return rulesByType.value[at].threshold ?? Number(defaultRule(at).threshold ?? fallback)
}
function setRuleThreshold(at: string, v: number) { rulesByType.value[at].threshold = v }

function ruleSustain(at: string, fallback: number): number {
  return rulesByType.value[at].sustain_min ?? Number(defaultRule(at).sustain_min ?? fallback)
}
function setRuleSustain(at: string, v: number) { rulesByType.value[at].sustain_min = v }

function ruleWarning(at: string, fallback: number): number {
  return rulesByType.value[at].warning_threshold ?? Number(defaultRule(at).warning_threshold ?? fallback)
}
function setRuleWarning(at: string, v: number) { rulesByType.value[at].warning_threshold = v }

function ruleCritical(at: string, fallback: number): number {
  return rulesByType.value[at].critical_threshold ?? Number(defaultRule(at).critical_threshold ?? fallback)
}
function setRuleCritical(at: string, v: number) { rulesByType.value[at].critical_threshold = v }

const pctFmt = (v: number) => `${v}%`
const minFmt = (v: number) => `${v}m`
const loadFmt = (v: number) => v.toFixed(1)
</script>

<template>
  <BaseCard variant="bg2" class="settings-card">
    <CollapsibleGroup :title="t('hosts.setting.alerting.title')" icon="notifications" :defaultOpen="false">
      <div v-if="loading" class="loading-row"><Spinner size="md" /></div>

      <template v-else>
        <p class="section-hint">{{ t('hosts.setting.alerting.intro') }}</p>

      <!-- ── Channel ── -->
      <div class="st-sub">{{ t('hosts.setting.alerting.channelSection') }}</div>

      <FormField layout="horizontal" bordered>
        <template #label>
          {{ t('hosts.setting.alerting.fields.emailEnabled') }}
          <HelpTip :text="t('hosts.setting.alerting.tips.inherit', { v: defaults?.email_enabled ? t('hosts.setting.alerting.on') : t('hosts.setting.alerting.off') })" />
        </template>
        <ToggleSwitch
          :modelValue="settings.email_enabled ?? defaults?.email_enabled ?? false"
          @update:modelValue="(v: boolean) => settings.email_enabled = v"
          size="sm"
        />
      </FormField>

      <FormField layout="horizontal" bordered>
        <template #label>
          {{ t('hosts.setting.alerting.fields.recipients') }}
          <HelpTip :text="t('hosts.setting.alerting.tips.recipients')" />
        </template>
        <BaseSelect
          v-if="adminOptions.length"
          multiple
          :options="adminOptions"
          :modelValue="recipientIds"
          :placeholder="t('hosts.setting.alerting.recipientsEmpty')"
          @update:modelValue="(v: any) => recipientIds = v as string[]"
        />
      </FormField>

      <FormField layout="horizontal" bordered>
        <template #label>{{ t('hosts.setting.alerting.fields.minSeverity') }}</template>
        <BaseSelect
          :modelValue="settings.min_severity ?? defaults?.min_severity ?? 'warning'"
          :options="severityOptions"
          @update:modelValue="(v: any) => settings.min_severity = v as Severity"
        />
      </FormField>

      <FormField layout="horizontal" bordered>
        <template #label>{{ t('hosts.setting.alerting.fields.notifyResolve') }}</template>
        <ToggleSwitch
          :modelValue="settings.notify_resolve ?? defaults?.notify_resolve ?? false"
          @update:modelValue="(v: boolean) => settings.notify_resolve = v"
          size="sm"
        />
      </FormField>

      <FormField layout="horizontal" bordered>
        <template #label>
          {{ t('hosts.setting.alerting.fields.cooldown') }}
          <HelpTip :text="t('hosts.setting.alerting.tips.cooldown')" />
        </template>
        <NumberInput
          :modelValue="settings.cooldown_min ?? defaults?.cooldown_min ?? 30"
          :min="1" :max="1440"
          @update:modelValue="(v: number) => settings.cooldown_min = v"
        />
      </FormField>

      <!-- ── Per-type rules ── -->
      <div class="st-sub">
        {{ t('hosts.setting.alerting.rulesSection') }}
        <HelpTip :text="t('hosts.setting.alerting.rulesTip')" />
      </div>

      <FormField
        v-for="at in TOGGLE_ONLY"
        :key="at"
        :label="t(`hosts.setting.alerting.types.${at}`)"
        layout="horizontal"
        bordered
      >
        <ToggleSwitch
          :modelValue="ruleEnabled(at)"
          @update:modelValue="(v: boolean) => setRuleEnabled(at, v)"
          size="sm"
        />
      </FormField>

      <FormField v-for="at in SINGLE_THRESHOLD" :key="at" layout="horizontal" bordered>
        <template #label>{{ t(`hosts.setting.alerting.types.${at}`) }}</template>
        <div class="alert-row">
          <ToggleSwitch :modelValue="ruleEnabled(at)" @update:modelValue="(v: boolean) => setRuleEnabled(at, v)" size="sm" />
          <RangeField
            class="alert-range"
            :label="t('hosts.setting.alerting.threshold')"
            :modelValue="ruleThreshold(at, at === 'load_high' ? 1.5 : 90)"
            :min="at === 'load_high' ? 0.5 : 50"
            :max="at === 'load_high' ? 5 : 100"
            :step="at === 'load_high' ? 0.1 : 1"
            show-value editable
            :value-format="at === 'load_high' ? loadFmt : pctFmt"
            @update:modelValue="(v: number) => setRuleThreshold(at, v)"
          />
          <RangeField
            class="alert-range"
            :label="t('hosts.setting.alerting.sustainMin')"
            :modelValue="ruleSustain(at, 5)"
            :min="1" :max="60" :step="1"
            show-value editable
            :value-format="minFmt"
            @update:modelValue="(v: number) => setRuleSustain(at, v)"
          />
        </div>
      </FormField>

      <FormField v-for="at in DUAL_THRESHOLD" :key="at" layout="horizontal" bordered>
        <template #label>{{ t(`hosts.setting.alerting.types.${at}`) }}</template>
        <div class="alert-row">
          <ToggleSwitch :modelValue="ruleEnabled(at)" @update:modelValue="(v: boolean) => setRuleEnabled(at, v)" size="sm" />
          <RangeField
            class="alert-range"
            :label="t('hosts.setting.alerting.warningThreshold')"
            :modelValue="ruleWarning(at, 85)"
            :min="50" :max="100" :step="1"
            show-value editable
            :value-format="pctFmt"
            @update:modelValue="(v: number) => setRuleWarning(at, v)"
          />
          <RangeField
            class="alert-range"
            :label="t('hosts.setting.alerting.criticalThreshold')"
            :modelValue="ruleCritical(at, 95)"
            :min="50" :max="100" :step="1"
            show-value editable
            :value-format="pctFmt"
            @update:modelValue="(v: number) => setRuleCritical(at, v)"
          />
        </div>
      </FormField>

        <div class="actions">
          <BaseButton size="sm" variant="ghost" @click="resetToDefaults">
            {{ t('hosts.setting.alerting.resetDefaults') }}
          </BaseButton>
        </div>
      </template>
    </CollapsibleGroup>
  </BaseCard>
</template>

<style scoped>
.loading-row {
  display: flex;
  justify-content: center;
  padding: var(--sp-4) 0;
}
.section-hint {
  color: var(--t2);
  font-size: var(--text-sm);
  margin: var(--sp-2) 0 0;
}

.st-sub {
  display: flex;
  align-items: center;
  gap: var(--sp-1);
  font-size: .95rem;
  font-weight: 600;
  color: var(--t1);
  padding: var(--sp-5) 0 var(--sp-2);
}

.alert-row {
  display: flex;
  align-items: center;
  gap: var(--sp-4);
  flex-wrap: nowrap;
  width: 100%;
}
.alert-range {
  flex: 1 1 0;
  min-width: 0;
}

.actions {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin-top: var(--sp-4);
}
.spacer { flex: 1; }
</style>

<script setup lang="ts">
// HostWingsSection — Wings 服务配置（panel.nodes 白名单字段 + push to wings）+ 服务状态 + 重启控制
//
// GET  /api/admin/nodes/{nodeId}/wings-config
//   → { panel, wings_service, wings_service_error, runtime_restart_required_fields }
// PUT  /api/admin/nodes/{nodeId}/wings-config (only changed fields)
//   → { panel_updated, wings_pushed, applied, changed, requires_wings_restart, restart_required_fields, ... }
// POST /api/admin/nodes/{nodeId}/wings/restart
//   → { ok, output, error, duration_ms }  (proxied through agent's wings.restart command)
//
// Save UX mirrors SettingsPage: a floating DirtyBar drives the save flow,
// no inline save/discard buttons. Leave-guard prompts on unsaved exit.
//
// Save-and-restart flow: when the dirty fields contain any value listed in
// `runtime_restart_required_fields`, the save click first pops a
// ConfirmDialog ("保存并重启 Wings"). On confirm we PUT the config and,
// if the push succeeded, fire POST /wings/restart and toast its outcome.
//
// 仅在 host.kind === 'wings_node' 时挂载。
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'
import { useDirtyFormSection } from '@/composables/useDirtyForm'
import FormField from '@/components/form/FormField.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import NumberInput from '@/components/form/NumberInput.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import ToggleSwitch from '@/components/ui/ToggleSwitch.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import AlertBanner from '@/components/ui/AlertBanner.vue'
import HelpTip from '@/components/ui/HelpTip.vue'
import Spinner from '@/components/ui/Spinner.vue'
import StatusDot from '@/components/ui/StatusDot.vue'
import MsIcon from '@/components/ui/MsIcon.vue'

defineOptions({ name: 'HostWingsSection' })

const props = defineProps<{ nodeId: number }>()
const { t } = useI18n({ useScope: 'global' })
const { get, post, raw } = useApiFetch()
const { toast } = useToast()
const { confirm } = useConfirm()

interface PanelSnapshot {
  name?: string
  description?: string
  fqdn?: string
  scheme?: 'http' | 'https'
  behind_proxy?: boolean
  maintenance_mode?: boolean
  memory?: number
  memory_overallocate?: number
  disk?: number
  disk_overallocate?: number
  upload_size?: number
  daemon_listen?: number
  daemon_sftp?: number
  daemon_base?: string
}

// FormState is a fully-required mirror used to bind v-model on strict-typed
// inputs without sprinkling `?? default` throughout the template. The load()
// function fills every field with a concrete fallback.
interface FormState {
  name: string
  description: string
  fqdn: string
  scheme: 'http' | 'https'
  behind_proxy: boolean
  maintenance_mode: boolean
  memory: number
  memory_overallocate: number
  disk: number
  disk_overallocate: number
  upload_size: number
  daemon_listen: number
  daemon_sftp: number
  daemon_base: string
}

const EMPTY_FORM: FormState = {
  name: '', description: '', fqdn: '', scheme: 'http',
  behind_proxy: false, maintenance_mode: false,
  memory: 0, memory_overallocate: -1,
  disk: 0, disk_overallocate: -1,
  upload_size: 100, daemon_listen: 8080, daemon_sftp: 2022,
  daemon_base: '/var/lib/pterodactyl/volumes',
}

interface WingsServiceState {
  service_name?: string
  active_state?: string | null     // active / inactive / failed / activating / ...
  sub_state?: string | null         // running / dead / failed / ...
  main_pid?: number | null
  since?: string | null             // ISO datetime; agent reports unit-state-change time
  error?: string | null
}

interface State {
  panel: PanelSnapshot
  wings_service: WingsServiceState | null
  wings_service_error: string | null
  runtime_restart_required_fields: string[]
}

const loading = ref(true)
const submitting = ref(false)
const restarting = ref(false)
const initial = ref<FormState>({ ...EMPTY_FORM })
const form = ref<FormState>({ ...EMPTY_FORM })
const wingsService = ref<WingsServiceState | null>(null)
const wingsServiceError = ref<string | null>(null)
const restartRequiredFields = ref<string[]>([])
const lastResult = ref<{ changed: string[]; restart_required?: string[] } | null>(null)

async function load() {
  loading.value = true
  try {
    const data = await get<State>(`/api/admin/nodes/${props.nodeId}/wings-config`)
    if (!data) return
    const p = data.panel || {}
    const normalized: FormState = {
      name: p.name ?? '',
      description: p.description ?? '',
      fqdn: p.fqdn ?? '',
      scheme: p.scheme ?? 'http',
      behind_proxy: p.behind_proxy ?? false,
      maintenance_mode: p.maintenance_mode ?? false,
      memory: p.memory ?? 0,
      memory_overallocate: p.memory_overallocate ?? -1,
      disk: p.disk ?? 0,
      disk_overallocate: p.disk_overallocate ?? -1,
      upload_size: p.upload_size ?? 100,
      daemon_listen: p.daemon_listen ?? 8080,
      daemon_sftp: p.daemon_sftp ?? 2022,
      daemon_base: p.daemon_base ?? '/var/lib/pterodactyl/volumes',
    }
    initial.value = { ...normalized }
    form.value = { ...normalized }
    wingsService.value = data.wings_service
    wingsServiceError.value = data.wings_service_error
    restartRequiredFields.value = data.runtime_restart_required_fields || []
  } finally {
    loading.value = false
  }
}

onMounted(load)

const FIELDS = [
  'name', 'description', 'fqdn', 'scheme', 'behind_proxy', 'maintenance_mode',
  'memory', 'memory_overallocate', 'disk', 'disk_overallocate',
  'upload_size', 'daemon_listen', 'daemon_sftp', 'daemon_base',
] as const

const dirtyFields = computed(() => {
  return FIELDS.filter(f => form.value[f] !== initial.value[f])
})
const isDirty = computed(() => dirtyFields.value.length > 0)

// Predict whether saving will require a wings restart by intersecting the
// dirty set against the runtime-restart-required field list reported by
// the backend (which mirrors wings_config.RUNTIME_RESTART_REQUIRED_FIELDS).
const willRequireRestart = computed(() =>
  dirtyFields.value.some(f => restartRequiredFields.value.includes(f)),
)
const restartFieldsLabel = computed(() =>
  dirtyFields.value
    .filter(f => restartRequiredFields.value.includes(f))
    .map(f => t(`hosts.setting.wings.fields.${camelOf(f)}`))
    .join('、'),
)

// snake_case form field name → camelCase i18n key (matches existing
// hosts.setting.wings.fields.* keys). Used only for dialog/banner text.
function camelOf(s: string): string {
  return s.replace(/_([a-z])/g, (_, c: string) => c.toUpperCase())
}

async function performSave(): Promise<{ ok: boolean; pushed: boolean }> {
  const body: Record<string, unknown> = {}
  for (const f of dirtyFields.value) body[f] = form.value[f]
  const res = await raw(`/api/admin/nodes/${props.nodeId}/wings-config`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res) return { ok: false, pushed: false }
  const json = await res.json()
  lastResult.value = { changed: json.changed || [], restart_required: json.restart_required_fields }
  return {
    ok: true,
    pushed: !!json.wings_pushed && json.applied === true,
  }
}

async function performRestart(): Promise<boolean> {
  restarting.value = true
  try {
    const r = await post<{ ok: boolean; error?: string; duration_ms?: number }>(
      `/api/admin/nodes/${props.nodeId}/wings/restart`, {},
    )
    if (!r) return false
    if (r.ok) {
      toast(t('hosts.setting.wings.restartOk', { ms: r.duration_ms ?? '?' }), 'success')
      return true
    }
    toast(t('hosts.setting.wings.restartFail', { err: r.error || '?' }), 'error')
    return false
  } finally {
    restarting.value = false
  }
}

async function save(): Promise<boolean> {
  if (!isDirty.value) return true
  // Save-and-restart confirmation when any dirty field needs a wings restart.
  // The dialog is shown BEFORE the PUT so the user opts in to the combined
  // action; on cancel we abort entirely (no partial save).
  let alsoRestart = false
  if (willRequireRestart.value) {
    const ok = await confirm({
      title: t('hosts.setting.wings.saveAndRestartTitle'),
      message: t('hosts.setting.wings.saveAndRestartMsg', { fields: restartFieldsLabel.value }),
      confirmText: t('hosts.setting.wings.saveAndRestartConfirm'),
      cancelText: t('hosts.setting.wings.cancel'),
    })
    if (ok !== true) return false
    alsoRestart = true
  }

  submitting.value = true
  let result: { ok: boolean; pushed: boolean }
  try {
    result = await performSave()
  } finally {
    submitting.value = false
  }
  if (!result.ok) return false
  toast(t('hosts.setting.wings.saved', { n: lastResult.value?.changed.length || 0 }), 'success')
  await load()

  // Only attempt the restart if wings actually accepted the patch — otherwise
  // restarting won't help (backend already suppresses restart_required_fields
  // when push failed, but defending in depth here).
  if (alsoRestart && result.pushed) {
    await performRestart()
  }
  return true
}

function discard() {
  form.value = { ...initial.value }
}

// Register into the page-wide DirtyBar / leave-guard owned by HostWingsPane.
useDirtyFormSection({ name: 'wings-config', isDirty, save, discard })

// Standalone restart button: only restarts wings, never pushes config.
// Confirmation makes the consequence (server brief offline) explicit.
async function restartWings() {
  const ok = await confirm({
    title: t('hosts.setting.wings.restartConfirmTitle'),
    message: t('hosts.setting.wings.restartConfirmMsg'),
    confirmText: t('hosts.setting.wings.restart'),
    cancelText: t('hosts.setting.wings.cancel'),
    variant: 'danger',
  })
  if (ok !== true) return
  await performRestart()
  await load()
}

// ----- Wings service status presentation helpers -----
// Maps systemd ActiveState/SubState into a single status-dot variant so the
// header banner reads at a glance: green (running), amber (transitional),
// red (dead/failed), gray (unknown).
const serviceTone = computed<'green' | 'amber' | 'red' | 'gray'>(() => {
  const s = wingsService.value
  if (!s || !s.active_state) return 'gray'
  if (s.active_state === 'active' && s.sub_state === 'running') return 'green'
  if (s.active_state === 'failed') return 'red'
  if (s.active_state === 'inactive' || s.sub_state === 'dead') return 'red'
  return 'amber'
})
const serviceStateLabel = computed(() => {
  const s = wingsService.value
  if (!s || !s.active_state) return t('hosts.setting.wings.serviceState.unknown')
  // Prefer sub_state when it carries useful info (running/dead); otherwise active_state.
  const key = s.sub_state || s.active_state
  const path = `hosts.setting.wings.serviceState.${key}`
  // Fall back to the raw key when no translation exists — systemd has many
  // sub-states and we only translate the common ones.
  const translated = t(path)
  return translated === path ? key : translated
})

const uptimeLabel = computed(() => {
  const since = wingsService.value?.since
  if (!since) return null
  const t0 = new Date(since).getTime()
  if (Number.isNaN(t0)) return null
  const sec = Math.max(0, Math.floor((Date.now() - t0) / 1000))
  const d = Math.floor(sec / 86400)
  const h = Math.floor((sec % 86400) / 3600)
  const m = Math.floor((sec % 3600) / 60)
  if (d > 0) return `${d}d ${h}h`
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
})

const schemeOptions = [
  { value: 'http', label: 'http' },
  { value: 'https', label: 'https' },
]
</script>

<template>
  <div class="wings-section">
    <div v-if="loading" class="loading-row"><Spinner size="md" /></div>

    <template v-else>
      <!-- Compact wings systemd status pill (one line, width follows form) -->
      <div class="svc-banner" :class="`svc-banner--${serviceTone}`">
        <StatusDot
          :status="serviceTone === 'green' ? 'running' : serviceTone === 'red' ? 'error' : serviceTone === 'amber' ? 'loading' : 'stopped'"
          size="sm"
        />
        <span class="svc-banner__state">{{ serviceStateLabel }}</span>
        <span v-if="uptimeLabel" class="svc-banner__sep">·</span>
        <span v-if="uptimeLabel" class="svc-banner__meta">
          {{ t('hosts.setting.wings.serviceUptime', { dur: uptimeLabel }) }}
        </span>
        <span v-if="wingsService?.main_pid" class="svc-banner__sep">·</span>
        <span v-if="wingsService?.main_pid" class="svc-banner__meta mono">
          PID {{ wingsService.main_pid }}
        </span>
      </div>

      <AlertBanner v-if="wingsServiceError" tone="warning" dense>
        {{ t('hosts.setting.wings.serviceError', { err: wingsServiceError }) }}
      </AlertBanner>

      <AlertBanner v-if="lastResult?.restart_required?.length" tone="warning" dense>
        {{ t('hosts.setting.wings.restartRequired', { fields: lastResult.restart_required.join(', ') }) }}
      </AlertBanner>

      <div class="form">
        <FormField layout="horizontal" bordered>
          <template #label>{{ t('hosts.setting.wings.fields.name') }}</template>
          <BaseInput v-model="form.name" />
        </FormField>

        <FormField layout="horizontal" bordered>
          <template #label>{{ t('hosts.setting.wings.fields.description') }}</template>
          <BaseInput v-model="form.description" />
        </FormField>

        <FormField layout="horizontal" bordered>
          <template #label>{{ t('hosts.setting.wings.fields.fqdn') }}</template>
          <BaseInput v-model="form.fqdn" />
        </FormField>

        <FormField layout="horizontal" bordered>
          <template #label>{{ t('hosts.setting.wings.fields.scheme') }}</template>
          <BaseSelect :modelValue="form.scheme || 'http'" :options="schemeOptions" @update:modelValue="(v: any) => form.scheme = v" />
        </FormField>

        <FormField layout="horizontal" bordered>
          <template #label>
            {{ t('hosts.setting.wings.fields.behindProxy') }}
            <HelpTip :text="t('hosts.setting.wings.tips.behindProxy')" />
          </template>
          <ToggleSwitch v-model="form.behind_proxy" size="sm" />
        </FormField>

        <FormField layout="horizontal" bordered>
          <template #label>
            {{ t('hosts.setting.wings.fields.maintenance') }}
            <HelpTip :text="t('hosts.setting.wings.tips.maintenance')" />
          </template>
          <ToggleSwitch v-model="form.maintenance_mode" size="sm" />
        </FormField>

        <FormField layout="horizontal" bordered>
          <template #label>{{ t('hosts.setting.wings.fields.memory') }}</template>
          <NumberInput v-model="form.memory" :min="0" />
        </FormField>

        <FormField layout="horizontal" bordered>
          <template #label>
            {{ t('hosts.setting.wings.fields.memoryOver') }}
            <HelpTip :text="t('hosts.setting.wings.tips.overallocate')" />
          </template>
          <NumberInput v-model="form.memory_overallocate" :min="-1" />
        </FormField>

        <FormField layout="horizontal" bordered>
          <template #label>{{ t('hosts.setting.wings.fields.disk') }}</template>
          <NumberInput v-model="form.disk" :min="0" />
        </FormField>

        <FormField layout="horizontal" bordered>
          <template #label>
            {{ t('hosts.setting.wings.fields.diskOver') }}
            <HelpTip :text="t('hosts.setting.wings.tips.overallocate')" />
          </template>
          <NumberInput v-model="form.disk_overallocate" :min="-1" />
        </FormField>

        <FormField layout="horizontal" bordered>
          <template #label>
            {{ t('hosts.setting.wings.fields.uploadSize') }}
            <HelpTip :text="t('hosts.setting.wings.tips.uploadSize')" />
          </template>
          <NumberInput v-model="form.upload_size" :min="1" :max="1048576" />
        </FormField>

        <FormField layout="horizontal" bordered>
          <template #label>{{ t('hosts.setting.wings.fields.daemonListen') }}</template>
          <NumberInput v-model="form.daemon_listen" :min="1" :max="65535" />
        </FormField>

        <FormField layout="horizontal" bordered>
          <template #label>{{ t('hosts.setting.wings.fields.daemonSftp') }}</template>
          <NumberInput v-model="form.daemon_sftp" :min="1" :max="65535" />
        </FormField>

        <FormField layout="horizontal" bordered>
          <template #label>
            {{ t('hosts.setting.wings.fields.daemonBase') }}
            <HelpTip :text="t('hosts.setting.wings.tips.daemonBase')" />
          </template>
          <BaseInput v-model="form.daemon_base" />
        </FormField>

        <!-- Standalone restart action: never pushes config; only restarts wings. -->
        <div class="actions">
          <span class="spacer" />
          <BaseButton size="sm" variant="default" :loading="restarting" @click="restartWings">
            <MsIcon name="restart_alt" size="xs" />
            {{ t('hosts.setting.wings.restart') }}
          </BaseButton>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.wings-section > * + * { margin-top: var(--sp-3); }
.loading-row {
  display: flex;
  justify-content: center;
  padding: var(--sp-4) 0;
}
.form {
  padding-top: var(--sp-2);
}
.actions {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin-top: var(--sp-3);
}
.spacer { flex: 1; }

/* Compact wings systemd status pill above the form. Width follows the
   form's max-width via its parent container. */
.svc-banner {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-2) var(--sp-3);
  background: var(--bg3);
  border: 1px solid var(--bd);
  border-radius: var(--r-sm);
  font-size: var(--text-sm);
  color: var(--t1);
}
.svc-banner__state {
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: .03em;
}
.svc-banner__meta {
  color: var(--t2);
  font-size: var(--text-xs);
}
.svc-banner__sep {
  color: var(--t3);
  font-size: var(--text-xs);
}
.svc-banner .mono {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}
.svc-banner--green { border-left: 3px solid var(--green); }
.svc-banner--amber { border-left: 3px solid var(--amber); }
.svc-banner--red   { border-left: 3px solid var(--red); }
.svc-banner--gray  { border-left: 3px solid var(--t3); }
</style>

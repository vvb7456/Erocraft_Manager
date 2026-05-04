<script lang="ts">
/**
 * PlanEditorModal — admin billing plan create/edit/duplicate.
 *
 * 5 tabs: basic / resources / runtime / pricing / display.
 * Builds a `PlanIn` payload and POSTs (create/duplicate) or PUTs (edit) to
 * `/api/admin/billing/plans`. Surfaces backend 409/422 detail in an inline
 * banner; client-side checks are kept minimal (Pydantic-mirroring boundary
 * checks only — never duplicate backend logic).
 */
export type EditorMode = 'create' | 'edit' | 'duplicate'

export interface PeriodOption {
  count: number
  discount_pct: number
}

export interface AdminPlan {
  id: number
  code: string
  display_name: string
  price_fen: number
  days: number
  currency_code: string
  period_options: PeriodOption[]
  node_id: number
  egg_id: number
  nest_id: number
  cpu: number
  memory_mb: number
  disk_mb: number
  swap_mb: number
  io: number
  database_limit: number
  backup_limit: number
  allocation_limit: number
  oom_disabled: boolean
  docker_image: string
  startup_command: string
  env_defaults: Record<string, string>
  is_active: boolean
  display_order: number
  description_md: string | null
  category_label: string | null
  created_at: string
  updated_at: string
}
</script>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'
import BaseModal from '@/components/ui/BaseModal.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import TabSwitcher, { type TabItem } from '@/components/ui/TabSwitcher.vue'
import AlertBanner from '@/components/ui/AlertBanner.vue'
import HelpTip from '@/components/ui/HelpTip.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import FormField from '@/components/form/FormField.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import BaseTextarea from '@/components/form/BaseTextarea.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import NumberInput from '@/components/form/NumberInput.vue'
import RangeField from '@/components/form/RangeField.vue'
import ToggleSwitch from '@/components/ui/ToggleSwitch.vue'

defineOptions({ name: 'PlanEditorModal' })

interface NodeRef { id: number; name: string }
interface NestRef { id: number; name: string }
interface EggRef  { id: number; name: string; nest_id: number }

const props = defineProps<{
  modelValue: boolean
  mode: EditorMode
  plan: AdminPlan | null
  nodesMap: Map<number, NodeRef>
  nestsMap: Map<number, NestRef>
  eggsMap: Map<number, EggRef>
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  saved: [plan: AdminPlan]
}>()

const { t } = useI18n({ useScope: 'global' })
const { get, raw } = useApiFetch()
const { toast } = useToast()
const { confirm } = useConfirm()

// ── Form state (mirrors PlanIn shape, with price_yuan as string for input) ──
interface PlanFormState {
  code: string
  display_name: string
  description_md: string
  is_active: boolean
  // Resources
  node_id: number | null
  nest_id: number | null
  egg_id: number | null
  cpu: number
  memory_mb: number
  disk_mb: number
  swap_mb: number
  io: number
  database_limit: number
  backup_limit: number
  allocation_limit: number
  oom_disabled: boolean
  // Runtime
  docker_image: string
  docker_image_custom: boolean
  startup_command: string
  env_defaults: Record<string, string>
  // Pricing
  currency_code: string
  price_yuan: string         // user-entered yuan, e.g. "9.90"; converted to fen on save
  days: number
  period_options: PeriodOption[]
  // Display
  category_label: string
  display_order: number
}

function emptyForm(): PlanFormState {
  return {
    code: '',
    display_name: '',
    description_md: '',
    is_active: true,
    node_id: null,
    nest_id: null,
    egg_id: null,
    cpu: 100,
    memory_mb: 1024,
    disk_mb: 5120,
    swap_mb: 0,
    io: 500,
    database_limit: 0,
    backup_limit: 0,
    allocation_limit: 1,
    oom_disabled: true,
    docker_image: '',
    docker_image_custom: false,
    startup_command: '',
    env_defaults: {},
    currency_code: 'CNY',
    price_yuan: '9.90',
    days: 30,
    period_options: [{ count: 1, discount_pct: 0 }],
    category_label: '',
    display_order: 0,
  }
}

function fromAdminPlan(p: AdminPlan, mode: EditorMode): PlanFormState {
  const declaredImages = listEggImages(p.egg_id)
  const isCustom = declaredImages.length > 0 && !declaredImages.some((i) => i.value === p.docker_image)
  return {
    code: mode === 'duplicate' ? '' : p.code,
    display_name: p.display_name,
    description_md: p.description_md ?? '',
    is_active: p.is_active,
    node_id: p.node_id,
    nest_id: p.nest_id,
    egg_id: p.egg_id,
    cpu: p.cpu,
    memory_mb: p.memory_mb,
    disk_mb: p.disk_mb,
    swap_mb: p.swap_mb,
    io: p.io,
    database_limit: p.database_limit,
    backup_limit: p.backup_limit,
    allocation_limit: p.allocation_limit,
    oom_disabled: p.oom_disabled,
    docker_image: p.docker_image,
    docker_image_custom: isCustom,
    startup_command: p.startup_command,
    env_defaults: { ...p.env_defaults },
    currency_code: p.currency_code,
    price_yuan: (p.price_fen / 100).toFixed(2),
    days: p.days,
    period_options: p.period_options.map((o) => ({ ...o })),
    category_label: p.category_label ?? '',
    display_order: p.display_order,
  }
}

const form = ref<PlanFormState>(emptyForm())
const orig = ref<string>('')   // JSON snapshot for dirty detection

const activeTab = ref<string>('basic')
const saving = ref(false)
const saveError = ref<string | null>(null)

// Egg variables (loaded per egg)
interface EggVariable {
  id: number
  name: string
  description: string
  env_variable: string
  default_value: string
  rules: string
  user_viewable: boolean
  user_editable: boolean
}
const eggVariables = ref<EggVariable[]>([])
const loadingEggVars = ref(false)

// Egg docker_images map (loaded per egg)
interface EggImageOption { value: string; label: string }
interface EggDetail {
  id: number
  docker_image: string
  startup: string
  docker_images: Record<string, string>
}
const eggDetailsCache = ref<Map<number, EggDetail>>(new Map())

const dockerImageOptions = computed<EggImageOption[]>(() => listEggImages(form.value.egg_id))

function listEggImages(eggId: number | null): EggImageOption[] {
  if (eggId == null) return []
  const detail = eggDetailsCache.value.get(eggId)
  if (!detail?.docker_images) return []
  return Object.entries(detail.docker_images).map(([label, image]) => ({
    value: image,
    label: `${label} — ${image}`,
  }))
}

// ── Computed ──
const isDirty = computed(() => JSON.stringify(form.value) !== orig.value)

const nodeOptions = computed(() => Array.from(props.nodesMap.values()).map((n) => ({
  value: n.id,
  label: n.name,
})))
const nestOptions = computed(() => Array.from(props.nestsMap.values()).map((n) => ({
  value: n.id,
  label: n.name,
})))
const eggOptions = computed(() => {
  const nestId = form.value.nest_id
  if (nestId == null) return []
  return Array.from(props.eggsMap.values())
    .filter((e) => e.nest_id === nestId)
    .map((e) => ({ value: e.id, label: e.name }))
})

const tabs = computed<TabItem[]>(() => [
  { key: 'basic',     label: t('billing.admin.plans.tabs.basic') },
  { key: 'resources', label: t('billing.admin.plans.tabs.resources') },
  { key: 'runtime',   label: t('billing.admin.plans.tabs.runtime') },
  { key: 'pricing',   label: t('billing.admin.plans.tabs.pricing') },
  { key: 'display',   label: t('billing.admin.plans.tabs.display') },
])

const modalTitle = computed(() => {
  if (props.mode === 'create') return t('billing.admin.plans.create')
  if (props.mode === 'duplicate') return t('billing.admin.plans.duplicateTitle', { code: props.plan?.code ?? '' })
  return t('billing.admin.plans.editTitle', { code: props.plan?.code ?? '' })
})

// ── Lifecycle: when modal opens, build form & load egg-related data ──
watch(() => props.modelValue, async (open) => {
  if (!open) return
  saveError.value = null
  activeTab.value = 'basic'

  // Build initial form
  if (props.mode === 'create' || !props.plan) {
    form.value = emptyForm()
  } else {
    // For edit/duplicate, ensure egg detail is loaded so docker image
    // options resolve correctly when computing dock_image_custom.
    await loadEggDetail(props.plan.egg_id)
    form.value = fromAdminPlan(props.plan, props.mode)
    if (props.plan.nest_id) await loadEggVariables(props.plan.egg_id)
  }
  orig.value = JSON.stringify(form.value)
})

// Watch egg change to (re)load variables + docker images
watch(() => form.value.egg_id, async (newId, oldId) => {
  if (newId == null || newId === oldId) return
  await loadEggDetail(newId)
  await loadEggVariables(newId)
})

// ── Loaders ──
async function loadEggVariables(eggId: number) {
  const nestId = form.value.nest_id ?? props.eggsMap.get(eggId)?.nest_id
  if (!nestId) return
  loadingEggVars.value = true
  const data = await get<{ variables: EggVariable[] }>(
    `/api/admin/resources/nests/${nestId}/eggs/${eggId}/variables`,
    { silent: true },
  )
  loadingEggVars.value = false
  if (!data?.variables) {
    eggVariables.value = []
    return
  }
  eggVariables.value = data.variables
  // Initialise env_defaults for any missing variable (using egg defaults).
  for (const v of data.variables) {
    if (form.value.env_defaults[v.env_variable] === undefined) {
      form.value.env_defaults[v.env_variable] = v.default_value ?? ''
    }
  }
  // Strip keys not declared by this egg.
  const declared = new Set(data.variables.map((v) => v.env_variable))
  for (const k of Object.keys(form.value.env_defaults)) {
    if (!declared.has(k)) delete form.value.env_defaults[k]
  }
}

async function loadEggDetail(eggId: number) {
  if (eggDetailsCache.value.has(eggId)) return
  const nestId = form.value.nest_id ?? props.eggsMap.get(eggId)?.nest_id
  if (!nestId) return
  // /api/nests/:nestId/eggs returns eggs list; we want one egg's detail.
  // Use the same endpoint and pluck.
  const data = await get<{ eggs: EggDetail[] }>(`/api/admin/resources/nests/${nestId}/eggs`, { silent: true })
  if (!data?.eggs) return
  for (const e of data.eggs) {
    eggDetailsCache.value.set(e.id, e)
  }
  // Pre-fill startup/docker_image when create-mode and empty.
  if (props.mode === 'create' && !form.value.startup_command) {
    const d = eggDetailsCache.value.get(eggId)
    if (d) {
      form.value.startup_command = d.startup
      form.value.docker_image = d.docker_image
    }
  }
}

// ── Egg switch confirmation ──
async function onNestChange(newNestId: string | number | boolean | (string | number | boolean)[]) {
  const v = Number(newNestId)
  if (v === form.value.nest_id) return
  if (form.value.egg_id != null && Object.keys(form.value.env_defaults).length > 0) {
    const ok = await confirm({
      title: t('billing.admin.plans.confirmSwitchEggTitle'),
      message: t('billing.admin.plans.hints.switchEggReset'),
    })
    if (!ok) return
  }
  form.value.nest_id = v
  form.value.egg_id = null
  form.value.env_defaults = {}
  eggVariables.value = []
}

async function onEggChange(newEggId: string | number | boolean | (string | number | boolean)[]) {
  const v = Number(newEggId)
  if (v === form.value.egg_id) return
  if (form.value.egg_id != null && Object.keys(form.value.env_defaults).length > 0) {
    const ok = await confirm({
      title: t('billing.admin.plans.confirmSwitchEggTitle'),
      message: t('billing.admin.plans.hints.switchEggReset'),
    })
    if (!ok) return
  }
  form.value.egg_id = v
  form.value.env_defaults = {}
}

function resetEnvDefaults() {
  for (const v of eggVariables.value) {
    form.value.env_defaults[v.env_variable] = v.default_value ?? ''
  }
}

// ── Period options editor ──
function addPeriod() {
  // Suggest the next reasonable count (max + 1, capped at 24)
  const maxCount = form.value.period_options.reduce((m, o) => Math.max(m, o.count), 0)
  const next = Math.min(maxCount + 1, 24)
  if (form.value.period_options.some((o) => o.count === next)) return
  form.value.period_options.push({ count: next, discount_pct: 0 })
}

function removePeriod(idx: number) {
  const opt = form.value.period_options[idx]
  if (opt.count === 1) return // can't remove base
  form.value.period_options.splice(idx, 1)
}

const periodErrors = computed<string[]>(() => {
  const errs: string[] = []
  const seen = new Set<number>()
  for (const o of form.value.period_options) {
    if (o.count < 1 || o.count > 24) errs.push(t('billing.admin.plans.errors.periodCountRange'))
    if (seen.has(o.count)) errs.push(t('billing.admin.plans.errors.periodCountDup', { c: o.count }))
    seen.add(o.count)
    if (o.discount_pct < 0 || o.discount_pct > 50) errs.push(t('billing.admin.plans.errors.periodDiscountRange'))
    if (o.count === 1 && o.discount_pct !== 0) errs.push(t('billing.admin.plans.errors.periodBaseDiscount'))
  }
  if (!form.value.period_options.some((o) => o.count === 1)) errs.push(t('billing.admin.plans.errors.periodNeedBase'))
  return Array.from(new Set(errs))
})

function periodTotalYuan(opt: PeriodOption): string {
  const priceFen = parsePriceFen(form.value.price_yuan)
  if (priceFen == null) return '—'
  const total = Math.round(priceFen * opt.count * (1 - opt.discount_pct / 100))
  return (total / 100).toFixed(2)
}

function periodTotalDays(opt: PeriodOption): number {
  return form.value.days * opt.count
}

// ── Helpers ──
function parsePriceFen(s: string): number | null {
  const v = parseFloat(s)
  if (isNaN(v) || v <= 0) return null
  return Math.round(v * 100)
}

// Quick client-side preflight (mirrors Pydantic boundaries only)
const preflightErrors = computed<string[]>(() => {
  const errs: string[] = []
  if (!form.value.code.trim()) errs.push(t('billing.admin.plans.errors.codeRequired'))
  if (!form.value.display_name.trim()) errs.push(t('billing.admin.plans.errors.nameRequired'))
  if (parsePriceFen(form.value.price_yuan) == null) errs.push(t('billing.admin.plans.errors.priceInvalid'))
  if (form.value.node_id == null) errs.push(t('billing.admin.plans.errors.nodeRequired'))
  if (form.value.nest_id == null) errs.push(t('billing.admin.plans.errors.nestRequired'))
  if (form.value.egg_id == null) errs.push(t('billing.admin.plans.errors.eggRequired'))
  if (!form.value.docker_image.trim()) errs.push(t('billing.admin.plans.errors.dockerImageRequired'))
  if (!form.value.startup_command.trim()) errs.push(t('billing.admin.plans.errors.startupRequired'))
  if (periodErrors.value.length > 0) errs.push(...periodErrors.value)
  return errs
})

const canSave = computed(() => preflightErrors.value.length === 0 && !saving.value)

// ── Save ──
function buildPayload(): Record<string, unknown> {
  return {
    code: form.value.code.trim(),
    display_name: form.value.display_name.trim(),
    price_fen: parsePriceFen(form.value.price_yuan),
    days: form.value.days,
    currency_code: form.value.currency_code,
    period_options: form.value.period_options.map((o) => ({
      count: o.count,
      discount_pct: o.discount_pct,
    })),
    node_id: form.value.node_id,
    egg_id: form.value.egg_id,
    nest_id: form.value.nest_id,
    cpu: form.value.cpu,
    memory_mb: form.value.memory_mb,
    disk_mb: form.value.disk_mb,
    swap_mb: form.value.swap_mb,
    io: form.value.io,
    database_limit: form.value.database_limit,
    backup_limit: form.value.backup_limit,
    allocation_limit: form.value.allocation_limit,
    oom_disabled: form.value.oom_disabled,
    docker_image: form.value.docker_image.trim(),
    startup_command: form.value.startup_command,
    env_defaults: form.value.env_defaults,
    is_active: form.value.is_active,
    display_order: form.value.display_order,
    description_md: form.value.description_md.trim() || null,
    category_label: form.value.category_label.trim() || null,
  }
}

async function doSave() {
  saveError.value = null
  if (!canSave.value) {
    saveError.value = preflightErrors.value.join('; ')
    return
  }
  saving.value = true
  const payload = buildPayload()
  const url = props.mode === 'edit' && props.plan
    ? `/api/admin/billing/plans/${props.plan.id}`
    : '/api/admin/billing/plans'
  const method = props.mode === 'edit' ? 'PUT' : 'POST'

  const res = await raw(url, {
    method,
    body: JSON.stringify(payload),
    headers: { 'Content-Type': 'application/json' },
    silent: true,
  })
  saving.value = false

  if (res && res.ok) {
    const saved = await res.json() as AdminPlan
    emit('saved', saved)
    toast(t('billing.admin.plans.saveSuccess'), 'success')
    closeModal(true)
  } else if (res) {
    let detail = `HTTP ${res.status}`
    try {
      const body = await res.json()
      detail = body.detail || body.message || detail
    } catch { /* ignore */ }
    saveError.value = detail
  } else {
    saveError.value = t('common.apiErrors.network')
  }
}

// ── Close handling (dirty confirm) ──
async function tryClose() {
  if (isDirty.value) {
    const ok = await confirm({
      title: t('billing.admin.plans.confirmDiscardTitle'),
      message: t('billing.admin.plans.confirmDiscardMessage'),
      variant: 'danger',
      confirmText: t('common.btn.discard'),
    })
    if (!ok) return
  }
  closeModal(false)
}

function closeModal(force: boolean) {
  if (force) {
    emit('update:modelValue', false)
    return
  }
  emit('update:modelValue', false)
}

function discardChanges() {
  if (orig.value) form.value = JSON.parse(orig.value)
}

// Auto-update docker_image when the dropdown selection changes via switching to custom
function onDockerImageSelectChange(v: string | number | boolean | (string | number | boolean)[]) {
  const s = String(v)
  if (s === '__custom__') {
    form.value.docker_image_custom = true
    return
  }
  form.value.docker_image_custom = false
  form.value.docker_image = s
}
</script>

<template>
  <BaseModal
    :model-value="modelValue"
    @update:model-value="(v) => v ? emit('update:modelValue', true) : tryClose()"
    :title="modalTitle"
    icon="local_offer"
    size="xl"
  >
    <div class="editor">
      <TabSwitcher v-model="activeTab" :tabs="tabs" />

      <AlertBanner v-if="saveError" tone="danger" class="editor__error">
        {{ saveError }}
      </AlertBanner>

      <!-- ═══ Tab: 基础 ═══ -->
      <div v-show="activeTab === 'basic'" class="tab-pane">
        <FormField :label="t('billing.admin.plans.fields.displayName')" required>
          <BaseInput v-model="form.display_name" :placeholder="t('billing.admin.plans.placeholders.displayName')" />
        </FormField>

        <FormField required>
          <template #label>{{ t('billing.admin.plans.fields.code') }}<HelpTip :text="t('billing.admin.plans.hints.code')" /></template>
          <BaseInput v-model="form.code" mono :placeholder="'st-basic'" />
        </FormField>

        <FormField>
          <template #label>{{ t('billing.admin.plans.fields.description') }}<HelpTip :text="t('billing.admin.plans.hints.description')" /></template>
          <BaseTextarea v-model="form.description_md" :rows="6" />
        </FormField>
      </div>

      <!-- ═══ Tab: 资源 ═══ -->
      <div v-show="activeTab === 'resources'" class="tab-pane">
        <div class="grid-2">
          <FormField :label="t('billing.admin.plans.fields.node')" required>
            <BaseSelect
              :model-value="form.node_id ?? ''"
              :options="nodeOptions"
              @update:model-value="(v) => form.node_id = v == null ? null : Number(v)"
            />
          </FormField>
          <FormField :label="t('billing.admin.plans.fields.nest')" required>
            <BaseSelect
              :model-value="form.nest_id ?? ''"
              :options="nestOptions"
              @update:model-value="onNestChange"
            />
          </FormField>
          <FormField :label="t('billing.admin.plans.fields.egg')" required>
            <BaseSelect
              :model-value="form.egg_id ?? ''"
              :options="eggOptions"
              :disabled="form.nest_id == null"
              @update:model-value="onEggChange"
            />
          </FormField>
        </div>

        <div class="grid-3">
          <FormField :label="t('billing.admin.plans.fields.cpu')">
            <template #label>{{ t('billing.admin.plans.fields.cpu') }}<HelpTip :text="t('billing.admin.plans.hints.cpu')" /></template>
            <NumberInput v-model="form.cpu" :min="1" :max="1000000" :step="50" />
          </FormField>
          <FormField>
            <template #label>{{ t('billing.admin.plans.fields.memory') }}<HelpTip :text="t('billing.admin.plans.hints.memory')" /></template>
            <NumberInput v-model="form.memory_mb" :min="1" :max="1000000" :step="128" />
          </FormField>
          <FormField :label="t('billing.admin.plans.fields.disk')">
            <NumberInput v-model="form.disk_mb" :min="1" :max="10000000" :step="512" />
          </FormField>
          <FormField>
            <template #label>{{ t('billing.admin.plans.fields.swap') }}<HelpTip :text="t('billing.admin.plans.hints.swap')" /></template>
            <NumberInput v-model="form.swap_mb" :min="-1" :max="1000000" :step="128" />
          </FormField>
          <FormField>
            <RangeField v-model="form.io" :min="10" :max="1000" :step="10" :label="t('billing.admin.plans.fields.io')" editable class="io-range">
              <template #label-append><HelpTip :text="t('billing.admin.plans.hints.io')" /></template>
            </RangeField>
          </FormField>
          <FormField :label="t('billing.admin.plans.fields.databaseLimit')">
            <NumberInput v-model="form.database_limit" :min="0" :max="1000" />
          </FormField>
          <FormField :label="t('billing.admin.plans.fields.backupLimit')">
            <NumberInput v-model="form.backup_limit" :min="0" :max="1000" />
          </FormField>
          <FormField>
            <template #label>{{ t('billing.admin.plans.fields.allocationLimit') }}<HelpTip :text="t('billing.admin.plans.hints.allocation')" /></template>
            <NumberInput v-model="form.allocation_limit" :min="1" :max="1000" />
          </FormField>
          <FormField :label="t('billing.admin.plans.fields.oomDisabled')" layout="horizontal" keep-horizontal class="oom-field">
            <ToggleSwitch v-model="form.oom_disabled" />
          </FormField>
        </div>
      </div>

      <!-- ═══ Tab: 运行环境 ═══ -->
      <div v-show="activeTab === 'runtime'" class="tab-pane">
        <FormField :label="t('billing.admin.plans.fields.dockerImage')" required>
          <div v-if="dockerImageOptions.length > 0 && !form.docker_image_custom" class="image-row">
            <BaseSelect
              :model-value="form.docker_image"
              :options="[
                ...dockerImageOptions,
                { value: '__custom__', label: t('billing.admin.plans.dockerImageCustom') },
              ]"
              @update:model-value="onDockerImageSelectChange"
            />
          </div>
          <div v-else class="image-row">
            <BaseInput v-model="form.docker_image" mono :placeholder="'ghcr.io/...'" />
            <BaseButton
              v-if="dockerImageOptions.length > 0"
              size="sm"
              @click="form.docker_image_custom = false; form.docker_image = dockerImageOptions[0]?.value ?? ''"
            >
              <MsIcon name="undo" />
              {{ t('billing.admin.plans.useEggImage') }}
            </BaseButton>
          </div>
        </FormField>

        <FormField :label="t('billing.admin.plans.fields.startupCommand')" required>
          <BaseTextarea v-model="form.startup_command" :rows="3" mono />
        </FormField>

        <div class="env-header">
          <h4>{{ t('billing.admin.plans.fields.envDefaults') }}</h4>
          <BaseButton
            v-if="eggVariables.length > 0"
            size="sm"
            @click="resetEnvDefaults"
          >
            <MsIcon name="undo" />
            {{ t('billing.admin.plans.resetEnvDefaults') }}
          </BaseButton>
        </div>

        <div v-if="form.egg_id == null" class="env-empty">
          {{ t('billing.admin.plans.envSelectEggFirst') }}
        </div>
        <div v-else-if="loadingEggVars" class="env-empty">
          {{ t('common.loading') }}
        </div>
        <div v-else-if="eggVariables.length === 0" class="env-empty">
          {{ t('billing.admin.plans.envNoVariables') }}
        </div>
        <div v-else class="env-grid">
          <FormField
            v-for="v in eggVariables"
            :key="v.env_variable"
            :label="v.env_variable"
            :hint="v.description"
          >
            <BaseInput
              :model-value="form.env_defaults[v.env_variable] ?? ''"
              @update:model-value="(val) => form.env_defaults[v.env_variable] = val"
              mono
              :placeholder="v.default_value ?? ''"
            />
          </FormField>
        </div>
      </div>

      <!-- ═══ Tab: 周期与价格 ═══ -->
      <div v-show="activeTab === 'pricing'" class="tab-pane">
        <div class="grid-3">
          <FormField :label="t('billing.admin.plans.fields.currency')">
            <BaseSelect
              :model-value="form.currency_code"
              :options="[{ value: 'CNY', label: 'CNY (¥)' }]"
              disabled
            />
          </FormField>
          <FormField :label="t('billing.admin.plans.fields.price')" required>
            <BaseInput v-model="form.price_yuan" mono placeholder="9.90" />
          </FormField>
          <FormField :label="t('billing.admin.plans.fields.days')" required>
            <NumberInput v-model="form.days" :min="1" :max="3650" />
          </FormField>
        </div>

        <div class="periods">
          <div class="periods-head">
            <h4>{{ t('billing.admin.plans.fields.periodOptions') }}</h4>
            <BaseButton size="sm" @click="addPeriod">
              <MsIcon name="add" />
              {{ t('billing.admin.plans.addPeriod') }}
            </BaseButton>
          </div>

          <table class="periods-table">
            <thead>
              <tr>
                <th>{{ t('billing.admin.plans.periods.count') }}</th>
                <th>{{ t('billing.admin.plans.periods.discount') }}</th>
                <th>{{ t('billing.admin.plans.periods.totalPrice') }}</th>
                <th>{{ t('billing.admin.plans.periods.totalDays') }}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(opt, idx) in form.period_options" :key="idx">
                <td>
                  <NumberInput
                    v-model="opt.count"
                    :min="1" :max="24" :step="1"
                    :disabled="opt.count === 1 && idx === form.period_options.findIndex((o) => o.count === 1)"
                  />
                </td>
                <td>
                  <NumberInput
                    v-model="opt.discount_pct"
                    :min="0" :max="50" :step="1"
                    :disabled="opt.count === 1"
                  />
                </td>
                <td class="mono">¥{{ periodTotalYuan(opt) }}</td>
                <td class="mono">{{ periodTotalDays(opt) }}{{ t('billing.admin.plans.dayUnit') }}</td>
                <td>
                  <button
                    class="period-del"
                    :disabled="opt.count === 1"
                    :title="opt.count === 1 ? t('billing.admin.plans.hints.periodCount1Locked') : t('billing.admin.plans.delete')"
                    @click="removePeriod(idx)"
                  >
                    <MsIcon :name="opt.count === 1 ? 'lock' : 'delete'" />
                  </button>
                </td>
              </tr>
            </tbody>
          </table>

          <ul v-if="periodErrors.length > 0" class="period-errors">
            <li v-for="(e, i) in periodErrors" :key="i">{{ e }}</li>
          </ul>
        </div>
      </div>

      <!-- ═══ Tab: 展示 ═══ -->
      <div v-show="activeTab === 'display'" class="tab-pane">
        <FormField>
          <template #label>{{ t('billing.admin.plans.fields.categoryLabel') }}<HelpTip :text="t('billing.admin.plans.hints.category')" /></template>
          <BaseInput v-model="form.category_label" :placeholder="t('billing.admin.plans.placeholders.categoryLabel')" />
        </FormField>
        <FormField>
          <template #label>{{ t('billing.admin.plans.fields.displayOrder') }}<HelpTip :text="t('billing.admin.plans.hints.displayOrder')" /></template>
          <NumberInput v-model="form.display_order" :min="0" :max="10000" />
        </FormField>
      </div>
    </div>

    <template #footer>
      <BaseButton v-if="isDirty" size="sm" @click="discardChanges">
        {{ t('common.btn.discard') }}
      </BaseButton>
      <BaseButton @click="tryClose">{{ t('common.btn.cancel') }}</BaseButton>
      <BaseButton variant="primary" :loading="saving" :disabled="!canSave" @click="doSave">
        {{ isDirty ? t('common.btn.saveDirty') : t('common.btn.save') }}
      </BaseButton>
    </template>
  </BaseModal>
</template>

<style scoped>
.editor {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}

.editor__error {
  margin-top: var(--sp-2);
}

.tab-pane {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
  padding-top: var(--sp-3);
}

.grid-2 {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--sp-4);
}

.grid-3 {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--sp-4);
}

/* OOM toggle row spans full width to avoid label-truncation in horizontal layout */
.oom-field {
  grid-column: 1 / -1;
}

/* IO RangeField: stack label and value vertically (label row, value row right-aligned). */
.io-range :deep(.range-field__header) {
  flex-direction: column;
  align-items: stretch;
  gap: 2px;
}
.io-range :deep(.range-field__value) {
  align-self: flex-end;
}

@media (max-width: 768px) {
  .grid-2, .grid-3 { grid-template-columns: 1fr; }
}

.image-row {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}

.image-row :deep(.base-select),
.image-row :deep(.base-input) {
  flex: 1;
  min-width: 0;
}

.env-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  margin-top: var(--sp-3);
  padding-bottom: var(--sp-2);
  border-bottom: 1px solid var(--bd);
}

.env-header h4 {
  margin: 0;
  font-size: var(--text-md);
  font-weight: 500;
  color: var(--t1);
}

.env-empty {
  color: var(--t3);
  font-size: var(--text-sm);
  padding: var(--sp-4);
  text-align: center;
  background: var(--bg-in);
  border-radius: var(--r-sm);
}

.env-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--sp-3) var(--sp-4);
}

@media (max-width: 768px) {
  .env-grid { grid-template-columns: 1fr; }
}

.periods {
  margin-top: var(--sp-3);
  border-top: 1px solid var(--bd);
  padding-top: var(--sp-4);
}

.periods-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--sp-3);
}

.periods-head h4 {
  margin: 0;
  font-size: var(--text-md);
  font-weight: 500;
  color: var(--t1);
}

.periods-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--text-sm);
}

.periods-table th {
  text-align: left;
  padding: var(--sp-2) var(--sp-3);
  color: var(--t2);
  font-weight: 500;
  border-bottom: 1px solid var(--bd);
}

.periods-table td {
  padding: var(--sp-2) var(--sp-3);
  border-bottom: 1px solid var(--bd);
  vertical-align: middle;
}

.periods-table tr:last-child td {
  border-bottom: none;
}

.mono {
  font-family: var(--font-mono, 'IBM Plex Mono', monospace);
  color: var(--t1);
}

.period-del {
  background: transparent;
  border: none;
  color: var(--t2);
  cursor: pointer;
  padding: var(--sp-1);
  border-radius: var(--r-xs);
  transition: background .15s ease, color .15s ease;
}

.period-del:hover:not(:disabled) {
  background: var(--bg3);
  color: var(--red);
}

.period-del:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.period-errors {
  margin: var(--sp-3) 0 0;
  padding-left: var(--sp-5);
  color: var(--red);
  font-size: var(--text-sm);
}

.period-errors li {
  margin-bottom: var(--sp-1);
}
</style>

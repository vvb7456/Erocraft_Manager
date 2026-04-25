<script setup lang="ts">
// SectionStartup — combined egg/startup/variables editor.
//
// The first row pair is the nest+egg switcher (per the doc's "no separate
// switch-egg section" rule). When the operator picks a different egg we
// reload its docker image / startup defaults / variable definitions from
// /api/admin/resources/nests/{nest}/eggs[/{egg}/variables] and reset
// dependent fields.
//
// Save behaviour:
//   - eggId changed  → destructive: confirm, then PUT /egg with the full
//     payload (nestId/eggId/environment/image/startup/skipScripts).
//   - eggId same     → split: PATCH /startup if any of image/startup/skip
//     changed, then PATCH /variables with only the changed env keys.
//
// Variable validation runs client-side via utils/eggRules. Per-field
// errors render below each input; the section also exposes a flat
// `validationErrors` list so the parent's DirtyBar can surface a count.
import { ref, computed, watch, inject, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'
import { useDirtyFormSection } from '@/composables/useDirtyForm'
import CollapsibleGroup from '@/components/ui/CollapsibleGroup.vue'
import BaseCard from '@/components/ui/BaseCard.vue'
import FormField from '@/components/form/FormField.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import BaseTextarea from '@/components/form/BaseTextarea.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import ToggleSwitch from '@/components/ui/ToggleSwitch.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import { validateVariable } from '@/utils/eggRules'
import type { AdminServerDetailResponse, DockerImageOption } from '@/types/adminServer'

defineOptions({ name: 'SectionStartup' })

const { t } = useI18n({ useScope: 'global' })
const { get, raw } = useApiFetch()
const { toast } = useToast()
const { confirm } = useConfirm()

const detail = inject<Ref<AdminServerDetailResponse | null>>('adminServerDetail')!
const serverId = inject<Ref<number | null>>('adminServerId')!
const reload = inject<() => Promise<void>>('reloadAdminServer', async () => {})

interface NestOpt { id: number; name: string }
interface EggOpt { id: number; name: string; docker_image: string; startup: string }
interface RawVarDef { name: string; env_variable: string; default_value: string; description: string; rules: string | null }
interface VarDef { name: string; envVariable: string; defaultValue: string; description: string; rules: string | null }

const CUSTOM = '__custom__'

// Loaded resource lists
const nests = ref<NestOpt[]>([])
const eggs = ref<EggOpt[]>([])

// Initial state (from server detail)
const initialNestId = ref(0)
const initialEggId = ref(0)
const initialImage = ref('')
const initialStartup = ref('')
const initialSkip = ref(false)
const initialVars = ref<Record<string, string>>({})

// Working form
const nestId = ref(0)
const eggId = ref(0)
const imageMode = ref<string>('')
const customImage = ref('')
const startup = ref('')
const skipScripts = ref(false)
const vars = ref<Record<string, string>>({})
const syncing = ref(false)

// Variable definitions for the *currently selected* egg (changes on egg swap).
const varDefs = ref<VarDef[]>([])
// Available docker_image presets (only meaningful for the original egg;
// after switching we just expose the new egg's default + Custom).
const imageOptions = computed(() => {
  const presets: DockerImageOption[] = (
    eggId.value === initialEggId.value
      ? (detail.value?.egg.dockerImages ?? [])
      : (() => {
          const e = eggs.value.find(e => e.id === eggId.value)
          return e ? [{ label: e.docker_image, value: e.docker_image }] : []
        })()
  )
  const opts = presets.map(o => ({ value: o.value, label: o.label === o.value ? o.value : `${o.label} · ${o.value}` }))
  opts.push({ value: CUSTOM, label: t('adminServer.settings.startup.imageCustomLabel') })
  return opts
})

const eggChanged = computed(() => eggId.value > 0 && eggId.value !== initialEggId.value)

function syncFromDetail() {
  const s = detail.value?.server
  const v = detail.value?.variables ?? []
  if (!s) return
  syncing.value = true
  initialNestId.value = s.nestId
  initialEggId.value = s.eggId
  initialImage.value = s.image
  initialStartup.value = s.startup
  initialSkip.value = s.skipScripts
  nestId.value = s.nestId
  eggId.value = s.eggId
  startup.value = s.startup
  skipScripts.value = s.skipScripts
  // image picker
  const presets = (detail.value?.egg.dockerImages ?? []).map(o => o.value)
  if (presets.includes(s.image)) {
    imageMode.value = s.image
    customImage.value = ''
  } else {
    imageMode.value = CUSTOM
    customImage.value = s.image
  }
  // variables: use server_variables (admin sees all)
  const baseVars: Record<string, string> = {}
  for (const item of v) baseVars[item.envVariable] = item.value
  initialVars.value = { ...baseVars }
  vars.value = { ...baseVars }
  // var defs derived from detail
  varDefs.value = v.map(item => ({
    name: item.name,
    envVariable: item.envVariable,
    defaultValue: item.defaultValue,
    description: item.description,
    rules: item.rules,
  }))
  syncing.value = false
}

// Container polls detail every 30s; the dirty-guarded sync is declared
// further down (after isDirty) to avoid TDZ.

// ── Resource loaders ─────────────────────────────────────────────
async function loadNests() {
  if (nests.value.length > 0) return
  const r = await get<{ nests: NestOpt[] }>('/api/admin/resources/nests')
  nests.value = r?.nests ?? []
}

async function loadEggs(nid: number) {
  const r = await get<{ eggs: EggOpt[] }>(`/api/admin/resources/nests/${nid}/eggs`)
  eggs.value = r?.eggs ?? []
}

// Lazy load nests on first mount + eggs for the current nest.
watch(detail, async (d) => {
  if (!d) return
  await loadNests()
  await loadEggs(d.server.nestId)
}, { immediate: true })

// Switching nests: reload eggs and clear pending egg pick (force user to
// re-select an egg under the new nest).
async function onNestChange(v: string | number | boolean | (string | number | boolean)[]) {
  if (typeof v !== 'number') return
  nestId.value = v
  await loadEggs(v)
  // If the previously selected egg doesn't belong to the new nest, reset.
  if (!eggs.value.some(e => e.id === eggId.value)) {
    eggId.value = 0
  }
}

// Switching egg: load fresh defaults + variables. We only overwrite the
// working fields (image/startup/vars) so that if the user re-selects the
// original egg we restore initial values cleanly.
async function onEggChange(v: string | number | boolean | (string | number | boolean)[]) {
  if (typeof v !== 'number') return
  eggId.value = v
  if (v === initialEggId.value) {
    // Reverted to the original egg — restore initial state.
    syncFromDetail()
    return
  }
  const egg = eggs.value.find(e => e.id === v)
  if (!egg) return
  // Pull variable defs for the new egg
  const vr = await get<{ variables: RawVarDef[] }>(
    `/api/admin/resources/nests/${nestId.value}/eggs/${v}/variables`,
  )
  const defs: VarDef[] = (vr?.variables ?? []).map(d => ({
    name: d.name,
    envVariable: d.env_variable,
    defaultValue: d.default_value,
    description: d.description,
    rules: d.rules,
  }))
  varDefs.value = defs
  const env: Record<string, string> = {}
  for (const d of defs) env[d.envVariable] = d.defaultValue
  vars.value = env
  // Reset image / startup to the new egg's defaults
  imageMode.value = egg.docker_image
  customImage.value = ''
  startup.value = egg.startup
  // skip_scripts is independent of egg
}

// ── Validation ───────────────────────────────────────────────────
const fieldErrors = computed<Record<string, string>>(() => {
  const out: Record<string, string> = {}
  for (const def of varDefs.value) {
    const val = vars.value[def.envVariable] ?? ''
    const err = validateVariable(val, def.rules)
    if (err) {
      out[def.envVariable] = t(`adminServer.settings.startup.varErrors.${err.key}`, err.params ?? {})
    }
  }
  return out
})

const validationErrors = computed<string[]>(() => {
  return Object.entries(fieldErrors.value).map(([k, msg]) => `${k}: ${msg}`)
})
defineExpose({ validationErrors })

// Publish to the parent's aggregated ref (read by AdminServerSettingsPane
// to render the DirtyBar invalid-hint and gate save).
const aggregated = inject<Ref<string[]> | null>('settingsValidationErrors', null)
watch(validationErrors, (v) => {
  if (aggregated) aggregated.value = v
}, { immediate: true })

// ── Dirty tracking ───────────────────────────────────────────────
const effectiveImage = computed(() =>
  imageMode.value === CUSTOM ? customImage.value.trim() : imageMode.value,
)

const startupSliceDirty = computed(() => (
  effectiveImage.value !== initialImage.value
  || startup.value !== initialStartup.value
  || skipScripts.value !== initialSkip.value
))

const varsSliceDirty = computed(() => {
  const a = vars.value, b = initialVars.value
  const keys = new Set([...Object.keys(a), ...Object.keys(b)])
  for (const k of keys) {
    if ((a[k] ?? '') !== (b[k] ?? '')) return true
  }
  return false
})

const isDirty = computed(() =>
  !syncing.value && (eggChanged.value || startupSliceDirty.value || varsSliceDirty.value),
)

// Now that isDirty exists, install the dirty-guarded sync. Container
// polls detail every 30s; without this guard each poll would stomp the
// user's pending edits and make DirtyBar flash.
watch(detail, () => { if (!isDirty.value) syncFromDetail() }, { immediate: true, deep: false })

function discard() { syncFromDetail() }

async function save(): Promise<boolean> {
  if (!isDirty.value || !serverId.value) return true
  if (validationErrors.value.length > 0) {
    toast(t('adminServer.settings.startup.errors.invalid', { n: validationErrors.value.length }), 'error')
    return false
  }
  if (effectiveImage.value === '') {
    toast(t('adminServer.settings.startup.errors.imageRequired'), 'error')
    return false
  }
  const sid = serverId.value

  if (eggChanged.value) {
    // Destructive: rebuilds server_variables and re-installs.
    const ok = await confirm({
      title: t('adminServer.settings.egg.confirm.title'),
      message: t('adminServer.settings.egg.confirm.message'),
      variant: 'danger',
      confirmText: t('adminServer.settings.egg.confirm.confirmText'),
    })
    if (!ok) return false
    const body = {
      nestId: nestId.value,
      eggId: eggId.value,
      environment: vars.value,
      image: effectiveImage.value,
      startup: startup.value,
      skipScripts: skipScripts.value,
    }
    const r = await raw(`/api/admin/servers/${sid}/egg`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!r) return false
  } else {
    if (startupSliceDirty.value) {
      const r = await raw(`/api/admin/servers/${sid}/startup`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          image: effectiveImage.value,
          startup: startup.value,
          skipScripts: skipScripts.value,
        }),
      })
      if (!r) return false
    }
    if (varsSliceDirty.value) {
      const changed: Record<string, string> = {}
      for (const k of Object.keys(vars.value)) {
        if ((vars.value[k] ?? '') !== (initialVars.value[k] ?? '')) {
          changed[k] = vars.value[k]
        }
      }
      if (Object.keys(changed).length > 0) {
        const r = await raw(`/api/admin/servers/${sid}/variables`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ variables: changed }),
        })
        if (!r) return false
      }
    }
  }

  toast(t('adminServer.settings.saved'), 'success')
  await reload()
  return true
}

useDirtyFormSection({ name: 'startup', isDirty, save, discard })
</script>

<template>
  <BaseCard variant="bg2" class="settings-card">
    <CollapsibleGroup :title="t('adminServer.settings.startup.title')" icon="terminal" :defaultOpen="false">
      <div class="form">
      <FormField layout="vertical" bordered>
        <template #label>{{ t('adminServer.settings.startup.nest') }}</template>
        <BaseSelect
          :modelValue="nestId"
          :options="nests.map(n => ({ value: n.id, label: n.name }))"
          searchable
          teleport
          @update:modelValue="onNestChange"
        />
      </FormField>

      <FormField
        layout="vertical"
        bordered
        :error="eggId === 0 && isDirty ? t('adminServer.settings.startup.errors.eggRequired') : undefined"
      >
        <template #label>{{ t('adminServer.settings.startup.egg') }}</template>
        <BaseSelect
          :modelValue="eggId"
          :options="eggs.map(e => ({ value: e.id, label: e.name }))"
          searchable
          teleport
          @update:modelValue="onEggChange"
        />
      </FormField>

      <FormField
        layout="vertical"
        bordered
        :error="effectiveImage === '' && isDirty ? t('adminServer.settings.startup.errors.imageRequired') : undefined"
      >
        <template #label>{{ t('adminServer.settings.startup.image') }}</template>
        <BaseSelect v-model="imageMode" :options="imageOptions" />
      </FormField>

      <FormField v-if="imageMode === CUSTOM" layout="vertical" bordered>
        <template #label>{{ t('adminServer.settings.startup.imageCustom') }}</template>
        <BaseInput v-model="customImage" placeholder="ghcr.io/..." />
      </FormField>

      <FormField layout="vertical" bordered>
        <template #label>{{ t('adminServer.settings.startup.startup') }}</template>
        <BaseTextarea v-model="startup" :rows="3" />
      </FormField>

      <FormField layout="horizontal" bordered>
        <template #label>{{ t('adminServer.settings.startup.skipScripts') }}</template>
        <ToggleSwitch v-model="skipScripts" size="sm" />
      </FormField>

      <div class="vars-head">
        <span class="muted">{{ t('adminServer.settings.startup.variables') }}</span>
      </div>
      <EmptyState
        v-if="varDefs.length === 0"
        :title="t('adminServer.settings.startup.noVariables')"
      />
      <FormField
        v-for="d in varDefs"
        :key="d.envVariable"
        layout="vertical"
        bordered
        :hint="d.description || undefined"
        :error="fieldErrors[d.envVariable]"
      >
        <template #label>
          {{ d.name }}
          <code class="env">{{ d.envVariable }}</code>
        </template>
        <BaseInput v-model="vars[d.envVariable]" :placeholder="d.defaultValue" />
      </FormField>
      </div>
    </CollapsibleGroup>
  </BaseCard>
</template>

<style scoped>
.form > * + * { margin-top: var(--sp-3); }
.muted { color: var(--t2); font-size: var(--text-sm); }
.vars-head {
  margin-top: var(--sp-4);
  padding-top: var(--sp-3);
  border-top: 1px dashed var(--bd);
}
.env {
  margin-left: var(--sp-2);
  font-family: 'IBM Plex Mono', monospace;
  font-size: var(--text-xs);
  color: var(--t3);
}
</style>

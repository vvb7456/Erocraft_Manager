<script setup lang="ts">
import { computed, inject, ref, watch, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { apiErrorMessage } from '@/composables/apiClient'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'
import { provideDirtyForm, useDirtyFormSection } from '@/composables/useDirtyForm'
import {
  deleteEgg,
  exportEggDownload,
  overwriteImportEggFile,
  updateEgg,
  type AffectedPlanWarning,
  type EggDetailOut,
  type EggUpdateIn,
} from '@/api/adminNestsEggs'
import BaseCard from '@/components/ui/BaseCard.vue'
import SectionHeader from '@/components/ui/SectionHeader.vue'
import CollapsibleGroup from '@/components/ui/CollapsibleGroup.vue'
import HelpTip from '@/components/ui/HelpTip.vue'
import FormField from '@/components/form/FormField.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import BaseTextarea from '@/components/form/BaseTextarea.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import ToggleSwitch from '@/components/ui/ToggleSwitch.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import AlertBanner from '@/components/ui/AlertBanner.vue'
import DirtyBar from '@/components/ui/DirtyBar.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import EggImagesEditor, {
  eggImageRowsToMap,
  formatEggImageValidationErrors,
  validateEggImageRows,
  type EggImageRow,
} from '@/components/nests/EggImagesEditor.vue'

defineOptions({ name: 'EggSettingsPane' })

const { t } = useI18n({ useScope: 'global' })
const router = useRouter()
const { toast } = useToast()
const { confirm } = useConfirm()

const egg = inject<Ref<EggDetailOut | null>>('eggDetail')!
const setEggDetail = inject<(next: EggDetailOut) => void>('setEggDetail')!
const setAffectedPlans = inject<(plans: AffectedPlanWarning[]) => void>('setAffectedPlans')!

interface FormState {
  name: string
  description: string
  startup: string
  dockerImages: EggImageRow[]
  force_outgoing_ip: boolean
  featuresText: string
  fileDenylistText: string
  update_url: string
  config_from: number | null
  config_stop: string
  config_startup: string
  config_files: string
  config_logs: string
}

function toLines(arr: string[] | null | undefined): string {
  return (arr || []).join('\n')
}

function parseLines(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map(s => s.trim())
    .filter(Boolean)
}

function imagesToRows(map: Record<string, string> | undefined): EggImageRow[] {
  const entries = Object.entries(map || {})
  if (!entries.length) return [{ label: 'Default', image: '' }]
  return entries.map(([label, image]) => ({ label, image }))
}

function snapshotFromEgg(e: EggDetailOut): FormState {
  return {
    name: e.name,
    description: e.description || '',
    startup: e.startup || '',
    dockerImages: imagesToRows(e.docker_images),
    force_outgoing_ip: !!e.force_outgoing_ip,
    featuresText: toLines(e.features),
    fileDenylistText: toLines(e.file_denylist),
    update_url: e.update_url || '',
    config_from: e.config_from ?? null,
    config_stop: e.config_stop || '',
    config_startup: e.config_startup || '',
    config_files: e.config_files || '',
    config_logs: e.config_logs || '',
  }
}

const emptyForm = (): FormState => ({
  name: '',
  description: '',
  startup: '',
  dockerImages: [{ label: 'Default', image: '' }],
  force_outgoing_ip: false,
  featuresText: '',
  fileDenylistText: '',
  update_url: '',
  config_from: null,
  config_stop: '',
  config_startup: '',
  config_files: '',
  config_logs: '',
})

const initial = ref<FormState>(emptyForm())
const form = ref<FormState>(emptyForm())
const imagesEditorRef = ref<InstanceType<typeof EggImagesEditor> | null>(null)
const overwriteFileInputRef = ref<HTMLInputElement | null>(null)
const overwriting = ref(false)
const exporting = ref(false)
const deleting = ref(false)

function syncFromEgg(e: EggDetailOut | null) {
  if (!e) return
  const snap = snapshotFromEgg(e)
  initial.value = JSON.parse(JSON.stringify(snap))
  form.value = JSON.parse(JSON.stringify(snap))
}

watch(egg, (e) => { syncFromEgg(e) }, { immediate: true })

const isDirty = computed(() => JSON.stringify(form.value) !== JSON.stringify(initial.value))

const isRenamingSpecial = computed(() =>
  !!egg.value?.in_special_registry && form.value.name.trim() !== egg.value.name,
)

const hasDependentConfigEggs = computed(() =>
  (egg.value?.dependent_config_eggs.length ?? 0) > 0,
)

const configFromOptions = computed(() => [
  { value: '', label: t('nests.egg.configFromNone') },
  ...(egg.value?.config_from_candidates || []).map(c => ({
    value: c.id,
    label: `${c.name} (#${c.id})`,
  })),
])

function isValidJsonObj(raw: string, allowEmpty: boolean): boolean {
  const s = raw.trim()
  if (!s) return allowEmpty
  try {
    const parsed = JSON.parse(s)
    return !!parsed && typeof parsed === 'object' && !Array.isArray(parsed)
  } catch {
    return false
  }
}

const validationErrors = computed<string[]>(() => {
  const errs: string[] = []
  if (!form.value.name.trim()) errs.push(t('nests.validation.nameRequired'))
  if (!form.value.startup.trim()) errs.push(t('nests.validation.startupRequired'))
  errs.push(...formatEggImageValidationErrors(validateEggImageRows(form.value.dockerImages), t))
  const inherits = form.value.config_from != null
  if (!inherits && !form.value.config_stop.trim()) {
    errs.push(t('nests.validation.configStopRequired'))
  }
  if (!isValidJsonObj(form.value.config_startup, inherits)) {
    errs.push(`${t('nests.egg.fields.configStartup')}: ${t('nests.egg.jsonObjectRequired')}`)
  }
  if (!isValidJsonObj(form.value.config_files, inherits)) {
    errs.push(`${t('nests.egg.fields.configFiles')}: ${t('nests.egg.jsonObjectRequired')}`)
  }
  if (!isValidJsonObj(form.value.config_logs, inherits)) {
    errs.push(`${t('nests.egg.fields.configLogs')}: ${t('nests.egg.jsonObjectRequired')}`)
  }
  return errs
})

async function save(): Promise<boolean> {
  if (!egg.value || !isDirty.value) return true
  if (validationErrors.value.length > 0) {
    toast(validationErrors.value[0]!, 'error')
    return false
  }
  const body: EggUpdateIn = {
    name: form.value.name.trim(),
    description: form.value.description.trim() || null,
    startup: form.value.startup.trim(),
    docker_images: eggImageRowsToMap(form.value.dockerImages),
    force_outgoing_ip: form.value.force_outgoing_ip,
    features: parseLines(form.value.featuresText),
    file_denylist: parseLines(form.value.fileDenylistText),
    update_url: form.value.update_url.trim() || null,
    config_from: form.value.config_from,
    config_stop: form.value.config_stop.trim() || null,
    config_startup: form.value.config_startup.trim() || null,
    config_files: form.value.config_files.trim() || null,
    config_logs: form.value.config_logs.trim() || null,
  }
  try {
    const res = await updateEgg(egg.value.id, body)
    setEggDetail(res.egg)
    syncFromEgg(res.egg)
    setAffectedPlans(res.affected_plans)
    if (res.affected_plans.length > 0) {
      toast(t('nests.egg.savedWithPlanWarnings', { n: res.affected_plans.length }), 'warning')
    } else {
      toast(t('nests.egg.saved'), 'success')
    }
    return true
  } catch (err) {
    toast(apiErrorMessage(err), 'error')
    return false
  }
}

function discard() {
  form.value = JSON.parse(JSON.stringify(initial.value))
}

const dirtyForm = provideDirtyForm()
dirtyForm.attachLeaveGuard()
useDirtyFormSection({ name: 'egg-settings', isDirty, save, discard }, dirtyForm)

async function handleExport() {
  if (!egg.value) return
  exporting.value = true
  try {
    await exportEggDownload(egg.value.id, `egg-${egg.value.id}`)
    toast(t('nests.egg.exported'), 'success')
  } catch (err) {
    toast(apiErrorMessage(err), 'error')
  } finally {
    exporting.value = false
  }
}

function triggerOverwriteImport() {
  if (!egg.value || overwriting.value) return
  overwriteFileInputRef.value?.click()
}

async function onOverwriteFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || !egg.value) return

  const ok = await confirm({
    title: t('nests.import.overwriteTitle'),
    message: t('nests.import.overwriteConfirm', { file: file.name }),
    confirmText: t('nests.import.submitOverwrite'),
  })
  if (!ok) return

  overwriting.value = true
  try {
    const res = await overwriteImportEggFile(egg.value.id, file)
    setEggDetail(res.egg)
    syncFromEgg(res.egg)
    setAffectedPlans(res.affected_plans)
    toast(t('nests.import.overwrittenOk', { name: res.egg.name }), 'success')
    if (res.affected_plans.length > 0) {
      toast(t('nests.egg.savedWithPlanWarnings', { n: res.affected_plans.length }), 'warning')
    }
  } catch (err) {
    toast(apiErrorMessage(err), 'error')
  } finally {
    overwriting.value = false
  }
}

async function handleDelete() {
  if (!egg.value) return
  const ok = await confirm({
    title: t('nests.egg.deleteTitle'),
    message: t('nests.egg.deleteMsg', { name: egg.value.name }),
    variant: 'danger',
    confirmText: t('common.btn.delete'),
  })
  if (!ok) return
  deleting.value = true
  try {
    await deleteEgg(egg.value.id)
    discard()
    toast(t('nests.egg.deleted', { name: egg.value.name }), 'success')
    await router.push({ name: 'nests', query: { tab: 'eggs' } })
  } catch (err) {
    toast(apiErrorMessage(err), 'error')
  } finally {
    deleting.value = false
  }
}
</script>

<template>
  <div v-if="egg" class="egg-settings">
    <BaseCard variant="bg2" density="compact">
      <SectionHeader icon="settings" :subtitle="t('nests.egg.sections.basicDesc')" flush>
        {{ t('nests.egg.sections.basic') }}
      </SectionHeader>

      <AlertBanner v-if="isRenamingSpecial" tone="danger" class="section-alert">
        {{ t('nests.egg.specialRenameDanger', { name: egg.name }) }}
      </AlertBanner>
      <AlertBanner v-else-if="egg.in_special_registry" tone="warning" dense class="section-alert">
        {{ t('nests.egg.specialRegistryNotice', { name: egg.name }) }}
      </AlertBanner>

      <div class="form-stack">
        <FormField :label="t('nests.egg.fields.name')" required density="compact">
          <BaseInput v-model="form.name" maxlength="191" />
        </FormField>

        <FormField :label="t('nests.egg.fields.description')" density="compact">
          <BaseTextarea v-model="form.description" :rows="3" />
        </FormField>

        <FormField required density="compact">
          <template #label>
            {{ t('nests.egg.fields.startup') }}
            <HelpTip :text="t('nests.egg.tips.startup')" />
          </template>
          <BaseTextarea v-model="form.startup" mono :rows="2" :spellcheck="false" />
        </FormField>

        <FormField :label="t('nests.egg.fields.updateUrl')" density="compact">
          <BaseInput v-model="form.update_url" placeholder="https://..." />
        </FormField>

        <FormField
          layout="horizontal"
          keep-horizontal
          control-fit
          bordered
          density="compact"
        >
          <template #label>
            {{ t('nests.egg.fields.forceOutgoingIp') }}
            <HelpTip :text="t('nests.egg.tips.forceOutgoingIp')" />
          </template>
          <ToggleSwitch v-model="form.force_outgoing_ip" size="sm" />
        </FormField>

        <div class="grid-2">
          <FormField density="compact">
            <template #label>
              {{ t('nests.egg.fields.features') }}
              <HelpTip :text="t('nests.egg.tips.onePerLine')" />
            </template>
            <BaseTextarea v-model="form.featuresText" mono :rows="3" :spellcheck="false" placeholder="eula&#10;pid_limit" />
          </FormField>

          <FormField density="compact">
            <template #label>
              {{ t('nests.egg.fields.fileDenylist') }}
              <HelpTip :text="form.config_from ? t('nests.egg.tips.fileDenylistInherited') : t('nests.egg.tips.onePerLine')" />
            </template>
            <BaseTextarea v-model="form.fileDenylistText" mono :rows="3" :spellcheck="false" />
          </FormField>
        </div>
      </div>
    </BaseCard>

    <BaseCard variant="bg2" density="compact">
      <SectionHeader icon="inventory_2" :subtitle="t('nests.egg.sections.imagesDesc')" flush>
        {{ t('nests.egg.sections.images') }}
        <template #actions>
          <BaseButton size="sm" variant="default" @click="imagesEditorRef?.addRow()">
            <MsIcon name="add" size="xs" />{{ t('nests.egg.addImage') }}
          </BaseButton>
        </template>
      </SectionHeader>

      <EggImagesEditor
        ref="imagesEditorRef"
        v-model="form.dockerImages"
        :show-header="false"
        :show-error="isDirty"
      />
    </BaseCard>

    <BaseCard variant="bg2" density="compact">
      <SectionHeader icon="data_object" :subtitle="t('nests.egg.sections.processDesc')" flush>
        {{ t('nests.egg.sections.process') }}
      </SectionHeader>

      <AlertBanner v-if="hasDependentConfigEggs" tone="info" dense class="section-alert">
        {{ t('nests.egg.dependentConfigNotice') }}
        <template v-for="(dep, idx) in egg.dependent_config_eggs" :key="dep.id">
          <span v-if="idx > 0">{{ t('common.listSep') }}</span>
          <router-link
            :to="{ name: 'egg-settings', params: { eggId: dep.id } }"
            class="inline-link"
          >
            {{ dep.name }} (#{{ dep.id }})
          </router-link>
        </template>
      </AlertBanner>

      <AlertBanner v-if="form.config_from != null" tone="info" dense class="section-alert">
        {{ t('nests.egg.configFromActiveNotice') }}
      </AlertBanner>

      <div class="form-stack">
        <div class="grid-2">
          <FormField density="compact">
            <template #label>
              {{ t('nests.egg.fields.configFrom') }}
              <HelpTip :text="hasDependentConfigEggs ? t('nests.egg.tips.configFromLocked') : t('nests.egg.tips.configFrom')" />
            </template>
            <BaseSelect
              teleport
              :disabled="hasDependentConfigEggs"
              :options="configFromOptions"
              :model-value="form.config_from ?? ''"
              @update:model-value="(v: any) => form.config_from = v === '' || v == null ? null : Number(v)"
            />
          </FormField>

          <FormField
            :label="t('nests.egg.fields.configStop')"
            :required="form.config_from == null"
            density="compact"
          >
            <BaseInput v-model="form.config_stop" placeholder="^C" maxlength="191" />
          </FormField>
        </div>

        <FormField
          :label="t('nests.egg.fields.configStartup')"
          :required="form.config_from == null"
          :error="!isValidJsonObj(form.config_startup, form.config_from != null) ? t('nests.egg.jsonObjectRequired') : undefined"
          density="compact"
        >
          <BaseTextarea v-model="form.config_startup" mono :rows="4" :spellcheck="false" />
        </FormField>

        <FormField
          :label="t('nests.egg.fields.configFiles')"
          :required="form.config_from == null"
          :error="!isValidJsonObj(form.config_files, form.config_from != null) ? t('nests.egg.jsonObjectRequired') : undefined"
          density="compact"
        >
          <BaseTextarea v-model="form.config_files" mono :rows="5" :spellcheck="false" />
        </FormField>

        <FormField
          :label="t('nests.egg.fields.configLogs')"
          :required="form.config_from == null"
          :error="!isValidJsonObj(form.config_logs, form.config_from != null) ? t('nests.egg.jsonObjectRequired') : undefined"
          density="compact"
        >
          <BaseTextarea v-model="form.config_logs" mono :rows="3" :spellcheck="false" />
        </FormField>
      </div>

      <CollapsibleGroup
        v-if="egg.config_from != null"
        :title="t('nests.egg.effectiveConfigTitle')"
        icon="visibility"
        :defaultOpen="false"
        class="effective-group"
      >
        <div class="form-stack effective-fields">
          <div class="grid-2">
            <FormField :label="t('nests.egg.fields.configStop')" density="compact">
              <BaseInput :model-value="egg.effective_config.config_stop || '—'" disabled />
            </FormField>
            <FormField :label="t('nests.egg.fields.fileDenylist')" density="compact">
              <BaseInput :model-value="egg.effective_config.file_denylist.join(', ') || '—'" disabled />
            </FormField>
          </div>
          <FormField :label="t('nests.egg.fields.configStartup')" density="compact">
            <BaseTextarea :model-value="egg.effective_config.config_startup || '{}'" mono :rows="3" disabled />
          </FormField>
          <FormField :label="t('nests.egg.fields.configFiles')" density="compact">
            <BaseTextarea :model-value="egg.effective_config.config_files || '{}'" mono :rows="4" disabled />
          </FormField>
          <FormField :label="t('nests.egg.fields.configLogs')" density="compact">
            <BaseTextarea :model-value="egg.effective_config.config_logs || '{}'" mono :rows="3" disabled />
          </FormField>
        </div>
      </CollapsibleGroup>
    </BaseCard>

    <!-- ── Import & Export ── -->
    <BaseCard variant="bg2" density="compact">
      <SectionHeader icon="swap_horiz" :subtitle="t('nests.egg.sections.transferDesc')" flush>
        {{ t('nests.egg.sections.transfer') }}
      </SectionHeader>
      <div class="transfer-actions">
        <BaseButton size="sm" variant="default" :loading="exporting" @click="handleExport">
          <MsIcon name="download" size="xs" />{{ t('nests.actions.exportJson') }}
        </BaseButton>
        <BaseButton size="sm" variant="default" :loading="overwriting" @click="triggerOverwriteImport">
          <MsIcon name="upload_file" size="xs" />{{ t('nests.actions.overwriteImport') }}
        </BaseButton>
        <input
          ref="overwriteFileInputRef"
          type="file"
          accept=".json,application/json"
          hidden
          @change="onOverwriteFileChange"
        />
      </div>
    </BaseCard>

    <!-- ── Danger zone (collapsed by default, matching HostSettingPane) ── -->
    <BaseCard variant="bg2" density="compact">
      <CollapsibleGroup
        :title="t('nests.egg.danger.title')"
        :subtitle="t('nests.egg.danger.desc')"
        icon="warning"
        :defaultOpen="false"
      >
        <div class="danger-row">
          <div class="danger-title">
            {{ t('nests.egg.deleteTitle') }}
            <HelpTip :text="t('nests.egg.danger.deleteHint')" />
          </div>
          <BaseButton size="sm" variant="danger" :loading="deleting" @click="handleDelete">
            <MsIcon name="delete" size="xs" />{{ t('nests.actions.deleteEgg') }}
          </BaseButton>
        </div>
      </CollapsibleGroup>
    </BaseCard>

    <DirtyBar
      :dirty="dirtyForm.isDirty.value"
      :saving="dirtyForm.saving.value"
      :errors="validationErrors"
      @save="dirtyForm.save"
      @discard="dirtyForm.discard"
    />
  </div>
</template>

<style scoped>
.egg-settings {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
  max-width: 960px;
  margin: 0 auto;
}
.section-alert {
  margin-bottom: var(--sp-3);
}
.form-stack {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.grid-2 {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: var(--sp-3);
}
.inline-link {
  color: inherit;
  font-weight: 600;
  text-decoration: underline;
  text-underline-offset: 2px;
}
.effective-group {
  margin-top: var(--sp-3);
  padding-top: var(--sp-2);
  border-top: 1px solid var(--bd);
}
.effective-fields {
  padding-top: var(--sp-2);
}
.transfer-actions {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}
.danger-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  padding-top: var(--sp-2);
  flex-wrap: wrap;
}
.danger-title {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--t1);
  font-size: var(--text-sm);
  font-weight: 600;
}
@media (max-width: 720px) {
  .grid-2 {
    grid-template-columns: 1fr;
  }
}
</style>

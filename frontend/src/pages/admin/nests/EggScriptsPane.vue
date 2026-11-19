<script setup lang="ts">
import { computed, inject, ref, watch, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { apiErrorMessage } from '@/composables/apiClient'
import { useToast } from '@/composables/useToast'
import { provideDirtyForm, useDirtyFormSection } from '@/composables/useDirtyForm'
import {
  updateEggScripts,
  type EggDetailOut,
  type EggScriptsUpdateIn,
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
import AlertBanner from '@/components/ui/AlertBanner.vue'
import DirtyBar from '@/components/ui/DirtyBar.vue'

defineOptions({ name: 'EggScriptsPane' })

const { t } = useI18n({ useScope: 'global' })
const { toast } = useToast()

const egg = inject<Ref<EggDetailOut | null>>('eggDetail')!
const setEggDetail = inject<(next: EggDetailOut) => void>('setEggDetail')!

interface ScriptFormState {
  copy_script_from: number | null
  script_container: string
  script_entry: string
  script_is_privileged: boolean
  script_install: string
}

const initial = ref<ScriptFormState>({
  copy_script_from: null,
  script_container: 'alpine:3.4',
  script_entry: 'ash',
  script_is_privileged: true,
  script_install: '',
})
const form = ref<ScriptFormState>({ ...initial.value })

function syncFromEgg(e: EggDetailOut | null) {
  if (!e) return
  const snap: ScriptFormState = {
    copy_script_from: e.copy_script_from ?? null,
    script_container: e.script_container || 'alpine:3.4',
    script_entry: e.script_entry || 'ash',
    script_is_privileged: !!e.script_is_privileged,
    script_install: e.script_install || '',
  }
  initial.value = { ...snap }
  form.value = { ...snap }
}

watch(egg, (e) => { syncFromEgg(e) }, { immediate: true })

const isDirty = computed(() => JSON.stringify(form.value) !== JSON.stringify(initial.value))

const hasDependentScriptEggs = computed(() =>
  (egg.value?.dependent_script_eggs.length ?? 0) > 0,
)

const copyScriptFromOptions = computed(() => [
  { value: '', label: t('nests.scripts.copyFromNone') },
  ...(egg.value?.copy_script_from_candidates || []).map(c => ({
    value: c.id,
    label: `${c.name} (#${c.id})`,
  })),
])

const validationErrors = computed<string[]>(() => {
  const errs: string[] = []
  if (!form.value.script_container.trim()) errs.push(t('nests.scripts.errors.containerRequired'))
  if (!form.value.script_entry.trim()) errs.push(t('nests.scripts.errors.entryRequired'))
  return errs
})

async function save(): Promise<boolean> {
  if (!egg.value || !isDirty.value) return true
  if (validationErrors.value.length > 0) {
    toast(validationErrors.value[0]!, 'error')
    return false
  }
  const body: EggScriptsUpdateIn = {
    copy_script_from: form.value.copy_script_from,
    script_container: form.value.script_container.trim(),
    script_entry: form.value.script_entry.trim(),
    script_is_privileged: form.value.script_is_privileged,
    script_install: form.value.script_install || null,
  }
  try {
    const updated = await updateEggScripts(egg.value.id, body)
    setEggDetail(updated)
    syncFromEgg(updated)
    toast(t('nests.scripts.saved'), 'success')
    return true
  } catch (err) {
    toast(apiErrorMessage(err), 'error')
    return false
  }
}

function discard() {
  form.value = { ...initial.value }
}

const dirtyForm = provideDirtyForm()
dirtyForm.attachLeaveGuard()
useDirtyFormSection({ name: 'egg-scripts', isDirty, save, discard }, dirtyForm)
</script>

<template>
  <div v-if="egg" class="scripts-pane">
    <BaseCard variant="bg2" density="compact">
      <SectionHeader icon="terminal" :subtitle="t('nests.scripts.subtitle')" flush>
        {{ t('nests.scripts.title') }}
      </SectionHeader>

      <AlertBanner v-if="hasDependentScriptEggs" tone="info" dense class="section-alert">
        {{ t('nests.scripts.dependentNotice') }}
        <template v-for="(dep, idx) in egg.dependent_script_eggs" :key="dep.id">
          <span v-if="idx > 0">{{ t('common.listSep') }}</span>
          <router-link
            :to="{ name: 'egg-scripts', params: { eggId: dep.id } }"
            class="inline-link"
          >
            {{ dep.name }} (#{{ dep.id }})
          </router-link>
        </template>
      </AlertBanner>

      <AlertBanner v-if="form.copy_script_from != null" tone="info" dense class="section-alert">
        {{ t('nests.scripts.copyFromActiveNotice') }}
      </AlertBanner>

      <div class="form-stack">
        <FormField density="compact">
          <template #label>
            {{ t('nests.scripts.fields.copyScriptFrom') }}
            <HelpTip :text="hasDependentScriptEggs ? t('nests.scripts.tips.copyFromLocked') : t('nests.scripts.tips.copyFrom')" />
          </template>
          <BaseSelect
            teleport
            :disabled="hasDependentScriptEggs"
            :options="copyScriptFromOptions"
            :model-value="form.copy_script_from ?? ''"
            @update:model-value="(v: any) => form.copy_script_from = v === '' || v == null ? null : Number(v)"
          />
        </FormField>

        <div class="grid-2">
          <FormField :label="t('nests.scripts.fields.container')" required density="compact">
            <BaseInput v-model="form.script_container" placeholder="alpine:3.4" maxlength="191" />
          </FormField>

          <FormField :label="t('nests.scripts.fields.entry')" required density="compact">
            <BaseInput v-model="form.script_entry" placeholder="ash" maxlength="191" />
          </FormField>
        </div>

        <FormField
          layout="horizontal"
          keep-horizontal
          control-fit
          bordered
          density="compact"
        >
          <template #label>
            {{ t('nests.scripts.fields.privileged') }}
            <HelpTip :text="t('nests.scripts.tips.privileged')" />
          </template>
          <ToggleSwitch v-model="form.script_is_privileged" size="sm" />
        </FormField>

        <FormField
          :label="t('nests.scripts.fields.installScript')"
          density="compact"
        >
          <BaseTextarea
            v-model="form.script_install"
            mono
            :rows="18"
            :spellcheck="false"
            :placeholder="t('nests.scripts.fields.installPlaceholder')"
          />
        </FormField>
      </div>

      <CollapsibleGroup
        v-if="egg.copy_script_from != null"
        :title="t('nests.scripts.effectiveTitle')"
        icon="visibility"
        :defaultOpen="false"
        class="effective-group"
      >
        <div class="form-stack effective-fields">
          <div class="grid-2">
            <FormField :label="t('nests.scripts.fields.container')" density="compact">
              <BaseInput :model-value="egg.effective_scripts.script_container || '—'" disabled />
            </FormField>
            <FormField :label="t('nests.scripts.fields.entry')" density="compact">
              <BaseInput :model-value="egg.effective_scripts.script_entry || '—'" disabled />
            </FormField>
          </div>
          <FormField :label="t('nests.scripts.fields.installScript')" density="compact">
            <BaseTextarea :model-value="egg.effective_scripts.script_install || '—'" mono :rows="10" disabled />
          </FormField>
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
.scripts-pane {
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
@media (max-width: 768px) {
  .grid-2 {
    grid-template-columns: 1fr;
  }
}
</style>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { parseRules, type ParsedRule } from '@/utils/eggRuleParser'
import { getEggMeta } from '@/config/eggRegistry'
import type { StartupVar, EggSettingsProps, EggSettingsExpose } from './types'
import FormField from '@/components/form/FormField.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import SecretInput from '@/components/ui/SecretInput.vue'
import ToggleSwitch from '@/components/ui/ToggleSwitch.vue'
import BaseCard from '@/components/ui/BaseCard.vue'

const props = defineProps<EggSettingsProps>()
const emit = defineEmits<{
  (e: 'update:dirty', dirty: boolean): void
}>()

const { t } = useI18n({ useScope: 'global' })
const { put, error: apiError } = useApiFetch()

// ── Derive visible fields ──

interface FormField_ {
  envVariable: string
  name: string
  description: string
  isEditable: boolean
  parsed: ParsedRule
}

const meta = computed(() => getEggMeta(props.eggName))

const fields = computed<FormField_[]>(() => {
  const hidden = new Set(meta.value.hiddenVars ?? [])
  return props.variables
    .filter(v => !hidden.has(v.envVariable))
    .map(v => ({
      envVariable: v.envVariable,
      name: v.name,
      description: v.description,
      isEditable: v.isEditable,
      parsed: parseRules(v.rules, v.envVariable),
    }))
})

// ── Form state ──

const form = ref<Record<string, string>>({})
const orig = ref<Record<string, string>>({})

function initForm(vars: StartupVar[]) {
  const f: Record<string, string> = {}
  for (const v of vars) {
    f[v.envVariable] = v.value ?? v.defaultValue ?? ''
  }
  form.value = { ...f }
  orig.value = { ...f }
}

watch(() => props.variables, (vars) => {
  if (vars.length) initForm(vars)
}, { immediate: true })

const isDirty = computed(() => {
  for (const key of Object.keys(form.value)) {
    if (form.value[key] !== orig.value[key]) return true
  }
  return false
})

watch(isDirty, (v) => emit('update:dirty', v))

// ── Save / Discard ──

async function save(): Promise<boolean> {
  const variables: Record<string, string> = {}
  for (const f of fields.value) {
    if (f.isEditable) {
      variables[f.envVariable] = form.value[f.envVariable] ?? ''
    }
  }
  // Also include hidden editable vars (unchanged) so they don't get wiped
  const hidden = new Set(meta.value.hiddenVars ?? [])
  for (const v of props.variables) {
    if (v.isEditable && hidden.has(v.envVariable) && !(v.envVariable in variables)) {
      variables[v.envVariable] = form.value[v.envVariable] ?? v.value ?? v.defaultValue ?? ''
    }
  }
  await put(`/api/user/servers/${props.serverId}/startup`, { variables })
  if (apiError.value) return false
  orig.value = { ...form.value }
  return true
}

function discard() {
  form.value = { ...orig.value }
}

defineExpose<EggSettingsExpose>({ save, discard })
</script>

<template>
  <div class="generic-settings">
    <BaseCard variant="bg2" class="generic-card">
      <p class="generic-desc">{{ t('serverSettings.genericDesc') }}</p>

      <FormField
        v-for="f in fields"
        :key="f.envVariable"
        :label="f.name"
        layout="horizontal"
      >
        <template v-if="f.description" #hint>{{ f.description }}</template>

        <!-- Toggle -->
        <ToggleSwitch
          v-if="f.parsed.type === 'toggle'"
          :model-value="form[f.envVariable] === 'true'"
          :disabled="!f.isEditable"
          @update:model-value="v => form[f.envVariable] = v ? 'true' : 'false'"
        />

        <!-- Select -->
        <BaseSelect
          v-else-if="f.parsed.type === 'select'"
          v-model="form[f.envVariable]"
          :options="f.parsed.options!.map(o => ({ value: o.value, label: o.label }))"
          :disabled="!f.isEditable"
        />

        <!-- Password -->
        <SecretInput
          v-else-if="f.parsed.type === 'password'"
          v-model="form[f.envVariable]"
          :disabled="!f.isEditable"
          toggleable
        />

        <!-- Text -->
        <BaseInput
          v-else
          v-model="form[f.envVariable]"
          :disabled="!f.isEditable"
        />
      </FormField>
    </BaseCard>
  </div>
</template>

<style scoped>
.generic-settings {
  max-width: 760px;
  margin-left: auto;
  margin-right: auto;
}

.generic-card {
  padding: var(--sp-2);
}

.generic-desc {
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--t1);
  margin: 0 0 var(--sp-4);
}
</style>

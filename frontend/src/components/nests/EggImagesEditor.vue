<script lang="ts">
export interface EggImageRow {
  label: string
  image: string
}

export type EggImageValidationError =
  | { code: 'empty' }
  | { code: 'incomplete' }
  | { code: 'too_long' }
  | { code: 'duplicate_label'; label: string }

export function validateEggImageRows(rows: readonly EggImageRow[]): EggImageValidationError[] {
  const errors: EggImageValidationError[] = []
  let hasComplete = false
  let hasIncomplete = false
  let hasTooLong = false
  const seenLabels = new Set<string>()
  const duplicateLabels = new Set<string>()

  for (const row of rows) {
    const label = row.label.trim()
    const image = row.image.trim()
    if (!label && !image) continue
    if (!label || !image) {
      hasIncomplete = true
    } else {
      hasComplete = true
      if (seenLabels.has(label)) {
        duplicateLabels.add(label)
      } else {
        seenLabels.add(label)
      }
    }
    if (image.length > 191) {
      hasTooLong = true
    }
  }

  if (hasIncomplete) {
    errors.push({ code: 'incomplete' })
  } else if (!hasComplete) {
    errors.push({ code: 'empty' })
  }
  if (hasTooLong) {
    errors.push({ code: 'too_long' })
  }
  for (const label of duplicateLabels) {
    errors.push({ code: 'duplicate_label', label })
  }
  return errors
}

export function formatEggImageValidationErrors(
  errors: readonly EggImageValidationError[],
  t: (key: string, params?: Record<string, unknown>) => string,
): string[] {
  return errors.map((err) => {
    switch (err.code) {
      case 'empty':
        return t('nests.validation.dockerImagesInvalid')
      case 'incomplete':
        return t('nests.validation.dockerImageIncomplete')
      case 'too_long':
        return t('nests.validation.dockerImageTooLong')
      case 'duplicate_label':
        return t('nests.validation.dockerImageDuplicateLabel', { label: err.label })
    }
  })
}

export function eggImageRowsToMap(rows: readonly EggImageRow[]): Record<string, string> {
  const out: Record<string, string> = {}
  for (const r of rows) {
    const k = r.label.trim()
    const v = r.image.trim()
    if (k && v) out[k] = v
  }
  return out
}
</script>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import BaseInput from '@/components/form/BaseInput.vue'
import FieldLabel from '@/components/form/FieldLabel.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import HelpTip from '@/components/ui/HelpTip.vue'
import MsIcon from '@/components/ui/MsIcon.vue'

defineOptions({ name: 'EggImagesEditor' })

const props = withDefaults(defineProps<{
  modelValue: EggImageRow[]
  showHeader?: boolean
  showError?: boolean
  error?: string
}>(), {
  showHeader: true,
  showError: false,
})

const emit = defineEmits<{
  'update:modelValue': [rows: EggImageRow[]]
}>()

const { t } = useI18n({ useScope: 'global' })
const touched = ref(false)

const validationErrors = computed(() => validateEggImageRows(props.modelValue))

const displayError = computed(() => {
  if (props.error) return props.error
  if (!validationErrors.value.length) return ''
  const immediate = validationErrors.value.filter(
    e => e.code === 'duplicate_label' || e.code === 'too_long',
  )
  const visible = (touched.value || props.showError) ? validationErrors.value : immediate
  if (!visible.length) return ''
  return formatEggImageValidationErrors(visible, t)[0] ?? ''
})

function updateRow(idx: number, patch: Partial<EggImageRow>) {
  touched.value = true
  const next = props.modelValue.map((row, i) => (i === idx ? { ...row, ...patch } : row))
  emit('update:modelValue', next)
}

function addRow() {
  touched.value = true
  emit('update:modelValue', [...props.modelValue, { label: '', image: '' }])
}

function removeRow(idx: number) {
  if (props.modelValue.length <= 1) return
  touched.value = true
  emit('update:modelValue', props.modelValue.filter((_, i) => i !== idx))
}

function resetTouched() {
  touched.value = false
}

defineExpose({ addRow, resetTouched })
</script>

<template>
  <div class="egg-images-editor">
    <FieldLabel v-if="showHeader" required>
      {{ t('nests.egg.fields.dockerImages') }}
      <HelpTip :text="t('nests.egg.sections.imagesDesc')" />
      <template #right>
        <BaseButton size="sm" variant="default" @click="addRow">
          <MsIcon name="add" size="xs" />{{ t('nests.egg.addImage') }}
        </BaseButton>
      </template>
    </FieldLabel>

    <div class="image-head">
      <span>{{ t('nests.egg.imageLabelCol') }}</span>
      <span>{{ t('nests.egg.imageValueCol') }}</span>
      <span />
    </div>

    <div v-for="(row, idx) in modelValue" :key="idx" class="image-row">
      <BaseInput
        :model-value="row.label"
        :placeholder="t('nests.egg.imageLabelPlaceholder')"
        @update:model-value="updateRow(idx, { label: $event })"
      />
      <BaseInput
        :model-value="row.image"
        :placeholder="t('nests.egg.imageValuePlaceholder')"
        maxlength="191"
        @update:model-value="updateRow(idx, { image: $event })"
      />
      <BaseButton
        size="sm"
        variant="danger"
        :disabled="modelValue.length <= 1"
        @click="removeRow(idx)"
      >
        <MsIcon name="delete" size="xs" />{{ t('common.btn.delete') }}
      </BaseButton>
    </div>

    <div v-if="displayError" class="field-error" role="alert">{{ displayError }}</div>
  </div>
</template>

<style scoped>
.egg-images-editor {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.image-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 2fr) auto;
  gap: var(--sp-2);
  font-size: var(--text-xs);
  color: var(--t3);
  padding: 0 2px;
}

.image-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 2fr) auto;
  gap: var(--sp-2);
  align-items: center;
}

.field-error {
  font-size: var(--hint-font, .72rem);
  line-height: 1.4;
  color: var(--red);
}

@media (max-width: 720px) {
  .image-head {
    display: none;
  }
  .image-row {
    grid-template-columns: minmax(0, 1fr) auto;
  }
  .image-row > :first-child {
    grid-column: 1 / -1;
  }
}
</style>

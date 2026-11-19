<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { apiErrorMessage } from '@/composables/apiClient'
import { useToast } from '@/composables/useToast'
import {
  createLocation,
  updateLocation,
  type LocationOut,
} from '@/api/adminNodesLocations'
import BaseModal from '@/components/ui/BaseModal.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import FormField from '@/components/form/FormField.vue'

defineOptions({ name: 'LocationEditorModal' })

const props = defineProps<{
  modelValue: boolean
  location?: LocationOut | null
  zIndex?: number
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  saved: [location: LocationOut]
}>()

const { t } = useI18n({ useScope: 'global' })
const { toast } = useToast()

const shortCode = ref('')
const longDesc = ref('')
const saving = ref(false)

const isEdit = computed(() => props.location != null)

watch(
  () => [props.modelValue, props.location],
  ([open]) => {
    if (open) {
      shortCode.value = props.location?.short ?? ''
      longDesc.value = props.location?.long ?? ''
    }
  },
)

const shortError = computed(() => {
  const s = shortCode.value.trim()
  if (s.length > 60) return t('hosts.locations.validation.shortTooLong')
  return undefined
})

const longError = computed(() => {
  if (longDesc.value.trim().length > 191) return t('hosts.locations.validation.longTooLong')
  return undefined
})

const canSubmit = computed(() => {
  const s = shortCode.value.trim()
  return s.length > 0 && !shortError.value && !longError.value && !saving.value
})

async function submit() {
  const s = shortCode.value.trim()
  if (!s) {
    toast(t('hosts.locations.validation.shortRequired'), 'error')
    return
  }
  if (!canSubmit.value) return
  saving.value = true
  try {
    const l = longDesc.value.trim() || null
    const saved = props.location
      ? await updateLocation(props.location.id, { short: s, long: l })
      : await createLocation({ short: s, long: l })
    toast(isEdit.value ? t('hosts.locations.updated') : t('hosts.locations.created'), 'success')
    emit('saved', saved)
    emit('update:modelValue', false)
  } catch (err) {
    toast(apiErrorMessage(err), 'error')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <BaseModal
    :model-value="modelValue"
    @update:model-value="emit('update:modelValue', $event)"
    :title="isEdit ? t('hosts.locations.editTitle') : t('hosts.locations.createTitle')"
    icon="public"
    size="sm"
    :z-index="zIndex"
  >
    <div class="loc-editor">
      <FormField
        :label="t('hosts.locations.fields.short')"
        :error="shortError"
        required
        density="compact"
      >
        <BaseInput
          v-model="shortCode"
          :placeholder="t('hosts.locations.fields.shortPlaceholder')"
          maxlength="60"
        />
      </FormField>

      <FormField
        :label="t('hosts.locations.fields.long')"
        :error="longError"
        density="compact"
      >
        <BaseInput
          v-model="longDesc"
          :placeholder="t('hosts.locations.fields.longPlaceholder')"
          maxlength="191"
        />
      </FormField>
    </div>

    <template #footer>
      <BaseButton variant="default" :disabled="saving" @click="emit('update:modelValue', false)">
        {{ t('common.btn.cancel') }}
      </BaseButton>
      <BaseButton variant="primary" :loading="saving" :disabled="!canSubmit" @click="submit">
        {{ isEdit ? t('common.btn.save') : t('hosts.locations.addBtn') }}
      </BaseButton>
    </template>
  </BaseModal>
</template>

<style scoped>
.loc-editor {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
</style>

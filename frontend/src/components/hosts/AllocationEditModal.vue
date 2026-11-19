<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { apiErrorMessage } from '@/composables/apiClient'
import { useToast } from '@/composables/useToast'
import { updateHostAllocation, type AllocationOut } from '@/api/adminNodesLocations'
import BaseModal from '@/components/ui/BaseModal.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import BaseTextarea from '@/components/form/BaseTextarea.vue'
import FormField from '@/components/form/FormField.vue'
import HelpTip from '@/components/ui/HelpTip.vue'

defineOptions({ name: 'AllocationEditModal' })

const props = defineProps<{
  modelValue: boolean
  hostId: number
  allocation: AllocationOut | null
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  updated: [allocation: AllocationOut]
}>()

const { t } = useI18n({ useScope: 'global' })
const { toast } = useToast()

const alias = ref('')
const notes = ref('')
const saving = ref(false)

watch(
  () => [props.modelValue, props.allocation],
  ([open]) => {
    if (open && props.allocation) {
      alias.value = props.allocation.alias || ''
      notes.value = props.allocation.notes || ''
    }
  },
)

const modalSubtitle = computed(() => {
  if (!props.allocation) return undefined
  const addr = `${props.allocation.ip}:${props.allocation.port}`
  return props.allocation.server ? `${addr} · ${props.allocation.server.name}` : addr
})

const notesTooLong = computed(() => notes.value.trim().length > 191)
const aliasTooLong = computed(() => alias.value.trim().length > 191)
const canSubmit = computed(() => !notesTooLong.value && !aliasTooLong.value && !!props.allocation)

async function submit() {
  if (!props.allocation || !canSubmit.value) return
  saving.value = true
  try {
    const updated = await updateHostAllocation(props.hostId, props.allocation.id, {
      alias: alias.value.trim() || null,
      notes: notes.value.trim() || null,
    })
    toast(t('hosts.allocations.edit.toastOk'), 'success')
    emit('updated', updated)
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
    :title="t('hosts.allocations.edit.title')"
    :subtitle="modalSubtitle"
    icon="edit"
    size="sm"
  >
    <div v-if="allocation" class="alloc-edit">
      <FormField
        :error="aliasTooLong ? t('hosts.allocations.edit.aliasTooLong') : undefined"
        density="compact"
      >
        <template #label>
          {{ t('hosts.allocations.columns.alias') }}
          <HelpTip :text="t('hosts.allocations.edit.aliasHint')" />
        </template>
        <BaseInput v-model="alias" maxlength="191" :placeholder="t('hosts.allocations.edit.aliasPlaceholder')" />
      </FormField>

      <FormField
        :label="t('hosts.allocations.columns.notes')"
        :error="notesTooLong ? t('hosts.allocations.edit.notesTooLong') : undefined"
        density="compact"
      >
        <BaseTextarea v-model="notes" :rows="3" maxlength="191" :placeholder="t('hosts.allocations.edit.notesPlaceholder')" />
      </FormField>
    </div>

    <template #footer>
      <BaseButton variant="default" :disabled="saving" @click="emit('update:modelValue', false)">
        {{ t('common.btn.cancel') }}
      </BaseButton>
      <BaseButton variant="primary" :loading="saving" :disabled="!canSubmit" @click="submit">
        {{ t('common.btn.save') }}
      </BaseButton>
    </template>
  </BaseModal>
</template>

<style scoped>
.alloc-edit {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
</style>

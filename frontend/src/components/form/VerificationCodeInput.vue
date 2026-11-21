<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseInput from '@/components/form/BaseInput.vue'

defineOptions({ name: 'VerificationCodeInput' })

withDefaults(defineProps<{
  id?: string
  modelValue: string
  disabled?: boolean
  sending?: boolean
  canSend?: boolean
  cooldownSeconds?: number
}>(), {
  disabled: false,
  sending: false,
  canSend: false,
  cooldownSeconds: 0,
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
  send: []
}>()

const { t } = useI18n({ useScope: 'global' })

function onInput(event: Event) {
  const input = event.target as HTMLInputElement | null
  if (!input) return
  const normalized = input.value.replace(/\s+/g, '').slice(0, 6)
  emit('update:modelValue', normalized)
  if (input.value !== normalized) input.value = normalized
}
</script>

<template>
  <div class="verification-code-row">
    <BaseInput
      :id="id"
      :model-value="modelValue"
      name="verification-code"
      type="text"
      inputmode="numeric"
      autocomplete="one-time-code"
      maxlength="16"
      :placeholder="t('common.verificationCode.placeholder')"
      :disabled="disabled"
      @input="onInput"
    />
    <BaseButton
      type="button"
      class="verification-code-btn"
      :loading="sending"
      :disabled="!canSend"
      @click="emit('send')"
    >
      {{
        cooldownSeconds > 0
          ? t('common.verificationCode.resendCountdown', { seconds: cooldownSeconds })
          : t('common.verificationCode.send')
      }}
    </BaseButton>
  </div>
</template>

<style scoped>
.verification-code-row {
  display: flex;
  align-items: stretch;
  gap: var(--sp-2);
}

.verification-code-row > :first-child {
  flex: 1;
  min-width: 0;
}

.verification-code-btn {
  flex-shrink: 0;
  white-space: nowrap;
}
</style>

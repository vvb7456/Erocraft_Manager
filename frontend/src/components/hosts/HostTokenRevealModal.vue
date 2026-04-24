<script setup lang="ts">
// C4 — One-time Bearer token display after a fresh host is created or the
// agent_token is rotated. Built atop SecretInput whose `@copied` event
// surfaces a toast. The value is never requestable again from the server.
import { watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useToast } from '@/composables/useToast'
import BaseModal from '@/components/ui/BaseModal.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import SecretInput from '@/components/ui/SecretInput.vue'
import FormField from '@/components/form/FormField.vue'
import HelpTip from '@/components/ui/HelpTip.vue'

defineOptions({ name: 'HostTokenRevealModal' })

const props = defineProps<{
  modelValue: boolean
  token: string
  /** Optional extra line, e.g. the host name this token belongs to. */
  info?: string
}>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()

const { t } = useI18n({ useScope: 'global' })
const { toast } = useToast()

function onCopied() {
  toast(t('hosts.tokenReveal.copied'), 'success')
}

function close() {
  emit('update:modelValue', false)
}

// ── Safety: once the modal was opened we never silently clear the caller's
// token ref — it is their responsibility to reset state when the modal
// closes (typical pattern: set token='' in the @update:modelValue handler).
watch(() => props.modelValue, () => { /* no-op; here for future side-effects */ })
</script>

<template>
  <BaseModal
    :modelValue="modelValue"
    @update:modelValue="emit('update:modelValue', $event)"
    :title="t('hosts.tokenReveal.title')"
    icon="vpn_key"
    tone="info"
    size="md"
    :closeOnOverlay="false"
    :closeOnEsc="false"
  >
    <p v-if="info" class="reveal-info">{{ info }}</p>

    <FormField layout="vertical">
      <template #label>
        {{ t('hosts.tokenReveal.label') }}
        <HelpTip :text="t('hosts.tokenReveal.subtitle')" />
      </template>
      <SecretInput
        :modelValue="token"
        readonly
        copyable
        :toggleable="false"
        :revealed="true"
        @copied="onCopied"
      />
    </FormField>

    <template #footer>
      <BaseButton variant="primary" @click="close">
        {{ t('hosts.tokenReveal.done') }}
      </BaseButton>
    </template>
  </BaseModal>
</template>

<style scoped>
.reveal-info {
  color: var(--t2);
  font-size: var(--text-sm);
  margin: 0 0 var(--sp-3);
}
</style>

<script setup lang="ts">
import { useId } from 'vue'
import MsIcon from '@/components/ui/MsIcon.vue'

export interface PaymentGatewayOption {
  code: string
  display_name: string
  icon_name: string
  logo_url: string | null
}

defineProps<{
  modelValue: string
  options: PaymentGatewayOption[]
  label: string
  disabled?: boolean
}>()

const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const groupName = useId()
</script>

<template>
  <fieldset class="gateway-list" :aria-label="label" :disabled="disabled">
    <label
      v-for="gateway in options"
      :key="gateway.code"
      class="gateway-option"
      :class="{ selected: modelValue === gateway.code }"
    >
      <img v-if="gateway.logo_url" :src="gateway.logo_url" alt="" class="gateway-logo" width="32" height="32" />
      <MsIcon v-else :name="gateway.icon_name" class="gateway-logo" size="lg" />
      <span class="gateway-name">{{ gateway.display_name }}</span>
      <input
        type="radio"
        :name="groupName"
        :value="gateway.code"
        :checked="modelValue === gateway.code"
        @change="emit('update:modelValue', gateway.code)"
      />
    </label>
  </fieldset>
</template>

<style scoped>
.gateway-list {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  min-width: 0;
  margin: 0;
  padding: 0;
  border: 0;
}
.gateway-option {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-3);
  border: 1px solid var(--bd);
  border-radius: var(--r-md);
  cursor: pointer;
  transition: border-color .15s, background .15s;
}
.gateway-list:not(:disabled) .gateway-option:not(.selected):hover {
  border-color: var(--bd-f);
}
.gateway-option.selected {
  border-color: var(--ac);
  background: color-mix(in srgb, var(--ac) 8%, transparent);
}
.gateway-logo {
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  object-fit: contain;
  color: var(--t2);
}
.gateway-name {
  flex: 1;
  min-width: 0;
  color: var(--t1);
  font-size: var(--text-base);
  font-weight: 500;
  overflow-wrap: anywhere;
}
input {
  flex-shrink: 0;
  width: 18px;
  height: 18px;
  margin: 0;
  accent-color: var(--ac);
  cursor: inherit;
}
.gateway-list:disabled .gateway-option {
  opacity: .6;
  cursor: not-allowed;
}
</style>

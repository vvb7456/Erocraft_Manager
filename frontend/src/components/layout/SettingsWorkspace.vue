<script setup lang="ts">
import { ref, watch } from 'vue'
import SettingsNavigation, { type SettingsNavItem } from './SettingsNavigation.vue'

const props = defineProps<{ items: SettingsNavItem[]; modelValue: string; label: string; disabled?: boolean; storageKey?: string; wide?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const content = ref<HTMLElement | null>(null)
watch(() => props.modelValue, () => { if (content.value) content.value.scrollTop = 0 }, { flush: 'post' })
</script>

<template>
  <div class="settings-workspace">
    <SettingsNavigation :items="items" :model-value="modelValue" :label="label" :disabled="disabled" :storage-key="storageKey" @update:model-value="emit('update:modelValue', $event)" />
    <div ref="content" class="settings-content" :class="{ 'settings-content--wide': wide }"><slot /></div>
  </div>
</template>

<style scoped>
.settings-workspace { display: grid; grid-template-columns: 184px minmax(0, 1fr); grid-template-rows: minmax(0, 1fr); gap: var(--sp-6); height: 100%; min-height: 0; }
.settings-content { min-width: 0; min-height: 0; width: 100%; max-width: 880px; overflow-y: auto; overscroll-behavior-y: contain; scrollbar-gutter: stable; padding-bottom: var(--sp-8); }
.settings-content--wide { max-width: none; }
@media (max-width: 1100px) {
  .settings-workspace { grid-template-columns: minmax(0, 1fr); grid-template-rows: auto; gap: var(--sp-4); height: auto; align-items: start; }
  .settings-content { overflow: visible; scrollbar-gutter: auto; padding-bottom: 0; }
}
</style>

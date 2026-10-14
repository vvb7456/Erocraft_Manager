<script setup lang="ts">
import { ref } from 'vue'

defineOptions({ name: 'BaseTextarea' })

withDefaults(defineProps<{
  modelValue?: string
  placeholder?: string
  rows?: number
  disabled?: boolean
  mono?: boolean
  spellcheck?: boolean
}>(), {
  rows: 3,
  spellcheck: true,
})

defineEmits<{
  'update:modelValue': [value: string]
}>()
const element = ref<HTMLTextAreaElement | null>(null)
defineExpose({ element, focus: () => element.value?.focus() })
</script>

<template>
  <textarea
    ref="element"
    :value="modelValue"
    :placeholder="placeholder"
    :rows="rows"
    :disabled="disabled"
    :spellcheck="spellcheck"
    :class="['form-textarea', { 'form-textarea--mono': mono }]"
    @input="$emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)"
  />
</template>

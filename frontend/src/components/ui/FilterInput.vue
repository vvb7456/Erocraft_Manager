<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import MsIcon from '@/components/ui/MsIcon.vue'
import BaseButton from './BaseButton.vue'

defineOptions({ name: 'FilterInput' })

const { t } = useI18n({ useScope: 'global' })
const model = defineModel<string>({ default: '' })

withDefaults(defineProps<{
  placeholder?: string
  clearable?: boolean
  ariaLabel?: string
  maxlength?: number | string
}>(), {
  placeholder: '',
  clearable: true,
})
const input = ref<HTMLInputElement | null>(null)
const focus = (options?: FocusOptions) => input.value?.focus(options)
defineExpose({ focus })

function clear() {
  model.value = ''
  focus()
}
</script>

<template>
  <div class="filter-input">
    <MsIcon name="search" size="sm" color="none" class="filter-input__icon" />
    <input
      ref="input"
      v-model="model"
      type="text"
      class="form-input filter-input__field"
      :placeholder="placeholder || t('common.filter_hint')"
      :aria-label="ariaLabel || placeholder || t('common.filter_hint')"
      :maxlength="maxlength"
    >
    <BaseButton
      v-if="clearable && model"
      class="filter-input__clear"
      variant="ghost"
      size="xs"
      square
      :aria-label="t('common.btn.clear')"
      @click="clear"
    >
      <MsIcon name="close" size="sm" color="none" />
    </BaseButton>
  </div>
</template>

<style scoped>
.filter-input {
  position: relative;
  display: flex;
  align-items: center;
  min-width: 0;
}

.filter-input__icon {
  position: absolute;
  left: 10px;
  font-size: 18px;
  color: var(--t3);
  pointer-events: none;
}

.filter-input__field {
  flex: 1 1 auto;
  min-width: 0;
  width: 100%;
  padding-left: 34px;
  padding-right: 32px;
  font-size: var(--filter-input-font, var(--input-font, .85rem));
}

.filter-input__clear {
  position: absolute;
  right: 6px;
  width: 22px;
  height: 22px;
  border: none;
  border-radius: 50%;
  background: transparent;
  color: var(--t3);
  padding: 0;
}
</style>

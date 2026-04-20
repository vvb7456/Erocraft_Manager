<script setup lang="ts">
import { useI18n } from 'vue-i18n'

defineOptions({ name: 'ToggleSwitch' })

const props = withDefaults(defineProps<{
  modelValue: boolean
  size?: 'sm' | 'md'
  disabled?: boolean
  labelOn?: string
  labelOff?: string
}>(), {
  size: 'md',
})

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const { t } = useI18n({ useScope: 'global' })

function toggle() {
  if (!props.disabled) {
    emit('update:modelValue', !props.modelValue)
  }
}
</script>

<template>
  <div
    class="seg-switch"
    :class="[`seg-switch--${size}`, { 'seg-switch--disabled': disabled }]"
    role="switch"
    :aria-checked="modelValue"
    @click="toggle"
  >
    <div class="seg-track">
      <div class="seg-slider" :class="{ 'seg-slider--on': modelValue }" />
      <span class="seg-btn" :class="{ active: !modelValue }">{{ labelOff ?? t('common.off') }}</span>
      <span class="seg-btn" :class="{ active: modelValue }">{{ labelOn ?? t('common.on') }}</span>
    </div>
  </div>
</template>

<style scoped>
.seg-switch {
  display: inline-flex;
  min-width: 0;
  width: fit-content !important;
  margin-left: auto;
}

.seg-switch--disabled {
  opacity: .5;
  pointer-events: none;
}

.seg-track {
  position: relative;
  display: grid;
  grid-template-columns: 1fr 1fr;
  border: 1px solid var(--bd);
  border-radius: var(--r-sm);
  background: var(--bg);
  overflow: hidden;
  cursor: pointer;
}

.seg-slider {
  position: absolute;
  top: 2px;
  bottom: 2px;
  width: calc(50% - 2px);
  left: 2px;
  border-radius: calc(var(--r-sm) - 2px);
  background: var(--ac);
  transition: left .2s ease;
  z-index: 0;
}

.seg-slider--on {
  left: calc(50%);
}

.seg-btn {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: inherit;
  font-weight: 600;
  cursor: pointer;
  color: var(--t3);
  transition: color .2s;
  text-align: center;
  white-space: nowrap;
  user-select: none;
}

.seg-btn.active {
  color: var(--bg);
}

.seg-btn:not(.active):hover {
  color: var(--t2);
}

/* Size: md */
.seg-switch--md .seg-track {
  height: 34px;
}
.seg-switch--md .seg-btn {
  padding: 0 16px;
  font-size: var(--text-sm);
}

/* Size: sm */
.seg-switch--sm .seg-track {
  height: 28px;
}
.seg-switch--sm .seg-btn {
  padding: 0 12px;
  font-size: var(--text-xs);
}
</style>

<script setup lang="ts">
import { computed, ref } from 'vue'
import MsIcon from './MsIcon.vue'

defineOptions({ name: 'TabSwitcher' })
export interface TabItem {
  key: string
  label: string
  icon?: string
  iconColor?: string
  badge?: string | number
  disabled?: boolean
  align?: 'right'
}
const props = defineProps<{ tabs: TabItem[]; modelValue: string }>()
const emit = defineEmits<{ 'update:modelValue': [key: string] }>()
const root = ref<HTMLElement | null>(null)
const firstRightIndex = computed(() => props.tabs.findIndex(tab => tab.align === 'right'))
function selectTab(tab: TabItem) {
  if (!tab.disabled && props.modelValue !== tab.key) emit('update:modelValue', tab.key)
}
function onKeydown(event: KeyboardEvent, index: number) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  const direction = event.key === 'ArrowLeft' || event.key === 'End' ? -1 : 1
  const length = props.tabs.length
  const start = event.key === 'Home' ? 0 : event.key === 'End' ? length - 1 : index + direction
  for (let offset = 0; offset < length; offset++) {
    const next = (start + offset * direction + length) % length
    const tab = props.tabs[next]
    if (tab && !tab.disabled) {
      root.value?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[next]?.focus()
      selectTab(tab)
      return
    }
  }
}
</script>

<template>
  <div ref="root" class="tab-switcher">
    <div class="tab-switcher__tabs" role="tablist">
      <button v-for="(tab, index) in tabs" :key="tab.key" type="button" role="tab" class="tab-switcher__tab"
        :class="{ 'tab-switcher__tab--active': modelValue === tab.key, 'tab-switcher__tab--right-first': index === firstRightIndex }"
        :disabled="tab.disabled" :aria-selected="modelValue === tab.key" :tabindex="modelValue === tab.key ? 0 : -1"
        @click="selectTab(tab)" @keydown="onKeydown($event, index)">
        <MsIcon v-if="tab.icon" :name="tab.icon" :color="tab.iconColor" size="sm" />
        <span>{{ tab.label }}</span><span v-if="tab.badge" class="tab-switcher__badge">{{ tab.badge }}</span>
      </button>
    </div>
    <div v-if="$slots.default" class="tab-switcher__extra"><slot /></div>
  </div>
</template>

<style scoped>
.tab-switcher { display: inline-flex; align-items: center; width: 100%; min-width: 0; min-height: 38px; gap: var(--sp-2); }
.tab-switcher__tabs { display: flex; align-items: center; gap: 4px; min-width: 0; overflow-x: auto; scrollbar-width: none; }
.tab-switcher__tabs::-webkit-scrollbar { display: none; }
.tab-switcher__tab { display: inline-flex; align-items: center; gap: 6px; flex-shrink: 0; padding: 6px 12px; border: 0; border-radius: var(--r-sm); background: none; color: var(--t2); font: inherit; font-size: var(--text-base); font-weight: 500; white-space: nowrap; cursor: pointer; transition: background .15s, color .15s; }
.tab-switcher__tab:hover { color: var(--t1); background: color-mix(in srgb, var(--t1) 6%, transparent); }
.tab-switcher__tab--active, .tab-switcher__tab--active:hover { color: var(--t1); background: color-mix(in srgb, var(--ac) 12%, transparent); font-weight: 600; }
.tab-switcher__tab--active :deep(.ms) { color: var(--ac); }
.tab-switcher__tab:focus-visible { outline: 2px solid var(--ac); outline-offset: -2px; }
.tab-switcher__tab:disabled { opacity: .4; cursor: not-allowed; }
.tab-switcher__tab--right-first { margin-left: auto; }
.tab-switcher__badge { color: var(--bg); background: var(--ac); border-radius: var(--r-pill); padding: 1px 6px; font-size: var(--text-xs); }
.tab-switcher__extra { display: flex; align-items: center; gap: var(--sp-2); margin-left: auto; }
.tab-switcher__tab :deep(.ms) { font-size: 18px; }
</style>

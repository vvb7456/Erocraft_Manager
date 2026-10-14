<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import MsIcon from '@/components/ui/MsIcon.vue'

export interface SettingsNavItem {
  key: string
  label: string
  icon?: string
  children?: SettingsNavItem[]
}
const props = defineProps<{ items: SettingsNavItem[]; modelValue: string; label: string; disabled?: boolean; storageKey?: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const menuOpen = ref(false)
const expanded = ref(new Set<string>())
let initialized = false

function persist() {
  if (!props.storageKey) return
  try { localStorage.setItem(`settings-nav:${props.storageKey}`, JSON.stringify([...expanded.value])) } catch { /* Storage may be unavailable. */ }
}
const entries = computed(() => {
  const result: (SettingsNavItem & { ancestors: string[]; visible: boolean })[] = []
  function add(items: SettingsNavItem[], ancestors: string[] = []) {
    for (const item of items) {
      result.push({ ...item, ancestors, visible: ancestors.every(key => expanded.value.has(key)) })
      if (item.children) add(item.children, [...ancestors, item.key])
    }
  }
  add(props.items)
  return result
})
const current = computed(() => entries.value.find(item => item.key === props.modelValue))
const visibleEntries = computed(() => entries.value.filter(item => item.visible))

watch([() => props.items, () => props.modelValue], () => {
  if (initialized) return
  if (props.storageKey) {
    try {
      const saved = JSON.parse(localStorage.getItem(`settings-nav:${props.storageKey}`) || 'null')
      if (Array.isArray(saved)) {
        expanded.value = new Set(saved.filter(key => typeof key === 'string'))
        initialized = true
        return
      }
    } catch { /* Storage may be unavailable. */ }
  }
  if (current.value) {
    expanded.value = new Set(current.value.ancestors)
    initialized = true
    persist()
  }
}, { immediate: true })

function select(item: SettingsNavItem) {
  if (props.disabled) return
  if (item.children?.length) {
    if (expanded.value.has(item.key)) expanded.value.delete(item.key)
    else expanded.value.add(item.key)
    persist()
  } else if (item.key !== props.modelValue) emit('update:modelValue', item.key)
}
</script>

<template>
  <nav class="settings-navigation" :aria-label="label">
    <button class="navigation-mobile-toggle" type="button" :aria-expanded="menuOpen" :disabled="disabled" @click="menuOpen = !menuOpen">
      <span>{{ current?.label || label }}</span><MsIcon :name="menuOpen ? 'expand_less' : 'expand_more'" size="sm" />
    </button>
    <div class="navigation-items" :class="{ 'navigation-items--open': menuOpen }">
      <button v-for="item in visibleEntries" :key="item.key" type="button" class="navigation-item"
        :class="{ 'navigation-item--active': item.key === modelValue, 'navigation-item--parent': current?.ancestors.includes(item.key), 'navigation-item--nested': item.ancestors.length > 0 }"
        :style="{ '--depth': item.ancestors.length }" :title="item.label" :disabled="disabled"
        :aria-current="item.key === modelValue ? 'page' : undefined" :aria-expanded="item.children?.length ? expanded.has(item.key) : undefined"
        @click="select(item)">
        <MsIcon v-if="item.icon" :name="item.icon" size="sm" class="navigation-icon" />
        <span class="navigation-label">{{ item.label }}</span>
        <MsIcon v-if="item.children?.length" name="chevron_right" size="xs" class="navigation-arrow" :class="{ 'navigation-arrow--open': expanded.has(item.key) }" />
      </button>
    </div>
  </nav>
</template>

<style scoped>
.settings-navigation { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
.navigation-items { display: flex; flex-direction: column; flex: 1; min-height: 0; gap: 2px; overflow-y: auto; overscroll-behavior-y: contain; scrollbar-width: thin; scrollbar-gutter: stable; padding-bottom: var(--sp-8); }
.navigation-item, .navigation-mobile-toggle { display: flex; align-items: center; gap: 8px; width: 100%; min-width: 0; padding: 10px 12px; border: 0; border-radius: var(--r-sm); background: none; color: var(--t2); font: inherit; font-size: var(--text-base); line-height: 1.4; text-align: left; cursor: pointer; transition: background .15s, color .15s; }
.navigation-item { flex-shrink: 0; }
.navigation-item--nested { padding-left: calc(12px + var(--depth) * 14px); font-size: var(--text-sm); }
.navigation-label { min-width: 0; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.navigation-icon, .navigation-arrow { flex-shrink: 0; color: inherit; }
.navigation-arrow { opacity: .65; transition: transform .15s; }
.navigation-arrow--open { transform: rotate(90deg); }
.navigation-item:hover, .navigation-mobile-toggle:hover { background: var(--bg3); color: var(--t1); }
.navigation-item--parent { color: var(--t1); }
.navigation-item--active, .navigation-item--active:hover { color: var(--ac); background: color-mix(in srgb, var(--ac) 10%, transparent); font-weight: 600; }
.navigation-item:focus-visible, .navigation-mobile-toggle:focus-visible { outline: 2px solid var(--ac); outline-offset: -2px; }
.navigation-item:disabled, .navigation-mobile-toggle:disabled { opacity: .6; cursor: default; }
.navigation-mobile-toggle { display: none; }
@media (max-width: 1100px) {
  .navigation-mobile-toggle { display: flex; justify-content: space-between; border: 1px solid var(--bd); background: var(--bg2); }
  .navigation-items { display: none; flex: none; max-height: 50dvh; margin-top: var(--sp-2); border: 1px solid var(--bd); border-radius: var(--r-md); padding: var(--sp-2); scrollbar-gutter: auto; }
  .navigation-items--open { display: flex; }
}
@media (prefers-reduced-motion: reduce) { .navigation-arrow { transition: none; } }
</style>

<script setup lang="ts">
import { computed, nextTick, ref, useId, watch } from 'vue'
import { autoUpdate, flip, offset, shift, size, useFloating } from '@floating-ui/vue'
import { useI18n } from 'vue-i18n'
import MsIcon from '../ui/MsIcon.vue'

defineOptions({ name: 'BaseSelect' })

export interface SelectOption {
  value: string | number | boolean
  label: string
  disabled?: boolean
}
type Value = SelectOption['value']

const props = withDefaults(defineProps<{
  modelValue: Value | Value[]
  options: (SelectOption | Value | Record<string, Value>)[]
  valueKey?: string
  labelKey?: string
  placeholder?: string
  displayText?: string
  searchable?: boolean
  searchPlaceholder?: string
  emptyText?: string
  disabled?: boolean
  size?: 'default' | 'sm'
  fit?: boolean
  teleport?: boolean
  prefix?: string
  multiple?: boolean
  ariaLabel?: string
}>(), {
  valueKey: 'value',
  labelKey: 'label',
  placeholder: '',
  displayText: '',
  searchable: false,
  searchPlaceholder: '',
  emptyText: '',
  size: 'default',
  teleport: true,
  prefix: '',
})

const emit = defineEmits<{
  'update:modelValue': [value: Value | Value[]]
  change: [value: Value | Value[]]
}>()
const { t } = useI18n({ useScope: 'global' })
const id = useId()
const rootRef = ref<HTMLElement | null>(null)
const triggerRef = ref<HTMLButtonElement | null>(null)
const panelRef = ref<HTMLElement | null>(null)
const searchRef = ref<HTMLInputElement | null>(null)
const listRef = ref<HTMLElement | null>(null)
const open = ref(false)
const search = ref('')
const highlightIdx = ref(-1)

const { floatingStyles } = useFloating(triggerRef, panelRef, {
  open,
  strategy: computed(() => props.teleport ? 'fixed' : 'absolute'),
  placement: 'bottom-start',
  whileElementsMounted: autoUpdate,
  middleware: [
    offset(4),
    flip({ padding: 8 }),
    shift({ padding: 8 }),
    size({ padding: 8, apply({ rects, availableWidth, availableHeight, elements }) {
      Object.assign(elements.floating.style, {
        width: `${Math.min(rects.reference.width, Math.max(0, availableWidth))}px`,
        maxHeight: `${Math.max(0, availableHeight)}px`,
      })
    } }),
  ],
})

const normalizedOptions = computed<SelectOption[]>(() => props.options.map(option => {
  if (typeof option !== 'object') return { value: option, label: String(option) }
  const entry = option as Record<string, Value>
  return {
    value: entry[props.valueKey] ?? entry.value ?? entry.id ?? entry.name ?? '',
    label: String(entry[props.labelKey] ?? entry.label ?? entry.name ?? entry.display_name ?? entry[props.valueKey] ?? ''),
    disabled: !!entry.disabled,
  }
}))
const filteredOptions = computed(() => {
  const query = props.searchable ? search.value.toLocaleLowerCase() : ''
  return normalizedOptions.value.filter(option => !query || `${option.label} ${option.value}`.toLocaleLowerCase().includes(query))
})
const selectedOptions = computed(() => normalizedOptions.value.filter(option => isSelected(option.value)))
const selectedLabel = computed(() => props.displayText || selectedOptions.value.map(option => option.label).join(', ') || props.placeholder)
const isPlaceholder = computed(() => !props.displayText && !selectedOptions.value.length)
const label = computed(() => props.ariaLabel || props.prefix || props.placeholder || selectedLabel.value)
const activeId = computed(() => highlightIdx.value < 0 ? undefined : `${id}-option-${highlightIdx.value}`)

function isSelected(value: Value) {
  return Array.isArray(props.modelValue) ? props.modelValue.includes(value) : props.modelValue === value
}
function resetHighlight() {
  const selected = filteredOptions.value.findIndex(option => !option.disabled && isSelected(option.value))
  highlightIdx.value = selected >= 0 ? selected : filteredOptions.value.findIndex(option => !option.disabled)
}
async function openPanel(last = false) {
  if (props.disabled) return
  search.value = ''
  open.value = true
  await nextTick()
  if (!open.value) return
  resetHighlight()
  if (last) moveHighlight('End')
  const target = searchRef.value || listRef.value
  target?.focus({ preventScroll: true })
  scrollToHighlighted()
}
function close(restoreFocus = false) {
  open.value = false
  if (restoreFocus) triggerRef.value?.focus({ preventScroll: true })
}
function select(option: SelectOption) {
  if (props.disabled || option.disabled) return
  let value: Value | Value[] = option.value
  if (props.multiple) {
    const current = Array.isArray(props.modelValue) ? props.modelValue : []
    value = current.includes(option.value) ? current.filter(item => item !== option.value) : [...current, option.value]
  }
  emit('update:modelValue', value)
  emit('change', value)
  if (!props.multiple) close(true)
}
function moveHighlight(key: string) {
  const enabled = filteredOptions.value.flatMap((option, index) => option.disabled ? [] : [index])
  if (!enabled.length) return
  const current = enabled.indexOf(highlightIdx.value)
  const next = key === 'Home' ? 0 : key === 'End' ? enabled.length - 1
    : (current + (key === 'ArrowUp' ? -1 : 1) + enabled.length) % enabled.length
  highlightIdx.value = enabled[next]!
}
function onTriggerKeydown(event: KeyboardEvent) {
  if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
  event.preventDefault()
  void openPanel(event.key === 'ArrowUp')
}
function onPanelKeydown(event: KeyboardEvent) {
  if (event.isComposing || event.keyCode === 229) return
  if (event.key === 'Tab') { close(true); return }
  if (event.key === 'Escape') { event.preventDefault(); close(true); return }
  if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
    if (props.searchable && ['Home', 'End'].includes(event.key)) return
    event.preventDefault()
    moveHighlight(event.key)
  } else if (event.key === 'Enter' || (!props.searchable && event.key === ' ')) {
    event.preventDefault()
    const option = filteredOptions.value[highlightIdx.value]
    if (option) select(option)
  }
}

watch(filteredOptions, resetHighlight)
watch(() => props.disabled, disabled => { if (disabled) close() })
function scrollToHighlighted() {
  const list = listRef.value
  const item = list?.querySelector<HTMLElement>(`[id="${activeId.value}"]`)
  if (!list || !item) return
  // Scroll only the options, never the surrounding form or modal.
  if (item.offsetTop < list.scrollTop) list.scrollTop = item.offsetTop
  else if (item.offsetTop + item.offsetHeight > list.scrollTop + list.clientHeight) list.scrollTop = item.offsetTop + item.offsetHeight - list.clientHeight
}
watch(highlightIdx, scrollToHighlighted, { flush: 'post' })
watch(open, (visible, _, onCleanup) => {
  if (!visible) return
  const outside = (event: Event) => {
    const target = event.target as Node
    if (!rootRef.value?.contains(target) && !panelRef.value?.contains(target)) close()
  }
  document.addEventListener('pointerdown', outside)
  document.addEventListener('focusin', outside)
  onCleanup(() => {
    document.removeEventListener('pointerdown', outside)
    document.removeEventListener('focusin', outside)
  })
})
</script>

<template>
  <div ref="rootRef" class="base-select" :class="[`base-select--${size}`, { 'base-select--fit': fit, 'base-select--open': open, 'base-select--disabled': disabled }]">
    <button ref="triggerRef" type="button" class="base-select__trigger" :disabled="disabled" :aria-label="label"
      aria-haspopup="listbox" :aria-expanded="open" :aria-controls="`${id}-list`" :title="selectedLabel"
      @click="open ? close() : openPanel()" @keydown="onTriggerKeydown">
      <span class="base-select__text text-truncate" :class="{ 'base-select__text--ph': isPlaceholder, 'base-select__text--muted': !multiple && selectedOptions[0]?.disabled }"><span v-if="prefix" class="base-select__prefix">{{ prefix }}</span>{{ selectedLabel }}</span>
      <MsIcon name="expand_more" size="sm" color="var(--t3)" />
    </button>
    <Teleport to="body" :disabled="!teleport">
      <Transition name="bs-fade">
        <div v-if="open" ref="panelRef" class="base-select__panel" :class="`base-select__panel--${size}`" :style="floatingStyles" @keydown.stop="onPanelKeydown">
          <input v-if="searchable" ref="searchRef" v-model="search" type="text" class="base-select__search"
            role="combobox" aria-autocomplete="list" :aria-label="label" :aria-expanded="open" :aria-controls="`${id}-list`" :aria-activedescendant="activeId"
            :placeholder="searchPlaceholder || t('common.filter_hint')" />
          <div :id="`${id}-list`" ref="listRef" class="base-select__list" role="listbox" :aria-label="label" :aria-multiselectable="multiple || undefined"
            :tabindex="searchable ? undefined : -1" :aria-activedescendant="searchable ? undefined : activeId">
            <div v-if="!filteredOptions.length" class="base-select__empty">{{ emptyText || t('common.no_matches') }}</div>
            <div v-for="(option, index) in filteredOptions" :id="`${id}-option-${index}`" :key="String(option.value)" class="base-select__item"
              :class="{ 'base-select__item--sel': isSelected(option.value), 'base-select__item--hl': index === highlightIdx, 'base-select__item--disabled': option.disabled }"
              role="option" :aria-selected="isSelected(option.value)" :aria-disabled="option.disabled" :title="option.label"
              @click="select(option)" @mouseenter="highlightIdx = index">
              <MsIcon v-if="multiple" :name="isSelected(option.value) ? 'check_box' : 'check_box_outline_blank'" size="sm" :color="isSelected(option.value) ? 'var(--ac)' : 'var(--t3)'" />
              <span class="base-select__item-label">{{ option.label }}</span>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.base-select { position: relative; width: var(--control-width, 100%); min-width: 0; max-width: 100%; }
.base-select--fit { --control-width: 140px; flex-shrink: 0; }
.base-select--disabled { opacity: .55; }
.base-select__trigger {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-1);
  width: 100%;
  min-width: 0;
  padding: 8px 12px;
  border: 1px solid var(--bd);
  border-radius: var(--r-sm);
  background: var(--bg);
  color: var(--t1);
  font-family: inherit;
  font-size: .85rem;
  text-align: left;
  cursor: pointer;
  transition: border-color .15s;
}
.base-select--sm .base-select__trigger { padding: 4px 8px; min-height: 28px; border-radius: var(--r-xs); font-size: .82rem; }
.base-select__trigger:hover:not(:disabled), .base-select--open .base-select__trigger { border-color: var(--ac); }
.base-select__trigger:focus-visible { outline: 2px solid var(--ac); outline-offset: 2px; }
.base-select__trigger:disabled { cursor: default; }
.base-select__text { flex: 1; min-width: 0; }
.base-select__text--ph, .base-select__text--muted, .base-select__prefix { color: var(--t3); }
.base-select__prefix { margin-right: 2px; }
.base-select__panel {
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: var(--bg2);
  border: 1px solid var(--bd);
  border-radius: var(--r-sm);
  box-shadow: var(--sh);
  z-index: 9999;
  overflow: hidden;
}
.base-select__search { flex-shrink: 0; width: 100%; min-width: 0; padding: 8px 10px; border: 0; border-bottom: 1px solid var(--bd); border-radius: 0; background: var(--bg); color: var(--t1); font: inherit; font-size: .85rem; outline: none; }
.base-select__list { position: relative; min-height: 0; max-height: 240px; overflow-y: auto; overscroll-behavior: contain; padding: var(--sp-1); outline: none; }
.base-select__item { display: flex; align-items: center; gap: var(--sp-2); min-width: 0; padding: 6px 12px; border-radius: var(--r-xs); font-size: .85rem; color: var(--t1); cursor: pointer; }
.base-select__panel--sm .base-select__item { padding: 4px 8px; font-size: .82rem; }
.base-select__item-label { flex: 1; min-width: 0; white-space: normal; overflow-wrap: anywhere; line-height: 1.5; }
.base-select__item:hover, .base-select__item--hl { background: var(--bg3); }
.base-select__item--sel { color: var(--ac); font-weight: 500; }
.base-select__item--disabled { opacity: .45; cursor: default; }
.base-select__empty { padding: 12px 10px; text-align: center; color: var(--t3); font-size: .82rem; }
.bs-fade-enter-active, .bs-fade-leave-active { transition: opacity .12s; }
.bs-fade-enter-from, .bs-fade-leave-to { opacity: 0; }
</style>

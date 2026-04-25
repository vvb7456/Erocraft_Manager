<script setup lang="ts">
// AllocationsChipInput — token-style port editor for the admin server
// settings page. Replaces the picker modal: each selected allocation is
// rendered as a chip, the first chip is the primary (cannot be removed
// individually), and a trailing search input drops into a teleported
// dropdown of available ports on the same node.
//
// The component is *purely presentational* w.r.t. persistence — it owns
// no API calls. Parent (SectionAllocations) maps the chip list back into
// add/remove/primary diffs against the server's current allocation set.
//
// Constraints enforced inline:
//   - The list cannot be reduced to zero chips. Removing the primary chip
//     still requires at least one extra to remain (so primary + extras > 0
//     at all times). The save guard in the parent additionally refuses to
//     persist an empty list.
//   - The first chip is always rendered with a "primary" badge.
import { computed, nextTick, onBeforeUnmount, onMounted, ref, type CSSProperties } from 'vue'
import { useI18n } from 'vue-i18n'
import MsIcon from '@/components/ui/MsIcon.vue'
import type { ServerAllocationSummary } from '@/types/adminServer'

defineOptions({ name: 'AllocationsChipInput' })

const props = defineProps<{
  // Currently selected allocations in render order. First entry = primary.
  modelValue: ServerAllocationSummary[]
  // Pool of available allocations on the same node (currently unassigned
  // panel rows + this server's existing allocations not in modelValue).
  available: ServerAllocationSummary[]
}>()

const emit = defineEmits<{
  'update:modelValue': [value: ServerAllocationSummary[]]
}>()

const { t } = useI18n({ useScope: 'global' })

const rootRef = ref<HTMLElement | null>(null)
const inputRef = ref<HTMLInputElement | null>(null)
const panelRef = ref<HTMLElement | null>(null)
const open = ref(false)
const search = ref('')
const teleportStyle = ref<CSSProperties>({})

function format(a: ServerAllocationSummary) {
  const label = a.ipAlias ? `${a.ipAlias} (${a.ip})` : a.ip
  return `${label}:${a.port}`
}

const selectedIds = computed(() => new Set(props.modelValue.map(a => a.id)))

const candidates = computed(() => {
  const q = search.value.trim().toLowerCase()
  return props.available.filter(a => {
    if (selectedIds.value.has(a.id)) return false
    if (!q) return true
    return format(a).toLowerCase().includes(q)
      || (a.notes ?? '').toLowerCase().includes(q)
  })
})

function add(a: ServerAllocationSummary) {
  emit('update:modelValue', [...props.modelValue, a])
  search.value = ''
  nextTick(() => inputRef.value?.focus())
}

function removeAt(idx: number) {
  if (props.modelValue.length <= 1) return  // never empty
  const next = props.modelValue.slice()
  next.splice(idx, 1)
  emit('update:modelValue', next)
}

function focusInput() {
  inputRef.value?.focus()
  open.value = true
  updatePanelPos()
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'Backspace' && search.value === '' && props.modelValue.length > 1) {
    // Remove the last chip on backspace, never the primary alone
    removeAt(props.modelValue.length - 1)
    return
  }
  if (e.key === 'Escape') {
    open.value = false
  }
}

function onClickOutside(e: MouseEvent) {
  const target = e.target as Node
  if (rootRef.value?.contains(target)) return
  if (panelRef.value?.contains(target)) return
  open.value = false
}

function updatePanelPos() {
  const r = rootRef.value?.getBoundingClientRect()
  if (!r) return
  teleportStyle.value = {
    position: 'fixed',
    top: `${r.bottom + 4}px`,
    left: `${r.left}px`,
    minWidth: `${r.width}px`,
    maxWidth: `${Math.max(r.width, 360)}px`,
    zIndex: 9999,
  }
}

function onScrollOrResize() {
  if (open.value) updatePanelPos()
}

onMounted(() => {
  document.addEventListener('click', onClickOutside)
  window.addEventListener('scroll', onScrollOrResize, true)
  window.addEventListener('resize', onScrollOrResize)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', onClickOutside)
  window.removeEventListener('scroll', onScrollOrResize, true)
  window.removeEventListener('resize', onScrollOrResize)
})
</script>

<template>
  <div ref="rootRef" class="aci" :class="{ 'aci--open': open }" @click="focusInput">
    <span
      v-for="(a, idx) in modelValue"
      :key="a.id"
      class="chip"
      :class="{ 'chip--primary': idx === 0 }"
    >
      <span v-if="idx === 0" class="chip__tag">{{ t('adminServer.settings.allocations.primary') }}</span>
      <span class="chip__addr">{{ format(a) }}</span>
      <button
        v-if="modelValue.length > 1"
        type="button"
        class="chip__close"
        :aria-label="t('adminServer.settings.allocations.remove')"
        @click.stop="removeAt(idx)"
      >
        <MsIcon name="close" size="xxs" />
      </button>
    </span>
    <input
      ref="inputRef"
      v-model="search"
      class="aci__input"
      :placeholder="modelValue.length === 0 ? t('adminServer.settings.allocations.add') : ''"
      @focus="open = true; updatePanelPos()"
      @keydown="onKey"
      @click.stop
    />

    <Teleport to="body">
      <div
        v-if="open"
        ref="panelRef"
        class="aci__panel"
        :style="teleportStyle"
      >
        <div v-if="candidates.length === 0" class="aci__empty">
          {{ t('adminServer.settings.allocations.picker.noAvailable') }}
        </div>
        <div
          v-for="a in candidates"
          :key="a.id"
          class="aci__opt"
          @click.stop="add(a)"
        >
          <span class="aci__opt-addr">{{ format(a) }}</span>
          <span v-if="a.notes" class="aci__opt-notes">{{ a.notes }}</span>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.aci {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-1);
  padding: var(--sp-1) var(--sp-2);
  min-height: 36px;
  align-items: center;
  border: 1px solid var(--bd);
  border-radius: var(--r-sm);
  background: var(--bg);
  cursor: text;
  transition: border-color .15s;
}
.aci--open {
  border-color: var(--bd-f);
}
.chip {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1);
  padding: 2px var(--sp-2);
  background: var(--bg3);
  border: 1px solid var(--bd);
  border-radius: var(--r-pill);
  font-size: var(--text-xs);
  color: var(--t1);
  font-family: 'IBM Plex Mono', monospace;
}
.chip--primary {
  border-color: var(--bd-f);
  background: color-mix(in srgb, var(--ac) 15%, var(--bg3));
}
.chip__tag {
  font-family: 'IBM Plex Sans', sans-serif;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: .03em;
  color: var(--ac);
  text-transform: uppercase;
}
.chip__addr {
  white-space: nowrap;
}
.chip__close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  padding: 0;
  margin-left: 2px;
  border: none;
  background: transparent;
  color: var(--t3);
  cursor: pointer;
  border-radius: 50%;
}
.chip__close:hover {
  color: var(--red);
  background: color-mix(in srgb, var(--red) 18%, transparent);
}
.aci__input {
  flex: 1;
  min-width: 80px;
  border: none;
  background: transparent;
  color: var(--t1);
  outline: none;
  font-size: var(--text-sm);
  font-family: inherit;
  padding: 4px 0;
}
.aci__input::placeholder { color: var(--t3); }

.aci__panel {
  background: var(--bg2);
  border: 1px solid var(--bd);
  border-radius: var(--r-sm);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.35);
  max-height: 280px;
  overflow-y: auto;
  padding: var(--sp-1);
}
.aci__empty {
  padding: var(--sp-3);
  text-align: center;
  color: var(--t3);
  font-size: var(--text-sm);
}
.aci__opt {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-2) var(--sp-3);
  border-radius: var(--r-xs);
  cursor: pointer;
  font-size: var(--text-sm);
  color: var(--t1);
}
.aci__opt:hover {
  background: var(--bg4);
}
.aci__opt-addr {
  font-family: 'IBM Plex Mono', monospace;
  flex: 1;
  min-width: 0;
}
.aci__opt-notes {
  color: var(--t3);
  font-size: var(--text-xs);
}
</style>

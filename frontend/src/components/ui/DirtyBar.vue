<script setup lang="ts">
// DirtyBar — floating bottom save bar that appears when a form has
// unsaved changes. Mirrors the original SettingsPage pattern and is the
// canonical "you have unsaved changes" UI across the admin and user surfaces.
//
// Default usage:
//   <DirtyBar
//     :dirty="isDirty"
//     :saving="submitting"
//     @save="save"
//     @discard="discard"
//   />
//
// Slots (all optional, defaults preserved):
//   #hint     — left side. Defaults to <MsIcon edit/> + `hint` prop ||
//               i18n settings.unsavedHint. Override when the page needs
//               a custom message, chip cluster, or error list.
//   #extra    — middle. Empty by default; flexes to fill space. Use for
//               chip clusters / inline diagnostics that should sit
//               between the hint and the action buttons.
//   #actions  — right side. Defaults to a Discard + Save BaseButton pair
//               wired to the @discard / @save events. Override to add
//               extra buttons (e.g. EmailTemplates' Save current vs Save
//               all) or to remove the save button when validation fails.
//
// Props:
//   dirty: boolean             — when false the bar is unmounted (slide out).
//   saving?: boolean           — passed to default Save button as :loading.
//   hint?: string              — overrides default hint text.
//   saveText?, discardText?    — override default button labels.
//   layout?: 'row' | 'stack'   — 'row' (default) horizontal; 'stack' lays
//                                children vertically (useful for error lists).
//   confirmBeforeUnload?: bool — attach a window 'beforeunload' listener
//                                while dirty=true; the browser pops its
//                                native "leave?" dialog. Cleaned up on
//                                unmount or when dirty becomes false.
//
// The bar is teleported to <body> so it floats above page chrome and is
// unaffected by parent overflow.
import { onBeforeUnmount, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import BaseButton from '@/components/ui/BaseButton.vue'
import MsIcon from '@/components/ui/MsIcon.vue'

defineOptions({ name: 'DirtyBar' })

const props = withDefaults(defineProps<{
  dirty: boolean
  saving?: boolean
  hint?: string
  saveText?: string
  discardText?: string
  layout?: 'row' | 'stack'
  confirmBeforeUnload?: boolean
}>(), {
  saving: false,
  layout: 'row',
  confirmBeforeUnload: false,
})

defineEmits<{
  (e: 'save'): void
  (e: 'discard'): void
}>()

const { t } = useI18n({ useScope: 'global' })

// Browser-level "you have unsaved changes" guard. Opt-in because most
// pages rely on the in-app ConfirmDialog leave-guard (provided by
// useDirtyForm.attachLeaveGuard) and only want the native prompt as a
// last-resort safety net (e.g. tab close, hard reload).
function onBeforeUnload(e: BeforeUnloadEvent) {
  if (props.dirty) {
    e.preventDefault()
    e.returnValue = ''
  }
}
watch(
  () => props.confirmBeforeUnload && props.dirty,
  (active, prev) => {
    if (typeof window === 'undefined') return
    if (active && !prev) window.addEventListener('beforeunload', onBeforeUnload)
    if (!active && prev) window.removeEventListener('beforeunload', onBeforeUnload)
  },
  { immediate: true },
)
onBeforeUnmount(() => {
  if (typeof window !== 'undefined') {
    window.removeEventListener('beforeunload', onBeforeUnload)
  }
})
</script>

<template>
  <Teleport to="body">
    <Transition name="db-slide-up">
      <div v-if="dirty" class="db" :class="`db--${layout}`">
        <slot name="hint">
          <span class="db__text">
            <MsIcon name="edit" />
            {{ hint || t('settings.unsavedHint') }}
          </span>
        </slot>
        <slot name="extra" />
        <slot name="actions">
          <div class="db__actions">
            <BaseButton size="sm" :disabled="saving" @click="$emit('discard')">
              {{ discardText || t('settings.discardBtn') }}
            </BaseButton>
            <BaseButton variant="primary" size="sm" :loading="saving" @click="$emit('save')">
              {{ saveText || t('settings.save') }}
            </BaseButton>
          </div>
        </slot>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.db {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 1000;
  padding: var(--sp-3) var(--sp-5);
  background: var(--bg3);
  border-top: 1px solid var(--bd);
  box-shadow: 0 -4px 20px rgba(0, 0, 0, 0.35);
}
.db--row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
}
.db--stack {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
/* In row layout the #extra slot (between hint and actions) expands to
   fill remaining space, so chips / error lists naturally take the centre. */
.db--row > :slotted(*:not(:first-child):not(:last-child)) {
  flex: 1;
  min-width: 0;
}
.db__text {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--amber);
}
.db__text :deep(.ms-icon) { font-size: 1.1rem; }
.db__actions {
  display: flex;
  gap: var(--sp-2);
  flex-shrink: 0;
}

.db-slide-up-enter-active,
.db-slide-up-leave-active {
  transition: transform .24s ease, opacity .24s ease;
}
.db-slide-up-enter-from,
.db-slide-up-leave-to {
  transform: translateY(100%);
  opacity: 0;
}
</style>

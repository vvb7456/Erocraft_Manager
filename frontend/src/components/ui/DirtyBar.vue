<script setup lang="ts">
/**
 * DirtyBar — floating bottom save bar.
 *
 * Three slots (all optional):
 *   #hint    — left: hint text / error summary. Default: edit icon + `hint` prop.
 *   #extra   — middle: chips, diagnostics. Fills remaining space.
 *   #actions — right: save/discard buttons. Default: Discard + Save pair.
 *
 * Props:
 *   dirty, saving, hint, saveText, discardText, layout ('row'|'stack'),
 *   confirmBeforeUnload
 */
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

defineEmits<{ save: []; discard: [] }>()

const { t } = useI18n({ useScope: 'global' })

function onBeforeUnload(e: BeforeUnloadEvent) {
  if (props.dirty) { e.preventDefault(); e.returnValue = '' }
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
  if (typeof window !== 'undefined') window.removeEventListener('beforeunload', onBeforeUnload)
})
</script>

<template>
  <Teleport to="body">
    <Transition name="db-slide-up">
      <div v-if="dirty" class="db" :class="layout === 'stack' ? 'db--stack' : 'db--row'">
        <div class="db__hint">
          <slot name="hint">
            <MsIcon name="edit" class="db__hint-icon" />
            <span>{{ hint || t('settings.unsavedHint') }}</span>
          </slot>
        </div>
        <div v-if="$slots.extra" class="db__extra">
          <slot name="extra" />
        </div>
        <div class="db__actions">
          <slot name="actions">
            <BaseButton size="sm" :disabled="saving" @click="$emit('discard')">
              {{ discardText || t('settings.discardBtn') }}
            </BaseButton>
            <BaseButton variant="primary" size="sm" :loading="saving" @click="$emit('save')">
              {{ saveText || t('settings.save') }}
            </BaseButton>
          </slot>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.db {
  position: fixed; bottom: 0; left: 0; right: 0; z-index: 1000;
  padding: var(--sp-3) var(--sp-5);
  background: var(--bg3);
  border-top: 1px solid var(--bd);
  box-shadow: 0 -4px 20px rgba(0, 0, 0, 0.35);
}
.db--row {
  display: flex; align-items: center; justify-content: space-between;
  gap: var(--sp-3);
}
.db--stack {
  display: flex; flex-direction: column;
  gap: var(--sp-2);
}
.db--stack .db__hint { width: 100%; }
.db--stack .db__actions { justify-content: flex-end; }

/* Hint */
.db__hint {
  display: flex; align-items: center; gap: var(--sp-2);
  font-size: var(--text-sm); font-weight: 500; color: var(--amber);
  flex-shrink: 0;
}
.db__hint-icon { font-size: 1.1rem; flex-shrink: 0; }

/* Extra (middle) */
.db__extra {
  flex: 1 1 auto; min-width: 0;
  display: flex; align-items: center; gap: var(--sp-2);
  overflow: hidden;
}
.db--stack .db__extra { width: 100%; flex: none; }

/* Actions */
.db__actions {
  display: flex; gap: var(--sp-2); flex-shrink: 0;
  margin-left: auto;
}

/* Transition */
.db-slide-up-enter-active,
.db-slide-up-leave-active { transition: transform .24s ease, opacity .24s ease; }
.db-slide-up-enter-from,
.db-slide-up-leave-to { transform: translateY(100%); opacity: 0; }
</style>

<script setup lang="ts">
/**
 * DirtyBar — floating bottom save bar.
 *
 * The bar has two visual modes driven by `errors`:
 *   * Clean   (errors empty)        → amber edit icon + `hint` text, Save enabled.
 *   * Invalid (errors non-empty)    → red error icon + `errorsLabel` (or auto
 *                                     "N issues"), error chips in the middle,
 *                                     Save disabled.
 *
 * Three slots (all optional, override defaults):
 *   #hint    — left header. Slot props: { hasErrors, errors }. Default: see above.
 *   #extra   — middle. Default: per-error chip when invalid, empty otherwise.
 *              SettingsPage uses this for clickable tab-switch chips.
 *   #actions — right: save/discard buttons. Default: Discard + Save pair.
 *
 * Props:
 *   dirty, saving, errors, errorsLabel, hint, saveText, discardText,
 *   layout ('row'|'stack'), confirmBeforeUnload.
 */
import { computed, onBeforeUnmount, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import BaseButton from '@/components/ui/BaseButton.vue'
import MsIcon from '@/components/ui/MsIcon.vue'

defineOptions({ name: 'DirtyBar' })

const props = withDefaults(defineProps<{
  dirty: boolean
  saving?: boolean
  /**
   * Validation errors. When non-empty, Save is disabled and the bar enters
   * invalid mode. Strings should be short, already-localised user-facing
   * labels (used directly as chip text by the default #extra slot).
   */
  errors?: readonly string[]
  /** Override the auto-generated "N issues" header in invalid mode. */
  errorsLabel?: string
  hint?: string
  saveText?: string
  discardText?: string
  layout?: 'row' | 'stack'
  confirmBeforeUnload?: boolean
}>(), {
  saving: false,
  errors: () => [],
  layout: 'row',
  confirmBeforeUnload: false,
})

defineEmits<{ save: []; discard: [] }>()

const hasErrors = computed(() => props.errors.length > 0)

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
      <div v-if="dirty" class="db" :class="[layout === 'stack' ? 'db--stack' : 'db--row', hasErrors && 'db--invalid']">
        <div class="db__hint" :class="hasErrors && 'db__hint--error'">
          <slot name="hint" :has-errors="hasErrors" :errors="errors">
            <template v-if="hasErrors">
              <MsIcon name="error" class="db__hint-icon" />
              <span>{{ errorsLabel || t('settings.validate.header', { n: errors.length }) }}</span>
            </template>
            <template v-else>
              <MsIcon name="edit" class="db__hint-icon" />
              <span>{{ hint || t('settings.unsavedHint') }}</span>
            </template>
          </slot>
        </div>
        <div v-if="$slots.extra || hasErrors" class="db__extra">
          <slot name="extra" :has-errors="hasErrors" :errors="errors">
            <span v-for="(e, i) in errors" :key="i" class="db__err-chip">{{ e }}</span>
          </slot>
        </div>
        <div class="db__actions">
          <slot name="actions">
            <BaseButton size="sm" :disabled="saving" @click="$emit('discard')">
              {{ discardText || t('settings.discardBtn') }}
            </BaseButton>
            <BaseButton variant="primary" size="sm" :loading="saving" :disabled="hasErrors" @click="$emit('save')">
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
.db__hint--error { color: var(--red); }
.db__hint-icon { font-size: 1.1rem; flex-shrink: 0; }

/* Extra (middle) */
.db__extra {
  flex: 1 1 auto; min-width: 0;
  display: flex; align-items: center; gap: var(--sp-2);
  overflow: hidden;
}
.db--stack .db__extra { width: 100%; flex: none; }

/* Default error chips */
.db__err-chip {
  display: inline-flex; align-items: center; gap: var(--sp-1);
  font-size: var(--text-xs); white-space: nowrap;
  color: var(--t2);
}
.db__err-chip + .db__err-chip::before { content: ' · '; color: var(--t3); }

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

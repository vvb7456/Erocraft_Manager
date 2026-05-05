<script setup lang="ts">
import { watch, ref, onUnmounted } from 'vue'
import { lockBodyScroll, unlockBodyScroll } from './BaseModal.vue'

const props = withDefaults(defineProps<{
  modelValue: boolean
  title?: string
}>(), { title: '' })

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const inner = ref<HTMLElement>()

function close() { emit('update:modelValue', false) }

function onOverlay(e: MouseEvent) {
  if (e.target === e.currentTarget) close()
}

/* Lock body scroll via the shared BaseModal counter so that closing a
   BottomSheet stacked on top of an open BaseModal (or vice versa) does not
   prematurely re-enable page scrolling. (Audit FM4.) */
let isLocked = false
watch(() => props.modelValue, (open) => {
  if (open && !isLocked) { lockBodyScroll(); isLocked = true }
  else if (!open && isLocked) { unlockBodyScroll(); isLocked = false }
})
onUnmounted(() => { if (isLocked) { unlockBodyScroll(); isLocked = false } })
</script>

<template>
  <Teleport to="body">
    <Transition name="bs">
      <div v-if="modelValue" class="bs-overlay" @click="onOverlay">
        <div ref="inner" class="bs-panel" role="dialog" aria-modal="true">
          <div class="bs-handle" @click="close"><span /></div>
          <div v-if="title" class="bs-title">{{ title }}</div>
          <div class="bs-body">
            <slot />
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style>
.bs-overlay {
  position: fixed;
  inset: 0;
  z-index: 9000;
  background: rgba(0,0,0,.35);
  display: flex;
  align-items: flex-end;
  justify-content: center;
}

.bs-panel {
  width: 100%;
  max-width: 480px;
  max-height: 80dvh;
  background: var(--bg2);
  border-radius: var(--r-lg) var(--r-lg) 0 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  -webkit-overflow-scrolling: touch;
  padding-bottom: env(safe-area-inset-bottom);
}

.bs-handle {
  display: flex;
  justify-content: center;
  padding: 10px 0 4px;
  cursor: pointer;
}
.bs-handle span {
  width: 36px;
  height: 4px;
  border-radius: 2px;
  background: var(--bd);
}

.bs-title {
  font-size: .9rem;
  font-weight: 600;
  padding: 0 var(--sp-4) var(--sp-3);
  color: var(--t1);
}

.bs-body {
  padding: 0 var(--sp-4) var(--sp-4);
}

/* transitions */
.bs-enter-active, .bs-leave-active { transition: opacity .2s; }
.bs-enter-active .bs-panel, .bs-leave-active .bs-panel { transition: transform .25s ease-out; }
.bs-enter-from { opacity: 0; }
.bs-enter-from .bs-panel { transform: translateY(100%); }
.bs-leave-to { opacity: 0; }
.bs-leave-to .bs-panel { transform: translateY(100%); }
</style>

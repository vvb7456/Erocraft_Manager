<script setup lang="ts">
import { watch, ref, nextTick, onUnmounted } from 'vue'
import { lockBodyScroll, unlockBodyScroll } from './BaseModal.vue'

const props = withDefaults(defineProps<{
  modelValue: boolean
  title?: string
  persistent?: boolean
}>(), {
  title: '',
  persistent: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const overlayRef = ref<HTMLElement>()
const inner = ref<HTMLElement>()
const mouseDownOnOverlay = ref(false)

function close() {
  if (props.persistent) return
  emit('update:modelValue', false)
}

function onOverlayMousedown(e: MouseEvent) {
  mouseDownOnOverlay.value = e.target === e.currentTarget
}

function onOverlayClick(e: MouseEvent) {
  if (e.target === e.currentTarget && mouseDownOnOverlay.value && !props.persistent) close()
  mouseDownOnOverlay.value = false
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && !props.persistent) {
    e.stopPropagation()
    close()
  }
}

/* Lock body scroll via the shared BaseModal counter so that closing a
   BottomSheet stacked on top of an open BaseModal (or vice versa) does not
   prematurely re-enable page scrolling. (Audit FM4.) */
let isLocked = false
watch(() => props.modelValue, (open) => {
  if (open) {
    if (!isLocked) { lockBodyScroll(); isLocked = true }
    nextTick(() => overlayRef.value?.focus({ preventScroll: true }))
  } else if (isLocked) {
    unlockBodyScroll()
    isLocked = false
  }
}, { immediate: true })
onUnmounted(() => { if (isLocked) { unlockBodyScroll(); isLocked = false } })
</script>

<template>
  <Teleport to="body">
    <Transition name="bs">
      <div
        v-if="modelValue"
        ref="overlayRef"
        class="bs-overlay"
        tabindex="-1"
        @mousedown="onOverlayMousedown"
        @click="onOverlayClick"
        @keydown="onKeydown"
      >
        <div ref="inner" class="bs-panel" :class="{ 'bs-panel--persistent': persistent }" role="dialog" aria-modal="true">
          <div v-if="!persistent || title" class="bs-header">
            <div v-if="!persistent" class="bs-handle" @click="close"><span /></div>
            <div v-if="title" class="bs-title">{{ title }}</div>
          </div>
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
  outline: none;
}

.bs-panel {
  width: 100%;
  max-width: 480px;
  max-height: calc(100svh - var(--app-header-h, 0px));
  background: var(--bg2);
  border-radius: var(--r-lg) var(--r-lg) 0 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  padding-bottom: env(safe-area-inset-bottom);
}

.bs-panel--persistent {
  padding-top: var(--sp-4);
}

/* Header is a non-scrolling flex item; only .bs-body scrolls. Avoids
   iOS Safari's broken position:sticky inside flex+overflow containers. */
.bs-header {
  flex-shrink: 0;
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
  flex: 1;
  overflow-y: auto;
  overscroll-behavior: contain;
  -webkit-overflow-scrolling: touch;
  touch-action: pan-y;
}

/* transitions */
.bs-enter-active, .bs-leave-active { transition: opacity .2s; }
.bs-enter-active .bs-panel, .bs-leave-active .bs-panel { transition: transform .25s ease-out; }
.bs-enter-from { opacity: 0; }
.bs-enter-from .bs-panel { transform: translateY(100%); }
.bs-leave-to { opacity: 0; }
.bs-leave-to .bs-panel { transform: translateY(100%); }
</style>

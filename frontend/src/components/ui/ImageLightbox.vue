<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { lockBodyScroll, unlockBodyScroll } from './BaseModal.vue'
import MsIcon from './MsIcon.vue'

defineOptions({ name: 'ImageLightbox' })

const props = withDefaults(defineProps<{
  modelValue: boolean
  src: string
  alt?: string
  failed?: boolean
}>(), {
  alt: '',
  failed: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  error: []
}>()

const { t } = useI18n({ useScope: 'global' })

const overlayRef = ref<HTMLElement | null>(null)
const loadError = ref(false)
const mouseDownOnOverlay = ref(false)
const isFailed = computed(() => props.failed || loadError.value)

let hasBodyLock = false
let previousFocus: HTMLElement | null = null

function close() {
  emit('update:modelValue', false)
}

function onOverlayMousedown(e: MouseEvent) {
  mouseDownOnOverlay.value = e.target === e.currentTarget
}

function onOverlayClick(e: MouseEvent) {
  if (e.target === e.currentTarget && mouseDownOnOverlay.value) close()
  mouseDownOnOverlay.value = false
}

function onImgError() {
  loadError.value = true
  emit('error')
}

watch(() => props.src, () => {
  loadError.value = false
})

watch(() => props.modelValue, async (open, wasOpen) => {
  if (open) {
    loadError.value = false
    if (!hasBodyLock) { lockBodyScroll(); hasBodyLock = true }
    if (!wasOpen) {
      previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    }
    await nextTick()
    overlayRef.value?.focus({ preventScroll: true })
  } else {
    if (hasBodyLock) { unlockBodyScroll(); hasBodyLock = false }
    if (wasOpen) {
      const target = previousFocus?.isConnected ? previousFocus : null
      previousFocus = null
      await nextTick()
      target?.focus({ preventScroll: true })
    }
  }
}, { immediate: true })

onUnmounted(() => {
  if (hasBodyLock) { unlockBodyScroll(); hasBodyLock = false }
})
</script>

<template>
  <Teleport to="body">
    <Transition name="lightbox">
      <div
        v-if="modelValue"
        ref="overlayRef"
        class="lightbox-overlay"
        role="dialog"
        aria-modal="true"
        :aria-label="alt || t('support.viewImage')"
        tabindex="-1"
        @mousedown="onOverlayMousedown"
        @click="onOverlayClick"
        @keydown.esc.stop.prevent="close"
      >
        <button
          type="button"
          class="lightbox-close"
          :aria-label="t('common.btn.close')"
          :title="t('common.btn.close')"
          @click="close"
        >
          <MsIcon name="close" size="md" color="none" />
        </button>

        <span v-if="isFailed" class="lightbox-unavailable" role="img" :aria-label="alt">
          <MsIcon name="image_not_supported" size="lg" />
        </span>
        <img
          v-else
          class="lightbox-img"
          :src="src"
          :alt="alt"
          @error="onImgError"
        />
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.lightbox-overlay {
  position: fixed;
  inset: 0;
  z-index: 9500;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: max(16px, env(safe-area-inset-top)) max(12px, env(safe-area-inset-right)) max(16px, env(safe-area-inset-bottom)) max(12px, env(safe-area-inset-left));
  background: rgba(0, 0, 0, .9);
  outline: none;
}

.lightbox-close {
  position: absolute;
  top: max(12px, env(safe-area-inset-top));
  right: max(12px, env(safe-area-inset-right));
  z-index: 1;
  width: 40px;
  height: 40px;
  display: grid;
  place-items: center;
  padding: 0;
  border: 1px solid rgba(255, 255, 255, .16);
  border-radius: 50%;
  background: rgba(20, 24, 28, .65);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  color: #fff;
  cursor: pointer;
  transition: background .15s ease;
}

.lightbox-close:hover {
  background: rgba(40, 46, 54, .85);
}

.lightbox-close:focus-visible {
  outline: 2px solid var(--ac);
  outline-offset: 2px;
}

.lightbox-img {
  display: block;
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
}

.lightbox-unavailable {
  display: grid;
  place-items: center;
  width: 72px;
  height: 72px;
  border-radius: var(--r-lg);
  background: rgba(255, 255, 255, .08);
  color: rgba(255, 255, 255, .65);
}

.lightbox-enter-active,
.lightbox-leave-active {
  transition: opacity .18s ease;
}

.lightbox-enter-from,
.lightbox-leave-to {
  opacity: 0;
}
</style>

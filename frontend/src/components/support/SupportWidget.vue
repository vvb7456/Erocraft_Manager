<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useSupportStore } from '@/stores/support'
import { useApiFetch } from '@/composables/useApiFetch'
import { lockBodyScroll, unlockBodyScroll } from '@/components/ui/BaseModal.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import LoadingCenter from '@/components/ui/LoadingCenter.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import SupportChat from './SupportChat.vue'
import SupportConnectionBadge from './SupportConnectionBadge.vue'

const { t } = useI18n()
const support = useSupportStore()
const route = useRoute()
const { post, handleError } = useApiFetch()
const cid = ref<number | null>(null)
const loading = ref(false)
const panel = ref<HTMLElement | null>(null)
const launcher = ref<HTMLButtonElement | null>(null)
const media = window.matchMedia('(max-width: 600px), (max-width: 1000px) and (pointer: coarse)')
const mobile = ref(media.matches)
const viewportHeight = ref(window.visualViewport?.height || window.innerHeight)
const viewportTop = ref(window.visualViewport?.offsetTop || 0)
const viewportBottom = ref(Math.max(0, window.innerHeight - viewportHeight.value - viewportTop.value))
const viewportStyle = computed(() => ({ '--chat-viewport-height': `${viewportHeight.value}px`, '--chat-viewport-bottom': `${viewportBottom.value}px` }))
let alive = true
let locked = false
let previousFocus: HTMLElement | null = null
async function load() {
  if (loading.value || cid.value) return
  loading.value = true
  try {
    const data = await post<{ id: number }>('/api/support/conversation')
    if (data && alive) cid.value = data.id
  } finally { loading.value = false }
}
function updateViewport() {
  viewportHeight.value = window.visualViewport?.height || window.innerHeight
  viewportTop.value = window.visualViewport?.offsetTop || 0
  viewportBottom.value = Math.max(0, window.innerHeight - viewportHeight.value - viewportTop.value)
}
function updateMedia() { mobile.value = media.matches }
function navigate() { if (mobile.value) support.open = false }
function trapFocus(event: KeyboardEvent) {
  if (!mobile.value || event.key !== 'Tab' || !panel.value) return
  const elements = [...panel.value.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], textarea:not([disabled]), [tabindex="0"]')].filter(el => el.getClientRects().length)
  const first = elements[0], last = elements[elements.length - 1]
  if (!first || !last) { event.preventDefault(); return }
  if (event.shiftKey && (document.activeElement === first || document.activeElement === panel.value)) { event.preventDefault(); last.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
}
watch([() => support.open, mobile], async ([open, isMobile], previous) => {
  const wasOpen = previous?.[0] || false
  if (open && isMobile && !locked) { lockBodyScroll(); locked = true }
  else if ((!open || !isMobile) && locked) { unlockBodyScroll(); locked = false }
  if (open) {
    if (!wasOpen) previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    updateViewport()
    void load().catch(handleError)
    await nextTick()
    if (alive && support.open && !wasOpen) panel.value?.focus({ preventScroll: true })
  } else if (wasOpen) {
    const target = previousFocus?.isConnected && !panel.value?.contains(previousFocus) ? previousFocus : launcher.value
    previousFocus = null
    await nextTick()
    if (alive && !support.open) target?.focus({ preventScroll: true })
  }
}, { immediate: true })
watch(() => route.fullPath, navigate)
onMounted(() => {
  media.addEventListener('change', updateMedia)
  window.addEventListener('resize', updateViewport)
  window.visualViewport?.addEventListener('resize', updateViewport)
  window.visualViewport?.addEventListener('scroll', updateViewport)
})
onBeforeUnmount(() => {
  alive = false
  if (locked) unlockBodyScroll()
  media.removeEventListener('change', updateMedia)
  window.removeEventListener('resize', updateViewport)
  window.visualViewport?.removeEventListener('resize', updateViewport)
  window.visualViewport?.removeEventListener('scroll', updateViewport)
})
</script>

<template>
  <Teleport to="body">
    <div class="support-widget" :class="{ 'is-mobile': mobile, 'is-open': support.open }" :style="viewportStyle">
      <div class="chat-surface">
      <Transition name="chat-content">
        <section v-show="support.open" id="support-chat-panel" ref="panel" class="chat-panel" :inert="!support.open" role="dialog" :aria-modal="mobile ? 'true' : 'false'" aria-labelledby="support-chat-title" tabindex="-1" @keydown="trapFocus" @keydown.esc.stop="support.open = false">
          <header class="chat-header">
            <span class="support-avatar"><MsIcon name="support_agent" size="sm" /></span>
            <div class="heading"><h2 id="support-chat-title">{{ t('support.title') }}</h2></div>
            <SupportConnectionBadge />
            <BaseButton variant="ghost" size="sm" square class="header-action" :aria-label="t('support.minimize')" :title="t('support.minimize')" @click="support.open = false"><MsIcon name="close_fullscreen" size="sm" /></BaseButton>
          </header>
          <SupportChat v-if="cid" :conversation-id="cid" :active="support.open" :compact="mobile && viewportHeight < 480" @navigate="navigate" />
          <LoadingCenter v-else-if="loading" class="widget-loading" />
          <div v-else class="widget-error"><MsIcon name="chat_bubble" size="lg" /><BaseButton size="sm" @click="load">{{ t('support.retry') }}</BaseButton></div>
        </section>
      </Transition>
      </div>
      <button ref="launcher" type="button" class="chat-launcher" :disabled="support.open" :aria-hidden="support.open ? 'true' : undefined" :aria-label="t('support.title')" :title="t('support.title')" :aria-expanded="support.open" aria-controls="support-chat-panel" @click="support.open = true">
        <MsIcon name="chat_bubble" size="md" color="none" />
        <span v-if="support.unread" class="unread-count" :aria-label="t('support.newMessages', { count: support.unread })">{{ support.unread > 99 ? '99+' : support.unread }}</span>
      </button>
    </div>
  </Teleport>
</template>

<style scoped>
.support-widget { --chat-open-width: min(408px, calc(100vw - 48px)); --chat-open-height: min(640px, calc(100dvh - 48px - env(safe-area-inset-bottom))); position: fixed; right: max(24px, env(safe-area-inset-right)); bottom: calc(24px + env(safe-area-inset-bottom)); width: 56px; height: 56px; border-radius: 28px; box-shadow: 0 6px 24px #0003; z-index: 900; transition: width .36s cubic-bezier(.22, 1, .36, 1), height .36s cubic-bezier(.22, 1, .36, 1), border-radius .3s ease, right .36s cubic-bezier(.22, 1, .36, 1), bottom .36s cubic-bezier(.22, 1, .36, 1), box-shadow .3s ease; }
.support-widget.is-open { width: var(--chat-open-width); height: var(--chat-open-height); border-radius: 24px; box-shadow: 0 24px 80px #0004, 0 4px 16px #0001; }
.chat-surface { position: absolute; inset: 0; overflow: hidden; border-radius: inherit; background: var(--ac-solid); transition: background .22s ease; }
.is-open .chat-surface { background: var(--bg2); }
.chat-launcher { position: absolute; inset: 0; display: grid; place-items: center; width: 100%; height: 100%; padding: 0; border: 0; border-radius: inherit; background: transparent; color: var(--t-inv); cursor: pointer; opacity: 1; visibility: visible; transition: opacity .14s ease .14s; }
.chat-launcher:hover { background: #ffffff0d; }
.is-open .chat-launcher { opacity: 0; visibility: hidden; pointer-events: none; transition: opacity .08s ease, visibility 0s .08s; }
.unread-count { position: absolute; right: -5px; top: -6px; display: grid; place-items: center; min-width: 22px; height: 22px; padding: 0 5px; border: 2px solid var(--bg2); border-radius: var(--r-lg); background: var(--red); color: var(--t-inv); font-size: var(--text-xs); font-weight: 700; }
.chat-panel { position: absolute; bottom: 0; right: 0; display: flex; flex-direction: column; width: var(--chat-open-width); height: var(--chat-open-height); min-height: 0; overflow: hidden; border: 1px solid var(--bd); border-radius: inherit; outline: none; }
.chat-header { flex-shrink: 0; display: flex; align-items: center; gap: 8px; padding: 10px 12px; border-bottom: 1px solid color-mix(in srgb, var(--bd) 65%, transparent); background: linear-gradient(120deg, color-mix(in srgb, var(--ac) 6%, var(--bg2)), var(--bg2) 75%); }
.support-avatar { display: grid; place-items: center; width: 32px; height: 32px; flex-shrink: 0; border-radius: 11px; background: color-mix(in srgb, var(--ac) 14%, var(--bg2)); color: var(--ac); }
.heading { flex: 1; min-width: 0; }
.heading h2 { margin: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--t1); font-size: var(--text-base); font-weight: 600; letter-spacing: -.02em; }
.header-action { flex-shrink: 0; height: 32px; width: 32px; }
.widget-loading, .widget-error { flex: 1; display: flex; align-items: center; justify-content: center; }
.widget-error { flex-direction: column; gap: 20px; color: var(--t3); }
.chat-launcher:focus-visible { outline: 2px solid var(--ac); outline-offset: 4px; }
.chat-content-enter-active { transition: opacity .2s ease .1s; }
.chat-content-leave-active { transition: opacity .1s ease; }
.chat-content-enter-from, .chat-content-leave-to { opacity: 0; }
.is-mobile { --chat-open-width: 100vw; --chat-open-height: var(--chat-viewport-height, 100dvh); right: 16px; bottom: calc(16px + env(safe-area-inset-bottom)); width: 52px; height: 52px; border-radius: 26px; }
.is-mobile.is-open { right: 0; bottom: var(--chat-viewport-bottom, 0px); border-radius: 0; }
.is-mobile .chat-panel { padding-bottom: env(safe-area-inset-bottom); border: 0; }
.is-mobile .chat-header { padding: max(8px, env(safe-area-inset-top)) 12px 8px; }
.is-mobile .header-action { width: 40px; height: 40px; }
@media (prefers-reduced-motion: reduce) { .support-widget, .chat-surface, .chat-launcher, .chat-content-enter-active, .chat-content-leave-active { transition: none; } }
</style>

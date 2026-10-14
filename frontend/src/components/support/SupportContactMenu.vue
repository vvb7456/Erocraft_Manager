<script setup lang="ts">
import { nextTick, ref, useId, watch } from 'vue'
import { autoUpdate, flip, offset, shift, useFloating } from '@floating-ui/vue'
import { RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'
import MsIcon from '@/components/ui/MsIcon.vue'

const props = defineProps<{ username: string }>()
const { t } = useI18n()
const id = useId()
const open = ref(false)
const trigger = ref<HTMLButtonElement | null>(null)
const menu = ref<HTMLElement | null>(null)
const { floatingStyles } = useFloating(trigger, menu, {
  open, placement: 'bottom-start', strategy: 'fixed', whileElementsMounted: autoUpdate,
  middleware: [offset(6), flip({ padding: 12 }), shift({ padding: 12 })],
})

function close(restoreFocus = false) {
  open.value = false
  if (restoreFocus) trigger.value?.focus({ preventScroll: true })
}
async function toggle() {
  if (open.value) { close(); return }
  open.value = true
  await nextTick()
  if (open.value) menu.value?.querySelector('a')?.focus({ preventScroll: true })
}
function outside(event: Event) {
  if (!trigger.value?.contains(event.target as Node) && !menu.value?.contains(event.target as Node)) close()
}
function move(event: KeyboardEvent) {
  const links = [...(menu.value?.querySelectorAll('a') || [])]
  if (!links.length || !['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  const current = links.indexOf(document.activeElement as HTMLAnchorElement)
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? links.length - 1 : (current + (event.key === 'ArrowUp' ? -1 : 1) + links.length) % links.length
  links[next]?.focus({ preventScroll: true })
}
watch(() => props.username, () => close())
watch(open, (visible, _, onCleanup) => {
  if (!visible) return
  document.addEventListener('pointerdown', outside)
  document.addEventListener('focusin', outside)
  onCleanup(() => {
    document.removeEventListener('pointerdown', outside)
    document.removeEventListener('focusin', outside)
  })
})
</script>

<template>
  <div class="contact-menu">
    <h3><button ref="trigger" type="button" class="contact-trigger" :aria-expanded="open" :aria-controls="id" :title="username" @click="toggle" @keydown.esc.stop.prevent="close(true)" @keydown.down.prevent="!open && toggle()"><span>{{ username }}</span><MsIcon name="expand_more" size="xs" /></button></h3>
    <Teleport to="body">
      <nav v-if="open" :id="id" ref="menu" class="contact-dropdown" :style="floatingStyles" :aria-label="t('support.customerActions', { name: username })" @keydown="move" @keydown.esc.stop.prevent="close(true)">
        <RouterLink :to="{ name: 'users', query: { q: username } }" @click="close()"><MsIcon name="person" size="sm" />{{ t('support.viewUser') }}</RouterLink>
        <RouterLink :to="{ name: 'servers', query: { q: username } }" @click="close()"><MsIcon name="dns" size="sm" />{{ t('support.viewServers') }}</RouterLink>
        <RouterLink :to="{ name: 'admin-billing', query: { tab: 'orders', q: username } }" @click="close()"><MsIcon name="receipt_long" size="sm" />{{ t('support.viewOrders') }}</RouterLink>
      </nav>
    </Teleport>
  </div>
</template>

<style scoped>
.contact-menu { min-width: 0; max-width: 100%; }
.contact-menu h3 { margin: 0; font-size: var(--text-base); font-weight: 600; }
.contact-trigger { display: flex; align-items: center; gap: 4px; width: max-content; max-width: 100%; padding: 5px 6px; border: 0; border-radius: 7px; background: transparent; color: var(--t1); font: inherit; cursor: pointer; }
.contact-trigger > span:first-child { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.contact-trigger > .ms { flex-shrink: 0; }
.contact-trigger:hover, .contact-trigger[aria-expanded="true"] { color: var(--ac); background: color-mix(in srgb, var(--ac) 8%, transparent); }
.contact-dropdown { width: min(208px, calc(100vw - 24px)); z-index: 950; display: flex; flex-direction: column; gap: 2px; padding: var(--sp-1); border: 1px solid var(--bd); border-radius: var(--r-lg); background: var(--bg2); box-shadow: var(--sh); }
.contact-dropdown a { display: flex; align-items: center; gap: 9px; min-height: 40px; padding: 8px 10px; border-radius: 8px; color: var(--t1); text-decoration: none; font-size: var(--text-sm); }
.contact-dropdown a:hover { background: var(--bg3); color: var(--ac); }
.contact-trigger:focus-visible, .contact-dropdown a:focus-visible { outline: 2px solid var(--ac); outline-offset: -2px; }
</style>

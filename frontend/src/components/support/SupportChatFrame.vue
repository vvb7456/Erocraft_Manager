<script setup lang="ts">
import { ref, watchEffect } from 'vue'
import { lockBodyScroll, unlockBodyScroll } from '@/components/ui/BaseModal.vue'

defineOptions({ inheritAttrs: false })
const props = withDefaults(defineProps<{ fullscreen?: boolean; open?: boolean; variant?: 'floating' | 'workspace'; empty?: boolean }>(), { fullscreen: false, open: true, variant: 'workspace' })
const element = ref<HTMLElement | null>(null)

watchEffect(onCleanup => {
  if (!props.fullscreen || !props.open) return
  lockBodyScroll()
  onCleanup(unlockBodyScroll)
})

defineExpose({ element, focus: (options?: FocusOptions) => element.value?.focus(options) })
</script>

<template>
  <Teleport to="body" :disabled="!fullscreen">
    <section v-show="open" ref="element" v-bind="$attrs" class="chat-frame" :class="[fullscreen ? 'chat-frame--fullscreen' : `chat-frame--${variant}`, { 'chat-frame--empty': empty && !fullscreen }]">
      <slot />
    </section>
  </Teleport>
</template>

<style scoped>
.chat-frame { display: flex; flex-direction: column; min-width: 0; min-height: 0; overflow: hidden; background: var(--bg2); outline: none; }
.chat-frame--floating { position: absolute; bottom: 0; right: 0; width: var(--chat-open-width); height: var(--chat-open-height); border: 1px solid var(--bd); border-radius: inherit; }
.chat-frame--workspace { border: 1px solid var(--bd); border-radius: 18px; }
.chat-frame--empty { border-style: dashed; background: color-mix(in srgb, var(--bg2) 45%, transparent); }
.chat-frame--fullscreen { position: fixed; inset: 0; z-index: 900; }
</style>

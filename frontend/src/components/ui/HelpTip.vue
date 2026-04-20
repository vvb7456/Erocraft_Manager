<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue'

defineOptions({ name: 'HelpTip' })

defineProps<{ text: string }>()

const open = ref(false)
const el = ref<HTMLElement>()

function toggle(e: Event) {
  e.stopPropagation()
  open.value = !open.value
}

function onDocClick(e: Event) {
  if (el.value && !el.value.contains(e.target as Node)) {
    open.value = false
  }
}

onMounted(() => document.addEventListener('click', onDocClick))
onBeforeUnmount(() => document.removeEventListener('click', onDocClick))
</script>

<template>
  <span ref="el" class="cc-help-tip" :class="{ open }" :data-tip="text" @click="toggle">?</span>
</template>

<style scoped>
.cc-help-tip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: var(--bd);
  color: var(--t3);
  font-size: .65rem;
  cursor: help;
  flex-shrink: 0;
  position: relative;
  vertical-align: middle;
  margin-left: 4px;
}
.cc-help-tip:hover::after,
.cc-help-tip.open::after {
  content: attr(data-tip);
  position: absolute;
  bottom: calc(100% + 6px);
  left: 0;
  background: var(--bg-in);
  border: 1px solid var(--bd);
  color: var(--t1);
  padding: 6px 10px;
  border-radius: 6px;
  font-size: .72rem;
  line-height: 1.4;
  white-space: pre-line;
  width: max-content;
  max-width: 280px;
  z-index: 10000;
  box-shadow: 0 4px 12px rgba(0, 0, 0, .15);
  pointer-events: none;
}
</style>

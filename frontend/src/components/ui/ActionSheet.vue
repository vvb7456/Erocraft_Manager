<script setup lang="ts">
defineOptions({ name: 'ActionSheet' })

const open = defineModel<boolean>({ required: true })

defineProps<{
  title?: string
}>()
</script>

<template>
  <BottomSheet v-model="open" :title="title">
    <div v-if="$slots.info" class="action-sheet__info">
      <slot name="info" />
    </div>
    <div class="action-sheet__actions">
      <slot />
    </div>
  </BottomSheet>
</template>

<script lang="ts">
import BottomSheet from './BottomSheet.vue'
export default { components: { BottomSheet } }
</script>

<style scoped>
.action-sheet__info {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: .82rem;
  color: var(--t2);
  padding-bottom: var(--sp-3);
  border-bottom: 1px solid var(--bd);
  margin-bottom: var(--sp-1);
}

.action-sheet__actions {
  display: flex;
  flex-direction: column;
}

:slotted(button),
:slotted(a) {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  width: 100%;
  padding: var(--sp-3) var(--sp-1);
  background: none;
  border: none;
  font-size: .88rem;
  font-family: inherit;
  color: var(--t1);
  cursor: pointer;
  border-radius: var(--r-sm);
  text-decoration: none;
  transition: background .15s;
}

:slotted(button:hover),
:slotted(a:hover) {
  background: var(--bg3);
}

:slotted(button:active),
:slotted(a:active) {
  background: var(--bg2);
}

:slotted(button:disabled) {
  opacity: .4;
  cursor: not-allowed;
}

:slotted(.action-sheet--danger) {
  color: var(--red);
  margin-top: var(--sp-2);
  border-top: 1px solid var(--bd);
  padding-top: var(--sp-3);
}
</style>

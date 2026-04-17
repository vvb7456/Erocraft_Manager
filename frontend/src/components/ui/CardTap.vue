<script setup lang="ts">
defineOptions({ name: 'CardTap' })

const emit = defineEmits<{ tap: [] }>()
</script>

<template>
  <div class="card-tap" @click="emit('tap')">
    <slot />
  </div>
</template>

<style scoped>
.card-tap {
  cursor: pointer;
  transition: opacity .15s, transform .15s;
}

.card-tap:active {
  opacity: .7;
  transform: scale(.98);
}

/* ── Shared card layout slots ── */
:slotted(.card-row--main) {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}

:slotted(.card-row--sub) {
  font-size: .82rem;
  color: var(--t2);
  margin-top: 2px;
}

:slotted(.card-expiry-row) {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-top: var(--sp-2);
  font-size: .85rem;
  font-weight: 500;
}

:slotted(.card-detail) {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--sp-2) var(--sp-4);
  margin-top: var(--sp-2);
}

:slotted(.card-detail--3col) {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--sp-2) var(--sp-3);
  margin-top: var(--sp-2);
}
</style>
